#!/usr/bin/env python3
"""Actual SIP/ICE/DTLS-SRTP test using a WAV fixture, never the host microphone.
Run on the Mac host: .venv-test/bin/python scripts/test_webphone_media.py
Dependencies: aiortc==1.14.0, aiohttp==3.12.15.
"""
import asyncio
import argparse
import hashlib
import json
from pathlib import Path
import re
import tempfile
import uuid
import wave
import aiohttp
from aiortc import RTCPeerConnection, RTCSessionDescription, RTCConfiguration, RTCRtpSender
from aiortc.contrib.media import MediaPlayer

BASE = 'http://localhost:8000'
parser=argparse.ArgumentParser()
parser.add_argument('--destination', choices=['9998','9999'], default='9998')
DEST=parser.parse_args().destination

def headers(message):
    return {k.lower(): v.strip() for k,v in (line.split(':',1) for line in message.split('\r\n\r\n')[0].split('\r\n')[1:] if ':' in line)}

def digest(challenge, method, uri):
    fields = dict(re.findall(r'(\w+)="([^"]*)"', challenge))
    realm, nonce = fields['realm'], fields['nonce']
    md5 = lambda value: hashlib.md5(value.encode()).hexdigest()
    cnonce = uuid.uuid4().hex
    response = md5(f'{md5("1003:"+realm+":demo-web-1003")}:{nonce}:00000001:{cnonce}:auth:{md5(method+":"+uri)}')
    return f'Digest username="1003", realm="{realm}", nonce="{nonce}", uri="{uri}", response="{response}", algorithm=MD5, qop=auth, nc=00000001, cnonce="{cnonce}"' + (f', opaque="{fields["opaque"]}"' if 'opaque' in fields else '')

class SIP:
    def __init__(self, ws):
        self.ws=ws;self.id=uuid.uuid4().hex;self.tag=uuid.uuid4().hex[:12];self.cseq=0;self.to=f'<sip:{DEST}@asterisk>'
    async def send(self, method, uri, body='', auth=None, to=None, seq=None, extra=''):
        if seq is None: self.cseq+=1
        seq = seq or self.cseq
        message=(f'{method} {uri} SIP/2.0\r\nVia: SIP/2.0/WS fixture.invalid;branch=z9hG4bK{uuid.uuid4().hex};rport\r\n'
                 f'Max-Forwards: 70\r\nFrom: <sip:1003@asterisk>;tag={self.tag}\r\nTo: {to or self.to}\r\n'
                 f'Call-ID: {self.id}\r\nCSeq: {seq} {method}\r\nContact: <sip:1003@fixture.invalid;transport=ws>\r\n'
                 f'Allow: INVITE, ACK, CANCEL, BYE, OPTIONS\r\nSupported: outbound\r\n{extra}')
        if auth: message+=f'Authorization: {auth}\r\n'
        if body: message+='Content-Type: application/sdp\r\n'
        await self.ws.send_str(message+f'Content-Length: {len(body.encode())}\r\n\r\n'+body)
    async def response(self, method):
        while True:
            msg=await asyncio.wait_for(self.ws.receive(),15)
            assert msg.type==aiohttp.WSMsgType.TEXT, msg
            text=msg.data
            if text.startswith('SIP/2.0') and headers(text).get('cseq','').endswith(method):
                code=int(text.split()[1])
                if code>=200:return code,text
    async def request(self, method, uri, body='', to=None, extra=''):
        await self.send(method,uri,body,to=to,extra=extra)
        code,text=await self.response(method)
        if code==401:
            if method=='INVITE': await self.send('ACK',uri,to=headers(text)['to'],seq=self.cseq)
            await self.send(method,uri,body,digest(headers(text)['www-authenticate'],method,uri),to=to,extra=extra)
            code,text=await self.response(method)
        assert code==200,(code,text[:500])
        print(f'{method}: 200',flush=True)
        return text

async def main():
    pc=RTCPeerConnection(RTCConfiguration(iceServers=[]))
    received={'frames':0,'nonzero_frames':0}
    receive_tasks=[]
    @pc.on('track')
    def on_track(track):
        async def consume():
            try:
                while True:
                    frame=await track.recv()
                    received['frames']+=1
                    if any(bytes(frame.planes[0])):received['nonzero_frames']+=1
            except Exception:
                pass
        receive_tasks.append(asyncio.create_task(consume()))
    with tempfile.TemporaryDirectory() as temp:
        fixture=Path(temp)/'fixture.wav'
        with wave.open('asterisk/sounds/ko.wav') as src, wave.open(str(fixture),'wb') as out:
            out.setparams(src.getparams())
            out.writeframes(b'\0'*32000+src.readframes(src.getnframes())+b'\0'*32000)
        player=MediaPlayer(str(fixture),loop=True)
        pc.addTrack(player.audio)
        pc.getTransceivers()[0].setCodecPreferences([c for c in RTCRtpSender.getCapabilities('audio').codecs if c.mimeType=='audio/PCMU'])
        await pc.setLocalDescription(await pc.createOffer())
        try:
            async with aiohttp.ClientSession() as http, http.ws_connect(BASE+'/ws') as events, http.ws_connect(BASE+'/sip',protocols=['sip'],origin=BASE) as ws:
                await events.receive_json()
                sip=SIP(ws)
                await sip.request('REGISTER','sip:asterisk',to='<sip:1003@asterisk>',extra='Expires: 120\r\n')
                response=await sip.request('INVITE',f'sip:{DEST}@asterisk',pc.localDescription.sdp)
                sip.to=headers(response)['to']
                await pc.setRemoteDescription(RTCSessionDescription(response.split('\r\n\r\n',1)[1],'answer'))
                await sip.send('ACK',f'sip:{DEST}@asterisk',seq=sip.cseq)
                transcript=[];call_id=None
                async with asyncio.timeout(30):
                    while True:
                        event=await events.receive_json()
                        print(json.dumps(event,ensure_ascii=False),flush=True)
                        if event['type']=='call_started':call_id=event['call_id']
                        if event.get('call_id')!=call_id:continue
                        transcript.append(event)
                        if event['type']=='final' and event.get('text'):break
                assert pc.connectionState=='connected',pc.connectionState
                assert any(e['type']=='partial' for e in transcript), 'No partial'
                stats=await pc.getStats()
                sent=sum(getattr(s,'packetsSent',0) for s in stats.values() if s.type=='outbound-rtp')
                assert sent>0
                if DEST=='9999':assert received['nonzero_frames']>10,received
                await sip.request('BYE',f'sip:{DEST}@asterisk')
                async with asyncio.timeout(10):
                    while True:
                        event=await events.receive_json()
                        if event.get('call_id')==call_id and event['type']=='call_ended':break
                await sip.request('REGISTER','sip:asterisk',to='<sip:1003@asterisk>',extra='Expires: 0\r\n')
                print(json.dumps({'result':'PASS','ice_dtls':pc.connectionState,'srtp_packets_sent':sent,'call_id':call_id,'destination':DEST,'received':received}),flush=True)
        finally:
            player.audio.stop()
            await pc.close()
            for task in receive_tasks:task.cancel()
            await asyncio.gather(*receive_tasks,return_exceptions=True)

asyncio.run(main())
