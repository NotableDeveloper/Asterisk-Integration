"""Diagnostic: compare official Korean samples with INT8 and FP32 online models."""
from pathlib import Path
import wave
import numpy as np
import sherpa_onnx as s
root=Path('/models/sherpa-onnx-streaming-zipformer-korean-2024-06-16')
for suffix in ['.int8.onnx','.onnx']:
 r=s.OnlineRecognizer.from_transducer(tokens=str(root/'tokens.txt'),encoder=str(root/('encoder-epoch-99-avg-1'+suffix)),decoder=str(root/('decoder-epoch-99-avg-1'+suffix)),joiner=str(root/('joiner-epoch-99-avg-1'+suffix)),num_threads=2)
 for path in [root/'test_wavs/0.wav',Path('/models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17/test_wavs/ko.wav')]:
  with wave.open(str(path)) as w:
   rate=w.getframerate();audio=np.frombuffer(w.readframes(w.getnframes()),dtype='<i2').astype(np.float32)/32768
  stream=r.create_stream();stream.accept_waveform(rate,np.concatenate([audio,np.zeros(rate,dtype=np.float32)]));stream.input_finished()
  while r.is_ready(stream): r.decode_stream(stream)
  print(suffix,path.name,repr(r.get_result(stream)),flush=True)
