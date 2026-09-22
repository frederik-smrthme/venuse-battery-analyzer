from __future__ import annotations

from typing import Any

from aiohttp import ClientError, ClientSession


class AnalyzerApiError(Exception):
    pass


class AnalyzerApi:
    def __init__(self, session: ClientSession, base_url: str) -> None:
        self.session = session
        self.base_url = base_url.rstrip('/')

    async def status(self) -> dict[str, Any]:
        try:
            async with self.session.get(f'{self.base_url}/api/v1/status', timeout=10) as response:
                if response.status != 200:
                    raise AnalyzerApiError(f'HTTP {response.status}')
                return await response.json()
        except (ClientError, TimeoutError) as exc:
            raise AnalyzerApiError(str(exc)) from exc

    async def health(self) -> bool:
        try:
            async with self.session.get(f'{self.base_url}/health', timeout=5) as response:
                return response.status == 200
        except (ClientError, TimeoutError):
            return False
