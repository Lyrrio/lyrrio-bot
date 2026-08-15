import unittest
from pathlib import Path

from catalog import AnimeCatalog


class CatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = AnimeCatalog(Path(__file__).resolve().parents[1] / "data" / "catalog.json")

    def test_every_anime_has_characters(self):
        for slug, _ in self.catalog.choices():
            self.assertGreater(self.catalog.count(slug), 0, slug)

    def test_typo_and_alias_resolution(self):
        cases = [
            ("one-piece", "Lufy", "Luffy"),
            ("one-piece", "Law", "Law"),
            ("naruto", "Narutto", "Naruto"),
            ("mushoku-tensei", "Rudeuss", "Rudeus"),
            ("my-hero-academia", "Deku", "Izuku"),
            ("demon-slayer", "Tanjiroo", "Tanjirou"),
            ("jujutsu-kaisen", "Gojo", "Gojou"),
            ("death-note", "Kira", "Light"),
        ]
        for slug, answer, expected in cases:
            with self.subTest(slug=slug, answer=answer):
                result = self.catalog.resolve(slug, answer)
                self.assertIsNotNone(result)
                self.assertIn(expected, result.name)


if __name__ == "__main__":
    unittest.main()
