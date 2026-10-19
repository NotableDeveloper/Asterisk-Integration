#!/usr/bin/env python3
"""Real ARI→Local channel→snoop→RTP→two-pass→WebSocket smoke test."""
import asyncio
import json
import os
import time
import aiohttp

async def main():
    base = os.getenv('STT_URL', 'http://localhost:8000')
    async with aiohttp.ClientSession() as http:
        async with http.get(base + '/health/ready') as resp:
            assert resp.status == 200, await resp.text()
        async with http.ws_connect(base + '/ws') as ws:
            await ws.receive_json()  # snapshot
            async with http.post(base + '/api/demo') as resp:
                assert resp.status == 200, await resp.text()
                call_id = (await resp.json())['call_id']
            events = []
            start = time.monotonic()
            while time.monotonic() - start < 60:
                message = await asyncio.wait_for(ws.receive_json(), 35)
                if message.get('call_id') != call_id:
                    continue
                events.append(message)
                print(json.dumps(message, ensure_ascii=False), flush=True)
                if message['type'] == 'call_ended':
                    break
            assert any(e['type']=='partial' and e.get('text') for e in events), 'No partial recognition'
            finals = [e for e in events if e['type']=='final' and e.get('text')]
            assert finals, 'No final recognition'
            assert any(any('\uac00' <= c <= '\ud7a3' for c in e['text']) for e in finals), 'No Korean text'
            metrics = [e for e in events if e['type']=='metrics']
            assert metrics and all(e['packets']>0 and e['overflow']==0 for e in metrics), 'Audio missing/overflow'
            assert events[-1]['type']=='call_ended', 'Call did not end'
            async with http.get(base + '/health/ready') as resp:
                status = await resp.json()
                assert status['active_calls']==status['audio_sessions']==0, status
            print(json.dumps({'result':'PASS', 'elapsed_seconds':round(time.monotonic()-start,2),'final_segments':len(finals)}))

asyncio.run(main())
