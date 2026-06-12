"""
voice.py — STT (Whisper) + TTS (edge-tts).

listen()  → records until silence, returns transcribed text
speak()   → synthesises text and plays audio
"""

from __future__ import annotations

import asyncio
import os
import tempfile

# ---------------------------------------------------------------------------
# STT — listen
# ---------------------------------------------------------------------------

_SAMPLE_RATE = 16000  # Hz — Whisper wants 16 kHz
_CHANNELS = 1
_SILENCE_THRESHOLD = 0.01  # RMS below this = silence
_SILENCE_SECONDS = 1.5  # seconds of silence to consider speech done
_MAX_SECONDS = 60  # hard cap on recording length


def listen(provider: str = "openai-whisper", model_name: str = "base", language: str = "pt") -> str:
    """
    Record from the microphone until silence, then transcribe.

    provider: "openai-whisper" | "faster-whisper"
    Returns the transcribed text (stripped).
    """
    audio_data = _record_until_silence()
    return _transcribe(audio_data, provider, model_name, language)


def _record_until_silence():
    import numpy as np
    import sounddevice as sd

    chunk_duration = 0.1  # seconds per chunk
    chunk_samples = int(_SAMPLE_RATE * chunk_duration)
    silence_chunks_needed = int(_SILENCE_SECONDS / chunk_duration)
    max_chunks = int(_MAX_SECONDS / chunk_duration)

    print("  [ouvindo...]", flush=True)

    frames = []
    silence_count = 0
    started_speaking = False

    with sd.InputStream(samplerate=_SAMPLE_RATE, channels=_CHANNELS, dtype="float32") as stream:
        for _ in range(max_chunks):
            chunk, _ = stream.read(chunk_samples)
            frames.append(chunk.copy())
            rms = float(np.sqrt(np.mean(chunk**2)))

            if rms > _SILENCE_THRESHOLD:
                started_speaking = True
                silence_count = 0
            elif started_speaking:
                silence_count += 1
                if silence_count >= silence_chunks_needed:
                    break

    print("  [processando...]", flush=True)
    return np.concatenate(frames, axis=0)


def _transcribe(audio, provider: str, model_name: str, language: str) -> str:
    import numpy as np

    audio_flat = audio.flatten().astype(np.float32)

    if provider == "faster-whisper":
        return _transcribe_faster_whisper(audio_flat, model_name, language)
    else:
        return _transcribe_openai_whisper(audio_flat, model_name, language)


def _transcribe_openai_whisper(audio, model_name: str, language: str) -> str:

    model = _get_whisper_model(model_name)
    result = model.transcribe(audio, language=language, fp16=False)
    return result["text"].strip()


_whisper_model_cache: dict[str, object] = {}


def _get_whisper_model(model_name: str):
    if model_name not in _whisper_model_cache:
        import whisper

        _whisper_model_cache[model_name] = whisper.load_model(model_name)
    return _whisper_model_cache[model_name]


def _transcribe_faster_whisper(audio, model_name: str, language: str) -> str:
    from faster_whisper import WhisperModel

    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    segments, _ = model.transcribe(audio, language=language)
    return " ".join(seg.text for seg in segments).strip()


# ---------------------------------------------------------------------------
# TTS — speak
# ---------------------------------------------------------------------------


def speak(
    text: str, voice: str = "pt-BR-FranciscaNeural", rate: str = "+0%", volume: str = "+0%"
) -> None:
    """
    Synthesise text with edge-tts and play it immediately.
    Blocks until playback is done.
    """
    asyncio.run(_speak_async(text, voice, rate, volume))


async def _speak_async(text: str, voice: str, rate: str, volume: str) -> None:
    import edge_tts

    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        communicate = edge_tts.Communicate(text, voice=voice, rate=rate, volume=volume)
        await communicate.save(tmp_path)
        _play_audio_file(tmp_path)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def _play_audio_file(path: str) -> None:
    """Play an audio file (mp3/wav) via sounddevice."""
    import sounddevice as sd
    import soundfile as sf

    # soundfile can't read mp3 natively — use pydub if available, else convert
    try:
        data, samplerate = sf.read(path, dtype="float32")
    except Exception:
        # Fallback: convert mp3 → wav via pydub
        try:
            from pydub import AudioSegment

            audio = AudioSegment.from_mp3(path)
            wav_path = path.replace(".mp3", ".wav")
            audio.export(wav_path, format="wav")
            data, samplerate = sf.read(wav_path, dtype="float32")
            os.unlink(wav_path)
        except Exception as e:
            print(f"  [TTS playback error: {e}]")
            return

    sd.play(data, samplerate)
    sd.wait()


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def ts() -> str:
    """Return current time as HH:MM:SS.mmm (12-char timestamp)."""
    from datetime import datetime

    now = datetime.now()
    return now.strftime("%H:%M:%S.") + f"{now.microsecond // 1000:03d}"


def strip_markdown(text: str) -> str:
    """Remove common markdown so TTS reads clean text."""
    import re

    text = re.sub(r"\*{1,3}(.+?)\*{1,3}", r"\1", text)  # bold / italic
    text = re.sub(r"#{1,6}\s*", "", text)  # headings
    text = re.sub(r"`{1,3}[^`]*`{1,3}", "", text)  # code
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)  # links
    text = re.sub(r"^[-*]\s+", "", text, flags=re.MULTILINE)  # list bullets
    text = re.sub(r"^>\s+", "", text, flags=re.MULTILINE)  # blockquotes
    text = re.sub(r"^---+$", "", text, flags=re.MULTILINE)  # hr
    return text


# ---------------------------------------------------------------------------
# Voice config helpers
# ---------------------------------------------------------------------------


def load_voice_config(providers_config: dict) -> dict:
    """Extract STT/TTS config from providers.yaml content."""
    stt = providers_config.get("stt", {})
    tts = providers_config.get("tts", {})
    return {
        "stt_provider": stt.get("provider", "openai-whisper"),
        "stt_model": stt.get("model", "base"),
        "stt_language": stt.get("language", "pt"),
        "tts_voice": tts.get("voice", "pt-BR-FranciscaNeural"),
        "tts_rate": tts.get("rate", "+0%"),
        "tts_volume": tts.get("volume", "+0%"),
    }
