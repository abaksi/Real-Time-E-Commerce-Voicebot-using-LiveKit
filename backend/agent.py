"""
agent.py
--------
Main voice agent for the eCommerce VoiceBot, orchestrating the real-time pipeline:
    1. Voice Activity Detection (VAD)
    2. Speech-to-Text (STT)
    3. LLM response generation
    4. Text-to-Speech (TTS)
    5. LiveKit audio playback
Handles event registration, audio stream management, and conversation state.
"""

import asyncio
import logging
import json
import os
import sys
import struct
import math
import re
import time
from collections import deque
from pathlib import Path
from dotenv import load_dotenv
from logging_config import setup_logging

# ── Lazy module handles (imported inside worker process) ─────────────────────
stt = tts = llm_client = rtc = agents = None

_PREWARM_STATE_KEY = "voicebot-prewarm-state"

# ── Audio playback state (module-level for cross-coroutine access) ───────────
_agent_audio_source = None
_bot_is_speaking    = False
_ignore_audio_until = 0.0

# ── VAD tuning constants ─────────────────────────────────────────────────────
SPEECH_THRESHOLD          = 0.0018   # Minimum RMS to count as speech
REQUIRED_SPEECH_FRAMES    = 12       # Consecutive frames needed to start buffering
SILENCE_TIMEOUT_FRAMES    = 120      # Silent frames after which utterance is finalised (~2.5s)
MAX_BUFFER_CHUNKS         = 420      # Hard cap on buffer size (prevents runaway memory)
MIN_SPEECH_BUFFER         = 50       # Discard buffers shorter than this (noise bursts)
POST_PLAYBACK_IGNORE_SECS = 1.0      # Suppress mic capture for 1s after TTS (echo gate)
UTTERANCE_QUEUE_SIZE      = 1        # Drop stale utterances; always process the latest

# ── Filler words that should not reach the LLM ───────────────────────────────
_FILLER = {
    "okay", "ok", "alright", "all right", "hmm", "uh", "huh",
    "right", "sure", "certainly", "yeah", "yep",
}

# ── Spoken digit words → numerals ────────────────────────────────────────────
_DIGIT_WORDS = {
    "zero":"0","one":"1","two":"2","three":"3","four":"4",
    "five":"5","six":"6","seven":"7","eight":"8","nine":"9",
}

# ── Logging ───────────────────────────────────────────────────────────────────
import os
log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
logger = setup_logging("voicebot-agent", "agent.log", level=log_level)
logging.getLogger("livekit").setLevel(logging.INFO)
logging.getLogger("livekit.agents").setLevel(logging.INFO)
sys.path.append(str(Path(__file__).parent))


# ── Module helpers ────────────────────────────────────────────────────────────


def ensure_backend_modules():
    """
    Import backend modules (STT, TTS, LLM) lazily inside the worker process.
    Ensures global handles are set for the agent pipeline.
    """
    global stt, tts, llm_client
    if stt is None:
        import stt as _s, tts as _t, llm_client as _l
        stt, tts, llm_client = _s, _t, _l
        logger.info("[STARTUP] Backend modules imported")



def ensure_livekit_runtime():
    """
    Import LiveKit runtime modules lazily and ensure backend modules are loaded.
    """
    global rtc, agents
    ensure_backend_modules()
    if rtc is None:
        from livekit import rtc as _r, agents as _a
        rtc, agents = _r, _a
        logger.info("[STARTUP] LiveKit runtime imported")


def _log_error(task):
    """
    Asyncio task done-callback that logs unhandled exceptions.
    Used to ensure background tasks don't silently fail.
    Args:
        task (asyncio.Task): The asyncio task to check for errors.
    """
    try:
        task.result()
    except Exception as e:
        logger.error(f"[TASK] Unhandled error: {e}", exc_info=True)


def _prewarm_process(proc):
    """
    Load heavy dependencies in the idle worker process before a room job starts.
    Preloads STT, LLM, and TTS to reduce latency for the first user interaction.
    Args:
        proc: The process object to store prewarm state.
    """
    ensure_livekit_runtime()
    logger.info("[PREWARM] Starting process prewarm")

    prewarm_state = {
        "stt_ready": False,
        "llm_warm": False,
        "tts_format": (22050, 1),
    }

    try:
        stt.load_stt_model()
        prewarm_state["stt_ready"] = True
        logger.info("[PREWARM] STT model ready")
    except Exception as e:
        logger.error(f"[PREWARM] STT preload failed: {e}")

    try:
        llm_client.warmup_ollama()
        prewarm_state["llm_warm"] = True
        logger.info("[PREWARM] Ollama warmup attempted")
    except Exception as e:
        logger.warning(f"[PREWARM] Ollama warmup skipped: {e}")

    try:
        prewarm_state["tts_format"] = tts.get_output_format()
    except Exception as e:
        logger.warning(f"[PREWARM] TTS format detection failed: {e}")

    proc.userdata[_PREWARM_STATE_KEY] = prewarm_state
    logger.info(
        "[PREWARM] Complete "
        f"(stt_ready={prewarm_state['stt_ready']}, llm_warm={prewarm_state['llm_warm']}, "
        f"tts={prewarm_state['tts_format'][0]}Hz/{prewarm_state['tts_format'][1]}ch)"
    )


async def _send(ctx, msg_type: str, text: str):
    """
    Publish a JSON data message over the LiveKit data channel.
    Used for sending status, user, and bot messages to the frontend.
    Args:
        ctx: LiveKit context.
        msg_type (str): Type of message ('bot', 'user', etc.).
        text (str): Message text.
    """
    try:
        await ctx.room.local_participant.publish_data(
            json.dumps({"type": msg_type, "text": text}).encode(),
            reliable=True,
        )
    except Exception as e:
        logger.warning(f"[DATA] Failed to send '{msg_type}': {e}")


# ── Text utilities ────────────────────────────────────────────────────────────

def _normalize(text: str) -> str:
    """
    Normalise STT transcript:
      • Convert digit-words to numerals  ("one two three" → "1 2 3")
      • Collapse spaced digit runs       ("order 1 2 3 4 5" → "order 12345")
    Args:
        text (str): Input transcript text.
    Returns:
        str: Normalized text.
    """
    text = " ".join((text or "").strip().split())
    text = " ".join(_DIGIT_WORDS.get(w.lower().strip(".,!?"), w) for w in text.split())

    def _collapse_order(m):
        return m.group(1) + re.sub(r"\D", "", m.group(2))

    text = re.sub(
        r"\b(order(?:\s*(?:id|number|no\.?))?\s*)([\d\s,\-\.]{2,})\b",
        _collapse_order, text, flags=re.IGNORECASE,
    )
    text = re.sub(r"\b(?:\d[\s,\-]*){4,}\d\b", lambda m: re.sub(r"\D", "", m.group()), text)
    return text


def _is_filler(text: str) -> bool:
    """
    Return True if *text* is a short filler/noise utterance with no domain value.
    Args:
        text (str): Input text.
    Returns:
        bool: True if filler, else False.
    """
    cleaned = re.sub(r"[^a-z0-9\s]", "", text.lower()).strip()
    if not cleaned:
        return True
    # Numeric-only fragments (e.g. "3 4 5") are often split tails of a query.
    if re.fullmatch(r"[\d\s]+", cleaned):
        return True
    bare = cleaned.rstrip(".,!?")
    # Always allow greetings through (LLM should respond to them)
    if bare in {"hi", "hello", "hey", "howdy", "hi there", "hello there"}:
        return False
    if bare in _FILLER:
        return True
    # Very short with no e-commerce keywords → treat as filler
    domain_kw = {"order","status","return","refund","policy","shipping",
                 "warranty","product","price","laptop","phone","tablet"}
    if len(cleaned.split()) <= 2 and len(cleaned) <= 12 and not any(k in cleaned for k in domain_kw):
        return True
    return False


# ── Entrypoint ────────────────────────────────────────────────────────────────

async def entrypoint(ctx):
    """
    Agent startup sequence:
      1. Preload STT model and warm up LLM (before connecting so first reply is fast)
      2. Register LiveKit event handlers
      3. Connect to the LiveKit room
      4. Publish the persistent audio output track
      5. Discover any participants who joined before us
      6. Send intro message + ready signal to the frontend
    Args:
        ctx: LiveKit context object.
    """
    ensure_livekit_runtime()
    logger.info(f"[STARTUP] Agent starting for room: {ctx.room.name}")

    prewarm_state = ctx.proc.userdata.get(_PREWARM_STATE_KEY, {})

    # 1. Preload STT
    if prewarm_state.get("stt_ready"):
        logger.info("[STARTUP] Reusing prewarmed STT model")
    else:
        logger.info("[STARTUP] Loading STT model...")
        try:
            stt.load_stt_model()
            logger.info("[STT] Model ready")
        except Exception as e:
            logger.error(f"[STT] Preload failed: {e}", exc_info=True)

    # 2. Warm up LLM (best-effort; non-blocking on failure)
    if prewarm_state.get("llm_warm"):
        logger.info("[STARTUP] Reusing prewarmed LLM state")
    else:
        logger.info("[STARTUP] Warming up LLM...")
        try:
            await asyncio.to_thread(llm_client.warmup_ollama)
        except Exception as e:
            logger.warning(f"[LLM] Warmup skipped: {e}", exc_info=True)

    # 3. Detect TTS output format
    try:
        tts_rate, tts_channels = prewarm_state.get("tts_format", tts.get_output_format())
    except Exception:
        tts_rate, tts_channels = 22050, 1
    logger.info(f"[TTS] Output format: {tts_rate}Hz, {tts_channels}ch")

    logger.info("[STARTUP] Models ready — connecting to LiveKit room...")

    # 4. Queue + background worker
    utterance_queue: asyncio.Queue = asyncio.Queue(maxsize=UTTERANCE_QUEUE_SIZE)
    active_track_sids: set = set()
    conversation_history: deque = deque(maxlen=8)

    async def queue_worker():
        logger.info("[QUEUE] Worker started")
        while True:
            payload = await utterance_queue.get()
            try:
                await process_audio_buffer(
                    ctx,
                    payload["buffer"],
                    payload["sample_rate"],
                    payload.get("channels", 1),
                    conversation_history,
                )
            except Exception as e:
                logger.error(f"[QUEUE] Worker error: {e}", exc_info=True)
            finally:
                utterance_queue.task_done()

    worker_task = asyncio.create_task(queue_worker())
    worker_task.add_done_callback(_log_error)

    # 5. Register event handlers BEFORE connecting (no missed events)
    @ctx.room.on("track_published")
    def on_track_published(publication, participant):
        if participant.identity == ctx.room.local_participant.identity:
            return
        if publication.kind == rtc.TrackKind.KIND_AUDIO:
            logger.info(f"[TRACK] Audio published by {participant.identity}, subscribing...")
            try:
                publication.set_subscribed(True)
            except Exception as e:
                logger.error(f"[TRACK] set_subscribed failed: {e}")

    @ctx.room.on("track_subscribed")
    def on_track_subscribed(track, publication, participant):
        if participant.identity == ctx.room.local_participant.identity:
            return
        if track.kind == rtc.TrackKind.KIND_AUDIO:
            if publication.sid in active_track_sids:
                return  # already handling this track
            active_track_sids.add(publication.sid)
            logger.info(f"[TRACK] Subscribed to audio from {participant.identity} ({publication.sid})")
            task = asyncio.create_task(
                handle_audio_stream(ctx, track, participant, utterance_queue)
            )
            task.add_done_callback(_log_error)

    # 6. Connect
    await ctx.connect()
    logger.info(f"[AGENT] Connected | Room: {ctx.room.name} | Identity: {ctx.room.local_participant.identity}")


    # 7. Publish persistent audio output track
    global _agent_audio_source
    _agent_audio_source = rtc.AudioSource(sample_rate=tts_rate, num_channels=tts_channels)
    audio_track = rtc.LocalAudioTrack.create_audio_track("agent_voice", _agent_audio_source)
    pub_opts = rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
    pub = await ctx.room.local_participant.publish_track(audio_track, pub_opts)
    logger.info(f"[AGENT] Audio track published: {pub.sid}")

    # Wait for audio track to be in a valid state before TTS playback
    max_retries = 10
    for i in range(max_retries):
        if _agent_audio_source is not None and hasattr(_agent_audio_source, 'capture_frame'):
            logger.info(f"[AGENT] Audio source ready for playback (attempt {i+1})")
            break
        logger.info(f"[AGENT] Waiting for audio source to be ready (attempt {i+1})")
        await asyncio.sleep(0.3)
    else:
        logger.warning("[AGENT] Audio source not ready after retries; TTS playback may fail.")

    # 8. Discover already-joined participants
    for participant in ctx.room.remote_participants.values():
        for publication in participant.track_publications.values():
            if publication.kind == rtc.TrackKind.KIND_AUDIO:
                if publication.subscribed and publication.track:
                    if publication.sid not in active_track_sids:
                        active_track_sids.add(publication.sid)
                        task = asyncio.create_task(
                            handle_audio_stream(ctx, publication.track, participant, utterance_queue)
                        )
                        task.add_done_callback(_log_error)
                elif not publication.subscribed:
                    publication.set_subscribed(True)

    logger.info(f"[AGENT] Remote participants on join: {list(ctx.room.remote_participants.keys())}")

    # 9. Greet + signal frontend that the bot is ready
    intro = (
        "Hi! I'm Ira, your e-commerce assistant. "
        "I can help with orders, products, shipping, and returns. "
        "How can I help you today?"
    )

    # Show intro text in chat immediately
    await _send(ctx, "bot", intro)


    # Speak the intro — text is already visible so text & speech are in sync
    global _bot_is_speaking, _ignore_audio_until
    tts_playback_success = False
    try:
        logger.info("[TTS] Synthesising intro...")
        tts_result = await asyncio.wait_for(
            asyncio.to_thread(tts.synthesize_text_to_pcm, intro),
            timeout=20,
        )
        if tts_result:
            _bot_is_speaking = True
            # Retry TTS playback if InvalidState error occurs
            for attempt in range(3):
                try:
                    logger.info(f"[TTS] Attempting intro playback (try {attempt+1})")
                    logger.info(f"[TTS] _agent_audio_source: {_agent_audio_source}")
                    await asyncio.wait_for(
                        play_audio_pcm(
                            tts_result["pcm_bytes"],
                            tts_result["sample_rate"],
                            tts_result["channels"],
                        ),
                        timeout=45,
                    )
                    tts_playback_success = True
                    break
                except Exception as e:
                    logger.warning(f"[TTS] Intro playback failed (attempt {attempt+1}): {e}", exc_info=True)
                    await asyncio.sleep(0.5)
            _bot_is_speaking = False
            _ignore_audio_until = time.monotonic() + POST_PLAYBACK_IGNORE_SECS
    except Exception as e:
        logger.warning(f"[TTS] Intro speech failed: {e}", exc_info=True)
        _bot_is_speaking = False
    if not tts_playback_success:
        logger.warning("[TTS] Intro playback did not succeed after retries.")

    # Signal ready AFTER speech — user knows to speak now
    await _send(ctx, "ready", "")
    logger.info("[AGENT] Intro spoken and ready signal sent to frontend")


# ── Audio stream handler (VAD) ────────────────────────────────────────────────

async def handle_audio_stream(ctx, track, participant, utterance_queue: asyncio.Queue):
    """
    Read incoming audio frames, apply RMS-based VAD, buffer speech,
    and enqueue completed utterances for downstream processing.
    Args:
        ctx: LiveKit context.
        track: Audio track object.
        participant: Participant object.
        utterance_queue (asyncio.Queue): Queue for completed utterances.
    """
    logger.info(f"[VAD] Listening to {participant.identity}")
    audio_stream = rtc.AudioStream(track)

    frame_buffer  = []
    is_speaking   = False
    silence_frames = 0
    speech_frames  = 0
    frame_count    = 0
    current_sample_rate = None
    current_channels = None

    async for event in audio_stream:
        frame = event.frame
        data  = frame.data.tobytes()
        frame_count += 1
        if not data:
            continue

        frame_sample_rate = getattr(frame, "sample_rate", None) or 48000
        frame_channels = getattr(frame, "num_channels", None) or 1

        if current_sample_rate != frame_sample_rate or current_channels != frame_channels:
            current_sample_rate = frame_sample_rate
            current_channels = frame_channels
            logger.info(
                f"[VAD] Input format from {participant.identity}: "
                f"{current_sample_rate}Hz, {current_channels}ch"
            )

        # Echo gate: suppress mic while the bot is speaking or just finished

        if _bot_is_speaking or time.monotonic() < _ignore_audio_until:
            continue

        # --- User silence detection for >15s ---
        # 55 frames at 20ms = ~1.1s, so 750 frames ≈ 15s
        if silence_frames > 750 and not is_speaking:
            polite_wait_message = "I am still here, let me know if you need anything."
            logger.info(f"[SILENCE] User silent >15s, sending polite wait message.")
            await _send(ctx, "bot", polite_wait_message)
            silence_frames = 0  # reset so message is not repeated

        # RMS energy of this frame
        count  = len(data) // 2
        shorts = struct.unpack(f"{count}h", data)
        rms    = math.sqrt(sum(s * s for s in shorts) / count) / 32768.0

        if frame_count % 200 == 0:
            logger.info(f"[VAD] Frame={frame_count} RMS={rms:.5f} speaking={is_speaking} buf={len(frame_buffer)}")

        if rms > SPEECH_THRESHOLD:
            speech_frames += 1
            if speech_frames >= REQUIRED_SPEECH_FRAMES:
                if not is_speaking:
                    logger.info(f"[VAD] Speech start (RMS={rms:.5f})")
                    is_speaking   = True
                silence_frames = 0
            if is_speaking:
                frame_buffer.append(data)

        elif is_speaking:
            speech_frames  = 0
            silence_frames += 1
            frame_buffer.append(data)

            if silence_frames > SILENCE_TIMEOUT_FRAMES or len(frame_buffer) > MAX_BUFFER_CHUNKS:
                reason = "silence" if silence_frames > SILENCE_TIMEOUT_FRAMES else "max-duration"
                logger.info(f"[VAD] Utterance end ({reason}, {len(frame_buffer)} chunks)")
                is_speaking    = False
                silence_frames = 0
                payload        = list(frame_buffer)
                frame_buffer   = []

                if len(payload) < MIN_SPEECH_BUFFER:
                    logger.debug(f"[VAD] Discarding noise burst ({len(payload)} chunks)")
                    speech_frames = 0
                    continue

                # Drop oldest utterance if queue is full (keep real-time)
                if utterance_queue.full():
                    try:
                        utterance_queue.get_nowait()
                        utterance_queue.task_done()
                        logger.warning("[QUEUE] Dropped stale utterance to keep real-time")
                    except Exception:
                        pass

                try:
                    utterance_queue.put_nowait({
                        "buffer": payload,
                        "sample_rate": current_sample_rate or 48000,
                        "channels": current_channels or 1,
                    })
                    logger.info(f"[QUEUE] Enqueued utterance (size={utterance_queue.qsize()})")
                except Exception:
                    logger.warning("[QUEUE] Failed to enqueue utterance")
        else:
            speech_frames = 0


# ── Processing pipeline ───────────────────────────────────────────────────────

async def process_audio_buffer(
    ctx,
    buffer: list,
    sample_rate: int,
    channels: int,
    conversation_history: deque,
):
    """
    STT → LLM → TTS → Playback for one completed utterance.
    Args:
        ctx: LiveKit context.
        buffer (list): Audio buffer chunks.
        sample_rate (int): Audio sample rate.
        channels (int): Number of channels.
        conversation_history (deque): Conversation history for context.
    """
    ensure_livekit_runtime()
    t0 = time.perf_counter()
    logger.info(
        f"[PIPELINE] Processing {len(buffer)} chunks at {sample_rate}Hz/{channels}ch..."
    )

    try:
        audio_bytes = b"".join(buffer)

        # Hybrid Whisper model selection
        # Use 'tiny' for short utterances, 'base' for longer/product queries
        duration_sec = len(audio_bytes) / (2 * sample_rate)  # 2 bytes per sample
        if duration_sec < 2.0:
            model_name = "tiny"
        else:
            model_name = "base"
        logger.info(f"[PIPELINE] Using Whisper model: {model_name} (duration={duration_sec:.2f}s)")

        # STT
        t_stt = time.perf_counter()
        text = await asyncio.wait_for(
            asyncio.to_thread(stt.transcribe_audio_to_text, audio_bytes, sample_rate, channels, model_name),
            timeout=12,
        )
        logger.info(f"[LATENCY] STT={int((time.perf_counter() - t_stt) * 1000)}ms")

        if not text or len(text.strip()) < 2:
            logger.info("[PIPELINE] Short/empty transcription — skipping")
            return

        normalized = _normalize(text)
        if _is_filler(normalized):
            logger.info(f"[PIPELINE] Dropped filler: '{normalized}'")
            return

        logger.info(f"AI IN: {normalized}")
        await _send(ctx, "user",   normalized)
        await _send(ctx, "status", "Processing…")

        # Check for exit/goodbye intent
        exit_phrases = ["bye", "goodbye", "that is it", "that's it", "exit", "end chat", "disconnect", "close chat", "see you", "thank you, that's all", "thanks, that's all"]
        if any(phrase in normalized.lower() for phrase in exit_phrases):
            goodbye_msg = "Thank you for chatting with me! If you need anything else, just let me know. This chat will disconnect in a few seconds."
            await _send(ctx, "bot", goodbye_msg)
            await _send(ctx, "disconnect", "")
            logger.info("[PIPELINE] User exit intent detected, sent goodbye and disconnect signal.")
            return

        # LLM
        t_llm = time.perf_counter()
        history_snap = list(conversation_history)

        llm_timeout = int(os.environ.get("PIPELINE_LLM_TIMEOUT_SECONDS", "10"))
        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(llm_client.generate_response, normalized, history_snap),
                timeout=llm_timeout,
            )
            logger.info(f"[LATENCY] LLM={int((time.perf_counter() - t_llm) * 1000)}ms")
        except asyncio.TimeoutError:
            logger.error("[PIPELINE] LLM step timed out")
            response = "Sorry, I'm having trouble thinking of a response right now. Please try again in a moment."
        except Exception as e:
            logger.error(f"[PIPELINE] LLM error: {e}", exc_info=True)
            response = "Sorry, something went wrong with my answer. Please try again."

        conversation_history.append({"user": normalized, "assistant": response})
        logger.info(f"AI OUT: {response}")
        await _send(ctx, "bot",          response)
        await _send(ctx, "status_clear", "")

        # TTS
        t_tts = time.perf_counter()
        tts_result = await asyncio.wait_for(
            asyncio.to_thread(tts.synthesize_text_to_pcm, response),
            timeout=12,
        )
        logger.info(f"[LATENCY] TTS={int((time.perf_counter() - t_tts) * 1000)}ms")

        if not tts_result:
            logger.error("[PIPELINE] TTS returned nothing")
            await _send(ctx, "error", "Voice synthesis failed. Please try again.")
            return

        # Playback
        global _bot_is_speaking, _ignore_audio_until
        _bot_is_speaking = True
        try:
            t_play = time.perf_counter()
            await asyncio.wait_for(
                play_audio_pcm(
                    tts_result["pcm_bytes"],
                    tts_result["sample_rate"],
                    tts_result["channels"],
                ),
                timeout=30,
            )
            logger.info(
                f"[LATENCY] PLAY={int((time.perf_counter()-t_play)*1000)}ms "
                f"TOTAL={int((time.perf_counter()-t0)*1000)}ms"
            )
        finally:
            _bot_is_speaking    = False
            _ignore_audio_until = time.monotonic() + POST_PLAYBACK_IGNORE_SECS

    except asyncio.TimeoutError:
        logger.error("[PIPELINE] Step timed out")
        await _send(ctx, "status_clear", "")
        # Avoid interruptive popup spam for transient timeout spikes.
        await _send(ctx, "bot", "I missed part of that. Please repeat your request clearly.")
    except Exception as e:
        logger.error(f"[PIPELINE] Error: {e}", exc_info=True)
        await _send(ctx, "status_clear", "")
        await _send(ctx, "error", "Something went wrong. Please try again.")


async def play_audio_pcm(pcm_bytes: bytes, sample_rate: int, channels: int):
    """
    Stream PCM16 bytes to the persistent LiveKit audio source in 20ms chunks.
    Args:
        pcm_bytes (bytes): PCM16 audio bytes.
        sample_rate (int): Audio sample rate.
        channels (int): Number of channels.
    """
    global _agent_audio_source
    if _agent_audio_source is None:
        logger.error("[PLAYBACK] No audio source available")
        return

    logger.info("[PLAYBACK] Streaming audio...")
    bytes_per_sample = 2
    chunk_frames     = int(sample_rate * 0.02)          # 20ms worth of frames
    chunk_size       = chunk_frames * channels * bytes_per_sample

    for offset in range(0, len(pcm_bytes), chunk_size):
        data = pcm_bytes[offset: offset + chunk_size]
        if not data:
            continue
        frame = rtc.AudioFrame(
            data=data,
            sample_rate=sample_rate,
            num_channels=channels,
            samples_per_channel=len(data) // (bytes_per_sample * channels),
        )
        await _agent_audio_source.capture_frame(frame)
        await asyncio.sleep(0.02 * 0.8)   # slight under-sleep to avoid buffer underrun

    logger.info("[PLAYBACK] Done")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    load_dotenv(Path(__file__).parent.parent / ".env")
    ensure_livekit_runtime()

    url = os.environ.get("LIVEKIT_URL", "")
    logger.info(f"[STARTUP] Worker starting — LiveKit URL: {url}")

    from livekit.agents import cli, WorkerOptions

    agent_port = int(os.environ.get("LIVEKIT_AGENT_HTTP_PORT", 8081))
    try:
        cli.run_app(
            WorkerOptions(
                entrypoint_fnc=entrypoint,
                prewarm_fnc=_prewarm_process,
                initialize_process_timeout=180.0,
                num_idle_processes=1,
                port=agent_port,
            )
        )
    except SystemExit:
        pass
    except Exception as e:
        logger.error(f"[STARTUP] Worker crash: {e}", exc_info=True)
