#!/usr/bin/env python3
"""Convert the official Korean sample to Asterisk PCM16 mono 8k WAV."""
import argparse
from pathlib import Path
import wave
import numpy as np
import soxr

parser = argparse.ArgumentParser()
parser.add_argument('--source', default='/models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17/test_wavs/ko.wav')
parser.add_argument('--output', default='/output/ko.wav')
args = parser.parse_args()
with wave.open(args.source, 'rb') as stream:
    if stream.getsampwidth() != 2 or stream.getnchannels() != 1:
        raise ValueError('Expected mono PCM16 WAV')
    audio = np.frombuffer(stream.readframes(stream.getnframes()), dtype='<i2').astype(np.float32) / 32768
    audio = soxr.resample(audio, stream.getframerate(), 8000)
Path(args.output).parent.mkdir(parents=True, exist_ok=True)
with wave.open(args.output, 'wb') as stream:
    stream.setnchannels(1)
    stream.setsampwidth(2)
    stream.setframerate(8000)
    stream.writeframes((np.clip(audio, -1, 32767/32768) * 32768).astype('<i2').tobytes())
print(f'Created {args.output}: {len(audio)/8000:.2f}s; source={args.source}')
