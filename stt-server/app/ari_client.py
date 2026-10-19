"""ARI lifecycle: originals → per-speaker snoop + isolated media bridge."""
import asyncio
import logging
import os
import uuid
from dataclasses import dataclass, field
import aiohttp

log = logging.getLogger(__name__)
APP = 'agent-assist'

def uid(prefix):
    return prefix + '-' + uuid.uuid4().hex

@dataclass
class Call:
    id: str
    channels: set = field(default_factory=set)
    bridges: set = field(default_factory=set)
    sessions: list = field(default_factory=list)

class ARI:
    def __init__(self, audio, publish):
        self.audio = audio
        self.publish = publish
        self.url = os.getenv('ARI_URL', 'http://asterisk:8088/ari')
        self.calls = {}
        self.originals = {}
        self.connected = False
        self.http = None

    async def request(self, method, path, **params):
        async with self.http.request(method, self.url + path, params=params) as resp:
            if method == 'DELETE' and resp.status == 404:
                return None
            if resp.status >= 400:
                raise RuntimeError(f'ARI {method} {path}: HTTP {resp.status} {(await resp.text())[:200]}')
            if resp.status == 204:
                return None
            return await resp.json()

    async def run(self):
        auth = aiohttp.BasicAuth(os.getenv('ARI_USER', 'assist'), os.getenv('ARI_PASSWORD', 'local-demo-ari'))
        async with aiohttp.ClientSession(auth=auth, timeout=aiohttp.ClientTimeout(total=10)) as self.http:
            try:
                while True:
                    try:
                        async with self.http.ws_connect(self.url + '/events', params={'app': APP}, heartbeat=20) as ws:
                            self.connected = True
                            log.info('ARI connected')
                            async for msg in ws:
                                if msg.type == aiohttp.WSMsgType.TEXT:
                                    event = msg.json()
                                    try:
                                        await self.handle(event)
                                    except Exception:
                                        log.exception('ARI event failed: %s', event.get('type'))
                                        channel = event.get('channel', {}).get('id')
                                        call_id = self.originals.get(channel)
                                        if call_id:
                                            await self.cleanup(call_id)
                                elif msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSED):
                                    break
                    except (aiohttp.ClientError, OSError, asyncio.TimeoutError):
                        log.warning('ARI unavailable; retrying in 2 seconds')
                    finally:
                        self.connected = False
                        for call_id in list(self.calls):
                            await self.cleanup(call_id)
                    await asyncio.sleep(2)
            finally:
                self.connected = False
                for call_id in list(self.calls):
                    await self.cleanup(call_id)

    async def handle(self, event):
        kind = event['type']
        channel = event.get('channel', {})
        channel_id = channel.get('id', '')
        if kind in ('StasisEnd', 'ChannelDestroyed'):
            if channel_id in self.originals:
                await self.cleanup(self.originals[channel_id])
            return
        if kind != 'StasisStart':
            return
        args = event.get('args', [])
        if not args or args[0] == 'internal':
            return
        if args[0] == 'peer':
            call_id, speaker = args[1:3]
            call = self.calls.get(call_id)
            if not call:
                await self.request('DELETE', f'/channels/{channel_id}')
                return
            call.channels.add(channel_id)
            self.originals[channel_id] = call_id
            await self.request('POST', f'/bridges/{call_id}/addChannel', channel=channel_id)
            await self.attach(call, channel_id, speaker)
            return
        if len(self.calls) >= 2:
            await self.request('DELETE', f'/channels/{channel_id}')
            return
        call = Call(channel_id)
        self.calls[call.id] = call
        call.channels.add(channel_id)
        self.originals[channel_id] = call.id
        await self.publish(dict(type='call_started', call_id=call.id))
        await self.request('POST', f'/channels/{channel_id}/answer')
        role = args[0]
        if role == 'microphone':
            await self.attach(call, channel_id, 'customer', spy='in')
            # Generate silence to keep media flowing while the browser speaks.
            await self.request('POST', f'/channels/{channel_id}/silence')
            return
        if role in ('demo', 'demo-local'):
            await self.attach(call, channel_id, 'customer', spy='out' if role == 'demo' else 'in')
            if role == 'demo':
                await self.request('POST', f'/channels/{channel_id}/play', media='sound:custom/ko')
            return
        await self.request('POST', f'/bridges/{call.id}', type='mixing,proxy_media')
        call.bridges.add(call.id)
        await self.request('POST', f'/bridges/{call.id}/addChannel', channel=channel_id)
        await self.attach(call, channel_id, role)
        peer_id = uid('peer')
        call.channels.add(peer_id)
        self.originals[peer_id] = call.id
        await self.request('POST', '/channels', endpoint='PJSIP/' + args[1],
                           channelId=peer_id, app=APP, appArgs=f'peer,{call.id},{"agent" if role == "customer" else "customer"}', timeout=30)

    async def attach(self, call, original, speaker, spy='in'):
        session = await self.audio.open(call.id, speaker)
        call.sessions.append(session)
        snoop, external, bridge = uid('snoop'), uid('media'), uid('tap')
        # Register IDs before requests so partial setup is always cleaned up.
        call.channels.update((snoop, external))
        call.bridges.add(bridge)
        await self.request('POST', f'/channels/{original}/snoop/{snoop}', spy=spy, whisper='none', app=APP, appArgs='internal')
        await self.request('POST', '/channels/externalMedia', channelId=external, app=APP,
                           external_host=f'{os.getenv("RTP_HOST", "stt")}:{session.port}',
                           format='ulaw', encapsulation='rtp', transport='udp', connection_type='client', direction='both', data='internal')
        await self.request('POST', f'/bridges/{bridge}', type='mixing,proxy_media')
        await self.request('POST', f'/bridges/{bridge}/addChannel', channel=snoop + ',' + external)

    async def cleanup(self, call_id):
        call = self.calls.pop(call_id, None)
        if not call:
            return
        for channel in call.channels:
            self.originals.pop(channel, None)
            try:
                await self.request('DELETE', f'/channels/{channel}')
            except Exception:
                log.warning('Could not delete channel %s', channel)
        for bridge in call.bridges:
            try:
                await self.request('DELETE', f'/bridges/{bridge}')
            except Exception:
                log.warning('Could not delete bridge %s', bridge)
        for session in call.sessions:
            await self.audio.close(session)
        await self.publish(dict(type='call_ended', call_id=call_id))

    async def demo(self):
        if not self.connected:
            raise RuntimeError('ARI is not connected')
        channel = uid('demo')
        await self.request('POST', '/channels', endpoint='Local/9999@sample/n', channelId=channel,
                           app=APP, appArgs='demo-local', timeout=30, formats='ulaw')
        return channel
