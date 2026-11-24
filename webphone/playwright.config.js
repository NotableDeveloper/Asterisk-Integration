import { defineConfig } from "@playwright/test";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

// A repeating synthetic microphone gives a real bidirectional media check.
const audioPath = path.join(os.tmpdir(), `fcr-webphone-mic-${process.pid}.wav`);
// Eight seconds of tone cover the greeting and exercise the microphone meter. Follow
// with a Korean inquiry, then enough silence to finish the call naturally.
const speech = fs.readFileSync(new URL("./tests/fixtures/inquiry.wav", import.meta.url));
const data = speech.indexOf("data");
const pcm = speech.subarray(data + 8, data + 8 + speech.readUInt32LE(data + 4));
const rate = speech.readUInt32LE(24);
const toneFrames = rate * 8;
const frames = toneFrames + pcm.length / 2 + rate * 12;
const wav = Buffer.alloc(44 + frames * 2);
wav.write("RIFF", 0); wav.writeUInt32LE(wav.length - 8, 4); wav.write("WAVEfmt ", 8);
wav.writeUInt32LE(16, 16); wav.writeUInt16LE(1, 20); wav.writeUInt16LE(1, 22);
wav.writeUInt32LE(rate, 24); wav.writeUInt32LE(rate * 2, 28);
wav.writeUInt16LE(2, 32); wav.writeUInt16LE(16, 34); wav.write("data", 36);
wav.writeUInt32LE(frames * 2, 40);
for (let i = 0; i < toneFrames; i++) wav.writeInt16LE(Math.round(12000 * Math.sin(2 * Math.PI * 440 * i / rate)), 44 + i * 2);
pcm.copy(wav, 44 + toneFrames * 2);
fs.writeFileSync(audioPath, wav);
process.on("exit", () => fs.rmSync(audioPath, { force: true }));

export default defineConfig({
  testDir: "./tests",
  workers: 1,
  timeout: 45000,
  expect: { timeout: 15000 },
  use: {
    baseURL: "http://localhost:8080",
    channel: "chrome",
    permissions: ["microphone"],
    launchOptions: { args: ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream", `--use-file-for-fake-audio-capture=${audioPath}`] },
    trace: "off",
  },
});
