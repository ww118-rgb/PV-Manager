"""Manual enable switch for real actuator writes."""
from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([PVEnableSwitch(entry.runtime_data)])


class PVEnableSwitch(SwitchEntity):
    _attr_should_poll = False
    _attr_name = "PV Energiemanager Regelung"
    _attr_icon = "mdi:solar-power"

    def __init__(self, manager):
        self.manager = manager
        self._attr_unique_id = f"{manager.entry.entry_id}_enabled"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, manager.entry.entry_id)},
            name="PV Energiemanager",
        )

    @property
    def is_on(self):
        return self.manager.enabled

    async def async_turn_on(self, **kwargs):
        self.manager.enable(True)

    async def async_turn_off(self, **kwargs):
        self.manager.enable(False)

    async def async_added_to_hass(self):
        self.async_on_remove(self.manager.subscribe(self.async_write_ha_state))
