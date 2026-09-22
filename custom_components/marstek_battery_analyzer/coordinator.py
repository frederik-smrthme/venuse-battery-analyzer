from __future__ import annotations

from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import AnalyzerApi, AnalyzerApiError
from .const import DOMAIN


class AnalyzerCoordinator(DataUpdateCoordinator[dict]):
    def __init__(self, hass: HomeAssistant, api: AnalyzerApi) -> None:
        super().__init__(
            hass,
            logger=__import__('logging').getLogger(__name__),
            name=DOMAIN,
            update_interval=timedelta(seconds=5),
        )
        self.api = api

    async def _async_update_data(self) -> dict:
        try:
            return await self.api.status()
        except AnalyzerApiError as exc:
            raise UpdateFailed(str(exc)) from exc
