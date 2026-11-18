"""Build the two fixed Korean prompts using macOS Yuna; no runtime TTS needed."""

from pathlib import Path
import shutil
import subprocess
import tempfile


def main():
    for command in ("say", "ffmpeg"):
        if not shutil.which(command):
            raise SystemExit(f"{command} is required to regenerate the checked-in WAV prompts")
    sounds = Path(__file__).resolve().parents[1] / "asterisk" / "sounds"
    with tempfile.TemporaryDirectory(prefix="fcr-prompts-") as directory:
        for name in ("greeting", "connecting"):
            source = sounds / f"{name}.txt"
            intermediate = Path(directory) / f"{name}.aiff"
            subprocess.run(["say", "-v", "Yuna", "-r", "170", "-f", str(source), "-o", str(intermediate)], check=True)
            target = sounds / f"{name}.wav"
            subprocess.run([
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(intermediate),
                "-ar", "8000", "-ac", "1", "-c:a", "pcm_s16le", "-map_metadata", "-1", str(target),
            ], check=True)
            print(f"Created {target.name}")


if __name__ == "__main__":
    main()
