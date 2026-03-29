

"""
tts.py
------
Text-to-Speech (TTS) module for the eCommerce VoiceBot.
Uses edge-tts to synthesize speech and decodes to PCM for real-time playback.
Handles text cleaning, synthesis, and audio decoding.
"""

import os
import io
import asyncio
from logging_config import setup_logging
import threading
import numpy as np

import av
import edge_tts

log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
logger = setup_logging("voicebot-agent", "tts.log", level=log_level)
_tts_lock = threading.Lock()



def clean_tts_text(text: str) -> str:
    """
    Prepare and clean text for TTS synthesis.
    Args:
        text (str): Input text to clean.
    Returns:
        str: Cleaned text suitable for TTS.
    Notes:
        - Strips whitespace and normalizes spacing.
    import os
    """
    cleaned = " ".join((text or "").strip().split())
    if not cleaned:
        return cleaned
    cleaned = cleaned.replace(";", ", ")
    return cleaned


def decode_audio_to_pcm(audio_bytes: bytes):
    """
    Decode compressed audio bytes (mp3/webm) to PCM16 mono bytes for playback.
    Args:
        audio_bytes (bytes): Compressed audio bytes (mp3/webm).
    Returns:
        tuple: (pcm_bytes, sample_rate, channels)
    """
    container = av.open(io.BytesIO(audio_bytes))
    resampler = av.audio.resampler.AudioResampler(format="s16", layout="mono", rate=24000)
    pcm_chunks = []

    for frame in container.decode(audio=0):
        converted = resampler.resample(frame)
        if isinstance(converted, list):
            for part in converted:
                arr = part.to_ndarray()
                if arr.ndim > 1:
                    arr = arr[0]
                pcm_chunks.append(np.ascontiguousarray(arr).tobytes())
        else:
            arr = converted.to_ndarray()
            if arr.ndim > 1:
                arr = arr[0]
            pcm_chunks.append(np.ascontiguousarray(arr).tobytes())

    pcm_bytes = b"".join(pcm_chunks)
    return pcm_bytes, 24000, 1



async def synthesize_edge_tts_bytes(text: str) -> bytes:
    """
    Synthesize speech using edge-tts and return audio bytes (mp3/webm).
    Args:
        text (str): Text to synthesize.
    Returns:
        bytes: Synthesized audio bytes.
    """
    voice = os.environ.get("EDGE_TTS_VOICE", "en-US-JennyNeural")
    rate = os.environ.get("EDGE_TTS_RATE", "+5%")
    volume = os.environ.get("EDGE_TTS_VOLUME", "+0%")

    communicate = edge_tts.Communicate(text=text, voice=voice, rate=rate, volume=volume)
    audio_data = bytearray()
    async for chunk in communicate.stream():
        if chunk.get("type") == "audio":
            audio_data.extend(chunk.get("data", b""))
    return bytes(audio_data)



def synthesize_text_to_pcm(text: str):
    """
    Synthesize text to in-memory PCM16 bytes for LiveKit playback.
    Args:
        text (str): Text to synthesize.
    Returns:
        dict or None: Dict with PCM bytes, sample rate, and channels, or None on error.
    """
    if not text or not text.strip():
        logger.warning("TTS synthesis skipped: empty text")
        return None

    try:
        with _tts_lock:
            audio_bytes = asyncio.run(synthesize_edge_tts_bytes(clean_tts_text(text)))
        if not audio_bytes:
            logger.error("TTS synthesis returned empty audio bytes")
            return None
        pcm_bytes, sample_rate, channels = decode_audio_to_pcm(audio_bytes)
        if not pcm_bytes:
            logger.error("TTS decode produced empty PCM")
            return None
        return {
            "pcm_bytes": pcm_bytes,
            "sample_rate": sample_rate,
            "channels": channels,
        }
    except Exception as e:
        logger.error(f"TTS synthesis error: {e}", exc_info=True)
        return None


def get_output_format():
    """
    Return the target playback format (sample rate, channels) for edge-tts path.
    Returns:
        tuple: (sample_rate, channels)
    """
    return 24000, 1
