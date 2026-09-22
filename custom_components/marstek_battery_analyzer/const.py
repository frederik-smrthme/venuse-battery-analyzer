from homeassistant.const import Platform

DOMAIN = 'marstek_battery_analyzer'
PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR]
CONF_URL = 'url'
DEFAULT_URL = 'http://homeassistant.local:8099'
