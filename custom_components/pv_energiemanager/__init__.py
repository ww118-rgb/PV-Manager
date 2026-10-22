"""PV Energiemanager Home Assistant custom integration."""
from homeassistant.const import Platform

from .manager import PowerManager

PLATFORMS = [Platform.SENSOR, Platform.SWITCH]


async def async_setup_entry(hass, entry):
    manager = PowerManager(hass, entry)
    entry.runtime_data = manager
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    manager.start()
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def _async_options_updated(hass, entry):
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass, entry):
    manager = entry.runtime_data
    manager.stop()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
