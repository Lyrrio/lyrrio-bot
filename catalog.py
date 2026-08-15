from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.casefold())
    value = "".join(char for char in value if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


@dataclass(frozen=True)
class Character:
    id: int
    name: str


class AnimeCatalog:
    def __init__(self, path: Path, config_path: Path | None = None):
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.generated_at = payload.get("generated_at", "inconnue")
        self._anime = payload["anime"]
        self._indexes: dict[str, dict[str, Character | None]] = {}
        for slug, anime in self._anime.items():
            index: dict[str, Character | None] = {}
            for raw in anime["characters"]:
                character = Character(int(raw["id"]), raw["name"])
                for alias in raw["aliases"]:
                    key = normalize(alias)
                    if not key:
                        continue
                    previous = index.get(key)
                    if previous is None and key in index:
                        continue
                    index[key] = character if previous in (None, character) else None
            self._indexes[slug] = index
        if config_path and config_path.exists():
            self._apply_manual_aliases(config_path)

    def choices(self) -> list[tuple[str, str]]:
        return [(slug, data["label"]) for slug, data in self._anime.items()]

    def label(self, slug: str) -> str:
        return self._anime[slug]["label"]

    def count(self, slug: str) -> int:
        return len(self._anime[slug]["characters"])

    def resolve(self, slug: str, answer: str) -> Character | None:
        return self._resolve_index(self._indexes[slug], answer)

    def _apply_manual_aliases(self, config_path: Path) -> None:
        config = json.loads(config_path.read_text(encoding="utf-8"))
        for slug, settings in config.items():
            index = self._indexes.get(slug)
            if index is None:
                continue
            for canonical, aliases in settings.get("manual_aliases", {}).items():
                character = self._resolve_index(index, canonical)
                if character is None:
                    continue
                for alias in aliases:
                    key = normalize(alias)
                    if not key:
                        continue
                    previous = index.get(key)
                    if previous is None and key in index:
                        continue
                    index[key] = character if previous in (None, character) else None

    @staticmethod
    def _resolve_index(index: dict[str, Character | None], answer: str) -> Character | None:
        query = normalize(answer)
        if query in index:
            return index[query]
        if len(query) < 4:
            return None

        # Conserve le meilleur alias de chaque personnage, puis exige un score
        # net afin qu'une faute de frappe soit acceptée sans deviner au hasard.
        scores: dict[Character, float] = {}
        for alias, character in index.items():
            if character is None or abs(len(alias) - len(query)) > max(2, len(query) // 3):
                continue
            score = SequenceMatcher(None, query, alias).ratio()
            if score > scores.get(character, 0.0):
                scores[character] = score
        if not scores:
            return None
        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        best_character, best_score = ranked[0]
        cutoff = 0.72 if len(query) <= 4 else 0.78
        second_score = ranked[1][1] if len(ranked) > 1 else 0.0
        if best_score >= cutoff and (best_score >= 0.90 or best_score - second_score >= 0.08):
            return best_character
        return None
