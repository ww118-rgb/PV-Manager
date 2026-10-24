# PV-Manager – Modbus UI development (0.2.0 beta)

Branch: `develop/modbus-ui`. The released `main` integration (v0.1.3) remains unchanged.

## Confirmed target

- Home Assistant Core 2026.9+ for the shared Modbus transport `async_get_unit`.
- Add Modbus TCP devices, endpoints and read-only register datapoints through the Options Flow, without YAML.
- Create native Home Assistant sensor entities with stable unique IDs, individual polling, raw register diagnostics and clear unavailable states.
- Decode FC03/FC04 registers for int16/uint16/int32/uint32/float32, byte and word order, scale and offset.
- Preserve all current EMS settings, consumer entity IDs and 15-second prioritization logic.
- Implement write-capable number/switch and safe off semantics only in a separate reviewed stage; do not assume 0 A means charging paused.
- MQTT and OCPP are separate future adapters. Existing Home Assistant entities remain supported.

## Release gate

Do not merge to main until HACS/Hassfest and runtime installation are verified. Existing EMS must boot paused; missing measurements must not produce actuator writes. Do not claim network/simulator compatibility without real end-to-end confirmation.

Architecture briefing reviewed on 2026-10-24. Prototype source is kept in an installable ZIP until it is reviewed for inclusion in this branch.
