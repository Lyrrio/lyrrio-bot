from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


@dataclass(frozen=True)
class Wallet:
    user_id: int
    balance: int
    wins: int


class EconomyStore:
    """Petit portefeuille persistant stocké dans SQLite."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS wallets (
                    user_id INTEGER PRIMARY KEY,
                    balance INTEGER NOT NULL DEFAULT 0 CHECK (balance >= 0),
                    wins INTEGER NOT NULL DEFAULT 0 CHECK (wins >= 0)
                )
                """
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def get(self, user_id: int) -> Wallet:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT user_id, balance, wins FROM wallets WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        if row is None:
            return Wallet(user_id, 0, 0)
        return Wallet(int(row["user_id"]), int(row["balance"]), int(row["wins"]))

    def award_win(self, user_id: int, amount: int) -> Wallet:
        if amount <= 0:
            raise ValueError("La récompense doit être positive.")
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO wallets (user_id, balance, wins)
                VALUES (?, ?, 1)
                ON CONFLICT(user_id) DO UPDATE SET
                    balance = balance + excluded.balance,
                    wins = wins + 1
                """,
                (user_id, amount),
            )
        return self.get(user_id)

    def leaderboard(self, limit: int = 10) -> list[Wallet]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT user_id, balance, wins
                FROM wallets
                ORDER BY balance DESC, wins DESC, user_id ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            Wallet(int(row["user_id"]), int(row["balance"]), int(row["wins"]))
            for row in rows
        ]
