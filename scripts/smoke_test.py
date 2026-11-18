"""Check the running local Compose services; optionally transcribe a Korean WAV."""

import argparse
import base64
import json
from pathlib import Path
import urllib.error
import urllib.request


def request_json(url, *, data=None, headers=None):
    request = urllib.request.Request(url, data=data, headers=headers or {})
    with urllib.request.urlopen(request, timeout=180) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", type=Path, help="16-bit PCM Korean WAV, up to 120 seconds / 16 MiB")
    args = parser.parse_args()
    path = Path(__file__).resolve().parents[1] / ".env"
    credentials = dict(
        line.split("=", 1) for line in path.read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )
    token = base64.b64encode(("router:" + credentials["ARI_PASSWORD"]).encode()).decode()
    info = request_json(
        "http://127.0.0.1:8088/ari/asterisk/info",
        headers={"Authorization": "Basic " + token},
    )
    print("ARI authenticated:", info["system"]["version"])

    health = request_json("http://127.0.0.1:8000/health")
    assert health["status"] == "ok" and health["device"] == "cpu"
    assert health["compute_type"] == "int8" and health["vad_filter"] is False
    print("Whisper ready:", health["model"], "CPU INT8, VAD disabled")

    try:
        request_json("http://127.0.0.1:8000/transcribe", data=b"invalid wav")
    except urllib.error.HTTPError as error:
        if error.code != 422:
            raise
        print("Invalid audio rejected: HTTP 422")
    else:
        raise AssertionError("Invalid audio was accepted")

    if args.audio:
        if args.audio.stat().st_size > 16 * 1024 * 1024:
            parser.error("Audio exceeds 16 MiB")
        result = request_json(
            "http://127.0.0.1:8000/transcribe", data=args.audio.read_bytes(),
            headers={"Content-Type": "audio/wav"},
        )
        assert isinstance(result["text"], str)
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
