#!/usr/bin/env python3
"""Erzeugt ein kompaktes tägliches EPUB für kleine E-Ink-Reader."""

from __future__ import annotations

import argparse
import html
import json
from html.parser import HTMLParser
import re
import tempfile
import urllib.request
import uuid
import zipfile
from datetime import date, datetime
from pathlib import Path
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo


USER_AGENT = "DailyDigest-Xteink/0.1 (+https://github.com/technikerleben/dailydigest)"

WEATHER_CODES = {
    0: "klar",
    1: "überwiegend klar",
    2: "teilweise bewölkt",
    3: "bewölkt",
    45: "neblig",
    48: "neblig mit Reif",
    51: "leichter Nieselregen",
    53: "Nieselregen",
    55: "starker Nieselregen",
    61: "leichter Regen",
    63: "Regen",
    65: "starker Regen",
    71: "leichter Schneefall",
    73: "Schneefall",
    75: "starker Schneefall",
    80: "leichte Regenschauer",
    81: "Regenschauer",
    82: "starke Regenschauer",
    95: "Gewitter",
    96: "Gewitter mit Hagel",
    99: "starkes Gewitter mit Hagel",
}

STYLE = """@charset \"UTF-8\";
html { color: #111; background: #fff; }
body { margin: 5%; font-family: sans-serif; font-size: 1em; line-height: 1.38; }
h1 { margin: 0 0 .55em; font-size: 1.55em; line-height: 1.12; }
h2 { margin: 1.15em 0 .3em; padding-top: .25em; border-top: .12em solid #222; font-size: 1.18em; line-height: 1.2; }
p { margin: .28em 0 .7em; }
a { color: #111; text-decoration: underline; }
.kicker { margin: 0 0 .35em; font-size: .82em; font-weight: bold; letter-spacing: .08em; text-transform: uppercase; }
.datum { margin: 0 0 1.4em; font-size: 1.05em; }
.hero { margin: 1.2em 0; padding: .8em 0; border-top: .2em solid #111; border-bottom: .2em solid #111; text-align: center; }
.gross { display: block; margin: .05em 0; font-size: 2.2em; font-weight: bold; line-height: 1; }
.klein { display: block; margin-top: .3em; font-size: .95em; }
.kompakt { margin: .45em 0; padding: .45em 0; border-bottom: .08em solid #999; }
.zeit { font-weight: bold; }
.hinweis { margin: 1em 0; padding: .65em; border: .1em solid #555; font-size: .9em; }
.quelle { font-size: .86em; }
.seitenwechsel { page-break-before: always; break-before: page; }
ul { margin: .35em 0 .8em 1.2em; padding: 0; }
li { margin-bottom: .35em; }
"""


def fetch_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)


def fetch_bytes(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.read()


def weather_code_text(code: int) -> str:
    return WEATHER_CODES.get(int(code), "wechselhaft")


def select_location(config: dict, current_date: date) -> dict:
    """Wählt anhand des Datums einen vorübergehenden Wetterort."""
    for rule in config.get("location_schedule", []):
        start = date.fromisoformat(rule.get("from", "0001-01-01"))
        end = date.fromisoformat(rule.get("through", "9999-12-31"))
        if start <= current_date <= end:
            return rule["location"]
    return config["location"]


def get_weather(location: dict) -> list[dict]:
    if location.get("route"):
        route_weather = []
        for stop in location["route"]:
            stop_location = {
                **stop,
                "timezone": location.get("timezone", "Europe/Copenhagen"),
            }
            forecast = get_weather(stop_location)[0]
            forecast["place"] = stop["name"]
            route_weather.append(forecast)
        return route_weather

    params = (
        f"latitude={location['latitude']}&longitude={location['longitude']}"
        "&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max"
        f"&timezone={location['timezone']}&forecast_days=3"
    )
    data = fetch_json(f"https://api.open-meteo.com/v1/forecast?{params}")
    daily = data["daily"]
    return [
        {
            "date": daily["time"][index],
            "condition": weather_code_text(daily["weather_code"][index]),
            "maximum": round(daily["temperature_2m_max"][index]),
            "minimum": round(daily["temperature_2m_min"][index]),
            "rain": round(daily["precipitation_probability_max"][index]),
        }
        for index in range(len(daily["time"]))
    ]


def clean_text(value: str | None, limit: int = 700) -> str:
    if not value:
        return ""
    value = html.unescape(re.sub(r"<[^>]+>", " ", value))
    value = re.sub(r"\s+", " ", value).strip()
    if len(value) <= limit:
        return value
    shortened = value[: limit - 1].rsplit(" ", 1)[0]
    return shortened + "…"


class ArticleParagraphParser(HTMLParser):
    """Sammelt längere Absätze aus dem eigentlichen Artikelbereich."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.article_depth = 0
        self.paragraph_depth = 0
        self.current: list[str] = []
        self.paragraphs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "article":
            self.article_depth += 1
        elif tag == "p" and self.article_depth:
            self.paragraph_depth += 1
            if self.paragraph_depth == 1:
                self.current = []

    def handle_data(self, data: str) -> None:
        if self.article_depth and self.paragraph_depth:
            self.current.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "p" and self.article_depth and self.paragraph_depth:
            self.paragraph_depth -= 1
            if self.paragraph_depth == 0:
                paragraph = clean_text(" ".join(self.current), 10000)
                if len(paragraph) >= 70 and paragraph not in self.paragraphs:
                    self.paragraphs.append(paragraph)
                self.current = []
        elif tag == "article" and self.article_depth:
            self.article_depth -= 1


def extract_article_text(payload: bytes, limit: int = 1800) -> str:
    parser = ArticleParagraphParser()
    parser.feed(payload.decode("utf-8", errors="replace"))
    return clean_text(" ".join(parser.paragraphs), limit)


def first_text(element: ET.Element, names: tuple[str, ...]) -> str:
    for child in element.iter():
        local_name = child.tag.rsplit("}", 1)[-1].lower()
        if local_name in names and child.text:
            return child.text.strip()
    return ""


def first_link(element: ET.Element) -> str:
    for child in element.iter():
        if child.tag.rsplit("}", 1)[-1].lower() != "link":
            continue
        if child.get("href"):
            return child.get("href", "")
        if child.text:
            return child.text.strip()
    return ""


def parse_feed(payload: bytes, source: str, summary_limit: int = 700) -> list[dict]:
    root = ET.fromstring(payload)
    entries = [
        item
        for item in root.iter()
        if item.tag.rsplit("}", 1)[-1].lower() in {"item", "entry"}
    ]
    parsed = []
    for entry in entries:
        title = clean_text(first_text(entry, ("title",)), 140)
        summary = clean_text(first_text(entry, ("description", "summary", "content")), summary_limit)
        link = first_link(entry)
        if title and link:
            parsed.append({"title": title, "summary": summary, "link": link, "source": source})
    return parsed


def get_news(news_config: dict) -> list[dict]:
    collected: list[dict] = []
    seen: set[str] = set()
    summary_limit = int(news_config.get("summary_length", 700))
    for feed in news_config.get("feeds", []):
        try:
            entries = parse_feed(fetch_bytes(feed["url"]), feed["name"], summary_limit)
        except Exception as exc:  # Ein einzelner Feed soll die Ausgabe nicht verhindern.
            print(f"Warnung: Feed {feed['name']} nicht erreichbar: {exc}")
            continue
        for entry in entries:
            key = entry["title"].casefold()
            if key not in seen:
                seen.add(key)
                collected.append(entry)
    selected = collected[: int(news_config.get("max_items", 6))]
    if news_config.get("enrich_articles", False):
        for entry in selected:
            try:
                article_text = extract_article_text(fetch_bytes(entry["link"]), summary_limit)
                if len(article_text) > len(entry["summary"]):
                    entry["summary"] = article_text
            except Exception as exc:
                print(f'Warnung: Artikel {entry["link"]} nicht ausführlich lesbar: {exc}')
    return selected


def xhtml(title: str, body: str) -> str:
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" lang="de" xml:lang="de">
<head><title>{html.escape(title)}</title><link rel="stylesheet" type="text/css" href="style.css"/></head>
<body>{body}</body>
</html>'''


def build_pages(config: dict, now: datetime, weather: list[dict], news: list[dict]) -> dict[str, str]:
    weekday = ("Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag")
    months = ("", "Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember")
    date_text = f"{weekday[now.weekday()]}, {now.day}. {months[now.month]} {now.year}"
    first = weather[0]
    route_weather = any("place" in item for item in weather)
    calendar_enabled = config.get("calendar", {}).get("enabled", True)
    appointments = config.get("calendar", {}).get("appointments", []) if calendar_enabled else []

    if route_weather:
        route_minimum = min(item["minimum"] for item in weather)
        route_maximum = max(item["maximum"] for item in weather)
        route_rain = max(item["rain"] for item in weather)
        hero_temperature = f"{route_minimum}–{route_maximum} °C"
        hero_condition = f"Streckenwetter · Regenrisiko bis {route_rain} %"
        overview_weather = "".join(
            f'<p class="kompakt"><strong>{html.escape(item["place"])}</strong>: '
            f'{html.escape(item["condition"].capitalize())}, {item["minimum"]} bis {item["maximum"]} °C, '
            f'Regen bis {item["rain"]} %.</p>'
            for item in weather
        )
    else:
        hero_temperature = f'{first["maximum"]} °C'
        hero_condition = first["condition"].capitalize()
        overview_weather = (
            f'<p>{html.escape(first["condition"].capitalize())}, '
            f'{first["minimum"]} bis {first["maximum"]} °C. '
            f'Regenwahrscheinlichkeit bis {first["rain"]} %.</p>'
        )

    appointment_lines = "".join(
        f'<p class="kompakt"><span class="zeit">{html.escape(item["time"])}</span> {html.escape(item["title"])}</p>'
        for item in appointments
    ) or "<p>Heute sind keine Termine eingetragen.</p>"

    cover = xhtml(
        config["title"],
        f'<p class="kicker">Persönliche Morgenausgabe</p><h1>{html.escape(config["title"])}</h1>'
        f'<p class="datum">{html.escape(date_text)}</p><div class="hero"><span class="gross">{html.escape(hero_temperature)}</span>'
        f'<span class="klein">{html.escape(hero_condition)}</span></div>'
        + (f'<p><strong>Termine:</strong> {len(appointments)}</p>' if calendar_enabled else "")
        + f'<p><strong>Nachrichten:</strong> {len(news)}</p>'
        f'<p class="quelle">Erstellt um {now:%H:%M} Uhr</p>',
    )

    overview = xhtml(
        "Heute auf einen Blick",
        f'<p class="kicker">{html.escape(date_text)}</p><h1>Heute auf einen Blick</h1>'
        f'<h2>Wetter</h2>{overview_weather}'
        + (f'<h2>Termine</h2>{appointment_lines}' if calendar_enabled else "")
        + (f'<h2>Wichtigste Meldung</h2><p>{html.escape(news[0]["title"])}</p>' if news else '<h2>Nachrichten</h2><p>Der Nachrichtenfeed war nicht erreichbar.</p>'),
    )

    weather_blocks = []
    for day in weather:
        parsed_date = datetime.fromisoformat(day["date"])
        label = (
            item_label
            if (item_label := day.get("place"))
            else f"{weekday[parsed_date.weekday()]}, {parsed_date.day}. {months[parsed_date.month]}"
        )
        weather_blocks.append(
            f'<h2>{html.escape(label)}</h2><p>{html.escape(day["condition"].capitalize())}. '
            f'{day["minimum"]} bis {day["maximum"]} °C. Regenwahrscheinlichkeit bis {day["rain"]} %.</p>'
        )
    weather_page = xhtml(
        f'Wetter für {config["location"]["name"]}',
        f'<p class="kicker">{html.escape(config["location"]["name"])}</p><h1>Wetter</h1>' + "".join(weather_blocks)
        + '<p class="quelle"><a href="https://open-meteo.com/">Quelle: Open-Meteo</a></p>',
    )

    calendar_page = xhtml(
        "Termine",
        '<p class="kicker">Demo-Kalender</p><h1>Meine Termine</h1>'
        '<div class="hinweis"><strong>Hinweis:</strong> Alle Termine sind fiktive Beispiele.</div>' + appointment_lines,
    )

    news_blocks = []
    for index, item in enumerate(news):
        page_class = ' class="seitenwechsel"' if index else ""
        summary = f'<p>{html.escape(item["summary"])}</p>' if item["summary"] else ""
        news_blocks.append(
            f'<h2{page_class}>{html.escape(item["title"])}</h2>{summary}'
            f'<p class="quelle"><a href="{html.escape(item["link"], quote=True)}">Quelle: {html.escape(item["source"])}</a></p>'
        )
    if not news_blocks:
        news_blocks.append('<div class="hinweis">Heute konnten keine Nachrichten geladen werden. Die EPUB wurde trotzdem erstellt.</div>')
    news_page = xhtml(
        "Nachrichten",
        f'<p class="kicker">Stand: {now:%d.%m.%Y, %H:%M} Uhr</p><h1>Nachrichten</h1>' + "".join(news_blocks),
    )

    sources = xhtml(
        "Quellen und Hinweise",
        '<p class="kicker">Zum Tagesblatt</p><h1>Quellen und Hinweise</h1>'
        '<h2>Wetter</h2><p>Prognosedaten von Open-Meteo.</p>'
        '<h2>Nachrichten</h2><p>Ausführlichere Anrisse aus den konfigurierten RSS-Feeds. Die Überschriften verlinken auf die Originalmeldungen.</p>'
        + ('<h2>Termine</h2><p>Die aktuelle Projektversion verwendet ausschließlich fiktive Termine.</p>' if calendar_enabled else ""),
    )
    pages = {
        "cover.xhtml": cover,
        "overview.xhtml": overview,
        "weather.xhtml": weather_page,
    }
    if calendar_enabled:
        pages["calendar.xhtml"] = calendar_page
    pages["news.xhtml"] = news_page
    pages["sources.xhtml"] = sources
    return pages


def write_epub(output: Path, config: dict, now: datetime, weather: list[dict], news: list[dict]) -> None:
    pages = build_pages(config, now, weather, news)
    book_id = f"urn:uuid:{uuid.uuid4()}"
    modified = now.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")
    manifest = "".join(
        f'<item id="p{index}" href="{name}" media-type="application/xhtml+xml"/>'
        for index, name in enumerate(pages, 1)
    )
    spine = "".join(f'<itemref idref="p{index}"/>' for index in range(1, len(pages) + 1))
    nav_titles = {
        "cover.xhtml": "Titelseite",
        "overview.xhtml": "Heute",
        "weather.xhtml": "Wetter",
        "calendar.xhtml": "Termine",
        "news.xhtml": "Nachrichten",
        "sources.xhtml": "Quellen",
    }
    nav_items = "".join(
        f'<li><a href="{name}">{html.escape(nav_titles[name])}</a></li>'
        for name in pages
    )
    opf = f'''<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="book-id" xml:lang="de">
<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="book-id">{book_id}</dc:identifier>
<dc:title>{html.escape(config["title"])}</dc:title><dc:language>de</dc:language><dc:date>{now:%Y-%m-%d}</dc:date>
<meta property="dcterms:modified">{modified}</meta></metadata>
<manifest><item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
<item id="css" href="style.css" media-type="text/css"/>{manifest}</manifest><spine>{spine}</spine></package>'''
    nav = xhtml("Inhalt", f'<nav xmlns:epub="http://www.idpf.org/2007/ops" epub:type="toc"><h1>Inhalt</h1><ol>{nav_items}</ol></nav>')
    container = '''<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles>
<rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>'''

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        (root / "META-INF").mkdir()
        (root / "OEBPS").mkdir()
        (root / "mimetype").write_text("application/epub+zip", encoding="utf-8")
        (root / "META-INF" / "container.xml").write_text(container, encoding="utf-8")
        (root / "OEBPS" / "content.opf").write_text(opf, encoding="utf-8")
        (root / "OEBPS" / "nav.xhtml").write_text(nav, encoding="utf-8")
        (root / "OEBPS" / "style.css").write_text(STYLE, encoding="utf-8")
        for name, content in pages.items():
            (root / "OEBPS" / name).write_text(content, encoding="utf-8")

        with zipfile.ZipFile(output, "w") as archive:
            archive.write(root / "mimetype", "mimetype", compress_type=zipfile.ZIP_STORED)
            for path in sorted((root / "META-INF").rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(root), compress_type=zipfile.ZIP_DEFLATED)
            for path in sorted((root / "OEBPS").rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(root), compress_type=zipfile.ZIP_DEFLATED)



def write_publication_files(
    directory: Path,
    config: dict,
    now: datetime,
    weather: list[dict],
    news: list[dict],
    epub_name: str,
) -> None:
    """Erzeugt OPDS-Katalog und Downloadseite für GitHub Pages."""
    base_url = config["publication"]["base_url"].rstrip("/")
    updated = now.isoformat(timespec="seconds")
    date_text = now.strftime("%d.%m.%Y")
    issue_title = f'{config["title"]} – {date_text}'
    if weather and any("place" in item for item in weather):
        weather_text = (
            f'Streckenwetter: {min(item["minimum"] for item in weather)} bis '
            f'{max(item["maximum"] for item in weather)} °C, '
            f'Regenrisiko bis {max(item["rain"] for item in weather)} %'
        )
    elif weather:
        weather_text = (
            f'{weather[0]["condition"].capitalize()}, '
            f'{weather[0]["minimum"]} bis {weather[0]["maximum"]} °C'
        )
    else:
        weather_text = "Wetterdaten nicht verfügbar"
    summary = f"{weather_text}. {len(news)} Nachrichtenmeldungen."

    opds = f'''<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <id>tag:technikerleben.github.io,2026:dailydigest</id>
  <title>{html.escape(config["title"])}</title>
  <updated>{html.escape(updated)}</updated>
  <author><name>Daily Digest</name></author>
  <link rel="self" href="{html.escape(base_url)}/opds.xml" type="application/atom+xml;profile=opds-catalog;kind=acquisition"/>
  <link rel="alternate" href="{html.escape(base_url)}/" type="text/html"/>
  <entry>
    <id>tag:technikerleben.github.io,{now:%Y-%m-%d}:dailydigest</id>
    <title>{html.escape(issue_title)}</title>
    <updated>{html.escape(updated)}</updated>
    <author><name>Daily Digest</name></author>
    <summary>{html.escape(summary)}</summary>
    <link rel="http://opds-spec.org/acquisition/open-access" href="{html.escape(base_url)}/{html.escape(epub_name)}" type="application/epub+zip"/>
  </entry>
</feed>
'''

    page = f'''<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>{html.escape(issue_title)}</title>
  <style>
    body {{ max-width: 42rem; margin: 0 auto; padding: 2rem 1.25rem; font: 18px/1.5 system-ui, sans-serif; color: #17232d; background: #f5f4f1; }}
    main {{ background: #fff; border-radius: 1rem; padding: 1.5rem; box-shadow: 0 .25rem 1.2rem #0002; }}
    h1 {{ margin-top: 0; color: #3e5668; }}
    .weather {{ border-block: 2px solid #3e5668; padding: 1rem 0; }}
    a.button {{ display: block; margin: 1.25rem 0; padding: .9rem 1rem; border-radius: .7rem; color: #fff; background: #9e4e22; text-align: center; font-weight: 700; text-decoration: none; }}
    small {{ color: #5a6a78; }}
  </style>
</head>
<body>
  <main>
    <p>Persönliche Morgenausgabe</p>
    <h1>{html.escape(issue_title)}</h1>
    <p class="weather">{html.escape(weather_text)}</p>
    <p>{len(news)} Nachrichtenmeldungen.</p>
    <a class="button" href="{html.escape(epub_name)}">EPUB herunterladen</a>
    <p><a href="opds.xml">OPDS-Katalog öffnen</a></p>
    <small>Automatisch erstellt am {now:%d.%m.%Y} um {now:%H:%M} Uhr.</small>
  </main>
</body>
</html>
'''

    directory.mkdir(parents=True, exist_ok=True)
    (directory / "opds.xml").write_text(opds, encoding="utf-8")
    (directory / "index.html").write_text(page, encoding="utf-8")
    (directory / ".nojekyll").write_text("", encoding="utf-8")

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--output", default="dist/dailydigest.epub")
    arguments = parser.parse_args()

    config = json.loads(Path(arguments.config).read_text(encoding="utf-8"))
    timezone = ZoneInfo(config["location"]["timezone"])
    now = datetime.now(timezone)
    config["location"] = select_location(config, now.date())
    timezone = ZoneInfo(config["location"]["timezone"])
    now = now.astimezone(timezone)
    weather = get_weather(config["location"])
    news = get_news(config["news"])
    output = Path(arguments.output)
    write_epub(output, config, now, weather, news)
    write_publication_files(output.parent, config, now, weather, news, output.name)

    base_url = config["publication"]["base_url"].rstrip("/")
    manifest = {
        "date": now.date().isoformat(),
        "generated_at": now.isoformat(timespec="seconds"),
        "file": output.name,
        "size": output.stat().st_size,
        "epub_url": f"{base_url}/{output.name}",
        "opds_url": f"{base_url}/opds.xml",
    }
    (output.parent / "latest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Erstellt: {output} ({output.stat().st_size} Bytes)")


if __name__ == "__main__":
    main()
