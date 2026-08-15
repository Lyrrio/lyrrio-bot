import unittest

from game_logic import AnswerKind, RoundGame


class RoundGameTests(unittest.TestCase):
    def make_game(self, lives=2):
        game = RoundGame(1, "one-piece", lives, 20)
        game.add_player(1, "Luffy")
        game.add_player(2, "Zoro")
        game.start()
        return game

    def test_valid_answer_advances_turn(self):
        game = self.make_game()
        result = game.accept(100, "Monkey D., Luffy")
        self.assertEqual(result.kind, AnswerKind.VALID)
        self.assertEqual(game.current.user_id, 2)

    def test_duplicate_costs_a_life(self):
        game = self.make_game()
        game.accept(100, "Luffy")
        result = game.accept(100, "Luffy")
        self.assertEqual(result.kind, AnswerKind.DUPLICATE)
        self.assertEqual(result.lives_left, 1)

    def test_timeout_eliminates_and_declares_winner(self):
        game = self.make_game(lives=1)
        result = game.timeout()
        self.assertTrue(result.eliminated)
        self.assertEqual(result.winner_id, 2)
        self.assertTrue(game.finished)

    def test_lobby_refuses_duplicate_player(self):
        game = RoundGame(1, "naruto", 3, 20)
        self.assertTrue(game.add_player(1, "A"))
        self.assertFalse(game.add_player(1, "A"))


if __name__ == "__main__":
    unittest.main()
