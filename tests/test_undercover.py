import random
import tempfile
import unittest
from pathlib import Path

from undercover import UndercoverGame, UndercoverWordStore, WordPair


class UndercoverWordStoreTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[1]
        self.temporary = tempfile.TemporaryDirectory()
        self.store = UndercoverWordStore(
            self.root / "data" / "undercover_words.json",
            Path(self.temporary.name) / "undercover_edits.json",
        )

    def tearDown(self):
        self.temporary.cleanup()

    def test_default_categories_have_many_pairs(self):
        self.assertGreaterEqual(len(self.store.pairs("general")), 60)
        self.assertGreaterEqual(len(self.store.pairs("anime")), 60)

    def test_custom_category_and_pair_can_be_edited(self):
        category = self.store.add_category("Mes mots")
        pair = self.store.add_pair(category, "Rouge", "Bleu")
        edited = self.store.edit_pair(category, pair.id, "Vert", "Jaune")
        self.assertEqual((edited.word_1, edited.word_2), ("Vert", "Jaune"))
        self.store.delete_pair(category, pair.id)
        self.assertEqual(self.store.pairs(category), [])


class UndercoverGameTests(unittest.TestCase):
    def make_game(self, player_count=3):
        game = UndercoverGame(1, "general", 90, 1)
        for user_id in range(1, player_count + 1):
            game.add_player(user_id, f"Joueur {user_id}")
        game.start(WordPair(1, "general", "Chat", "Chien"), random.Random(42))
        return game

    def test_words_are_private_and_one_player_is_undercover(self):
        game = self.make_game()
        self.assertEqual(len(game.undercover_ids), 1)
        self.assertEqual(set(game.assignments.values()), {"Chat", "Chien"})
        self.assertIn(game.reveal(1), {"Chat", "Chien"})
        self.assertIn(1, game.revealed_ids)

    def test_vote_eliminates_undercover_and_civilians_win(self):
        game = self.make_game()
        undercover_id = next(iter(game.undercover_ids))
        civilians = [user_id for user_id in game.alive_ids if user_id != undercover_id]
        game.vote(civilians[0], undercover_id)
        game.vote(civilians[1], undercover_id)
        result = game.vote(undercover_id, civilians[0])
        self.assertTrue(game.finished)
        self.assertEqual(result.eliminated_id, undercover_id)
        self.assertEqual(set(result.winner_ids), set(civilians))


if __name__ == "__main__":
    unittest.main()
