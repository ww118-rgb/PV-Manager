## 0.2.1a2 — Startzustand des Modbus-Schreibaktors korrigiert

- Eigene, eindeutig registrierte Modbus-Schreibaktoren dürfen beim ersten Regelbefehl den ehrlichen HA-Initialzustand unknown besitzen.
- Wirklich unavailable, fremde oder fehlerhaft konfigurierte Aktoren bleiben gesperrt.
- Sicherheitsprüfung der Pause-/Aus-Zuordnung und verständlichere Fehlermeldung.
- Keine Änderung der Verteilungslogik und bestehenden Konfigurationen.

## 0.2.1a1 — Universeller Modbus-Schreibadapter (Entwicklungsbranch)

- Native `number`-Entitäten für konfigurierbare FC06/FC16-Schreibregister (16-/32-Bit und FLOAT32).
- Explizit eingestellter gerätespezifischer Pause-/Aus-Wert; EMS-Null darf keinesfalls blind als Modbus-Rohwert 0 gesendet werden.
- Getrennte Darstellung: 0/aktive Sollwerte als HA-Number; nach Befehlserfolg „last_sent_not_read_back“; unbekannter Zustand nach Neustart.
- Bisherige Lesesensoren und Verteilungsberechnung bleiben unverändert.
- Kein automatisches Schreiben beim Start oder durch das Anlegen eines Datenpunktes.
- **Beta/Entwicklungsstand:** Vor echter Hardware erst mit einem Simulator testen. Noch kein separater Enable-/Readback-Kanal und noch keine geführte Geräte-Einrichtung.

## 0.2.0b4 — Zeitsteuerung auf dem Home-Assistant-Ereignisloop repariert

- Modbus-Intervallcallback ist mit `@callback` gekennzeichnet und führt die nächste Abfrage auf dem Home-Assistant-Ereignisloop aus.
- Monitoring- und Regelzyklus verwenden ebenfalls einen korrekt gekennzeichneten Event-Loop-Callback statt einer nicht markierten Lambda-Funktion.
- Behebt die beobachtete Situation: Modbus `read_attempts` bleibt nach initialem erfolgreichem Abruf bei `1`; Managerwerte bleiben `Unbekannt`.
- Regressionstests prüfen den registrierten Callback und mehrere aufeinanderfolgende Intervalle.
- Gespeicherte Geräte, Register, Entitäts-IDs und Prioritäten bleiben unverändert. Keine Änderung der Verteilungsformel oder Aktorschnittstelle.

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
