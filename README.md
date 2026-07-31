# Daily Digest für Xteink

Dieses Projekt erzeugt jeden Morgen automatisch eine kompakte EPUB-Ausgabe für kleine E-Ink-Reader wie den Xteink X4 Pro.

Die aktuelle Grundversion enthält:

- Wetter für Wetter (Ruhr) über Open-Meteo
- ausführlichere Nachrichtenanrisse aus offiziellen RSS-Feeds
- klar gekennzeichnete Demo-Termine
- ein reduziertes, Xteink-freundliches EPUB-Layout
- einen täglichen GitHub-Actions-Lauf und einen manuellen Startknopf

## Ausgabe erzeugen

Python 3.11 oder neuer genügt; zusätzliche Pakete sind nicht erforderlich.

```bash
python src/generate.py --config config.json --output dist/dailydigest.epub
```

Die Datei `dist/latest.json` wird zusätzlich erzeugt. Sie kann später vom Reader verwendet werden, um eine neue Ausgabe zu erkennen.

## Automatischer Lauf

Der Workflow **Daily EPUB** läuft täglich um 04:30 UTC. Das entspricht 06:30 Uhr während der deutschen Sommerzeit und 05:30 Uhr während der Winterzeit. Er kann außerdem unter **Actions → Daily EPUB → Run workflow** manuell gestartet werden.

Die EPUB-Datei wird als Workflow-Artefakt `xteink-dailydigest` für sieben Tage gespeichert. Eine öffentliche Reader-Auslieferung ist noch nicht aktiviert.

## Datenschutz

Das Repository ist aktuell öffentlich. Deshalb enthält es ausschließlich öffentliche Wetter- und Nachrichtendaten sowie fiktive Termine. Private Kalenderadressen, Passwörter und Tokens dürfen niemals in `config.json` eingetragen werden. Spätere Zugangsdaten gehören in GitHub Actions Secrets.

## Quellen

- Wetter: [Open-Meteo](https://open-meteo.com/)
- Nachrichten: [tagesschau.de RSS](https://www.tagesschau.de/infoservices/rssfeeds)

Die Nachrichten werden als Anrisse von bis zu 700 Zeichen mit sichtbarer Quellenangabe und Link zum Original ausgegeben. Jede Meldung beginnt auf einer eigenen EPUB-Seite. Die Workflow-Artefakte werden nach sieben Tagen gelöscht.
