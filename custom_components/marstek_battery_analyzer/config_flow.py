from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers import network

from .api import AnalyzerApi
from .const import CONF_URL, DEFAULT_URL, DOMAIN


def _default_analyzer_url(hass) -> str:
    try:
        instance_url = network.get_url(
            hass,
            allow_internal=True,
            allow_external=False,
            allow_cloud=False,
        )
        parsed = urlsplit(instance_url)
        if parsed.hostname:
            host = parsed.hostname
            if ':' in host and not host.startswith('['):
                host = f'[{host}]'
            return urlunsplit(('http', f'{host}:8099', '', '', ''))
    except Exception:  # Home Assistant may not have a usable internal URL yet.
        pass
    return DEFAULT_URL


class MarstekBatteryAnalyzerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            url = user_input[CONF_URL].strip().rstrip('/')
            api = AnalyzerApi(async_get_clientsession(self.hass), url)
            if await api.health():
                await self.async_set_unique_id('marstek_battery_analyzer_local')
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title='Marstek Battery Analyzer',
                    data={CONF_URL: url},
                )
            errors['base'] = 'cannot_connect'

        schema = vol.Schema({
            vol.Required(CONF_URL, default=_default_analyzer_url(self.hass)): str,
        })
        return self.async_show_form(step_id='user', data_schema=schema, errors=errors)
