"""Native write-only Modbus command entities with explicit off-value mapping."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging

from homeassistant.components.modbus import async_get_unit
from homeassistant.components.number import NumberEntity
from homeassistant.helpers.entity import DeviceInfo
from modbus_connection import ModbusTcpParams

from .const import DOMAIN
from .modbus_writer import command_for_setpoint, CommandValueError

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    connections = {c["id"]: c for c in entry.options.get("modbus_connections", [])}
    units = {}
    entities = []
    for cfg in entry.options.get("modbus_write_points", []):
        conn = connections.get(cfg["connection_id"])
        if conn is None:
            _LOGGER.warning("Modbus-Schreibpunkt %s ohne Verbindung", cfg.get("name"))
            continue
        key = (conn["host"].lower(), int(conn["port"]), int(conn["unit_id"]))
        if key not in units:
            units[key] = async_get_unit(
                hass, entry, ModbusTcpParams(host=conn["host"], port=int(conn["port"])),
                int(conn["unit_id"]),
            )
        entities.append(PVModbusWriteNumber(entry, conn, cfg, units[key]))
    async_add_entities(entities)


class PVModbusWriteNumber(NumberEntity):
    """Accept a device-native number value; map HA zero to configured pause.

    The displayed value is the last *successfully transmitted* command, not
    device readback. On startup the value is unknown; no write is performed.
    """

    _attr_should_poll = False
    _attr_assumed_state = True

    def __init__(self, entry, connection, cfg, unit):
        self.cfg = cfg
        self.unit = unit
        self._attr_unique_id = f"{entry.entry_id}_mb_write_{cfg['id']}"
        self._attr_name = cfg["name"]
        self._attr_has_entity_name = True
        self._attr_native_unit_of_measurement = cfg.get("unit") or None
        self._attr_native_min_value = 0.0
        self._attr_native_max_value = float(cfg["active_max"])
        self._attr_native_step = float(cfg["step"])
        self._attr_native_value = None
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"modbus_{entry.entry_id}_{connection['id']}")},
            name=connection["name"], manufacturer="PV Energiemanager",
            model="Modbus TCP Datenpunkte",
        )
        self._write_lock = asyncio.Lock()
        self._last_sent = None
        self._last_error = None
        self._last_words = None

    @property
    def extra_state_attributes(self):
        return {
            "last_sent_at": self._last_sent,
            "last_write_error": self._last_error,
            "last_register_words": self._last_words,
            "feedback_status": "last_sent_not_read_back" if self._last_sent else "unknown_after_start",
            "off_value_configured": True,
            "register_address_zero_based": self.cfg["address"],
        }

    async def async_set_native_value(self, value: float) -> None:
        async with self._write_lock:
            _, words = command_for_setpoint(float(value), self.cfg)
            try:
                async with asyncio.timeout(10):
                    if int(self.cfg["function_code"]) == 6:
                        await self.unit.write_register(int(self.cfg["address"]), words[0])
                    else:
                        await self.unit.write_registers(int(self.cfg["address"]), words)
            except Exception as exc:
                self._last_error = f"{type(exc).__name__}: {exc}"
                self.async_write_ha_state()
                raise
            self._attr_native_value = float(value)
            self._last_sent = datetime.now(timezone.utc).isoformat()
            self._last_words = words
            self._last_error = None
            self.async_write_ha_state()
