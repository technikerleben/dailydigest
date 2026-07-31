import json
import sys
import tempfile
import unittest
import zipfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from generate import clean_text, weather_code_text, write_epub


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

    def test_epub_structure(self):
        config = {
            "title": "Testausgabe",
            "location": {"name": "Wetter (Ruhr)"},
            "calendar": {"appointments": [{"time": "08:00", "title": "Testtermin"}]},
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
            with zipfile.ZipFile(output) as archive:
                self.assertEqual(archive.namelist()[0], "mimetype")
                self.assertEqual(archive.getinfo("mimetype").compress_type, zipfile.ZIP_STORED)
                self.assertIn("OEBPS/content.opf", archive.namelist())
                self.assertIn("OEBPS/news.xhtml", archive.namelist())
                news_page = archive.read("OEBPS/news.xhtml").decode("utf-8")
                self.assertEqual(news_page.count('class="seitenwechsel"'), 2)


if __name__ == "__main__":
    unittest.main()
