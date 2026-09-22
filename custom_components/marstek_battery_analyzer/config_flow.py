from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import AnalyzerApi
from .const import CONF_URL, DEFAULT_URL, DOMAIN


class MarstekBatteryAnalyzerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            url = user_input[CONF_URL].rstrip('/')
            api = AnalyzerApi(async_get_clientsession(self.hass), url)
            if await api.health():
                await self.async_set_unique_id('marstek_battery_analyzer_local')
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title='Marstek Battery Analyzer',
                    data={CONF_URL: url},
                )
            errors['base'] = 'cannot_connect'

        schema = vol.Schema({vol.Required(CONF_URL, default=DEFAULT_URL): str})
        return self.async_show_form(step_id='user', data_schema=schema, errors=errors)
