import asyncio
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
import logging
import json
import math
import os
from pathlib import Path
import time
import uuid
import aiohttp
import numpy as np
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from .ari_client import ARI
from .rtp_receiver import RTPReceiver
from .stt_pipeline import Engines, Pipeline

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

class Hub:
    def __init__(self):
        self.clients = set()
        self.history = deque(maxlen=300)
        self.sequence = 0
        self.epoch = uuid.uuid4().hex

    async def publish(self, event):
        self.sequence += 1
        event = {**event, 'id': self.sequence, 'time': time.time()}
        self.history.append(event)
        for queue in list(self.clients):
            if queue.full():
                # Disconnect a slow consumer rather than accumulate unbounded audio text.
                self.clients.discard(queue)
                while not queue.empty():
                    queue.get_nowait()
                queue.put_nowait(None)
            else:
                queue.put_nowait(event)

@dataclass(eq=False)
class Session:
    port: int
    transport: object
    receiver: RTPReceiver
    queue: asyncio.Queue
    pipeline: Pipeline
    task: asyncio.Task | None = None
    monitor: asyncio.Task | None = None
    input_samples: int = 0
    input_energy: float = 0
    input_peak: float = 0

    def observe(self, samples):
        # Measure the decoded 8 kHz PCM actually handed to Pipeline.feed.
        self.input_samples += samples.size
        self.input_energy += float(np.dot(samples, samples))
        if samples.size:
            self.input_peak = max(self.input_peak, float(np.max(np.abs(samples))))

    def report(self, previous, elapsed, final=False):
        delta = {key: value - previous[key] for key, value in self.receiver.stats.items()}
        rms = math.sqrt(self.input_energy / self.input_samples) if self.input_samples else 0
        level = f'{20 * math.log10(rms):.1f}' if rms else '-inf'
        state = ('no_input' if not self.input_samples else
                 'digital_silence' if not self.input_peak else 'signal')
        log.info(
            'STT_AUDIO call_id=%s speaker=%s port=%d final=%s interval_s=%.2f '
            'state=%s packets=%d malformed=%d late=%d lost=%d overflow=%d '
            'input_samples=%d input_seconds=%.3f rms_dbfs=%s peak=%.6f queue=%d',
            self.pipeline.call_id, self.pipeline.speaker, self.port, final, elapsed,
            state, delta['packets'], delta['malformed'], delta['late'], delta['lost'],
            delta['overflow'], self.input_samples, self.input_samples / 8000,
            level, self.input_peak, self.queue.qsize())
        self.input_samples = 0
        self.input_energy = 0
        self.input_peak = 0
        return self.receiver.stats.copy()

class Audio:
    def __init__(self, engines, executor, hub):
        self.engines, self.executor, self.hub = engines, executor, hub
        self.sessions = set()

    async def infer(self, function, *args):
        return await asyncio.get_running_loop().run_in_executor(self.executor, function, *args)

    async def open(self, call_id, speaker):
        pipeline = await self.infer(Pipeline, self.engines, call_id, speaker)
        queue = asyncio.Queue(maxsize=100)
        transport, receiver = await asyncio.get_running_loop().create_datagram_endpoint(
            lambda: RTPReceiver(queue), local_addr=('0.0.0.0', 0))
        session = Session(transport.get_extra_info('sockname')[1], transport, receiver, queue, pipeline)
        self.sessions.add(session)
        session.task = asyncio.create_task(self.worker(session))
        session.monitor = asyncio.create_task(self.monitor(session))
        return session

    async def monitor(self, session):
        previous = dict.fromkeys(session.receiver.stats, 0)
        last = time.monotonic()
        while True:
            done, _ = await asyncio.wait({session.task}, timeout=1)
            now = time.monotonic()
            previous = session.report(previous, now - last, final=bool(done))
            last = now
            if done:
                return

    async def worker(self, session):
        try:
            while True:
                samples = await session.queue.get()
                final = samples is None
                if not final:
                    session.observe(samples)
                for event in await self.infer(session.pipeline.feed, np.empty(0, dtype=np.float32) if final else samples, final):
                    log.info('STT_RESULT %s', json.dumps(event, ensure_ascii=False))
                    if event['type'] == 'final':
                        await self.hub.publish(event)
                if final:
                    break
        except Exception:
            log.exception('Audio worker failed')
            await self.hub.publish(dict(type='error', call_id=session.pipeline.call_id, text='음성 처리 실패: 서버 로그를 확인하세요.'))

    async def close(self, session):
        session.transport.close()
        if not session.task.done():
            await session.queue.put(None)
        await session.task
        await session.monitor
        self.sessions.discard(session)
        p = session.pipeline
        await self.hub.publish(dict(type='metrics', call_id=p.call_id, speaker=p.speaker,
                                   **session.receiver.stats, audio_seconds=round(p.audio_seconds, 3),
                                   inference_seconds=round(p.inference_seconds, 3),
                                   rtf=round(p.inference_seconds / p.audio_seconds, 3) if p.audio_seconds else None))

hub = Hub()

@asynccontextmanager
async def lifespan(app):
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='inference')
    try:
        engines = await asyncio.get_running_loop().run_in_executor(executor, Engines, os.getenv('MODEL_ROOT', '/models'))
        app.state.audio = Audio(engines, executor, hub)
        app.state.ari = ARI(app.state.audio, hub.publish)
        task = asyncio.create_task(app.state.ari.run())
        yield
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
    finally:
        executor.shutdown(wait=True)

app = FastAPI(title='Local Agent Assist', lifespan=lifespan)
app.mount('/static', StaticFiles(directory=Path(__file__).resolve().parents[1] / 'static'), name='static')

@app.get('/')
async def index():
    return FileResponse(Path(__file__).resolve().parents[1] / 'static' / 'index.html',
                        headers={'Cache-Control': 'no-cache'})

@app.get('/health/ready')
async def ready():
    ari = app.state.ari
    return JSONResponse({'ready': ari.connected, 'ari_connected': ari.connected,
                         'active_calls': len(ari.calls), 'audio_sessions': len(app.state.audio.sessions)},
                        status_code=200 if ari.connected else 503)

@app.delete('/api/calls/{call_id}')
async def stop(call_id: str):
    if call_id not in app.state.ari.calls:
        raise HTTPException(404, 'Unknown call')
    await app.state.ari.cleanup(call_id)
    return {'stopped': call_id}

@app.websocket('/ws')
async def websocket(ws: WebSocket):
    await ws.accept()
    queue = asyncio.Queue(maxsize=100)
    hub.clients.add(queue)
    async def send():
        await ws.send_json({'type': 'snapshot', 'epoch': hub.epoch, 'events': list(hub.history)})
        while True:
            event = await queue.get()
            if event is None:
                await ws.close(code=1013)
                return
            await ws.send_json(event)
    async def receive():
        while True:
            await ws.receive_text()
    tasks = [asyncio.create_task(send()), asyncio.create_task(receive())]
    try:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            with suppress(WebSocketDisconnect):
                task.result()
    finally:
        hub.clients.discard(queue)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


@app.websocket('/sip')
async def sip_proxy(ws: WebSocket):
    """Same-origin SIP-only WebSocket relay; never exposes ARI credentials/API."""
    origin = ws.headers.get('origin')
    if origin not in {f'http://{ws.headers.get("host")}', f'https://{ws.headers.get("host")}'}:
        await ws.close(code=1008)
        return
    if 'sip' not in ws.headers.get('sec-websocket-protocol', '').split(', '):
        await ws.close(code=1008)
        return
    await ws.accept(subprotocol='sip')
    target = os.getenv('SIP_WS_URL', 'http://asterisk:8088/ws')
    async with aiohttp.ClientSession() as client:
        try:
            async with client.ws_connect(target, protocols=('sip',), max_msg_size=65536) as upstream:
                async def to_asterisk():
                    while True:
                        message = await ws.receive_text()
                        if len(message) > 65536:
                            await ws.close(code=1009)
                            return
                        await upstream.send_str(message)
                async def to_browser():
                    async for message in upstream:
                        if message.type == aiohttp.WSMsgType.TEXT:
                            await ws.send_text(message.data)
                        elif message.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.ERROR):
                            break
                tasks = [asyncio.create_task(to_asterisk()), asyncio.create_task(to_browser())]
                try:
                    done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                    for task in done:
                        with suppress(WebSocketDisconnect):
                            task.result()
                finally:
                    for task in tasks:
                        task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
        except (aiohttp.ClientError, OSError):
            log.warning('SIP WebSocket upstream unavailable')
        finally:
            with suppress(RuntimeError, WebSocketDisconnect):
                await ws.close(code=1001)
