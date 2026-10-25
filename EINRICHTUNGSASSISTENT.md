# Erstinstallation ohne Sensoren (ab 0.2.2b2)

1. PV Energiemanager unter Geräte & Dienste installieren. Der vorhandene Netzsensor ist **optional**; bei Modbus-Neuanbindung leer lassen.
2. Unter **Konfigurieren → Modbus-Datenquelle hinzufügen → Modbus-TCP-Gerät hinzufügen** die Geräteverbindung konfigurieren.
3. Dialog erneut öffnen: **Modbus-Datenquelle hinzufügen → Modbus-Lesesensor hinzufügen**. Registeradresse, FC03/04, Format, Einheit und Skalierung wählen. Das Gerät bzw. Register ist **kein fester Simulatordefault**.
4. Optional unter **Modbus-Datenquelle hinzufügen → Register testweise lesen** prüfen.
5. Danach **Anlage einrichten** und den neu erzeugten Netzsensor auswählen; Vorzeichen prüfen.
6. Die Regelung erst nach Prüfung der Anlage und Verbraucher aktivieren. Sie wird technisch blockiert, falls der Netzsensor fehlt oder ungültig ist.

Für einen bereits installierten PV-Manager ist keine Neuinstallation erforderlich. Die bestehenden Sensoren und Geräte bleiben erhalten.

---

# Einfacher Einrichtungsassistent – PV-Manager 0.2.2b1

## Zuerst Anlage

HA → Einstellungen → Geräte & Dienste → PV Energiemanager → Konfigurieren → **1. Anlage einrichten**.

1. Vorhandene Netzleistungs-Entität auswählen; optional PV- und Batteriesensoren.
2. Vorzeichen des Netzsensors wählen: Positiv = Einspeisung oder Negativ = Einspeisung. Mit **bekannter Netzbezug- und Einspeisesituation** gegenprüfen.
3. Aktuelle Interpretation („Netzbezug“/„Einspeisung“) lesen und die korrekte Zuordnung bestätigen. Reserve und Intervall nach Wunsch anpassen.

## Dann Verbraucher

**2. Verbraucher einrichten** → „Neuen Verbraucher“ oder einen vorhandenen Verbraucher zur Korrektur auswählen.

1. Name, Regelungsart, Priorität und Leistungsgrenzen in Watt.
2. Bestehenden schreibbaren HA-Sollwert auswählen (inklusive selbst erzeugten Modbus-`number`-Entitäten) oder Ein/Aus-Schalter wählen. Einheit W/kW/A passend zur gewählten Entität; bei A Phasenanzahl und Spannung.
3. Tatsächlich gemessene Istleistung (W/kW) auswählen und optional Nachfrage/Anforderung (binärer Sensor/Schalter).
4. Zusammenfassung, Warnungen und Einheiten-/Grenzenprüfung ansehen, erst dann bestätigen.

**Hinweis:** Neu anzulegende Modbus-Schreibregister werden vorläufig noch über **4. Erweiterte Einstellungen → Modbus-Schreibaktor hinzufügen** erstellt. Danach einfach zum Verbraucher-Assistenten zurückkehren und den fertigen `number`-Ausgang auswählen. Vorhandene Mess- und Schreibpunkte bleiben erhalten.

## Vor Reglerfreigabe prüfen

**3. Einstellungen prüfen** zeigt ohne Befehle zu senden, ob Netzsensor, Richtung, Aktoren und Istwerte plausibel sind. Ein Zustand „Leistungsmangel“ trotz PV-Erzeugung kann korrekt sein: Bei 21 kW PV und gleichzeitig 34,5 kW Last besteht echter Netzbezug.

Für die erste Erprobung ausschließlich den Simulator verwenden. Kein blindes Registerwert-0-Senden; Aus-/Pause-Semantik ist je Schreibpunkt getrennt und muss vorher manuell geprüft werden.

## Geprüftes / nicht Geprüftes

Automatische lokale Pure-Python-Regressionstests und GitHub-HACS-/Hassfest-Checks; kein tatsächlicher Home-Assistant-UI-Laufzeittest in unserer Umgebung. Die praktische Bestätigung erfolgt nach HACS-Update beim Nutzer.

## Stellstufen und Rücknavigation (0.2.2b3)

Im Verbraucherassistenten über das Feld „Navigation“ zum vorherigen Formular zurückkehren und Eingaben bearbeiten. Auf der letzten Zusammenfassung führt „Was möchtest du tun?“ unmittelbar zu den Leistungsgrenzen, den Aktoren oder den Rückmeldungen. Wähle alternativ „Mindestleistung automatisch anpassen“, wenn eine Wattvorgabe nicht zu den möglichen A-Stufen passt. Anschließend den korrigierten Wert prüfen und ausdrücklich speichern.

Beispiel: Drei Phasen zu 230 V, 1-A-Stufen, minimale aktive Wallboxvorgabe 6 A → 4140 W. Die 0-A-Stellung der HA-Nummer repräsentiert die separat konfigurierte Ladepause; sie ist **keine gültige aktive Ladestufe**.
