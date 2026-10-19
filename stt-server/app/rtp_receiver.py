"""RTP v2 / G.711 μ-law receiver (20 ms packets, no dynamic PT guessing)."""
import asyncio
import struct
from dataclasses import dataclass
import numpy as np

@dataclass
class Packet:
    sequence: int
    timestamp: int
    ssrc: int
    payload: bytes

def parse_rtp(data: bytes) -> Packet:
    if len(data) < 12 or data[0] >> 6 != 2:
        raise ValueError('Invalid RTP v2 header')
    if data[1] & 127 != 0:
        raise ValueError('Only RTP PCMU payload type 0 is supported')
    offset = 12 + 4 * (data[0] & 15)
    if offset > len(data):
        raise ValueError('Truncated CSRC list')
    if data[0] & 16:
        if offset + 4 > len(data):
            raise ValueError('Truncated extension')
        offset += 4 + struct.unpack_from('!H', data, offset + 2)[0] * 4
    end = len(data)
    if data[0] & 32:
        padding = data[-1]
        if padding == 0 or padding > end - offset:
            raise ValueError('Invalid RTP padding')
        end -= padding
    if offset >= end:
        raise ValueError('Empty or truncated RTP payload')
    seq, timestamp, ssrc = struct.unpack_from('!HII', data, 2)
    return Packet(seq, timestamp, ssrc, data[offset:end])

def decode_ulaw(payload: bytes) -> np.ndarray:
    values = np.bitwise_not(np.frombuffer(payload, dtype=np.uint8)).astype(np.int32)
    magnitude = (((values & 15) << 3) + 132) << ((values >> 4) & 7)
    magnitude -= 132
    return np.where(values & 128, -magnitude, magnitude).astype(np.float32) / 32768.0

class RTPReceiver(asyncio.DatagramProtocol):
    def __init__(self, queue):
        self.queue = queue
        self.ssrc = None
        self.sequence = None
        self.next_timestamp = None
        self.stats = dict(packets=0, malformed=0, late=0, lost=0, overflow=0)

    def datagram_received(self, data, addr):
        try:
            packet = parse_rtp(data)
        except ValueError:
            self.stats['malformed'] += 1
            return
        if self.ssrc is not None and packet.ssrc != self.ssrc:
            self.stats['malformed'] += 1
            return
        if self.sequence is not None:
            delta = (packet.sequence - self.sequence) & 65535
            if delta == 0 or delta >= 32768:
                self.stats['late'] += 1
                return
            self.stats['lost'] += delta - 1
        samples = decode_ulaw(packet.payload)
        if self.next_timestamp is not None:
            gap = (packet.timestamp - self.next_timestamp) & 0xffffffff
            if 0 < gap <= 4000:
                samples = np.concatenate((np.zeros(gap, dtype=np.float32), samples))
        self.ssrc = packet.ssrc
        self.sequence = packet.sequence
        self.next_timestamp = (packet.timestamp + len(packet.payload)) & 0xffffffff
        self.stats['packets'] += 1
        try:
            self.queue.put_nowait(samples)
        except asyncio.QueueFull:
            self.stats['overflow'] += 1
