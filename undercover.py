from __future__ import annotations

import json
import random
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from catalog import make_slug, normalize


@dataclass(frozen=True)
class WordPair:
    id: int
    category: str
    word_1: str
    word_2: str
    custom: bool = False


class UndercoverWordStore:
    def __init__(self, base_path: Path, edits_path: Path):
        self.base_path = base_path
        self.edits_path = edits_path
        self._base = json.loads(base_path.read_text(encoding="utf-8"))
        self._edits = self._empty_edits()
        if edits_path.exists():
            self._edits = {**self._empty_edits(), **json.loads(edits_path.read_text(encoding="utf-8"))}
        self._categories: dict[str, dict] = {}
        self._pairs: dict[str, list[WordPair]] = {}
        self._rebuild()

    @staticmethod
    def _empty_edits() -> dict:
        return {
            "next_pair_id": -1,
            "custom_categories": {},
            "category_edits": {},
            "deleted_categories": [],
            "added_pairs": [],
            "pair_edits": {},
            "deleted_pair_ids": [],
        }

    def _rebuild(self) -> None:
        hidden = set(self._edits.get("deleted_categories", []))
        categories: dict[str, dict] = {}
        for slug, raw in self._base["categories"].items():
            if slug not in hidden:
                categories[slug] = {"label": raw["label"], "custom": False}
        for slug, raw in self._edits.get("custom_categories", {}).items():
            if slug not in hidden:
                categories[slug] = {"label": raw["label"], "custom": True}
        for slug, changes in self._edits.get("category_edits", {}).items():
            if slug in categories and changes.get("label"):
                categories[slug]["label"] = changes["label"]

        deleted_ids = {int(value) for value in self._edits.get("deleted_pair_ids", [])}
        pair_edits = self._edits.get("pair_edits", {})
        pairs: dict[str, list[WordPair]] = {slug: [] for slug in categories}
        for slug, raw_category in self._base["categories"].items():
            if slug not in categories:
                continue
            for raw in raw_category.get("pairs", []):
                pair_id = int(raw["id"])
                if pair_id in deleted_ids:
                    continue
                edit = pair_edits.get(str(pair_id), {})
                pairs[slug].append(
                    WordPair(
                        pair_id,
                        slug,
                        edit.get("word_1", raw["word_1"]),
                        edit.get("word_2", raw["word_2"]),
                        False,
                    )
                )
        for raw in self._edits.get("added_pairs", []):
            slug = raw["category"]
            if slug in pairs:
                edit = pair_edits.get(str(raw["id"]), {})
                pairs[slug].append(
                    WordPair(
                        int(raw["id"]),
                        slug,
                        edit.get("word_1", raw["word_1"]),
                        edit.get("word_2", raw["word_2"]),
                        True,
                    )
                )
        self._categories = categories
        self._pairs = pairs

    def _save(self) -> None:
        self.edits_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.edits_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(self._edits, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.edits_path)
        self._rebuild()

    def choices(self) -> list[tuple[str, str]]:
        return sorted(
            ((slug, raw["label"]) for slug, raw in self._categories.items()),
            key=lambda item: item[1].casefold(),
        )

    def exists(self, category: str) -> bool:
        return category in self._categories

    def label(self, category: str) -> str:
        return self._categories[category]["label"]

    def is_custom(self, category: str) -> bool:
        return bool(self._categories[category]["custom"])

    def pairs(self, category: str) -> list[WordPair]:
        self._require_category(category)
        return list(self._pairs[category])

    def find_pairs(self, category: str, search: str = "") -> list[WordPair]:
        query = normalize(search)
        if not query:
            return self.pairs(category)
        return [
            pair
            for pair in self.pairs(category)
            if query in normalize(pair.word_1) or query in normalize(pair.word_2)
        ]

    def random_pair(self, category: str, rng: random.Random | None = None) -> WordPair:
        pairs = self.pairs(category)
        if not pairs:
            raise ValueError("Cette catégorie ne contient aucune paire.")
        return (rng or random).choice(pairs)

    def add_category(self, label: str, slug: str | None = None) -> str:
        chosen = make_slug(slug or label)
        if not chosen:
            raise ValueError("Identifiant de catégorie invalide.")
        if chosen in self._categories:
            raise ValueError("Cette catégorie existe déjà.")
        self._edits.setdefault("custom_categories", {})[chosen] = {"label": label.strip()}
        hidden = self._edits.setdefault("deleted_categories", [])
        if chosen in hidden:
            hidden.remove(chosen)
        self._save()
        return chosen

    def rename_category(self, category: str, label: str) -> None:
        self._require_category(category)
        self._edits.setdefault("category_edits", {}).setdefault(category, {})["label"] = label.strip()
        self._save()

    def delete_category(self, category: str) -> None:
        self._require_category(category)
        if category in self._edits.get("custom_categories", {}):
            del self._edits["custom_categories"][category]
            self._edits["added_pairs"] = [
                raw for raw in self._edits.get("added_pairs", []) if raw["category"] != category
            ]
            self._edits.get("category_edits", {}).pop(category, None)
        else:
            hidden = self._edits.setdefault("deleted_categories", [])
            if category not in hidden:
                hidden.append(category)
        self._save()

    def add_pair(self, category: str, word_1: str, word_2: str) -> WordPair:
        self._require_category(category)
        first, second = word_1.strip(), word_2.strip()
        if not normalize(first) or not normalize(second):
            raise ValueError("Les deux mots sont obligatoires.")
        if normalize(first) == normalize(second):
            raise ValueError("Les deux mots doivent être différents.")
        if any(
            {normalize(pair.word_1), normalize(pair.word_2)} == {normalize(first), normalize(second)}
            for pair in self._pairs[category]
        ):
            raise ValueError("Cette paire existe déjà.")
        pair_id = int(self._edits.get("next_pair_id", -1))
        self._edits["next_pair_id"] = pair_id - 1
        self._edits.setdefault("added_pairs", []).append(
            {"id": pair_id, "category": category, "word_1": first, "word_2": second}
        )
        self._save()
        return next(pair for pair in self._pairs[category] if pair.id == pair_id)

    def edit_pair(self, category: str, pair_id: int, word_1: str, word_2: str) -> WordPair:
        pair = self._require_pair(category, pair_id)
        first, second = word_1.strip(), word_2.strip()
        if not normalize(first) or not normalize(second) or normalize(first) == normalize(second):
            raise ValueError("Entre deux mots différents et non vides.")
        self._edits.setdefault("pair_edits", {})[str(pair.id)] = {
            "word_1": first,
            "word_2": second,
        }
        self._save()
        return self._require_pair(category, pair_id)

    def delete_pair(self, category: str, pair_id: int) -> WordPair:
        pair = self._require_pair(category, pair_id)
        added = self._edits.setdefault("added_pairs", [])
        if any(int(raw["id"]) == pair.id for raw in added):
            self._edits["added_pairs"] = [raw for raw in added if int(raw["id"]) != pair.id]
        else:
            deleted = self._edits.setdefault("deleted_pair_ids", [])
            if pair.id not in deleted:
                deleted.append(pair.id)
        self._edits.get("pair_edits", {}).pop(str(pair.id), None)
        self._save()
        return pair

    def _require_category(self, category: str) -> None:
        if category not in self._categories:
            raise ValueError("Catégorie Undercover introuvable.")

    def _require_pair(self, category: str, pair_id: int) -> WordPair:
        self._require_category(category)
        pair = next((item for item in self._pairs[category] if item.id == int(pair_id)), None)
        if pair is None:
            raise ValueError("Paire introuvable dans cette catégorie.")
        return pair


@dataclass(frozen=True)
class UndercoverPlayer:
    user_id: int
    name: str


@dataclass(frozen=True)
class VoteResult:
    complete: bool = False
    eliminated_id: int | None = None
    tie: bool = False
    winner_ids: tuple[int, ...] = ()
    undercover_won: bool = False


class UndercoverGame:
    def __init__(
        self,
        host_id: int,
        category: str,
        discussion_seconds: int = 90,
        undercover_count: int = 1,
    ):
        self.host_id = host_id
        self.category = category
        self.discussion_seconds = discussion_seconds
        self.undercover_count = undercover_count
        self.players: list[UndercoverPlayer] = []
        self.alive_ids: set[int] = set()
        self.undercover_ids: set[int] = set()
        self.assignments: dict[int, str] = {}
        self.revealed_ids: set[int] = set()
        self.votes: dict[int, int] = {}
        self.pair: WordPair | None = None
        self.started = False
        self.finished = False
        self.round_number = 0

    def add_player(self, user_id: int, name: str) -> bool:
        if self.started or any(player.user_id == user_id for player in self.players):
            return False
        self.players.append(UndercoverPlayer(user_id, name))
        return True

    def remove_player(self, user_id: int) -> bool:
        if self.started:
            return False
        before = len(self.players)
        self.players = [player for player in self.players if player.user_id != user_id]
        return len(self.players) != before

    def start(self, pair: WordPair, rng: random.Random | None = None) -> None:
        if len(self.players) < 3:
            raise ValueError("Il faut au moins trois joueurs.")
        if self.undercover_count < 1 or self.undercover_count > len(self.players) - 2:
            raise ValueError("Le nombre d'imposteurs doit laisser au moins deux civils.")
        generator = rng or random
        self.pair = pair
        self.alive_ids = {player.user_id for player in self.players}
        self.undercover_ids = set(
            generator.sample(list(self.alive_ids), self.undercover_count)
        )
        reverse_words = bool(generator.getrandbits(1))
        civilian_word = pair.word_2 if reverse_words else pair.word_1
        undercover_word = pair.word_1 if reverse_words else pair.word_2
        self.assignments = {
            player.user_id: (
                undercover_word if player.user_id in self.undercover_ids else civilian_word
            )
            for player in self.players
        }
        self.started = True
        self.round_number = 1

    def reveal(self, user_id: int) -> str:
        if not self.started or self.finished or user_id not in self.assignments:
            raise ValueError("Tu ne participes pas à cette partie active.")
        self.revealed_ids.add(user_id)
        return self.assignments[user_id]

    def vote(self, voter_id: int, target_id: int) -> VoteResult:
        if not self.started or self.finished:
            raise ValueError("Aucun vote Undercover n'est actif.")
        if voter_id not in self.alive_ids:
            raise ValueError("Tu n'es plus en jeu.")
        if target_id not in self.alive_ids:
            raise ValueError("Cette cible n'est plus en jeu.")
        if voter_id == target_id:
            raise ValueError("Tu ne peux pas voter contre toi-même.")
        self.votes[voter_id] = target_id
        if set(self.votes) != self.alive_ids:
            return VoteResult()

        counts = Counter(self.votes.values())
        best = max(counts.values())
        leaders = [user_id for user_id, count in counts.items() if count == best]
        self.votes.clear()
        if len(leaders) != 1:
            self.round_number += 1
            return VoteResult(complete=True, tie=True)

        eliminated_id = leaders[0]
        self.alive_ids.remove(eliminated_id)
        alive_undercover = self.alive_ids & self.undercover_ids
        alive_civilians = self.alive_ids - self.undercover_ids
        if not alive_undercover:
            self.finished = True
            winners = tuple(
                sorted(player.user_id for player in self.players if player.user_id not in self.undercover_ids)
            )
            return VoteResult(True, eliminated_id, False, winners, False)
        if len(alive_undercover) >= len(alive_civilians):
            self.finished = True
            return VoteResult(
                True, eliminated_id, False, tuple(sorted(self.undercover_ids)), True
            )
        self.round_number += 1
        return VoteResult(complete=True, eliminated_id=eliminated_id)
