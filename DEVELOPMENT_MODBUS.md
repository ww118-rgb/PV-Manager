# Modbus TCP – universeller Leseadapter für den PV-Manager

Stand: 0.2.0, erste Modbus-Ausbaustufe. **Nur lesend**: Es werden keine Modbus-Schreibbefehle erzeugt.
Alle Hosts, Ports, Unit-IDs, Registeradressen, Datentypen und Faktoren stammen aus den
Benutzereinstellungen. Es gibt keine fest einprogrammierten Simulatorwerte.

## Voraussetzungen

- Home Assistant **Core 2026.9 oder neuer**; getestet werden müssen konkrete Core-Versionen
  zusätzlich am realen System. Die verwendete API ist `async_get_unit` aus HA Modbus.
- PV-Manager aus HACS installiert und in **Einstellungen → Geräte & Dienste** bereits hinzugefügt.
- Ein vom Home-Assistant-Rechner erreichbarer **Modbus-TCP-Server**.
- Keine Modbus-Einträge in `configuration.yaml`, keine Helfer, keine Skripte notwendig.

## Einrichtung ausschließlich über die Oberfläche

1. **PV Energiemanager → Konfigurieren → Modbus-TCP-Gerät hinzufügen**.
   Gerätenamen, Hostnamen/IP, Port und Unit-ID eintragen. Eine Verbindung kann
   viele Register enthalten; die Core-Modbus-Komponente verwaltet den TCP-Kanal.
2. **Modbus-Lesesensor hinzufügen**. Gerät wählen und Register konfigurieren:
   - Adresse **0-basiert**, nicht die 40001-/30001-Referenznotation.
   - FC03 (Holding) oder FC04 (Input).
   - Datentyp `int16`, `uint16`, `int32`, `uint32`, `float32`.
   - Byte-/Wortreihenfolge `ABCD`, `BADC`, `CDAB`, `DCBA` (16 Bit: ABCD/BADC).
   - Umrechnung `angezeigter Wert = Rohwert × Faktor + Offset`.
   - Einheit: `W`, `kW`, `%` oder herstellerspezifisch; Polling-Intervall.
3. **Modbus-Register testweise lesen**: wählt einen bereits konfigurierten
   Datenpunkt und führt **genau einen Leseaufruf** aus; zeigt Rohregister, Wert
   und Fehler an. Dabei wird **kein Schreibbefehl** ausgeführt.
4. Im Gerätebereich von Home Assistant die neue `sensor`-Entität öffnen.
   Attribute: FC, Registeradresse, Rohregister, Datentyp, letztes erfolgreiches
   Lesen und letzter Fehler. Ein unerreichbarer Server führt zu `unavailable`.
5. Unter **PV Energiemanager → Konfigurieren → Allgemeine Einstellungen**
   den neuen Sensor als Netz-, Batterie- oder PV-Leistung auswählen.
6. Die eigentliche 15-Sekunden-Energieregelung bleibt nach Neustart deaktiviert.
   Sensoren lesen trotzdem unabhängig von der Regelung. Vor einem echten
   Verbrauchertest Vorzeichen und Leistungswerte prüfen.

## Grenzen dieser Version

- Kein FC06/FC16-Schreiben, keine `number`-Entität für Sollwerte, keine MQTT-
  oder eigene OCPP-Anbindung. Diese gehören zu nachfolgenden Ausbaustufen.
- Kein automatischer Register-Scan und keine vorgegebenen Geräteprofile.
- Der Lesetest prüft die aktuell gespeicherte Registerdefinition, nicht
  ungespeicherte Formulardaten.
- Eine erfolgreich bestandene GitHub-Action ist **kein** Nachweis einer
  funktionierenden TCP-Verbindung mit deiner Anlage.

## Netzwerkhinweis für Simulatoren

Bei VirtualBox-NAT ist die VM-Adresse möglicherweise **nicht** aus Home Assistant
sichtbar. Trage einen von **Home Assistant aus** erreichbaren Host und den
entsprechend weitergeleiteten Host-Port ein. Eventuelle Windows-Firewallregeln
und Portweiterleitungen werden außerhalb des PV-Managers konfiguriert.

## Testkriterien

1. Geräteverbindung und Register lassen sich ohne YAML erstellen.
2. FC03 und FC04 lesen die gewünschte Rohregisterlänge.
3. INT32 mit negativen Werten und negative Skalierungsfaktoren stimmen.
4. Bei Netzwerkunterbrechung wird der Sensor `unavailable`, nicht ein alter
   Messwert als gültig dargestellt.
5. Nach HA-Neustart bleiben Datenpunkte und Entity-IDs erhalten.
6. Vorhandene EMS-Konfigurationen behalten ihre Auswahl und funktionieren
   ohne Modbus-Konfiguration unverändert weiter.
