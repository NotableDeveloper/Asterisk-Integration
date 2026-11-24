"""Local single-model CPU transcription service; no VAD or routing logic."""

import asyncio
from contextlib import asynccontextmanager, suppress
from pathlib import Path
import re
import io
import logging
import time
import wave

from fastapi import FastAPI, HTTPException, Request
from faster_whisper import WhisperModel
from huggingface_hub import snapshot_download
from starlette.concurrency import run_in_threadpool


MODEL_ID = "Systran/faster-whisper-small"
MODEL_REVISION = "536b0662742c02347bc0e980a01041f333bce120"
MAX_BYTES = 16 * 1024 * 1024
MAX_SECONDS = 120
INQUIRIES = Path("/inquiries")
RESULT_TTL = 300
logger = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Loading multilingual Whisper small, device=cpu, compute_type=int8")
    model_path = snapshot_download(
        MODEL_ID,
        revision=MODEL_REVISION,
        allow_patterns=["config.json", "model.bin", "tokenizer.json", "vocabulary.*", "preprocessor_config.json"],
    )
    app.state.model = WhisperModel(
        model_path, device="cpu", compute_type="int8", cpu_threads=4,
        num_workers=1, local_files_only=True,
    )
    app.state.inference_lock = asyncio.Lock()
    logger.info("Whisper model ready")
    app.state.results = {}
    worker = asyncio.create_task(process_inquiries(app))
    try:
        yield
    finally:
        worker.cancel()
        with suppress(asyncio.CancelledError):
            await worker
        del app.state.model


app = FastAPI(title="Fast Contact Router — Whisper", lifespan=lifespan)


@app.get("/health")
async def health():
    return {
        "status": "ok", "model": MODEL_ID, "revision": MODEL_REVISION,
        "device": "cpu", "compute_type": "int8", "vad_filter": False,
    }


def validate_wav(audio: bytes, max_seconds: int = MAX_SECONDS) -> float:
    try:
        with wave.open(io.BytesIO(audio), "rb") as file:
            if file.getsampwidth() != 2 or file.getnchannels() not in (1, 2):
                raise HTTPException(422, "WAV must be 16-bit PCM, mono or stereo")
            if not 8000 <= file.getframerate() <= 48000:
                raise HTTPException(422, "WAV sample rate must be 8000–48000 Hz")
            duration = file.getnframes() / file.getframerate()
            if not 0 < duration <= max_seconds:
                raise HTTPException(422, f"WAV duration must be greater than 0 and at most {max_seconds} seconds")
            expected = file.getnframes() * file.getnchannels() * file.getsampwidth()
            if len(file.readframes(file.getnframes())) != expected:
                raise HTTPException(422, "Truncated WAV data")
            return duration
    except (wave.Error, EOFError) as error:
        raise HTTPException(422, "Invalid PCM WAV file") from error


def transcribe(model: WhisperModel, audio: bytes, duration: float):
    started = time.monotonic()
    segments, _ = model.transcribe(
        io.BytesIO(audio), language="ko", task="transcribe", beam_size=1,
        vad_filter=False, condition_on_previous_text=False,
    )
    text = "".join(segment.text for segment in segments).strip()
    return {"text": text, "language": "ko", "audio_seconds": duration,
            "processing_seconds": round(time.monotonic() - started, 3)}


@app.post("/transcribe")
async def transcribe_audio(request: Request):
    # Reject rather than build an unbounded inference queue.
    lock = request.app.state.inference_lock
    if lock.locked():
        raise HTTPException(429, "Whisper is busy; retry later", headers={"Retry-After": "1"})
    async with lock:
        audio = bytearray()
        async for chunk in request.stream():
            if len(audio) + len(chunk) > MAX_BYTES:
                raise HTTPException(413, "Audio exceeds 16 MiB")
            audio.extend(chunk)
        data = bytes(audio)
        duration = validate_wav(data)
        try:
            return await run_in_threadpool(transcribe, request.app.state.model, data, duration)
        except Exception as error:
            # Do not include customer text/audio in logs or API errors.
            logger.error("Whisper inference failed (%s)", type(error).__name__)
            raise HTTPException(500, "Transcription failed") from error


def transcribe_recording(model, path):
    audio = path.read_bytes()
    # The recording includes the initial 30s wait and the 120s speech window.
    duration = validate_wav(audio, max_seconds=152)
    return transcribe(model, audio, duration)


async def process_inquiries(app):
    while True:
        for key, (expires, _) in list(app.state.results.items()):
            if expires <= time.monotonic():
                del app.state.results[key]
        for path in sorted(INQUIRIES.glob("ready-*.wav"), key=lambda p: p.stat().st_mtime):
            key = path.name.split("-", 2)[1]
            try:
                async with app.state.inference_lock:
                    result = await run_in_threadpool(transcribe_recording, app.state.model, path)
                payload = {"status": "done", **result}
            except Exception:
                logger.exception("Call recording transcription failed")
                payload = {"status": "failed"}
            if key != "internal":
                app.state.results[key] = (time.monotonic() + RESULT_TTL, payload)
            path.unlink(missing_ok=True)
        await asyncio.sleep(0.5)


@app.get("/inquiries/{key}")
async def inquiry_result(key: str):
    if not re.fullmatch(r"[0-9a-f]{32}", key):
        raise HTTPException(404)
    entry = app.state.results.get(key)
    if entry and entry[0] > time.monotonic():
        return entry[1]
    if any(INQUIRIES.glob(f"ready-{key}-*.wav")):
        return {"status": "processing"}
    raise HTTPException(404)
