import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from app.main import Audio, Session
from app.rtp_receiver import RTPReceiver


def session():
    queue = asyncio.Queue()
    return Session(12345, None, RTPReceiver(queue), queue,
                   SimpleNamespace(call_id='test-call', speaker='customer'))


class AudioLoggingTests(unittest.TestCase):
    def test_levels_reset_and_packet_deltas(self):
        s = session()
        previous = s.receiver.stats.copy()
        s.receiver.stats['packets'] = 2
        s.observe(np.array([0.5, -0.5], dtype=np.float32))
        with self.assertLogs('app.main', level='INFO') as logs:
            previous = s.report(previous, 1)
            s.observe(np.zeros(160, dtype=np.float32))
            previous = s.report(previous, 1)
            s.report(previous, 1)
        self.assertIn('state=signal packets=2', logs.output[0])
        self.assertIn('rms_dbfs=-6.0 peak=0.500000', logs.output[0])
        self.assertIn('state=digital_silence packets=0', logs.output[1])
        self.assertIn('rms_dbfs=-inf peak=0.000000', logs.output[1])
        self.assertIn('state=no_input', logs.output[2])


class AudioMonitorTests(unittest.IsolatedAsyncioTestCase):
    async def test_idle_interval_and_final_report(self):
        s = session()
        s.task = asyncio.create_task(asyncio.sleep(0))
        audio = Audio(None, None, None)
        with patch('app.main.asyncio.wait', side_effect=[(set(), {s.task}), ({s.task}, set())]), \
                self.assertLogs('app.main', level='INFO') as logs:
            await audio.monitor(s)
        await s.task
        self.assertEqual(len(logs.output), 2)
        self.assertIn('final=False', logs.output[0])
        self.assertIn('state=no_input', logs.output[0])
        self.assertIn('final=True', logs.output[1])


class RecognitionLoggingTests(unittest.IsolatedAsyncioTestCase):
    async def test_partials_logged_but_only_finals_published_including_flush(self):
        from unittest.mock import AsyncMock
        from app.main import Hub
        import json

        s = session()
        s.pipeline.feed = lambda *args: None
        s.queue.put_nowait(np.zeros(160, dtype=np.float32))
        s.queue.put_nowait(None)
        base = dict(call_id='test-call', speaker='customer', segment_id=0)
        events = [dict(base, type='partial', text='안녕', engine='zipformer'),
                  dict(base, type='partial', text='안녕하세요', engine='sensevoice-fallback'),
                  dict(base, type='final', text='안녕하세요')]
        flushed = dict(base, segment_id=1, type='final', text='감사합니다')
        hub = Hub()
        client = asyncio.Queue()
        hub.clients.add(client)
        audio = Audio(None, None, hub)
        audio.infer = AsyncMock(side_effect=[events, [flushed]])
        with self.assertLogs('app.main', level='INFO') as logs:
            await audio.worker(s)
        recorded = [json.loads(line.split('STT_RESULT ', 1)[1]) for line in logs.output]
        self.assertEqual(recorded, events + [flushed])
        self.assertEqual([e['text'] for e in hub.history], ['안녕하세요', '감사합니다'])
        self.assertTrue(all(e['type'] == 'final' for e in hub.history))
        self.assertEqual(client.qsize(), 2)
        self.assertTrue(audio.infer.call_args.args[-1])
