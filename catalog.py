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


def make_slug(value: str) -> str:
    return normalize(value).replace(" ", "-")


@dataclass(frozen=True)
class Character:
    id: int
    name: str
    aliases: tuple[str, ...] = ()
    custom: bool = False


class AnimeCatalog:
    def __init__(
        self,
        path: Path,
        config_path: Path | None = None,
        edits_path: Path | None = None,
    ):
        self.path = path
        self.config_path = config_path
        self.edits_path = edits_path
        self.generated_at = "inconnue"
        self._base_anime: dict[str, dict] = {}
        self._edits = self._empty_edits()
        self._anime: dict[str, dict] = {}
        self._indexes: dict[str, dict[str, Character | None]] = {}
        self._aliases_by_id: dict[str, dict[int, list[str]]] = {}
        self.reload()

    @staticmethod
    def _empty_edits() -> dict:
        return {
            "next_character_id": -1,
            "custom_anime": {},
            "anime_edits": {},
            "deleted_anime": [],
        }

    def reload(self) -> None:
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        self.generated_at = payload.get("generated_at", "inconnue")
        self._base_anime = payload["anime"]
        if self.edits_path and self.edits_path.exists():
            saved = json.loads(self.edits_path.read_text(encoding="utf-8"))
            self._edits = {**self._empty_edits(), **saved}
        self._rebuild()

    def _rebuild(self) -> None:
        deleted_anime = set(self._edits.get("deleted_anime", []))
        anime: dict[str, dict] = {}
        for slug, raw in self._base_anime.items():
            if slug in deleted_anime:
                continue
            anime[slug] = {
                "label": raw["label"],
                "custom": False,
                "characters": [dict(character) for character in raw["characters"]],
            }
        for slug, raw in self._edits.get("custom_anime", {}).items():
            if slug in deleted_anime:
                continue
            anime[slug] = {
                "label": raw["label"],
                "custom": True,
                "characters": [dict(character) for character in raw.get("characters", [])],
            }

        for slug, changes in self._edits.get("anime_edits", {}).items():
            if slug not in anime:
                continue
            if changes.get("label"):
                anime[slug]["label"] = changes["label"]
            deleted_ids = {int(value) for value in changes.get("deleted_character_ids", [])}
            character_edits = changes.get("character_edits", {})
            characters = []
            for raw in anime[slug]["characters"]:
                if int(raw["id"]) in deleted_ids:
                    continue
                item = dict(raw)
                edit = character_edits.get(str(item["id"]), {})
                if edit.get("name"):
                    item["name"] = edit["name"]
                item["aliases"] = list(dict.fromkeys([*item.get("aliases", []), *edit.get("aliases", [])]))
                characters.append(item)
            characters.extend(dict(item) for item in changes.get("added_characters", []))
            anime[slug]["characters"] = characters

        self._anime = anime
        self._indexes = {}
        self._aliases_by_id = {}
        for slug, raw_anime in anime.items():
            index: dict[str, Character | None] = {}
            aliases_by_id: dict[int, list[str]] = {}
            for raw in raw_anime["characters"]:
                aliases = tuple(dict.fromkeys([raw["name"], *raw.get("aliases", [])]))
                character = Character(
                    int(raw["id"]), raw["name"], aliases, bool(raw_anime["custom"])
                )
                aliases_by_id[character.id] = list(aliases)
                for alias in aliases:
                    self._index_alias(index, alias, character)
            self._indexes[slug] = index
            self._aliases_by_id[slug] = aliases_by_id
        if self.config_path and self.config_path.exists():
            self._apply_manual_aliases(self.config_path)

    @staticmethod
    def _index_alias(
        index: dict[str, Character | None], alias: str, character: Character
    ) -> None:
        key = normalize(alias)
        if not key:
            return
        if key not in index:
            index[key] = character
        elif index[key] != character:
            index[key] = None

    def _save(self) -> None:
        if not self.edits_path:
            raise RuntimeError("Aucun fichier de modifications n'est configuré.")
        self.edits_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.edits_path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(self._edits, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(self.edits_path)
        self._rebuild()

    def choices(self) -> list[tuple[str, str]]:
        return sorted(
            ((slug, data["label"]) for slug, data in self._anime.items()),
            key=lambda item: item[1].casefold(),
        )

    def exists(self, slug: str) -> bool:
        return slug in self._anime

    def label(self, slug: str) -> str:
        return self._anime[slug]["label"]

    def count(self, slug: str) -> int:
        return len(self._anime[slug]["characters"])

    def is_custom(self, slug: str) -> bool:
        return bool(self._anime[slug]["custom"])

    def characters(self, slug: str) -> list[Character]:
        return sorted(
            (
                Character(
                    int(raw["id"]),
                    raw["name"],
                    tuple(self._aliases_by_id.get(slug, {}).get(int(raw["id"]), [raw["name"]])),
                    self.is_custom(slug),
                )
                for raw in self._anime[slug]["characters"]
            ),
            key=lambda character: character.name.casefold(),
        )

    def find_characters(self, slug: str, search: str = "") -> list[Character]:
        query = normalize(search)
        characters = self.characters(slug)
        if not query:
            return characters
        return [
            character
            for character in characters
            if any(query in normalize(alias) for alias in character.aliases)
        ]

    def resolve(self, slug: str, answer: str) -> Character | None:
        return self._resolve_index(self._indexes[slug], answer)

    def add_anime(self, label: str, slug: str | None = None) -> str:
        chosen_slug = make_slug(slug or label)
        if not chosen_slug:
            raise ValueError("Le nom de l'anime est invalide.")
        if chosen_slug in self._anime:
            raise ValueError("Cet anime existe déjà.")
        self._edits.setdefault("custom_anime", {})[chosen_slug] = {
            "label": label.strip(),
            "characters": [],
        }
        deleted = self._edits.setdefault("deleted_anime", [])
        if chosen_slug in deleted:
            deleted.remove(chosen_slug)
        self._save()
        return chosen_slug

    def rename_anime(self, slug: str, label: str) -> None:
        self._require_anime(slug)
        changes = self._anime_changes(slug)
        changes["label"] = label.strip()
        self._save()

    def delete_anime(self, slug: str) -> None:
        self._require_anime(slug)
        if slug in self._edits.get("custom_anime", {}):
            del self._edits["custom_anime"][slug]
            self._edits.get("anime_edits", {}).pop(slug, None)
        else:
            deleted = self._edits.setdefault("deleted_anime", [])
            if slug not in deleted:
                deleted.append(slug)
        self._save()

    def add_character(self, slug: str, name: str, aliases: list[str] | None = None) -> Character:
        self._require_anime(slug)
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("Le nom du personnage est vide.")
        if self.resolve(slug, clean_name):
            raise ValueError("Ce personnage ou ce nom existe déjà.")
        character_id = int(self._edits.get("next_character_id", -1))
        self._edits["next_character_id"] = character_id - 1
        raw = {
            "id": character_id,
            "name": clean_name,
            "aliases": self._clean_aliases(aliases or []),
        }
        if slug in self._edits.get("custom_anime", {}):
            self._edits["custom_anime"][slug].setdefault("characters", []).append(raw)
        else:
            self._anime_changes(slug).setdefault("added_characters", []).append(raw)
        self._save()
        return self.resolve(slug, clean_name)  # type: ignore[return-value]

    def delete_character(self, slug: str, answer: str) -> Character:
        character = self._require_character(slug, answer)
        custom = self._edits.get("custom_anime", {}).get(slug)
        if custom:
            custom["characters"] = [
                item for item in custom.get("characters", []) if int(item["id"]) != character.id
            ]
        else:
            changes = self._anime_changes(slug)
            added = changes.setdefault("added_characters", [])
            if any(int(item["id"]) == character.id for item in added):
                changes["added_characters"] = [
                    item for item in added if int(item["id"]) != character.id
                ]
            else:
                deleted = changes.setdefault("deleted_character_ids", [])
                if character.id not in deleted:
                    deleted.append(character.id)
            changes.setdefault("character_edits", {}).pop(str(character.id), None)
        self._save()
        return character

    def rename_character(self, slug: str, answer: str, new_name: str) -> Character:
        character = self._require_character(slug, answer)
        clean_name = new_name.strip()
        if not clean_name:
            raise ValueError("Le nouveau nom est vide.")
        self._character_edit(slug, character.id)["name"] = clean_name
        self._save()
        return self.resolve(slug, clean_name)  # type: ignore[return-value]

    def add_alias(self, slug: str, answer: str, alias: str) -> Character:
        character = self._require_character(slug, answer)
        clean_alias = alias.strip()
        if not normalize(clean_alias):
            raise ValueError("Le surnom est vide.")
        existing = self.resolve(slug, clean_alias)
        if existing and existing.id != character.id:
            raise ValueError(f"Ce nom désigne déjà {existing.name}.")
        edit = self._character_edit(slug, character.id)
        aliases = edit.setdefault("aliases", [])
        if normalize(clean_alias) not in {normalize(value) for value in aliases}:
            aliases.append(clean_alias)
        self._save()
        return self.resolve(slug, clean_alias)  # type: ignore[return-value]

    def _character_edit(self, slug: str, character_id: int) -> dict:
        custom = self._edits.get("custom_anime", {}).get(slug)
        if custom:
            for raw in custom.get("characters", []):
                if int(raw["id"]) == character_id:
                    return raw
        changes = self._anime_changes(slug)
        for raw in changes.setdefault("added_characters", []):
            if int(raw["id"]) == character_id:
                return raw
        return changes.setdefault("character_edits", {}).setdefault(str(character_id), {})

    def _anime_changes(self, slug: str) -> dict:
        return self._edits.setdefault("anime_edits", {}).setdefault(slug, {})

    def _require_anime(self, slug: str) -> None:
        if slug not in self._anime:
            raise ValueError("Anime introuvable.")

    def _require_character(self, slug: str, answer: str) -> Character:
        self._require_anime(slug)
        character = self.resolve(slug, answer)
        if character is None:
            raise ValueError("Personnage introuvable ou nom trop ambigu.")
        return character

    @staticmethod
    def _clean_aliases(aliases: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for alias in aliases:
            clean = alias.strip()
            key = normalize(clean)
            if key and key not in seen:
                seen.add(key)
                result.append(clean)
        return result

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
                    self._index_alias(index, alias, character)
                    visible = self._aliases_by_id[slug].setdefault(character.id, [character.name])
                    if normalize(alias) not in {normalize(value) for value in visible}:
                        visible.append(alias)

    @staticmethod
    def _resolve_index(index: dict[str, Character | None], answer: str) -> Character | None:
        query = normalize(answer)
        if query in index:
            return index[query]
        if len(query) < 4:
            return None

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
