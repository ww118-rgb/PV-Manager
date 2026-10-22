# Installation über HACS

1. In HACS auf **Benutzerdefinierte Repositories** gehen.
2. Repository: `https://github.com/ww118-rgb/PV-Manager`.
3. Kategorie **Integration** auswählen und hinzufügen.
4. **PV Energiemanager** herunterladen und Home Assistant **neu starten**.
5. Unter **Einstellungen → Geräte & Dienste → Integration hinzufügen** den PV Energiemanager wählen.
6. Netzsensor und optionalen Batteriesensor festlegen, dann über **Konfigurieren** Verbraucher hinzufügen.
7. Entitäten und Geräte-Grenzen kontrollieren. Der Regelungsschalter ist nach HA-Neustart zunächst aus.

Für den tatsächlichen Betrieb muss die Home-Assistant-Entität als Ausgang schreibbar sein. `input_number` oder `input_boolean` benötigen eine separate Automation, um ein Gerät zu erreichen.

Für manuelle Installation ausschließlich `custom_components/pv_energiemanager/` nach `/config/custom_components/pv_energiemanager/` kopieren. Keine zweite Kopie unter dem alten Namen installieren.

## Bekannte Grenzen

- Kein eigener direkter Modbus-/MQTT-/OCPP-Treiber; dafür Home-Assistant-Entitäten verwenden.
- Keine harte Hausanschluss- oder Strombegrenzung; externe Schutzmaßnahmen bleiben erforderlich.
- Unterschiedliche Home-Assistant-Core-Versionen müssen über reale Installationen geprüft werden.
- Das lokale Branding wird auf HA 2026.3+ unterstützt; HACS kann im eigenen Katalog trotzdem einen Platzhalter anzeigen.
- Ohne GitHub Release verwendet HACS den Stand des Standard-Branches; mit veröffentlichten Releases werden Versionen auswählbar.
