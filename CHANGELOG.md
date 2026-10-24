## 0.2.0b4 — Zeitsteuerung repariert

- Modbus-Zeitcallback mit HA-@callback dekoriert, damit folgende Polling-Abfragen sicher auf dem Ereignisloop laufen.
- Monitoring-/Regelzyklus nutzt ebenfalls einen gekennzeichneten Callback statt einer Executor-Lambda.
- Regressionstests für mehrere Intervallaufrufe; keine Änderung an der Verteilungsformel.
- Gerätekonfigurationen und Entity-IDs bleiben erhalten.

## 0.2.0b3 — Monitoring bei pausierter Regelung

- Netz-, Batterie- und PV-Sensorwerte werden alle 15 Sekunden (bzw. im konfigurierten Intervall) aktualisiert, selbst wenn der Regelschalter aus ist. Dabei werden niemals Aktoren beschrieben.
- Bei fehlenden Messwerten zeigt der Manager einen klaren Pausiert-/Messfehlerstatus und verwirft veraltete Budgetwerte.
- Modbus-Lesesensoren führen `last_attempt`, `last_success`, `read_attempts`, `successful_reads` und `last_error` als Diagnoseattribute, um unveränderte Werte von ausgefallener Abfrage zu unterscheiden.
- Modbus-Lesezugriffe werden nach 10 Sekunden begrenzt, damit blockierte Verbindungen weitere Pollingversuche nicht dauerhaft verhindern.

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
