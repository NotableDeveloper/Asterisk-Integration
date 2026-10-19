import unittest
from types import SimpleNamespace
from app.ari_client import ARI, Call

class Audio:
    def __init__(self): self.opened=[];self.closed=[]
    async def open(self, call, speaker):
        session=SimpleNamespace(port=20000+len(self.opened),speaker=speaker)
        self.opened.append(session);return session
    async def close(self, session): self.closed.append(session)

class ARITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.audio=Audio();self.events=[];self.requests=[]
        async def publish(e): self.events.append(e)
        self.ari=ARI(self.audio,publish)
        async def request(method,path,**params):
            self.requests.append((method,path,params));return {}
        self.ari.request=request

    async def test_speakers_are_isolated_and_cleanup_is_idempotent(self):
        await self.ari.handle({'type':'StasisStart','channel':{'id':'customer'},'args':['customer','1001']})
        peer=[r for r in self.requests if r[1]=='/channels' and r[0]=='POST'][0][2]
        await self.ari.handle({'type':'StasisStart','channel':{'id':peer['channelId']},'args':peer['appArgs'].split(',')})
        self.assertEqual([s.speaker for s in self.audio.opened],['customer','agent'])
        media=[r for r in self.requests if r[1]=='/channels/externalMedia']
        self.assertEqual(len({r[2]['external_host'] for r in media}),2)
        snoops=[r for r in self.requests if '/snoop/' in r[1]]
        self.assertTrue(all(r[2]['spy']=='in' for r in snoops))
        await self.ari.cleanup('customer');await self.ari.cleanup('customer')
        self.assertEqual(len(self.audio.closed),2)
        self.assertFalse(self.ari.calls);self.assertFalse(self.ari.originals)
        self.assertEqual(sum(e['type']=='call_ended' for e in self.events),1)

    async def test_microphone_rx_and_silence_without_peer(self):
        await self.ari.handle({'type':'StasisStart','channel':{'id':'mic'},'args':['microphone']})
        self.assertEqual(len(self.audio.opened),1)
        self.assertTrue(any(r[1]=='/channels/mic/silence' for r in self.requests))
        self.assertTrue(any('/snoop/' in r[1] and r[2]['spy']=='in' for r in self.requests))
        self.assertFalse(any(r[1]=='/channels' for r in self.requests))
        await self.ari.handle({'type':'StasisEnd','channel':{'id':'mic'}})
        self.assertEqual(len(self.audio.closed),1)

    async def test_internal_channels_do_not_recurse(self):
        for args in [[],['internal']]:
            await self.ari.handle({'type':'StasisStart','channel':{'id':'snoop'},'args':args})
        self.assertFalse(self.requests)

    async def test_partial_setup_resources_are_owned(self):
        call=Call('c');self.ari.calls['c']=call
        async def fail(method,path,**params): raise RuntimeError('setup failure')
        self.ari.request=fail
        with self.assertRaises(RuntimeError): await self.ari.attach(call,'original','customer')
        self.assertEqual(len(call.channels),2);self.assertEqual(len(call.bridges),1)
        await self.ari.cleanup('c')
        self.assertEqual(len(self.audio.closed),1)

if __name__=='__main__': unittest.main()
