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
