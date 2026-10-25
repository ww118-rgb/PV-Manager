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
