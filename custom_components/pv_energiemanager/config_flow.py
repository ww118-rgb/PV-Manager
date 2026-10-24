"""UI onboarding and consumer management for PV Energiemanager."""
from __future__ import annotations

from uuid import uuid4

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .modbus_codec import TYPE_WIDTH, WORD_ORDER, decode_registers
from .modbus_validation import validate_connection, validate_read_point

from .const import (
    DEFAULT_INTERVAL, DEFAULT_RESERVE, DEFAULT_SETTLE,
    DOMAIN, TYPE_CONTINUOUS, TYPE_ONOFF, TYPE_STEPPED, TYPES,
)


def _entity(domains: list[str]):
    return selector.EntitySelector(selector.EntitySelectorConfig(domain=domains))


def _num(lo: int, hi: int, step: int = 1):
    return selector.NumberSelector(selector.NumberSelectorConfig(min=lo, max=hi, step=step, mode="box"))


def _global_schema(settings: dict):
    return vol.Schema({
        vol.Required("grid_entity", default=settings.get("grid_entity", "")):
            _entity(["sensor", "number", "input_number"]),
        vol.Optional("battery_entity", description={"suggested_value": settings.get("battery_entity")})
            if settings.get("battery_entity") else vol.Optional("battery_entity"):
            _entity(["sensor", "number", "input_number"]),
        vol.Optional("pv_entity", description={"suggested_value": settings.get("pv_entity")})
            if settings.get("pv_entity") else vol.Optional("pv_entity"):
            _entity(["sensor", "number", "input_number"]),
        vol.Required("grid_export_positive", default=settings.get("grid_export_positive", True)):
            selector.BooleanSelector(),
        vol.Required("battery_charge_positive", default=settings.get("battery_charge_positive", True)):
            selector.BooleanSelector(),
        vol.Required("interval_s", default=settings.get("interval_s", DEFAULT_INTERVAL)):
            _num(5, 300),
        vol.Required("reserve_w", default=settings.get("reserve_w", DEFAULT_RESERVE)):
            _num(0, 10000, 10),
        vol.Required("feedback_settle_s", default=settings.get("feedback_settle_s", DEFAULT_SETTLE)):
            _num(0, 180),
    })


def _device_schema(values: dict | None = None):
    d = values or {}
    schema = {
        vol.Required("name", default=d.get("name", "Neuer Verbraucher")):
            selector.TextSelector(),
        vol.Required("priority", default=d.get("priority", 2)):
            _num(1, 10),
        vol.Required("subpriority", default=d.get("subpriority", 1)):
            _num(1, 99),
        vol.Required("kind", default=d.get("kind", TYPE_CONTINUOUS)):
            selector.SelectSelector(selector.SelectSelectorConfig(
                options=TYPES, mode="dropdown")),
        vol.Required("min_w", default=d.get("min_w", 1400)):
            _num(0, 100000, 10),
        vol.Required("max_w", default=d.get("max_w", 11000)):
            _num(1, 100000, 10),
        vol.Optional("steps_w", default=d.get("steps_w", "500,1000,1500,2000")):
            selector.TextSelector(),
        vol.Optional("demand_entity", description={"suggested_value": d.get("demand_entity")})
            if d.get("demand_entity") else vol.Optional("demand_entity"):
            _entity(["binary_sensor", "switch", "input_boolean"]),
        vol.Optional("actual_entity", description={"suggested_value": d.get("actual_entity")})
            if d.get("actual_entity") else vol.Optional("actual_entity"):
            _entity(["sensor", "number", "input_number"]),
        vol.Optional("power_output", description={"suggested_value": d.get("power_output")})
            if d.get("power_output") else vol.Optional("power_output"):
            _entity(["number", "input_number"]),
        vol.Optional("switch_output", description={"suggested_value": d.get("switch_output")})
            if d.get("switch_output") else vol.Optional("switch_output"):
            _entity(["switch", "input_boolean"]),
        vol.Required("output_unit", default=d.get("output_unit", "W")):
            selector.SelectSelector(selector.SelectSelectorConfig(options=["W", "kW", "A"])),
        vol.Required("phases", default=str(d.get("phases", 1))):
            selector.SelectSelector(selector.SelectSelectorConfig(options=["1", "3"])),
        vol.Required("voltage", default=d.get("voltage", 230)):
            _num(100, 260),
        vol.Required("start_delay_s", default=d.get("start_delay_s", 0)):
            _num(0, 3600),
        vol.Required("min_on_s", default=d.get("min_on_s", 0)):
            _num(0, 86400),
        vol.Required("min_off_s", default=d.get("min_off_s", 0)):
            _num(0, 86400),
    }
    return vol.Schema(schema)


def _validate_device(d):
    result = dict(d)
    kind = result["kind"]
    low, high = int(result["min_w"]), int(result["max_w"])
    if high < low or (kind != TYPE_STEPPED and high < 1):
        return None, "limits"
    if kind == TYPE_ONOFF:
        if not result.get("switch_output"):
            return None, "missing_switch"
        result["min_w"] = high
    elif not result.get("power_output"):
        return None, "missing_power_output"
    if kind == TYPE_STEPPED:
        try:
            stages = sorted(set(int(x.strip()) for x in result.get("steps_w", "").split(",") if x.strip()))
        except ValueError:
            return None, "invalid_steps"
        if not stages or any(x <= 0 or x > high for x in stages):
            return None, "invalid_steps"
        result["min_w"] = stages[0]
        result["max_w"] = stages[-1]
    # UI selector returns numeric fields as floats; normalize once in config.
    for key in ("priority", "subpriority", "min_w", "max_w", "voltage",
                "start_delay_s", "min_on_s", "min_off_s"):
        result[key] = int(result[key])
    result["phases"] = int(result["phases"])
    return result, None


# Modbus configuration is stored in options; existing consumer and system
# settings retain their IDs and schema.
def _modbus_connection_schema(values=None):
    values = values or {}
    return vol.Schema({
        vol.Required("name", default=values.get("name", "")): selector.TextSelector(),
        vol.Required("host", default=values.get("host", "")): selector.TextSelector(),
        vol.Required("port", default=values.get("port", 502)): _num(1, 65535),
        vol.Required("unit_id", default=values.get("unit_id", 1)): _num(0, 255),
    })


def _modbus_register_schema(connections: list[dict], values=None):
    values = values or {}
    return vol.Schema({
        vol.Required("connection_id", default=values.get("connection_id", connections[0]["id"])): selector.SelectSelector(
            selector.SelectSelectorConfig(options=[
                selector.SelectOptionDict(value=c["id"], label=c["name"])
                for c in connections
            ])),
        vol.Required("name", default=values.get("name", "")): selector.TextSelector(),
        vol.Required("address", default=values.get("address", 0)): _num(0, 65535),
        vol.Required("function_code", default=str(values.get("function_code", 3))): selector.SelectSelector(
            selector.SelectSelectorConfig(options=["3", "4"])),
        vol.Required("data_type", default=values.get("data_type", "int16")): selector.SelectSelector(
            selector.SelectSelectorConfig(options=list(TYPE_WIDTH))),
        vol.Required("byte_order", default=values.get("byte_order", "ABCD")): selector.SelectSelector(
            selector.SelectSelectorConfig(options=list(WORD_ORDER))),
        vol.Required("scale", default=values.get("scale", 1.0)): selector.NumberSelector(
            selector.NumberSelectorConfig(min=-1000000, max=1000000,
                                          step="any", mode="box")),
        vol.Required("offset", default=values.get("offset", 0.0)): selector.NumberSelector(
            selector.NumberSelectorConfig(min=-1000000, max=1000000,
                                          step="any", mode="box")),
        vol.Optional("unit", default=values.get("unit", "W")): selector.TextSelector(),
        vol.Required("poll_seconds", default=values.get("poll_seconds", 15)): _num(5, 3600),
    })


class PVConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Create a single local EMS instance."""
    VERSION = 1

    async def async_step_user(self, user_input=None):
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        if user_input is not None:
            return self.async_create_entry(title="PV Energiemanager", data=user_input)
        return self.async_show_form(step_id="user", data_schema=_global_schema({}))

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return PVOptionsFlow()


class PVOptionsFlow(config_entries.OptionsFlow):
    """Add, update and remove consumers without editing YAML."""

    def _devices(self):
        return list(self.config_entry.options.get("devices", []))

    def _save(self, *, devices=None, general=None):
        options = dict(self.config_entry.options)
        if devices is not None:
            options["devices"] = devices
        if general is not None:
            options.update(general)
        return self.async_create_entry(title="", data=options)

    async def async_step_init(self, user_input=None):
        return self.async_show_menu(
            step_id="init",
            menu_options=["general", "add", "edit", "remove",
                          "modbus_connection", "modbus_edit_connection",
                          "modbus_register", "modbus_edit_register",
                          "modbus_test_register", "modbus_remove_register", "modbus_remove_connection"],
        )

    async def async_step_general(self, user_input=None):
        if user_input is not None:
            # Persist explicit None for cleared optional selectors.  Otherwise
            # an entity from entry.data would reappear when data/options merge.
            options = dict(self.config_entry.options)
            options.update({"battery_entity": None, "pv_entity": None})
            options.update(user_input)
            return self.async_create_entry(title="", data=options)
        merged = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(step_id="general", data_schema=_global_schema(merged))

    async def async_step_add(self, user_input=None):
        errors = {}
        if user_input is not None:
            device, error = _validate_device(user_input)
            if error:
                errors["base"] = error
            else:
                other_outputs = {
                    d.get(key) for d in self._devices()
                    for key in ("power_output", "switch_output") if d.get(key)
                }
                if any(device.get(key) in other_outputs for key in
                       ("power_output", "switch_output") if device.get(key)):
                    errors["base"] = "duplicate_output"
                else:
                    device["id"] = uuid4().hex[:12]
                    return self._save(devices=[*self._devices(), device])
        return self.async_show_form(
            step_id="add", data_schema=_device_schema(), errors=errors
        )

    async def async_step_edit(self, user_input=None):
        devices = self._devices()
        if not devices:
            return self.async_abort(reason="no_devices")
        if user_input is not None:
            self._selected = user_input["device_id"]
            return await self.async_step_edit_form()
        return self.async_show_form(step_id="edit", data_schema=vol.Schema({
            vol.Required("device_id"): selector.SelectSelector(
                selector.SelectSelectorConfig(options=[
                    selector.SelectOptionDict(value=d["id"], label=d["name"])
                    for d in devices
                ])
            )
        }))

    async def async_step_edit_form(self, user_input=None):
        devices = self._devices()
        old = next((d for d in devices if d["id"] == self._selected), None)
        if old is None:
            return self.async_abort(reason="no_devices")
        errors = {}
        if user_input is not None:
            updated, error = _validate_device(user_input)
            if error:
                errors["base"] = error
            else:
                other_outputs = {
                    d.get(key) for d in devices if d["id"] != old["id"]
                    for key in ("power_output", "switch_output") if d.get(key)
                }
                if any(updated.get(key) in other_outputs for key in
                       ("power_output", "switch_output") if updated.get(key)):
                    errors["base"] = "duplicate_output"
                else:
                    updated["id"] = old["id"]
                    return self._save(devices=[updated if d["id"] == old["id"] else d
                                               for d in devices])
        return self.async_show_form(
            step_id="edit_form", data_schema=_device_schema(old), errors=errors
        )

    async def async_step_remove(self, user_input=None):
        devices = self._devices()
        if not devices:
            return self.async_abort(reason="no_devices")
        if user_input is not None:
            return self._save(devices=[d for d in devices
                                       if d["id"] != user_input["device_id"]])
        return self.async_show_form(step_id="remove", data_schema=vol.Schema({
            vol.Required("device_id"): selector.SelectSelector(
                selector.SelectSelectorConfig(options=[
                    selector.SelectOptionDict(value=d["id"], label=d["name"])
                    for d in devices
                ])
            )
        }))

    def _connections(self):
        return list(self.config_entry.options.get("modbus_connections", []))

    def _registers(self):
        return list(self.config_entry.options.get("modbus_registers", []))

    async def async_step_modbus_connection(self, user_input=None):
        """Register a Modbus-TCP endpoint, no network I/O until a register is read."""
        errors = {}
        if user_input is not None:
            conn, error = validate_connection(user_input)
            existing = self._connections()
            if error:
                errors["base"] = error
            elif any((c["host"].lower(), c["port"], c["unit_id"]) ==
                     (conn["host"].lower(), conn["port"], conn["unit_id"]) for c in existing):
                errors["base"] = "duplicate_endpoint"
            else:
                conn["id"] = uuid4().hex[:12]
                options = dict(self.config_entry.options)
                options["modbus_connections"] = [*existing, conn]
                return self.async_create_entry(title="", data=options)
        return self.async_show_form(
            step_id="modbus_connection",
            data_schema=_modbus_connection_schema(),
            errors=errors,
        )

    async def async_step_modbus_register(self, user_input=None):
        """Create a read-only native HA sensor from one Modbus register range."""
        connections = self._connections()
        if not connections:
            return self.async_abort(reason="no_modbus_connections")
        errors = {}
        if user_input is not None:
            reg, error = validate_read_point(
                user_input, {c["id"] for c in connections}
            )
            if error:
                errors["base"] = error
            else:
                reg["id"] = uuid4().hex[:12]
                options = dict(self.config_entry.options)
                options["modbus_registers"] = [*self._registers(), reg]
                return self.async_create_entry(title="", data=options)
        return self.async_show_form(
            step_id="modbus_register",
            data_schema=_modbus_register_schema(connections),
            errors=errors,
        )

    async def async_step_modbus_edit_connection(self, user_input=None):
        connections = self._connections()
        if not connections:
            return self.async_abort(reason="no_modbus_connections")
        if user_input:
            self._chosen_modbus_connection = user_input["connection_id"]
            return await self.async_step_modbus_edit_connection_form()
        return self.async_show_form(
            step_id="modbus_edit_connection",
            data_schema=vol.Schema({
                vol.Required("connection_id"): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=[
                        selector.SelectOptionDict(value=c["id"], label=c["name"])
                        for c in connections
                    ])),
            }),
        )

    async def async_step_modbus_edit_connection_form(self, user_input=None):
        connections = self._connections()
        old = next((c for c in connections if c["id"] == self._chosen_modbus_connection), None)
        if old is None:
            return self.async_abort(reason="no_modbus_connections")
        errors = {}
        if user_input:
            new, error = validate_connection(user_input)
            if error:
                errors["base"] = error
            elif any(c["id"] != old["id"] and
                     (c["host"].lower(), c["port"], c["unit_id"]) ==
                     (new["host"].lower(), new["port"], new["unit_id"]) for c in connections):
                errors["base"] = "duplicate_endpoint"
            else:
                new["id"] = old["id"]
                options = dict(self.config_entry.options)
                options["modbus_connections"] = [
                    new if c["id"] == old["id"] else c for c in connections
                ]
                return self.async_create_entry(title="", data=options)
        return self.async_show_form(
            step_id="modbus_edit_connection_form",
            data_schema=_modbus_connection_schema(old), errors=errors,
        )

    async def async_step_modbus_edit_register(self, user_input=None):
        registers = self._registers()
        if not registers:
            return self.async_abort(reason="no_modbus_registers")
        if user_input:
            self._chosen_modbus_register = user_input["register_id"]
            return await self.async_step_modbus_edit_register_form()
        return self.async_show_form(
            step_id="modbus_edit_register",
            data_schema=vol.Schema({
                vol.Required("register_id"): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=[
                        selector.SelectOptionDict(value=r["id"], label=r["name"])
                        for r in registers
                    ])),
            }),
        )

    async def async_step_modbus_edit_register_form(self, user_input=None):
        registers = self._registers()
        old = next((r for r in registers if r["id"] == self._chosen_modbus_register), None)
        if old is None:
            return self.async_abort(reason="no_modbus_registers")
        errors = {}
        if user_input:
            new, error = validate_read_point(
                user_input, {c["id"] for c in self._connections()}
            )
            if error:
                errors["base"] = error
            else:
                new["id"] = old["id"]
                options = dict(self.config_entry.options)
                options["modbus_registers"] = [
                    new if r["id"] == old["id"] else r for r in registers
                ]
                return self.async_create_entry(title="", data=options)
        return self.async_show_form(
            step_id="modbus_edit_register_form",
            data_schema=_modbus_register_schema(self._connections(), old), errors=errors,
        )

    async def async_step_modbus_test_register(self, user_input=None):
        """Run an explicitly requested register read without changing options."""
        regs = self._registers()
        if not regs:
            return self.async_abort(reason="no_modbus_registers")
        if user_input is not None:
            from homeassistant.components.modbus import async_get_temporary_unit
            from modbus_connection import ModbusTcpParams
            import asyncio

            reg = next((r for r in regs if r["id"] == user_input["register_id"]), None)
            conn = next((c for c in self._connections()
                         if reg and c["id"] == reg["connection_id"]), None)
            if not reg or not conn:
                return self.async_abort(reason="no_modbus_connections")
            try:
                async with asyncio.timeout(10):
                    async with async_get_temporary_unit(
                        self.hass,
                        ModbusTcpParams(host=conn["host"], port=int(conn["port"])),
                        int(conn["unit_id"]),
                    ) as unit:
                        if int(reg["function_code"]) == 3:
                            raw = await unit.read_holding_registers(
                                int(reg["address"]), TYPE_WIDTH[reg["data_type"]]
                            )
                        else:
                            raw = await unit.read_input_registers(
                                int(reg["address"]), TYPE_WIDTH[reg["data_type"]]
                            )
                    value = decode_registers(
                        list(raw), reg["data_type"], reg["byte_order"],
                        reg["scale"], reg["offset"],
                    )
                self._test_result = (
                    f"{reg['name']}: {value:g} {reg.get('unit', '')}; "
                    f"Rohregister: {list(raw)}"
                )
            except Exception as exc:
                self._test_result = (
                    f"Testlesen fehlgeschlagen: {type(exc).__name__}: {exc}"
                )
            return await self.async_step_modbus_test_result()
        return self.async_show_form(
            step_id="modbus_test_register",
            data_schema=vol.Schema({
                vol.Required("register_id"): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=[
                        selector.SelectOptionDict(value=r["id"], label=r["name"])
                        for r in regs
                    ]))
            }),
        )

    async def async_step_modbus_test_result(self, user_input=None):
        """Show the last explicit read result without persisting it."""
        if user_input is not None:
            return await self.async_step_init()
        return self.async_show_form(
            step_id="modbus_test_result",
            data_schema=vol.Schema({}),
            description_placeholders={"result": getattr(self, "_test_result", "")},
        )

    async def async_step_modbus_remove_register(self, user_input=None):
        registers = self._registers()
        if not registers:
            return self.async_abort(reason="no_modbus_registers")
        if user_input:
            options = dict(self.config_entry.options)
            options["modbus_registers"] = [
                r for r in registers if r["id"] != user_input["register_id"]
            ]
            return self.async_create_entry(title="", data=options)
        return self.async_show_form(
            step_id="modbus_remove_register",
            data_schema=vol.Schema({
                vol.Required("register_id"): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=[
                        selector.SelectOptionDict(value=r["id"], label=r["name"])
                        for r in registers
                    ])),
            }),
        )

    async def async_step_modbus_remove_connection(self, user_input=None):
        connections = self._connections()
        if not connections:
            return self.async_abort(reason="no_modbus_connections")
        if user_input:
            chosen = user_input["connection_id"]
            if any(r["connection_id"] == chosen for r in self._registers()):
                return self.async_show_form(
                    step_id="modbus_remove_connection",
                    data_schema=self._modbus_remove_connection_schema(),
                    errors={"base": "connection_has_registers"},
                )
            options = dict(self.config_entry.options)
            options["modbus_connections"] = [c for c in connections
                                             if c["id"] != chosen]
            return self.async_create_entry(title="", data=options)
        return self.async_show_form(
            step_id="modbus_remove_connection",
            data_schema=self._modbus_remove_connection_schema(),
        )

    def _modbus_remove_connection_schema(self):
        return vol.Schema({
            vol.Required("connection_id"): selector.SelectSelector(
                selector.SelectSelectorConfig(options=[
                    selector.SelectOptionDict(value=c["id"], label=c["name"])
                    for c in self._connections()
                ])),
        })
