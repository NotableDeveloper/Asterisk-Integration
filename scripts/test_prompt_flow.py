"""Exercise the real Asterisk prompt flow with synthetic caller audio via Local channels.

Requires running Compose services and scripts/requirements-test.txt. No SIP phone
or external call is used. Each test owns and cleans up its own channels and WAV.
"""

import array
import base64
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import wave

from websockets.sync.client import connect


ROOT = Path(__file__).resolve().parents[1]


def main():
    credentials = dict(
        line.split("=", 1) for line in (ROOT / ".env").read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )
    token = base64.b64encode(("router:" + credentials["ARI_PASSWORD"]).encode()).decode()
    headers = {"Authorization": "Basic " + token}

    def api(method, path, **params):
        url = "http://127.0.0.1:8088/ari" + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        request = urllib.request.Request(url, method=method, headers=headers)
        with urllib.request.urlopen(request, timeout=10) as response:
            body = response.read()
            return json.loads(body) if body else None

    with wave.open(str(ROOT / "asterisk/sounds/greeting.wav")) as file:
        greeting_seconds = file.getnframes() / file.getframerate()

    def scenario(name, sections, expect_routing):
        suffix = uuid.uuid4().hex
        app = "prompt-test-" + suffix
        channel_ids = {"test-" + suffix, "peer-" + suffix}
        caller_id, inbound_id = "test-" + suffix, "peer-" + suffix
        remote = "/tmp/fcr-test-" + suffix + ".wav"
        stages = {}
        played_at = None
        deadline = time.monotonic() + 80
        with tempfile.TemporaryDirectory(prefix="fcr-call-test-") as directory:
            source = Path(directory) / "caller.wav"
            samples = array.array("h")
            for seconds, frequency in [(greeting_seconds + 4, 0), *sections]:
                samples.extend(
                    int(10000 * math.sin(2 * math.pi * frequency * i / 8000))
                    for i in range(round(seconds * 8000))
                )
            if sys.byteorder != "little":
                samples.byteswap()
            with wave.open(str(source), "wb") as file:
                file.setnchannels(1)
                file.setsampwidth(2)
                file.setframerate(8000)
                file.writeframes(samples.tobytes())
            subprocess.run(["docker", "compose", "cp", str(source), "asterisk:" + remote], cwd=ROOT, check=True, capture_output=True)
            query = urllib.parse.urlencode({"app": app, "subscribeAll": "true"})
            try:
                with connect("ws://127.0.0.1:8088/ari/events?" + query, additional_headers=headers, proxy=None) as events:
                    api("POST", "/channels", endpoint="Local/7000@from-internal/n", app=app,
                        channelId=caller_id, otherChannelId=inbound_id)
                    while time.monotonic() < deadline:
                        event = json.loads(events.recv(timeout=50))
                        channel = event.get("channel", {}).get("id")
                        if channel not in channel_ids:
                            continue
                        if event["type"] == "StasisStart" and channel == caller_id:
                            played_at = time.monotonic()
                            api("POST", f"/channels/{caller_id}/play", media="sound:" + remote[:-4])
                        if event["type"] == "ChannelVarset" and event.get("variable") == "FCR_STAGE":
                            stage = event["value"]
                            stages[stage] = time.monotonic()
                            print(name, stage, flush=True)
                            if stage in ("FAILED", "INCOMPLETE"):
                                raise AssertionError(f"Unexpected stage: {stage}")
                            if stage == "CONNECTING_PROMPT":
                                assert expect_routing, "Routing prompt played without caller speech"
                                # 4s initial silence + 1s tone + 2s pause + 1s tone.
                                silence_wait = stages[stage] - (played_at + greeting_seconds + 8)
                                assert 2.7 <= silence_wait <= 3.8, silence_wait
                                print(f"Post-speech silence: {silence_wait:.3f}s", flush=True)
                            if stage == "NO_INPUT":
                                assert not expect_routing
                                assert "CONNECTING_PROMPT" not in stages
                                print("No-input call did not play the connecting prompt", flush=True)
                                return
                            if stage == "AWAITING_ROUTER" and channel == inbound_id:
                                assert expect_routing and "CONNECTING_PROMPT" in stages
                                assert stages["SPEECH_STARTED"] - stages["LISTENING"] >= 3.5
                                print("Both prompts completed; short pause did not finish the inquiry", flush=True)
                                return
                    raise AssertionError("Call flow did not complete")
            finally:
                for channel in channel_ids:
                    try:
                        api("DELETE", "/channels/" + channel)
                    except urllib.error.HTTPError as error:
                        if error.code != 404:
                            raise
                subprocess.run(["docker", "compose", "exec", "-T", "asterisk", "unlink", remote], cwd=ROOT, check=True, capture_output=True)

    scenario("speech-with-pause", [(1, 440), (2, 0), (1, 660), (5, 0)], True)
    scenario("no-speech", [(35, 0)], False)
    print("Asterisk prompt flow: 2 scenarios passed", flush=True)


if __name__ == "__main__":
    main()
