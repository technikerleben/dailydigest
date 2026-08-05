import json
import sys
import tempfile
import unittest
import zipfile
from xml.etree import ElementTree as ET
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from generate import (
    build_pages,
    clean_text,
    extract_article_text,
    parse_listing,
    summarize_day_periods,
    select_location,
    weather_code_text,
    write_epub,
    write_publication_files,
)


class GeneratorTests(unittest.TestCase):
    def test_weather_code(self):
        self.assertEqual(weather_code_text(3), "bewölkt")
        self.assertEqual(weather_code_text(12345), "wechselhaft")

    def test_clean_text(self):
        self.assertEqual(clean_text("<p>Hallo&nbsp; Welt</p>"), "Hallo Welt")

    def test_long_summary_uses_new_default_limit(self):
        summary = clean_text("Nachricht " * 100)
        self.assertLessEqual(len(summary), 700)
        self.assertTrue(summary.endswith("…"))

    def test_extracts_longer_article_text(self):
        payload = b"""
        <html><body><nav><p>Navigation should be ignored completely.</p></nav>
        <article>
          <p>Dies ist ein ausfuehrlicher erster Absatz mit genuegend Inhalt, damit er als Teil des Nachrichtentextes erkannt wird.</p>
          <p>Dies ist ein zweiter laengerer Absatz mit weiteren wichtigen Hintergruenden und Zusammenhaengen fuer die Leserinnen und Leser.</p>
        </article></body></html>
        """
        text = extract_article_text(payload, 500)
        self.assertIn("erster Absatz", text)
        self.assertIn("zweiter laengerer Absatz", text)
        self.assertNotIn("Navigation", text)

    def test_weather_day_periods(self):
        hourly = {
            "time": [f"2026-08-05T{hour:02d}:00" for hour in range(24)],
            "temperature_2m": [10 + hour / 2 for hour in range(24)],
            "precipitation_probability": list(range(24)),
            "weather_code": [1] * 6 + [2] * 6 + [3] * 6 + [61] * 6,
        }
        periods = summarize_day_periods(hourly, "2026-08-05")
        self.assertEqual(
            [period["label"] for period in periods],
            ["Morgen", "Nachmittag", "Abend"],
        )
        self.assertEqual(periods[0]["minimum"], 13)
        self.assertEqual(periods[2]["condition"], "leichter Regen")

    def test_listing_keeps_only_article_links(self):
        payload = b"""
        <main>
          <a href="/nrw/test-artikel-100.html">
            <span>Eine ausreichend lange regionale Meldung</span>
          </a>
          <a href="/navigation.html">Navigation</a>
        </main>
        """
        links = parse_listing(
            payload,
            "https://www1.wdr.de/start/",
            r"^https://www1\.wdr\.de/nrw/.+-\d+\.html$",
        )
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0]["title"], "Eine ausreichend lange regionale Meldung")

    def test_location_schedule(self):
        config = {
            "location": {"name": "Wetter (Ruhr)"},
            "location_schedule": [
                {"through": "2026-08-07", "location": {"name": "Kappeln"}},
                {
                    "from": "2026-08-08",
                    "through": "2026-08-08",
                    "location": {"name": "Reisetag"},
                },
                {
                    "from": "2026-08-09",
                    "through": "2026-08-16",
                    "location": {"name": "Saltum Strand"},
                },
            ],
        }
        self.assertEqual(select_location(config, datetime(2026, 8, 7).date())["name"], "Kappeln")
        self.assertEqual(select_location(config, datetime(2026, 8, 8).date())["name"], "Reisetag")
        self.assertEqual(select_location(config, datetime(2026, 8, 9).date())["name"], "Saltum Strand")
        self.assertEqual(select_location(config, datetime(2026, 8, 17).date())["name"], "Wetter (Ruhr)")

    def test_calendar_can_be_disabled(self):
        config = {
            "title": "Testausgabe",
            "location": {"name": "Saltum Strand"},
            "calendar": {"enabled": False, "appointments": []},
        }
        weather = [
            {
                "date": "2026-08-09",
                "condition": "klar",
                "maximum": 20,
                "minimum": 10,
                "rain": 5,
            }
        ]
        pages = build_pages(config, datetime(2026, 8, 9, 5, 15), weather, [])
        self.assertNotIn("calendar.xhtml", pages)
        self.assertNotIn("Termine", pages["cover.xhtml"])

    def test_epub_structure(self):
        config = {
            "title": "Testausgabe",
            "location": {"name": "Wetter (Ruhr)"},
            "calendar": {"appointments": [{"time": "08:00", "title": "Testtermin"}]},
            "publication": {"base_url": "https://technikerleben.github.io/dailydigest"},
        }
        weather = [{"date": "2026-07-22", "condition": "bewölkt", "maximum": 21, "minimum": 12, "rain": 40}]
        news = [
            {"title": "Meldung 1", "summary": "Ausführlicher Text 1", "link": "https://example.com/1", "source": "Test"},
            {"title": "Meldung 2", "summary": "Ausführlicher Text 2", "link": "https://example.com/2", "source": "Test"},
            {"title": "Meldung 3", "summary": "Ausführlicher Text 3", "link": "https://example.com/3", "source": "Test"},
        ]
        now = datetime(2026, 7, 22, 6, 30, tzinfo=ZoneInfo("Europe/Berlin"))

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "test.epub"
            write_epub(output, config, now, weather, news)
            write_publication_files(output.parent, config, now, weather, news, output.name)
            with zipfile.ZipFile(output) as archive:
                self.assertEqual(archive.namelist()[0], "mimetype")
                self.assertEqual(archive.getinfo("mimetype").compress_type, zipfile.ZIP_STORED)
                self.assertIn("OEBPS/content.opf", archive.namelist())
                self.assertIn("OEBPS/news.xhtml", archive.namelist())
                news_page = archive.read("OEBPS/news.xhtml").decode("utf-8")
                self.assertEqual(news_page.count('class="seitenwechsel"'), 2)

            self.assertTrue((output.parent / "index.html").exists())
            self.assertTrue((output.parent / ".nojekyll").exists())
            opds_path = output.parent / "opds.xml"
            self.assertTrue(opds_path.exists())
            ET.parse(opds_path)
            opds_text = opds_path.read_text(encoding="utf-8")
            self.assertIn("http://opds-spec.org/acquisition/open-access", opds_text)
            self.assertIn("test.epub", opds_text)


if __name__ == "__main__":
    unittest.main()
