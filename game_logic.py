from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto


class AnswerKind(Enum):
    VALID = auto()
    DUPLICATE = auto()
    UNKNOWN = auto()
    TIMEOUT = auto()


@dataclass
class Player:
    user_id: int
    name: str
    lives: int


@dataclass(frozen=True)
class TurnResult:
    kind: AnswerKind
    player_id: int
    character_name: str | None = None
    lives_left: int | None = None
    eliminated: bool = False
    winner_id: int | None = None


class RoundGame:
    def __init__(self, host_id: int, anime: str, lives: int, seconds: int):
        self.host_id = host_id
        self.anime = anime
        self.starting_lives = lives
        self.seconds = seconds
        self.players: list[Player] = []
        self.used_character_ids: set[int] = set()
        self.turn_index = 0
        self.started = False
        self.finished = False

    @property
    def current(self) -> Player:
        return self.players[self.turn_index]

    def add_player(self, user_id: int, name: str) -> bool:
        if self.started or any(player.user_id == user_id for player in self.players):
            return False
        self.players.append(Player(user_id, name, self.starting_lives))
        return True

    def remove_player(self, user_id: int) -> bool:
        if self.started:
            return False
        before = len(self.players)
        self.players = [player for player in self.players if player.user_id != user_id]
        return len(self.players) != before

    def start(self) -> None:
        if len(self.players) < 2:
            raise ValueError("Il faut au moins deux joueurs.")
        self.started = True

    def accept(self, character_id: int | None, character_name: str | None) -> TurnResult:
        if character_id is None:
            return self._penalty(AnswerKind.UNKNOWN)
        if character_id in self.used_character_ids:
            return self._penalty(AnswerKind.DUPLICATE, character_name)
        player_id = self.current.user_id
        self.used_character_ids.add(character_id)
        self._advance()
        return TurnResult(AnswerKind.VALID, player_id, character_name)

    def timeout(self) -> TurnResult:
        return self._penalty(AnswerKind.TIMEOUT)

    def _penalty(self, kind: AnswerKind, character_name: str | None = None) -> TurnResult:
        player = self.current
        player.lives -= 1
        eliminated = player.lives <= 0
        player_id = player.user_id
        lives_left = max(0, player.lives)
        if eliminated:
            self.players.pop(self.turn_index)
            if self.players:
                self.turn_index %= len(self.players)
        else:
            self._advance()
        winner_id = None
        if len(self.players) == 1:
            self.finished = True
            winner_id = self.players[0].user_id
        return TurnResult(kind, player_id, character_name, lives_left, eliminated, winner_id)

    def _advance(self) -> None:
        self.turn_index = (self.turn_index + 1) % len(self.players)
