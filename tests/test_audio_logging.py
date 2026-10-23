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
