## 0.3.0b1 — Ein Regeldurchgang statt konkurrierender Timer

- Vereinfachung des Managers auf exakt einen sequentiellen Zyklus: Messwerte lesen, Leistungsbilanz bilden, alle Verbraucher nach Priorität in gerätespezifischen Schritten verteilen, notwendige Sollwerte schreiben (Reduzierungen zuerst), danach 15 Sekunden warten. Läuft ein Schreibvorgang länger, startet die Wartezeit erst nach Abschluss.
- Der zuvor zusätzlich alle 5 Sekunden schreibende Netzbezugsschutz ist entfernt. Ebenso entfernt: künstliche Begrenzung auf zwei Ampere pro Zyklus, mehrzyklische Regler-Bestätigung und Sicherheitswiederfreigabe. Modbus-Sensoreingänge dürfen unverändert alle 5 Sekunden gelesen werden; deren Abfrage löst niemals einen Regel-Schreibbefehl aus.
- Der physikalische Leistungsansatz bleibt stetig: Netz + Batterie + angerechnete gesteuerte Verbraucher − Reserve. Während Netzbezug wird dieselbe einzige Berechnung um eine Netzbezugsbegrenzung ergänzt; geringe Änderungen bis 150 W führen nicht zu einer unnötigen Gerätestufe.
- Native Ampere-Stufung, gleiche Aufteilung innerhalb einer Prioritätsgruppe, Unterprioritäten, Hardware-Mindestlaufzeiten, Pausenwerte, Fremdverstellungserkennung und Write-Validierung bleiben erhalten und arbeiten nur im normalen Zyklus.
- Redundante Reglerdateien und entsprechende Diagnoseeinträge entfallen; Sensoren/Aktoren/Protokollzuordnungen bestehender Installationen bleiben unverändert.

**Einschränkung:** Die vereinfachte Regelung führt bewusst keine zusätzliche sicherheitsgerichtete Schnellabschaltung zwischen den Durchgängen aus. Eine Home-Assistant-Softwaresteuerung ersetzt keine Geräteschutz- und Netzanschlussschutzfunktionen.

## 0.2.3b1 — Durchgängige Leistungsbilanz und koordinierte Netzbezugssperre

**Root-Cause-Fix:** Der bisherige Regelkern hat bei Netzbezug von 999 auf 1001 W plötzlich die gesamte positive Batterieladung aus dem Leistungsbudget gestrichen. 2 W Messwertänderung konnten dadurch ein 6-kW-Sollwertspringen auslösen. Dieser Diskontinuitätsfehler ist behoben.

- Das physikalische Budget wird immer aus dem zusammengehörigen Leistungsfluss **Netz + Batterie + bereits angerechnete Verbraucher − Reserve** berechnet. Batterie positiv bedeutet Laden. Der Sprung beim Überschreiten der 1-kW-Schutzschwelle ist entfernt.
- **Separate Kontrollentscheidung:** Bei aktuellem Netzbezug über 150 W darf das normale Regelwerk die **Summe** der bereits angeforderten Verbraucherleistung nicht erhöhen, kann diese Leistung aber nach Prioritäten neu verteilen. Der schnelle Netzbezugsschutz reduziert bei mindestens 1000 W weiterhin alle fünf Sekunden.
- Nach einem schnellen Eingriff wird das Wieder-Hochregeln erst nach Ablauf der vorhandenen 30-s-Haltezeit **und** zwei stabilen Beobachtungen freigegeben.
- Neuer Diagnosesensor „Für Steuerung freigegebenes Budget“, um physikalisches und kontrolltechnisch freigegebenes Budget transparent zu unterscheiden.
- Tests an der kritischen 999-/1001-W-Schwelle, bei gleichzeitig ladender Batterie und Netzbezug, Prioritätswechsel und schneller Sicherheitsreduzierung. Bestehende Universalität und Modbus-Geräteübersetzungen bleiben erhalten.
- Die Änderung ist keine Garantie für perfekte Nulleinspeisung bei schneller PV-/Hauslaständerung. Datenalter und Reaktionsverhalten der tatsächlichen Batterie bleiben für den Simulator-Praxistest relevant.

## 0.2.2b9 — Netzbezug-Schutz bei abrupten PV-Schwankungen

- Zusätzliche Sicherheitsprüfung alle 5 Sekunden, unabhängig vom normalen 15-Sekunden-Gesamtregler. Ab 1.000 W gemessenem Netzbezug werden nur vorhandene steuerbare Lasten reduziert, niemals erhöht.
- Bei erheblichem Netzbezug wird gleichzeitig ladende Batterie nicht als unmittelbar verfügbare Leistungsreserve angerechnet.
- Der Sicherheitsregler gibt 300 W zusätzliche Reserve, respektiert Gruppenprioritäten und wartet nach einem Eingriff mindestens die konfigurierte Rückmeldezeit, normalerweise 15 s, auf dessen physikalische Wirkung. Ein um weitere 2 kW wachsender Netzbezug kann schneller erneut reduziert werden.
- Während der Wirkungskontrolle werden die vorherigen Sollwerte als Referenz berücksichtigt, damit unveränderte physikalische Messungen keine mehrfache Reduzierung auslösen. Der normale Regler darf eine Notreduzierung für mindestens 30 s nicht durch Hochregeln konterkarieren.
- Diagnose: Anzahl Netzbezug-Schutz-Eingriffe, Netzbezug beim letzten Eingriff, letzte reduzierte Sollleistung.
- Kein fester herstellerspezifischer Modbus-Wert, keine Änderung der Nutzerkonfiguration oder Batterie-Vorzeichen; die vorhandene Anstiegsbegrenzung bleibt erhalten.
- Beta-Schutzfunktion: Ein 5-Sekunden-Software-Regler ersetzt keine netzseitige Hardware-Schutzmaßnahme. Weiterhin nur im Simulator testen, bis die physikalische Wirkung geprüft wurde.

## 0.2.2b8 — Begrenztes Hochregeln bei schnell wechselnder PV-Leistung

- Grobe Gerätestufen ab 300 W: pro normalem Regelzyklus maximal 2 aktive Stufen **nach oben**; Ein-/Aus-Schaltungen dürfen immer auf die konfigurierte Mindestleistung beginnen.
- Herunterregeln, Pausieren und höherpriorisierte Verdrängung sind **nicht** gebremst.
- Geräte mit feinen Stellstufen oder ohne stufenweise Stellgröße behalten das bisherige Verhalten.
- Neuer Diagnosesensor „Wegen Anstiegsbegrenzung zurückgehalten“ zeigt den Unterschied zwischen berechnetem Plan und im aktuellen Zyklus freigegebenen Sollwerten.
- Dies ist eine konservative Teststrategie und keine Prognose: abrupte PV-Verluste schneller als Messung/Regelung können weiterhin kurz Netzbezug auslösen.
- Es werden keine Hersteller-/Simulatoradressen, Batterievoreinstellungen oder Wallbox-Ampere-Grenzen geändert.

## 0.2.2b7 — Hysterese für stufenweise geregelte Verbraucher

- 100 W zusätzliche Reserve vor dem Hochregeln in die nächste verfügbare Stufe.
- Ein Leistungsdefizit bis 150 W führt nicht zu einem unnötigen 690-W-Ladestromsprung.
- Mittlere Defizite (über 150 W, unter 1000 W) werden über zwei Regelzyklen bestätigt; größere Defizite werden sofort abgebaut.
- Bei geänderter Nachfrage, Prioritätsbelegung oder Gerätesperre keine Verzögerung durch die Hysterese.
- Der vorhandene 15-Sekunden-Regelzyklus und die Modbus-Geräteübersetzung bleiben unverändert.
- Werte sind zunächst konservative Startwerte für den Simulator und werden nach realen Messungen ggf. konfigurierbar gemacht.

## 0.2.2b6 — Geräte-Stellstufen bereits bei der Leistungsaufteilung berücksichtigen

- Für stufenlos konfigurierte Verbraucher mit tatsächlich diskreten Stellgrößen (z. B. 1 A) liest die Regelung die Home-Assistant-Schrittweite aus dem vorhandenen Sollwertaktor und bildet daraus echte Leistungsstufen.
- Der Verteilungsalgorithmus plant keine unerreichbaren Zwischenleistungen mehr, die später beide Wallboxen gemeinsam abrunden würden. Beispiel: Bei 11.000 W Gruppenbudget kann 8 A + 7 A statt 7 A + 7 A zugeordnet werden.
- Für Gerätenummern ohne sinnvoll auf ganze Watt abbildbare Schrittweite bleibt die bisherige feinere kontinuierliche Berechnung erhalten; keine gerätespezifischen festen Werte.
- Die tatsächlich erreichbare Maximalleistung eines Geräts wird für nachfolgende Prioritätsgruppen berücksichtigt.
- Regressionstest für eine bei automatischer Batterieladung stabil auf 8 A regelbare Situation ergänzt.
- Keine Veränderung an Vorzeichenkonvention, Modbus-Registern oder Benutzerkonfiguration. Bei zeitlich versetzten Eingangsmessungen kann weiterhin eine Hysterese nötig sein.

## 0.2.2b5 — Anzeige nach Ampere-Rundung korrigiert

- Zugewiesene Leistung zeigt nun die Summe der tatsächlich als Gerätesollwerte übertragenen, quantisierten Leistungen, statt der theoretisch geplanten Wattwerte.
- Nicht weitergereichte Leistung bezieht die nach einer Gerätestufe verbleibende Differenz ein.
- Beispiel: 11.000 W geplante Obergrenze bei dreiphasiger 230-V-Wallbox mit 1-A-Schritten führt zu 15 A = 10.350 W; die 650 W je Wallbox sind nicht zugewiesen.
- Die eigentliche Prioritäts- und Leistungsregelung sowie die Modbus-Ausgabe bleiben unverändert.
- Weiterhin wichtig: Gemessener Netzexport und dieser rechnerische Rest unterscheiden sich durch Sensor-/Abfragezeitpunkte, Reserve und andere Lasten.

## 0.2.2b4 — Null-Sollwert aktiv senden, Istlast-Budget absichern

- Beim Einschalten werden Verbraucher mit Sollwert 0 W ausdrücklich über den konfigurierten Pause-/Aus-Befehl synchronisiert; 0 W intern bedeutet nicht automatisch, dass die Hardware gestoppt hat.
- Istleistung, die höher ist als der zuletzt erfolgreich kommandierte Sollwert, wird **nicht** mehr als wieder frei werdende Leistung zum Leistungsbudget addiert.
- Weiterlaufende Verbraucher bei 0-W-Vorgabe werden nach einer angemessenen Frist erneut pausiert; die Diagnose meldet „Aktorabweichung“.
- Watt→Ampere-Rundung: Identische erreichbare Stromstufen werden nicht mehr unnötig jedes Intervall gesendet. Ein manueller Override kann nach einer Schonfrist erneut auf den EMS-Wert gesetzt werden.
- Prioritäten, Verteilungsformel, Modbusregister, sichere Aus-/Pause-Zuordnung und bestehende Einstellungen bleiben erhalten.
- Zusätzliche Regressionstests für beide mit Sollwert 0 W weiterladenden Wallboxen und die Ampere-Rundung.

**Sicherheitsinformation:** „Modbus-Schreiben erfolgreich“ ist kein Nachweis, dass die Hardware pausiert. Konfigurierter Aus-/Pause-Befehl muss für jedes Gerät verifiziert sein (bei manchen Wallboxen bedeutet rohe 0 A volle/unbegrenzte Ladung). Bis zur Bestätigung nur am Simulator testen.

## 0.2.2b3 — Verbraucher-Assistent: Zurück und Stellstufen korrigieren

- In den Formularen des Verbraucher-Assistenten Navigation über Dropdown „Weiter / Zurück“ (HA bietet keinen nativen Zurück-Button für Formulare).
- Auf der Zusammenfassung direkt zu Leistungsgrenzen, Sollwertaktor oder Istwerten zurückspringen – Eingaben bleiben erhalten.
- Mindestleistung automatisch auf die nächste darstellbare aktive Stellstufe anheben, nur auf ausdrückliche Auswahl.
- Aktive Geräte-Mindestleistung des Modbus-Nummeraktors getrennt vom 0-Pause-Befehl prüfen.
- Präzise Wattvorschläge und Priorität ohne überflüssige Nachkommastellen in der Zusammenfassung.
- Bestehende Verbraucher, Entity-IDs, Regeln und Registerkonfigurationen unverändert.

## 0.2.2b2 — Erstinstallation ohne Netzsensor möglich

- Erste HA-Einrichtung lässt das Anlegen des Hubs ohne vorhandene Sensoren zu. Netzsensor ist beim ersten Schritt optional.
- In der Konfiguration jetzt direkt „Modbus-Datenquelle hinzufügen“ mit geführter Reihenfolge Gerät → Lesesensor → Lesetest → Anlagenzuordnung.
- Die Regelung lässt sich nicht einschalten, solange kein gültiger Netzleistungs-Sensor hinterlegt ist. Keine Befehle bei unvollständiger Einrichtung.
- Bereits eingerichtete Installationen und IDs bleiben unverändert.
- Regressionstests für leeren Bootstrap, vorhandene Sensoren und gesperrte Regelungsfreigabe.

## 0.2.2b1 – Einfache Einrichtung und Diagnosen

- Neues Hauptmenü: Anlage einrichten, Verbraucher einrichten, Einstellungen prüfen, Erweiterte Einstellungen.
- Geführte mehrstufige Einrichtungsdialoge mit Dropdowns für HA-Entitäten, Reglerart, Geräteeinheit und Phase.
- Bestehende Verbraucher über Assistent bearbeiten, IDs und Zeit-/Sicherheitsparameter erhalten.
- Netzvorzeichen und aktuelle physikalische Interpretation vor Speichern anzeigen.
- Aktor-Zuordnung vor Speichern auf Vorhandensein, Einheit, Gerätebereich, Stellstufen prüfen.
- Deutliche Hinweise zu fehlender Istleistungsmessung und dauerhaft angenommener Anforderung.
- Vorhandene Modbus-Lese- und Schreibpunkte sowie die reine Verteilungslogik bleiben unverändert.
- Kein automatischer Start der Regelung; keine Schreibbefehle beim Einrichtungscheck.
- Erweiterte Einstellungen behalten alle bisherigen technischen Formulare.

## 0.2.1a2 — Schreibhürde bei unbekanntem Initialzustand behoben

- Modbus-Schreibaktoren ohne Readback starten weiterhin ehrlich mit HA-Zustand `unknown`.
- Nur für eindeutig registrierte, eigene PV-Manager-Modbus-`number`-Entitäten mit explizit konfiguriertem Aus-/Pausewert ist ein erster EMS-Schreibbefehl trotz `unknown` erlaubt.
- Fehlende, `unavailable`, fremde oder mit Schreibfehlern markierte Aktoren bleiben gesperrt.
- Fehlermeldung nennt jetzt den tatsächlichen Home-Assistant-Zustand.
- Regelungsformel, Benutzer-Konfiguration und Geräteübersetzung unverändert.

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
