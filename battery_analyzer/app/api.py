from __future__ import annotations

from aiohttp import web

from analyzer import Analyzer
from db import Database


class ApiServer:
    def __init__(self, analyzer: Analyzer, db: Database) -> None:
        self.analyzer = analyzer
        self.db = db
        self.app = web.Application()
        self.app.add_routes([
            web.get('/health', self.health),
            web.get('/api/v1/status', self.status),
            web.get('/api/v1/cycles', self.cycles),
            web.get('/api/v1/cycles/{cycle_id}', self.cycle),
        ])

    async def health(self, request: web.Request) -> web.Response:
        return web.json_response({'status': 'ok', 'version': '0.1.0'})

    async def status(self, request: web.Request) -> web.Response:
        return web.json_response(self.analyzer.status())

    async def cycles(self, request: web.Request) -> web.Response:
        try:
            limit = min(max(int(request.query.get('limit', '20')), 1), 200)
        except ValueError:
            limit = 20
        return web.json_response({'cycles': self.db.recent_cycles(limit)})

    async def cycle(self, request: web.Request) -> web.Response:
        try:
            cycle_id = int(request.match_info['cycle_id'])
        except ValueError:
            raise web.HTTPBadRequest(text='invalid cycle id')
        row = self.db.get_cycle(cycle_id)
        if row is None:
            raise web.HTTPNotFound(text='cycle not found')
        row['events'] = self.db.cycle_events(cycle_id)
        row['samples'] = self.db.cycle_samples(cycle_id)
        return web.json_response(row)
