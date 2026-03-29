
"""
stt.py
------
Speech-to-Text (STT) module for the eCommerce VoiceBot.
Uses faster-whisper to transcribe in-memory PCM audio to text.
Handles model loading, audio normalization, and transcription logic.
"""


import os
from logging_config import setup_logging
import numpy as np
from faster_whisper import WhisperModel

log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
logger = setup_logging("voicebot-agent", "stt.log", level=log_level)
# Cache for multiple models
_model_cache = {}


def _env_bool(name: str, default: bool = False) -> bool:
    """
    Helper to parse boolean environment variables.
    Args:
        name (str): Environment variable name.
        default (bool, optional): Default value if variable is not set. Defaults to False.
    Returns:
        bool: True for '1', 'true', 'yes', 'on' (case-insensitive), else False.
    """
    value = os.environ.get(name)
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}



def load_stt_model(model_name: str = None) -> WhisperModel:
    """
    Load and cache the faster-whisper model for STT.
    Args:
        model_name (str, optional): Name of the Whisper model to use. Defaults to None (uses env or 'base').
    Returns:
        WhisperModel: Loaded WhisperModel instance for the given model_name.
    """
    global _model_cache
    if model_name is None:
        model_name = os.environ.get("WHISPER_MODEL", "base")
    if model_name not in _model_cache:
        device = os.environ.get("FASTER_WHISPER_DEVICE", "cpu")
        compute_type = os.environ.get("FASTER_WHISPER_COMPUTE_TYPE", "int8")
        logger.info(f"[STT] Loading faster-whisper '{model_name}' ({device}/{compute_type})...")
        _model_cache[model_name] = WhisperModel(model_name, device=device, compute_type=compute_type)
        logger.info(f"[STT] Model '{model_name}' loaded")
    return _model_cache[model_name]



def transcribe_audio_to_text(audio_bytes: bytes, sample_rate: int, channels: int = 1, model_name: str = None):
    """
    Transcribe raw PCM16 audio bytes to text using faster-whisper.
    Handles mono conversion, downsampling, and speech/no-speech filtering.
    Args:
        audio_bytes (bytes): Raw PCM16 audio bytes.
        sample_rate (int): Audio sample rate.
        channels (int, optional): Number of audio channels. Defaults to 1.
        model_name (str, optional): Name of the Whisper model to use (e.g., 'tiny', 'base').
    Returns:
        str or None: Transcribed text string, or None if rejected.
    """
    try:
        model = load_stt_model(model_name)
        audio = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        # Mix down to mono if needed
        if channels > 1:
            audio = audio.reshape(-1, channels).mean(axis=1)
        # Downsample to 16kHz (faster-whisper expects 16kHz input)
        if sample_rate == 48000:
            audio = audio[::3]
        elif sample_rate != 16000:
            new_len = max(1, int(len(audio) * 16000 / sample_rate))
            audio = np.interp(
                np.linspace(0, len(audio) - 1, new_len),
                np.arange(len(audio)),
                audio,
            ).astype(np.float32)
        min_samples = int(os.environ.get("STT_MIN_SAMPLES", "6000"))
        if len(audio) < min_samples:
            logger.debug(f"[STT] Audio too short ({len(audio)} samples), skipping")
            return None
        logger.info(f"[STT] Transcribing {len(audio)} samples...")
        initial_prompt = os.environ.get(
            "STT_INITIAL_PROMPT",
            "Order IDs are usually five digits. Product names include Smartphone X, Laptop Pro, Wireless Headphones, Phone Case, and Tablet Ultra.",
        )
        segments, _ = model.transcribe(
            audio,
            language="en",
            beam_size=max(1, int(os.environ.get("STT_BEAM_SIZE", "2"))),
            best_of=max(1, int(os.environ.get("STT_BEST_OF", "2"))),
            vad_filter=_env_bool("STT_VAD_FILTER", True),
            condition_on_previous_text=False,
            initial_prompt=initial_prompt,
        )
        parts = []
        no_speech_probs = []
        for seg in segments:
            if seg.text and seg.text.strip():
                parts.append(seg.text.strip())
            if hasattr(seg, "no_speech_prob") and seg.no_speech_prob is not None:
                no_speech_probs.append(float(seg.no_speech_prob))
        # Reject if whisper's own no-speech confidence is too high
        if no_speech_probs:
            threshold = float(os.environ.get("STT_NO_SPEECH_THRESHOLD", "0.7"))
            avg = sum(no_speech_probs) / len(no_speech_probs)
            if avg > threshold:
                logger.info(f"[STT] Rejected — avg no_speech_prob={avg:.2f} > {threshold}")
                return None
        text = " ".join(parts).strip()
        if not text:
            logger.warning("[STT] Empty transcription result")
            return None
        logger.info(f"[STT] Result: '{text}'")
        return text
    except Exception as e:
        logger.error(f"[STT] Exception: {e}", exc_info=True)
        return None
        logger.error(f"[STT] Error: {e}")
        return None
