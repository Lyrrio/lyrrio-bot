import tempfile
import unittest
from pathlib import Path

from economy import EconomyStore


class EconomyTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.store = EconomyStore(Path(self.temp_directory.name) / "economy.db")

    def tearDown(self):
        self.temp_directory.cleanup()

    def test_new_wallet_is_empty(self):
        wallet = self.store.get(123)
        self.assertEqual(wallet.balance, 0)
        self.assertEqual(wallet.wins, 0)

    def test_award_win_is_persistent_and_additive(self):
        self.store.award_win(123, 100)
        wallet = self.store.award_win(123, 100)
        self.assertEqual(wallet.balance, 200)
        self.assertEqual(wallet.wins, 2)

        reopened = EconomyStore(Path(self.temp_directory.name) / "economy.db")
        self.assertEqual(reopened.get(123), wallet)

    def test_leaderboard_orders_by_balance_then_wins(self):
        self.store.award_win(1, 200)
        self.store.award_win(2, 100)
        self.store.award_win(2, 100)
        self.assertEqual([wallet.user_id for wallet in self.store.leaderboard()], [2, 1])

    def test_reward_must_be_positive(self):
        with self.assertRaises(ValueError):
            self.store.award_win(123, 0)


if __name__ == "__main__":
    unittest.main()
