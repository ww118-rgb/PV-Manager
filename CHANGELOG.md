## v0.2.0 – universeller Modbus-TCP-Leseadapter

- UI-Konfiguration von mehreren Modbus-TCP-Geräten und Lesedatenpunkten.
- Freie Host-/Port-/Unit-ID-/Registeradressen, FC03/04 und Datenformate.
- Neue native Sensoren mit stabilen IDs, Rohwertdiagnose und Verbindungsstatus.
- Ein expliziter Testlesedialog ohne Schreibbefehle.
- Keine Änderung am Prioritätenalgorithmus oder an bestehenden Verbrauchern.
- HA-Core-Mindeststand 2026.9 wegen `async_get_unit`.
- Modbus-Schreiben und MQTT sind noch nicht Bestandteil dieser Version.

## v0.1.3

- HACS-Custom-Repository-Validierung: Katalogpflichtfelder `description`/`topics` werden für die Custom-Repository-Prüfung ausgenommen; eine verständliche Repository-Beschreibung und Themen bleiben empfohlen.
- Optionale PV-/Batteriesensoren lassen sich in den globalen Optionen jetzt zuverlässig entfernen.
- Keine Änderung am Leistungsverteiler oder an den Aktorschnittstellen.

# Änderungsprotokoll

## 0.1.2 – Repository- und HACS-Vorbereitung
- Korrekte GitHub-Metadaten für `ww118-rgb/PV-Manager`.
- `strings.json`, eigene lokale Branding-Dateien und GitHub-Actions-Prüfungen ergänzt.
- HACS-Dokumentation und gesonderte Installationshinweise überarbeitet.

## 0.1.1 – Erster HACS-Paketentwurf
- Home-Assistant-Custom-Integration und Konfiguration der Energiemanager-Verbraucher.
