## Schneller Netzbezug-Schutz ab 0.2.2b9

Die Gesamtberechnung bleibt alle 15 Sekunden. Zusätzlich prüft der Manager alle 5 Sekunden die Netzleistung auf erheblichen Bezug (initial mindestens 1000 W) und senkt gegebenenfalls die aktuell steuerbaren Verbraucher nach konfigurierter Priorität ab. Batterie-Laden wird bei großem Netzbezug nicht als unmittelbar frei angenommen. Nach einem Schutz-Eingriff gibt der Manager der echten Messung eine Wirkungsfrist und verhindert sofortiges erneutes Hochregeln. Drei neue Sensoren dokumentieren die Eingriffe. Das ist ein Software-Betaregler, kein Ersatz für hardwareseitige Schutzfunktionen.

## Testbetrieb mit schnell schwankender PV-Leistung (ab 0.2.2b8)

Für Geräte mit groben Stellstufen (mindestens 300 W pro Stellstufe) ist die Hochregelung zunächst auf **zwei Stufen pro EMS-Regelzyklus** begrenzt. Reduzieren und Abschalten bleiben unmittelbar. Die Begrenzung wird als eigener Sensor „Wegen Anstiegsbegrenzung zurückgehalten“ sichtbar. Bei dreiphasigen 230-V-Wallboxen mit 1-A-Schritten entspricht dies höchstens +2 A je Zyklus. 16 A entsprechen 11.040 W: Sowohl die Verbraucher-Maximalleistung als auch die Number-Entitätsobergrenze müssen 16 A ermöglichen. Die 5-s-Sensorabfragen sind von der Standard-Regelperiode (15 s) unabhängig. Die Begrenzung ersetzt keinen schnellen netzseitigen Schutz für reale Geräte.

## Ab 0.2.2b4: Abgleich zwischen Sollwert, Ampere und tatsächlicher Last

Intern plant der Energiemanager in Watt. Ein Verbraucher mit Ampere-Ausgang wird mit konfigurierter Spannung/Phasenzahl in eine gültige, nicht über dem Leistungsbudget liegende Stromstufe umgerechnet. Nach dem expliziten Aktivieren der Regelung erhalten Verbraucher mit geplantem 0-W-Sollwert einen tatsächlichen Pause-/Aus-Befehl – **ausschließlich** den gerätespezifisch konfigurierten. Der 0-W-Sollwert ist kein physikalischer Wirknachweis. Eine unerwartet weiterlaufende Wallbox wird nicht als vermeintlich wieder frei gewordener Überschuss zum Budget addiert; eine dauerhafte Abweichung erscheint als „Aktorabweichung“. Ohne unabhängigen Istleistungssensor bleibt die tatsächliche Leistungsaufnahme unbestätigt.

Vorsicht: Bei der für Tests verwendeten Wallbox bedeutet der rohe Registerwert 0 A „unbegrenzt“. Der Pausewert (im Simulator 1 A) muss **pro Gerät** geprüft werden, bevor automatische Steuerbefehle zugelassen werden. Bei der Wärmepumpe deaktiviert 0 W ggf. nur den PV-Sollwert, nicht die gesamte Heizung.

## Wichtig: Modbus zuerst einrichten, ohne vorhandene Sensoren

Ab 0.2.2b3 kann die Integration **ohne Netzsensor** angelegt werden. Der erste Einrichtungsdialog hat nur einen optionalen bereits vorhandenen Netzsensor. Nach Installation unter **Konfigurieren → Modbus-Datenquelle hinzufügen** die Geräteverbindung und den Netz-Lesesensor erstellen. Erst danach unter **Anlage einrichten** als Netzsensor zuordnen. Ohne gültige Netzleistung ist die Regelungsfreigabe gesperrt. Siehe [Einrichtungsassistent](EINRICHTUNGSASSISTENT.md).

# PV Energiemanager – geführte Einrichtung (0.2.2b3)

Der Bereich **Konfigurieren** zeigt jetzt zuerst vier klar erkennbare Optionen:

1. **Anlage einrichten**: Netz-, PV- und Batteriesensor per HA-Dropdown auswählen, Netz-/Batterie-Vorzeichen verstehen, Messwert live vorab prüfen.
2. **Verbraucher einrichten**: neuen Verbraucher anlegen oder vorhandenen bearbeiten – Eckdaten, Sollwertaktor, Einheit, W→A-Umrechnung (falls nötig), Istleistung und Anforderung, anschließend Zusammenfassung.
3. **Einstellungen prüfen**: aktuelle Netzrichtung, Aktor- und Ist-Sensoren sowie unklare Anforderungsquellen ohne Schreibbefehle anzeigen.
4. **Erweiterte Einstellungen**: alle bisherigen Dialoge zur Modbus-Geräte-/Registerverwaltung, Schreiben und Expertenparameter bleiben erhalten.

**Das Update löscht keine Verbraucher, Modbus-Verbindungen, Sensoren oder Entitäts-IDs.** Zur Neu-Einrichtung bestehende Geräte im Assistenten **bearbeiten**; nicht die Integration löschen. Kompatibilität wird vor dem Speichern geprüft (Ausgang vorhanden, korrekte Einheit, Minimal- und Maximalgrenzen, bei Ampere auch Stellstufen). Warnungen bei fehlenden Istleistungs- und Anforderungsquellen sind sichtbar.

Für neue Modbus-Ausgänge weiterhin zunächst **Erweiterte Einstellungen → Modbus-Schreibaktor hinzufügen** verwenden, danach im Verbraucherassistenten den entstandenen HA-Sollwertaktor auswählen. Eine vollständig integrierte Registereingabe direkt im Verbraucher-Assistenten ist für eine spätere Version vorgesehen. MQTT/OCPP bleiben über vorhandene HA-Entitäten nutzbar; ein nativer MQTT-Datenpunkteditor ist noch offen.

**Sicherheit:** Die Regelung wird durch die Einrichtung nicht eingeschaltet und nach Home-Assistant-Neustart weiterhin deaktiviert. Bestehende Geräte können bereits unabhängig vom Energiemanager Leistung aufnehmen. „Unbekannt“ bedeutet keine Istleistungsmessung, nicht 0 W. Auch bei PV-Erzeugung kann Netzbezug entstehen, wenn Verbraucher mehr Energie aufnehmen als erzeugt wird. Vor dem Automatiktest Netzvorzeichen, tatsächliche Verbraucherlasten und gerätespezifische Pausewerte prüfen.

---

# PV-Manager 0.2.1a1 – universelle Modbus-Schreibadapter-Beta

**Entwicklungsfassung, nicht ungeprüft auf reale Anlagen anwenden.**

Modbus-TCP-Output als native Home-Assistant-`number`-Entität über den OptionsFlow einrichten: IP/Port/Unit, Registeradresse, FC06 oder FC16, Datentyp, Bytefolge, Einheit, aktiver Bereich, Schrittweite, Skalierung und **verpflichtender Pause-/Aus-Gerätewert**.

Der Energiemanager gibt weiterhin W aus, kann über die bestehende Verbraucherkonfiguration nach A, W oder kW umrechnen und die `number`-Entität ansprechen. Die Entität übersetzt den HA-Nullwert ausschließlich in den konfigurierten Geräte-Pausewert. Für eine dreiphasige Wallbox mit 230 V bedeutet 6 A = 4.140 W; 4.414 W wird bei 1-A-Schritten auf 6 A **abgerundet**, nicht exakt umgerechnet.

**Inbetriebnahme:** Zuerst Geräte-Pause-/Auswert anhand der echten Gerätedokumentation prüfen. `number` ist nach Neustart bewusst `unknown`, bis der Nutzer über HA explizit einen ersten sicheren Befehl ausführt. Dabei signalisiert die Anzeige lediglich den letzten gesendeten Befehl – keine echte Istwertrückmeldung. Der EMS-Regelschalter bleibt nach Neustart ausgeschaltet.

## Einschränkung

Off und laufender Sollwert werden in diesem ersten Adapter **auf dasselbe Schreibregister** übertragen. Geräte mit separatem Freigaberegister, mehreren Schreibschritten oder verpflichtender Rücklesebestätigung benötigen eine spätere Erweiterung und dürfen hiermit noch nicht betrieben werden. MQTT und OCPP folgen separat. Die alte v0.2.0b5 kann weiter auf dem main-Branch laufen.

---

# PV-Manager für Home Assistant – 0.2.2b3 (geführte Einrichtung)

**Aktueller Stand:** Die bestehende PV-Überschussregelung bleibt erhalten.
Neu: Modbus-TCP-Verbindungen und frei definierbare **Lesesensoren** werden
über die Home-Assistant-Konfigurationsdialoge eingerichtet – ohne YAML,
Helfer oder eigene Skripte. Der Modbus-Adapter benutzt die geteilte
Verbindungsinfrastruktur aus Home Assistant Core 2026.9+.

**Modbus-Schreibaktoren sind in dieser Version noch nicht enthalten.** Die
Berechnung kann weiterhin vorhandene beschreibbare HA-`number`- und
`switch`-Entitäten ansprechen; deren Verbindung zum Gerät muss derzeit über
andere Integrationen erfolgen. MQTT/OCPP-Adapter folgen später.

**[Schritt-für-Schritt Modbus-Anleitung](DEVELOPMENT_MODBUS.md)** – mit
Registertypen, negativer Skalierung, Lesetest und Fehlerdiagnose.

Bei einem Update über HACS: Home Assistant neu starten, unter
**Einstellungen → Geräte & Dienste → PV Energiemanager → Konfigurieren** die
Modbus-Geräte und Lesesensoren hinzufügen. Vorhandene EMS-Verbraucher und
Optionen bleiben erhalten. Die echte Regelung startet deaktiviert.

---

# Frühere Prototyp-Dokumentation (v0.1.x)

> **Installierbarer Prototyp (v0.1.2)**. Die Integration steuert nach Aktivierung echte Home-Assistant-Aktoren.
> Bitte zunächst mit begrenzten Leistungswerten und unter Aufsicht in Betrieb nehmen.
> GitHub-Repository: `ww118-rgb/PV-Manager`.

## Installation über HACS (Custom Repository)

1. Das öffentliche Repository `ww118-rgb/PV-Manager` muss die Integration unter `custom_components/pv_energiemanager/` enthalten.
2. In Home Assistant HACS öffnen → Drei-Punkte-Menü → **Benutzerdefinierte Repositories**.
3. `https://github.com/ww118-rgb/PV-Manager` eingeben und Kategorie **Integration** auswählen.
4. Repository hinzufügen, `PV Energiemanager` in HACS öffnen und herunterladen.
5. Home Assistant neu starten.
6. Unter **Einstellungen → Geräte & Dienste → Integration hinzufügen** den PV Energiemanager auswählen.
7. Zuerst Netz- und gegebenenfalls Batteriesensor konfigurieren, danach Verbraucher und Aktoren hinzufügen.
8. Erst nach Prüfung der Aktorgrenzen den Regelschalter aktivieren.

Eine öffentliche Aufnahme in den HACS-Standardkatalog ist **nicht** erforderlich.

---

# PV Energiemanager für Home Assistant – v0.1.0

Direkt installierbare **Home-Assistant-Custom-Integration** mit echter zyklischer Sollwertberechnung und Aktor-Schreibbefehlen. Keine Demo, keine künstlichen Sensoren, kein Simulator und kein Testmodus in der Integration.

**Status:** Erste Prototypversion. Der Python-Berechnungskern wurde lokal geprüft; ein vollständiger Lauf in einer realen Home-Assistant-Installation mit deinen Geräten ist **noch nicht** erfolgt. Bitte anfänglich mit einer kleinen Leistungsgrenze und beobachtetem Hausanschluss testen. Ausschließlich als Energiemanagement oberhalb der technischen Sicherheitsregelungen einsetzen.

## Installation

1. ZIP herunterladen und entpacken.
2. Den Ordner `custom_components/pv_energiemanager` einschließlich aller Dateien nach `<Home Assistant config>/custom_components/pv_energiemanager` kopieren. Beispiel: `/config/custom_components/pv_energiemanager/`.
3. Home Assistant **neu starten**.
4. **Einstellungen → Geräte & Dienste → Integration hinzufügen** → „PV Energiemanager“.
5. Den **Netzleistungssensor** zuordnen. Optional Batterie/PV auswählen, Vorzeichen und 15-Sekunden-Intervall einstellen.
6. Im Integrationsmenü **Konfigurieren** → **Verbraucher hinzufügen**. Für jeden Verbraucher Leistungsgrenzen, Prioritäten, Anforderung und Schreibausgänge auswählen. Nach Änderungen wird die Integration neu geladen.
7. Unter den Entitäten des Energiemanagers den Schalter **„PV Energiemanager Regelung“** aktivieren. **Erst danach werden echte Befehle geschrieben.** Nach jedem Home-Assistant-Neustart / Integrations-Reload ist die Regelung zunächst wieder pausiert.
8. Die Entitäten „Verteilungsbudget“, „Zugewiesene Leistung“, pro Verbraucher „Sollleistung“, „Istleistung“ und „Letzter Fehler“ beobachten.

## Benötigte Home-Assistant-Entitäten

### Anlagenwerte

- **Netzleistung**, Pflicht: `sensor`, `number` oder `input_number`; in W oder kW. Standard: **positiv = Netzeinspeisung**, negativ = Bezug. Vorzeichen umkehrbar.
- **Batterieleistung**, optional: W oder kW. Standard: **positiv = Batterieladung**, negativ = Entladung. Vorzeichen umkehrbar. Fehlt eine Batterie, rechnet der Manager mit 0 W.
- **PV-Erzeugung**, optional: nur zur Anzeige, nicht als zusätzlicher Summand der Bilanz.
- Sicherheitsreserve und Regelintervall sind konfigurierbar (Standard **0 W**, **15 s**).

### Je Verbraucher

- **Name und Hauptpriorität 1–10**; innerhalb einer Gruppe **Unterpriorität 1–99** (1 zuerst).
- **Anforderung**: optional `binary_sensor`, `switch`, `input_boolean` (**on** = Gerät fordert Leistung an). Ohne diese Entität wird der Verbraucher als dauerhaft anfordernd betrachtet.
- **Istleistung**: optionaler Sensor in W/kW. Ohne gültigen Wert wird für die Leistungsbilanz der zuvor gesetzte Sollwert angenommen.
- **Stufenlos**: Sollleistung (W) zwischen `min_w` und `max_w`, oder ausgeschaltet.
- **Gestuft**: Liste wie `500,1000,1500,2000` W.
- **Ein/Aus**: Leistung entweder 0 oder genau `max_w`.
- **Leistungsausgang** für stufenlos/gestuft: *schreibbare* Home-Assistant-Entität aus `number.*` oder `input_number.*`.
- **Schaltausgang**: `switch.*` oder `input_boolean.*`; bei Ein/Aus verpflichtend, bei regelbaren Geräten optional. Der Energiemanager schreibt zuerst den Leistungswert und schaltet dann bei Bedarf ein. Beim Abschalten nutzt er den Schaltausgang, falls vorhanden.
- **Sollwerteinheit** für `number`-Aktoren: W, kW, oder A. Für A wird `W = A × Spannung × Phasenanzahl` angenähert; korrektes Phasenmodell / elektrische Begrenzungen im Gerät sind erforderlich.
- **Einschaltverzögerung, Mindestlaufzeit, Mindestauszeit**: Sekunden je Verbraucher.

**Wichtige Aktorbedingung:** Für stufenlos/gestuft ohne Schaltausgang muss die `number`-Entität tatsächlich den Wert **0** akzeptieren, um abzuschalten. Hat die Entität beispielsweise eine Mindestgrenze von 6 A, muss zusätzlich ein passender Schaltausgang zugeordnet werden.

## Regelprinzip

Alle 15 Sekunden (konfigurierbar) vollständige Messwertaufnahme, Neuberechnung, Prioritätsverteilung und Schreibbefehle. Zwischen zwei Zyklen keine neue Optimierung. Normale kurzfristige Netzbezüge sind möglich.

**Leistungsbudget, in W:**

```
Budget = Netz + Batterie + Summe(angerechnete Verbraucherleistung) - Reserve
Angerechnet = Ist, wenn frischer Sensorwert vorhanden, ansonsten letzter Sollwert
```

Dies ist ein **rechnerisches Leistungsbudget**. Fehlende Istsensoren erlauben keine exakte physikalische Verbrauchszuordnung. Das Netz / der Speicher korrigiert die Bilanz beim folgenden Zyklus. Bereits laufende Verbraucher werden bei jedem Zyklus neu berücksichtigt, damit ihre Leistung nicht „verschwindet“.

1. Hauptprioritäten von 1 nach 10.
2. Geräte ohne Anforderung zählen nicht zum Gruppenbedarf.
3. Innerhalb einer Priorität werden zunächst die technisch möglichen Mindestleistungen in Reihenfolge der Unterpriorität zugelassen; dann werden aktive Geräte so gleichmäßig wie möglich bis zu ihren Maximalwerten erhöht.
4. Leistungsstufen werden exakt eingehalten; für stufenlose Geräte erfolgt die interne Verteilung in 100-W-Schritten.
5. Nachrangige Gruppen werden grundsätzlich erst bei gedecktem **konfiguriertem Maximalbedarf** höherer Gruppen versorgt. Ist ein höheres Gerät bereits seit dem letzten Schreibvorgang stabil unter seiner Sollleistung und sein Istsensor aktuell, darf die **nachweislich ungenutzte Differenz** an nachrangige Gruppen weitergegeben werden. Diese Zuteilung ist jederzeit widerrufbar.
6. Fehlt der Istsensor, gilt rechnerisch der letzte Sollwert. Eine reale Netzeinspeisung kann dennoch bei der nächsten Budgetberechnung für weitere Leistung sorgen. Deshalb kann bei späterer Vollauslastung kurzfristig Netzbezug auftreten.
7. Schreibbefehle nur bei Änderungen. Niedrigere Prioritäten werden vor neuen Erhöhungen reduziert, innerhalb des gleichen 15-s-Zyklus.

**Achtung:** Ein fehlender gültiger Netz- oder Batteriesensor blockiert neue Befehle, schaltet angeschlossene Verbraucher aber nicht automatisch ab. Eine abgeschaltete EMS-Regelung lässt die letzten Aktoreinstellungen bestehen. Fallbacks, Notabschaltung und Maximalstromschutz müssen geräteseitig bzw. durch andere abgesicherte Mechanismen sichergestellt sein.

## Protokolle

Der Manager selbst kommuniziert über Home-Assistant-Entitäten. Modbus-, MQTT-, OCPP- oder Herstelleranbindungen werden durch die jeweilige vorhandene HA-Integration bereitgestellt. Die gewählten `number`-/`switch`-Entitäten müssen tatsächliche Schreibaktionen unterstützen. `input_number` und `input_boolean` sind reine Helfer: Werden sie ausgewählt, muss eine Automation oder eine andere Anbindung die Änderungen **an das echte Gerät weiterleiten**.

Eine OCPP-Wallbox kann beispielsweise einen Stromgrenzwert in Ampere annehmen, während der Energiemanager intern mit Watt rechnet. Die Leistungsermittlung über feste Spannung/Phasenzahl ist nur eine Näherung; insbesondere Phasenwechsel müssen gerätespezifisch behandelt werden.

## Einschränkungen der Version 0.1.2

- Nicht in einem echten HA-Installationskontext mit deinen Geräten validiert. Fehlerberichte und Logs sind deshalb ausdrücklich erwünscht.
- Kein eigener nativer Modbus-/MQTT-/OCPP-Treiber: **Home Assistant stellt die Adapter**.
- Bereits ausgelöste Schaltvorgänge werden als Serviceaufrufe verarbeitet; **eine elektrische Bestätigung der tatsächlichen Umsetzung wird nicht immer garantiert**. Istsensoren liefern optional Rückmeldung.
- Mindestlaufzeiten werden ab erfolgreichen Schreibbefehlen verfolgt, nicht über einen Neustart hinweg persistiert.
- Ausgänge werden bei pausierter Regelung oder fehlenden Messwerten **nicht automatisch in den sicheren Zustand versetzt**.
- Keine harte Begrenzung des Netzimports oder Anschlussstroms. Kurzzeitiger Netzbezug ist konzeptionell erlaubt; Gerätesicherheit muss unabhängig davon bestehen.
- Kein gleichzeitiger Schreibzugriff durch weitere Automationen empfohlen. Mehrere Controller desselben Aktors würden gegeneinander arbeiten.

## Fehlersuche

Unter **Einstellungen → System → Protokolle** nach `custom_components.pv_energiemanager` suchen. Zusätzlich den Entitätswert **„Letzter Fehler“** und die Werte **Netzleistung**, **Batterieleistung**, **Verteilungsbudget** sowie den Sollwert des betreffenden Gerätes notieren.

Für reproduzierbare Bugreports hilfreich: Home-Assistant-Version, Gerätetyp, anonymisierte Entitätsnamen, Prioritäten, Soll-/Istwerte und Zeitpunkt der Abweichung.


## HACS/HA Kompatibilität und Qualität

- Die lokale Integration ist in `custom_components/pv_energiemanager/` gekapselt. Die HACS-Konfiguration liegt im Repository-Root.
- `strings.json` dient als englische Originalübersetzung; `translations/de.json` und `translations/en.json` ergänzen die UI.
- Das lokale Icon liegt unter `brand/icon.png` (in Home Assistant seit 2026.3 unterstützt). Die Anzeige in HACS kann trotz funktionierendem Icon anders ausfallen.
- GitHub Actions führen HACS-Validierung, Hassfest und Python-Kernprüfungen durch. Ein erfolgreiches Prüfergebnis ersetzt keinen Test der HA-Runtime mit angeschlossenen Aktoren.
- **Keine Kompatibilität mit sämtlichen Home-Assistant-Core-Versionen zugesichert.** Die Unterstützung einzelner Core-Versionen wird anhand echter Installations- und Laufzeittests dokumentiert.
- Der Quellcode ist unabhängig vom alten `power-manager` und verwendet dessen Steuerungslogik nicht.


### Fehlerdiagnose bei unveränderten Modbus-Werten (ab 0.2.0b4)

Unter **Entwicklerwerkzeuge → Zustände** die Modbus-Sensor-Entität auswählen und die Attribute `last_attempt`, `last_success`, `read_attempts`, `successful_reads` und `last_error` prüfen. Ein gleichbleibender Zahlenwert kann eine echte gleichbleibende physikalische Messung sein; der Pollingzähler und `last_success` zeigen, ob Abfragen weiterhin funktionieren. Fehlschläge melden die Sensoren als `unavailable` und tragen den Fehler in `last_error` ein.

Der PV-Manager zeigt Netz-, Batterie- und PV-Leistungen nun auch bei ausgeschaltetem Regelschalter an. Die passive Auswertung erzeugt **keine** Aktorbefehle. Die `Regelzyklen` zählen weiterhin nur aktive Regelungszyklen.


### Verhalten schreibbarer Modbus-Sollwerte ab 0.2.1a2

Ein neu gestarteter nativer Modbus-Schreibaktor hat ohne Rücklesung den Zustand `unknown`, bis der erste Befehl erfolgreich übertragen wurde. Dies verhindert bewusst, einen unbestätigten Gerätezustand vorzutäuschen. Die EMS-Regelung darf den **ersten** Befehl dennoch an einen eindeutig zugehörigen, korrekt konfigurierten und verfügbaren PV-Manager-Schreibaktor senden. Andere unbekannte oder nicht verfügbare HA-Aktoren bleiben gesperrt. **Für echte Geräte** muss die Aus-/Pause-Semantik ausdrücklich geprüft sein und die Inbetriebnahme beaufsichtigt erfolgen. Ein anfänglich unbekannter Geräte-Istverbrauch darf nicht als physikalisch 0 W interpretiert werden.

### Zurück im geführten Verbraucher-Assistenten (ab 0.2.2b3)

Home Assistant besitzt für OptionsFlow-Formulare keinen nativen Zurück-Button. In jedem Schritt befindet sich nun eine Auswahlliste „Navigation“ mit Weiter bzw. Zurück. Auf der letzten Seite kann man direkt Leistungsgrenzen, Stellwert oder Rückmeldungen bearbeiten, ohne alle Schritte von vorne zu beginnen.

Bei stufenweiser Geräteansteuerung in Ampere schlägt der Assistent den nächsten tatsächlich erreichbaren Mindestwert vor. Beispiel: Drei Phasen, 230 V, 1-A-Schritte, mindestens 6 A → 4140 W. Der Nutzer kann den Vorschlag gezielt übernehmen; es wird weder unbemerkt gerundet noch ein Register angesprochen.
