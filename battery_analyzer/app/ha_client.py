from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime

import aiohttp

from analyzer import Analyzer, utcnow
from config import Settings

LOGGER = logging.getLogger(__name__)
WS_URL = 'ws://supervisor/core/websocket'


class HomeAssistantClient:
    def __init__(self, settings: Settings, analyzer: Analyzer) -> None:
        self.settings = settings
        self.analyzer = analyzer
        self.token = os.environ.get('SUPERVISOR_TOKEN', '')
        if not self.token:
            raise RuntimeError('SUPERVISOR_TOKEN is not available')
        self._message_id = 1

    def _next_id(self) -> int:
        value = self._message_id
        self._message_id += 1
        return value

    async def run_forever(self) -> None:
        backoff = 1
        while True:
            try:
                await self._run_once()
                backoff = 1
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                LOGGER.exception('Home Assistant websocket failed: %s', exc)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)

    async def _run_once(self) -> None:
        timeout = aiohttp.ClientTimeout(total=None, sock_connect=30, sock_read=None)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.ws_connect(WS_URL, heartbeat=30) as ws:
                auth_req = await ws.receive_json()
                if auth_req.get('type') != 'auth_required':
                    raise RuntimeError(f'Unexpected websocket auth message: {auth_req}')
                await ws.send_json({'type': 'auth', 'access_token': self.token})
                auth_result = await ws.receive_json()
                if auth_result.get('type') != 'auth_ok':
                    raise RuntimeError(f'Home Assistant websocket auth failed: {auth_result}')

                get_states_id = self._next_id()
                await ws.send_json({'id': get_states_id, 'type': 'get_states'})
                while True:
                    msg = await ws.receive_json()
                    if msg.get('id') == get_states_id:
                        if not msg.get('success'):
                            raise RuntimeError(f'get_states failed: {msg}')
                        self.analyzer.set_initial_states(msg.get('result') or [])
                        self.analyzer.evaluate(utcnow())
                        break

                sub_id = self._next_id()
                await ws.send_json({'id': sub_id, 'type': 'subscribe_events', 'event_type': 'state_changed'})
                while True:
                    msg = await ws.receive_json()
                    if msg.get('type') == 'result' and msg.get('id') == sub_id:
                        if not msg.get('success'):
                            raise RuntimeError(f'subscribe_events failed: {msg}')
                        continue
                    if msg.get('type') != 'event':
                        continue
                    event = msg.get('event') or {}
                    data = event.get('data') or {}
                    entity_id = data.get('entity_id')
                    if entity_id not in self.settings.watched_entities:
                        continue
                    new_state = data.get('new_state') or {}
                    state = new_state.get('state')
                    time_fired = event.get('time_fired')
                    ts = None
                    if time_fired:
                        try:
                            ts = datetime.fromisoformat(time_fired.replace('Z', '+00:00'))
                        except ValueError:
                            ts = None
                    self.analyzer.handle_state(entity_id, state, ts)
