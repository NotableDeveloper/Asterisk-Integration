import asyncio
import struct
import unittest
import numpy as np
from app.rtp_receiver import parse_rtp, decode_ulaw, RTPReceiver

def packet(seq=1, timestamp=0, payload=b'\xff'*160, first=128, pt=0):
    return struct.pack('!BBHII', first, pt, seq, timestamp, 42) + payload

class RTPTests(unittest.TestCase):
    def test_pcmu_known_values(self):
        np.testing.assert_allclose(decode_ulaw(bytes([255,127,0,128])), [0,0,-32124/32768,32124/32768])

    def test_csrc_extension_padding(self):
        raw=packet(first=0xb1, payload=struct.pack('!IHHI', 7, 1, 1, 8)+b'abc'+b'\0\0\0\4')
        self.assertEqual(parse_rtp(raw).payload,b'abc')

    def test_rejects_invalid(self):
        for raw in [b'', packet(first=0), packet(pt=8), packet(first=0x90,payload=b'\0'), packet(first=0xa0,payload=b'\0')]:
            with self.assertRaises(ValueError): parse_rtp(raw)

    def test_wrap_loss_late_and_queue_bound(self):
        queue=asyncio.Queue(maxsize=2); receiver=RTPReceiver(queue)
        receiver.datagram_received(packet(65535,0),None)
        receiver.datagram_received(packet(1,320),None)
        self.assertEqual(len(queue.get_nowait()),160)
        self.assertEqual(len(queue.get_nowait()),320)
        receiver.datagram_received(packet(0,160),None)
        receiver.datagram_received(packet(1,320),None)
        self.assertEqual(receiver.stats['late'],2)
        self.assertEqual(receiver.stats['lost'],1)
        for i in range(2,5): receiver.datagram_received(packet(i,i*160),None)
        self.assertEqual(receiver.stats['overflow'],1)

    def test_malformed_and_ssrc(self):
        q=asyncio.Queue(); r=RTPReceiver(q)
        r.datagram_received(b'bad',None)
        r.datagram_received(packet(),None)
        raw=bytearray(packet(2,160));struct.pack_into('!I',raw,8,99)
        r.datagram_received(raw,None)
        self.assertEqual(r.stats['malformed'],2)
        self.assertEqual(q.qsize(),1)

if __name__=='__main__': unittest.main()
