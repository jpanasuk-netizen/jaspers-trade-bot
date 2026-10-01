"""Checks the ETH fade against the study's causal streak rule."""

from __future__ import annotations

import unittest

from eth_desk.signal import (
    breakeven_win_rate,
    candle_color,
    fade_signal,
    price_ok,
    shared_budget,
)


class FadeTests(unittest.TestCase):
    def test_silent_under_five(self) -> None:
        self.assertIsNone(fade_signal([1, 1, 1, 1]))

    def test_exact_five_fades_and_uses_the_length_five_fraction(self) -> None:
        got = fade_signal([1, 1, 1, 1, 1])
        assert got is not None
        self.assertEqual(got["side"], "NO")
        self.assertEqual(got["rule"], "streak_fade_5")
        self.assertAlmostEqual(float(got["half_kelly"]), 0.036712393450017075)

    def test_six_is_one_bet_at_the_stricter_fraction(self) -> None:
        got = fade_signal([-1, -1, -1, -1, -1, -1, -1])
        assert got is not None
        self.assertEqual(got["side"], "YES")
        self.assertEqual(got["rule"], "streak_fade_6")
        self.assertAlmostEqual(float(got["half_kelly"]), 0.03171117506240596)

    def test_push_resets(self) -> None:
        self.assertIsNone(fade_signal([1, 1, 1, 1, 1, 0, -1]))

    def test_color(self) -> None:
        self.assertEqual(candle_color(1.0, 2.0), 1)
        self.assertEqual(candle_color(2.0, 1.0), -1)
        self.assertEqual(candle_color(1.0, 1.0), 0)

    def test_price_gate(self) -> None:
        self.assertAlmostEqual(breakeven_win_rate(0.50, 1.0, 0.02), 0.52)
        self.assertTrue(price_ok(0.50, 1.0, 0.02))
        self.assertFalse(price_ok(0.56, 1.0, 0.02))

    def test_shared_budget_leaves_the_other_clip(self) -> None:
        self.assertAlmostEqual(shared_budget(10.0, 0.036712393450017075, 2.0), 0.3671)
        self.assertEqual(shared_budget(2.0, 0.036712393450017075, 2.0), 0.0)
        self.assertEqual(shared_budget(2.5, 0.50, 2.0), 0.5)


if __name__ == "__main__":
    unittest.main()
