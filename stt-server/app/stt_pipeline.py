"""Shared CPU models, per-speaker online/VAD/resampler state.
All methods run on one dedicated inference executor, never the asyncio loop.
"""
from pathlib import Path
from collections import deque
import os
import re
import time
import numpy as np
import sherpa_onnx as sherpa
import soxr

class Engines:
    def __init__(self, root):
        root = Path(root)
        online = root / 'sherpa-onnx-streaming-zipformer-korean-2024-06-16'
        offline = root / 'sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17'
        def model(prefix):
            files = sorted(online.glob(prefix + '*.onnx'))
            quantized = [f for f in files if 'int8' in f.name]
            if not files:
                raise FileNotFoundError(f'Missing {prefix} in {online}; run download_models.py')
            return str((quantized or files)[0])
        self.online = sherpa.OnlineRecognizer.from_transducer(
            tokens=str(online / 'tokens.txt'), encoder=model('encoder'),
            decoder=model('decoder'), joiner=model('joiner'), num_threads=2,
            sample_rate=16000, feature_dim=80, decoding_method='greedy_search',
            enable_endpoint_detection=False)
        self.offline = sherpa.OfflineRecognizer.from_sense_voice(
            model=str(offline / 'model.int8.onnx'), tokens=str(offline / 'tokens.txt'),
            num_threads=2, language='ko', use_itn=True)
        self.vad_config = sherpa.VadModelConfig()
        self.vad_config.silero_vad.model = str(root / 'silero_vad.onnx')
        self.vad_config.silero_vad.min_silence_duration = 0.5
        self.vad_config.silero_vad.min_speech_duration = 0.2
        self.vad_config.silero_vad.max_speech_duration = 15
        self.vad_config.sample_rate = 16000

class Pipeline:
    def __init__(self, engines, call_id, speaker):
        self.engines = engines
        self.call_id = call_id
        self.speaker = speaker
        self.stream = engines.online.create_stream()
        self.vad = sherpa.VoiceActivityDetector(engines.vad_config, buffer_size_in_seconds=30)
        self.resampler = soxr.ResampleStream(8000, 16000, 1, dtype='float32')
        self.pending = np.empty(0, dtype=np.float32)
        self.segment = 0
        self.last_partial = ''
        self.audio_seconds = 0
        self.inference_seconds = 0
        self.rolling = deque(maxlen=250)  # 8 seconds at 512 samples / 16 kHz
        self.fallback_elapsed = 0
        self.fallback_enabled = os.getenv('PARTIAL_FALLBACK', '1') == '1'

    def event(self, kind, text, **extra):
        return dict(type=kind, call_id=self.call_id, speaker=self.speaker,
                    segment_id=self.segment, text=text, **extra)

    def feed(self, samples, final=False):
        start = time.monotonic()
        self.audio_seconds += len(samples) / 8000
        audio = self.resampler.resample_chunk(samples, last=final)
        if final:
            audio = np.concatenate((audio, np.zeros(16000, dtype=np.float32)))
        self.pending = np.concatenate((self.pending, audio))
        events = []
        window = self.engines.vad_config.silero_vad.window_size
        while len(self.pending) >= window:
            chunk, self.pending = self.pending[:window], self.pending[window:]
            self.stream.accept_waveform(16000, chunk)
            while self.engines.online.is_ready(self.stream):
                self.engines.online.decode_stream(self.stream)
            self.vad.accept_waveform(chunk)
            self.rolling.append(chunk.copy())
            self.fallback_elapsed += len(chunk)
            text = self.engines.online.get_result(self.stream).strip()
            if text and text != self.last_partial:
                self.last_partial = text
                events.append(self.event('partial', text, engine='zipformer'))
            if (not text and self.fallback_enabled and self.vad.is_speech_detected()
                    and self.fallback_elapsed >= 16000 and self.vad.empty()):
                self.fallback_elapsed = 0
                interim = self.engines.offline.create_stream()
                interim.accept_waveform(16000, np.concatenate(list(self.rolling)))
                self.engines.offline.decode_stream(interim)
                interim_text = re.sub(r'<\|[^|]+\|>', '', interim.result.text).strip()
                if interim_text and interim_text != self.last_partial:
                    self.last_partial = interim_text
                    events.append(self.event('partial', interim_text, engine='sensevoice-fallback'))
            events.extend(self.drain())
        if final:
            self.vad.flush()
            events.extend(self.drain())
        self.inference_seconds += time.monotonic() - start
        return events

    def drain(self):
        events = []
        while not self.vad.empty():
            samples = np.array(self.vad.front.samples, dtype=np.float32)
            self.vad.pop()
            stream = self.engines.offline.create_stream()
            stream.accept_waveform(16000, samples)
            start = time.monotonic()
            self.engines.offline.decode_stream(stream)
            result = stream.result
            text = re.sub(r'<\|[^|]+\|>', '', result.text).strip()
            emotion = re.sub(r'[<>|]', '', getattr(result, 'emotion', '') or '') or 'UNKNOWN'
            if emotion == 'EMO_UNKNOWN':
                emotion = 'UNKNOWN'
            acoustic_event = re.sub(r'[<>|]', '', getattr(result, 'event', '') or '')
            events.append(self.event('final', text, emotion=emotion, acoustic_event=acoustic_event,
                                     final_inference_ms=round((time.monotonic()-start)*1000, 1)))
            self.segment += 1
            self.stream = self.engines.online.create_stream()
            self.last_partial = ''
            self.rolling.clear()
            self.fallback_elapsed = 0
        return events
