"""UI onboarding and consumer management for PV Energiemanager."""
from __future__ import annotations

from uuid import uuid4

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

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
            menu_options=["general", "add", "edit", "remove"],
        )

    async def async_step_general(self, user_input=None):
        if user_input is not None:
            # Remove optional selectors explicitly if cleared.
            options = {key: val for key, val in self.config_entry.options.items()
                       if key not in ("battery_entity", "pv_entity")}
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
