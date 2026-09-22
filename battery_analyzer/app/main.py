from __future__ import annotations

import asyncio
import logging

from aiohttp import web

from analyzer import Analyzer
from api import ApiServer
from config import Settings
from db import Database
from ha_client import HomeAssistantClient

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s: %(message)s',
)
LOGGER = logging.getLogger('marstek_battery_analyzer')


async def ticker(analyzer: Analyzer) -> None:
    while True:
        await asyncio.sleep(1)
        analyzer.tick()


async def main() -> None:
    settings = Settings.load()
    db = Database()
    analyzer = Analyzer(settings, db)
    ha = HomeAssistantClient(settings, analyzer)
    api = ApiServer(analyzer, db)

    runner = web.AppRunner(api.app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', settings.api_port)
    await site.start()

    LOGGER.info('REST API listening on port %s', settings.api_port)
    LOGGER.info(
        'Battery config: %s cells, %.2f kWh gross, %.1f Ah, %.1f%% DoD',
        settings.battery_cell_count,
        settings.battery_gross_capacity_kwh,
        settings.battery_capacity_ah,
        settings.battery_dod_percent,
    )

    await asyncio.gather(
        ha.run_forever(),
        ticker(analyzer),
    )


if __name__ == '__main__':
    asyncio.run(main())
