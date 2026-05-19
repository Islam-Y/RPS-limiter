import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import offline_replay as replay


class OfflineReplayTest(unittest.TestCase):
    def test_sliding_window_stays_starved_after_burst(self):
        # Arrange
        limiter = replay.SlidingWindowLimiter(replay.initial_config("sliding"))

        # Act
        first = limiter.allow(600.0)
        second = limiter.allow(600.0)

        # Assert
        self.assertEqual(600.0, first)
        self.assertEqual(400.0, second)

    def test_token_bucket_uses_capacity_for_burst(self):
        # Arrange
        limiter = replay.TokenBucketLimiter(replay.initial_config("token"))

        # Act
        first = limiter.allow(180.0)
        second = limiter.allow(180.0)

        # Assert
        self.assertEqual(180.0, first)
        self.assertEqual(120.0, second)

    def test_adaptive_universal_mix_uses_both_algorithms(self):
        # Arrange
        scenario = replay.make_scenarios(20260420)[-1]
        candidate = replay.Candidate(
            name="adaptive_baseline",
            mode="adaptive",
            adaptive=True,
            start_algorithm="sliding",
            overrides={"TOKEN_TUNER_ENABLED": False},
        )

        # Act
        result = replay.run_adaptive_scenario(
            scenario,
            candidate,
            backend_capacity_rps=100.0,
        )

        # Assert
        self.assertGreater(result.sliding_seconds, 0)
        self.assertGreater(result.token_seconds, 0)

    def test_search_summary_is_sorted_by_score(self):
        # Arrange
        scenarios = replay.make_scenarios(20260420)[:2]
        candidates = replay.build_default_candidates(search=False)

        # Act
        summary_rows, raw_rows = replay.evaluate_candidates(
            candidates,
            scenarios,
            backend_capacity_rps=100.0,
        )

        # Assert
        self.assertGreater(len(raw_rows), 0)
        self.assertGreaterEqual(
            float(summary_rows[0]["weighted_score"]),
            float(summary_rows[-1]["weighted_score"]),
        )


if __name__ == "__main__":
    unittest.main()
