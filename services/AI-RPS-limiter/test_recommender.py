import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import main as ai


def make_points(values):
    base = datetime(2026, 3, 20, tzinfo=timezone.utc)
    return [
        ai.TimePoint(ts=base + timedelta(seconds=index), rps=value)
        for index, value in enumerate(values)
    ]


def token_config():
    return ai.LimitConfigIn(algorithm="token", capacity=200, fillRate=100.0)


def sliding_config():
    return ai.LimitConfigIn(algorithm="sliding", limit=900, window=10)


class RecommenderStateMachineTest(unittest.TestCase):
    def setUp(self):
        self._saved = {
            "ALLOW_ALGO_SWITCH": ai.ALLOW_ALGO_SWITCH,
            "MIN_ALGO_SWITCH_INTERVAL_SECONDS": ai.MIN_ALGO_SWITCH_INTERVAL_SECONDS,
            "ATTACK_STREAK_REQUIRED": ai.ATTACK_STREAK_REQUIRED,
            "RECOVERY_STREAK_REQUIRED": ai.RECOVERY_STREAK_REQUIRED,
            "TOKEN_MIN_HOLD_SECONDS": ai.TOKEN_MIN_HOLD_SECONDS,
            "TOKEN_EXIT_NON_BURST_STREAK": ai.TOKEN_EXIT_NON_BURST_STREAK,
            "BURSTINESS_POINTS": ai.BURSTINESS_POINTS,
            "BURSTINESS_THRESHOLD": ai.BURSTINESS_THRESHOLD,
            "DDOS_MULTIPLIER": ai.DDOS_MULTIPLIER,
            "MIN_CHANGE_INTERVAL_SECONDS": ai.MIN_CHANGE_INTERVAL_SECONDS,
        }
        ai.ALLOW_ALGO_SWITCH = True
        ai.MIN_ALGO_SWITCH_INTERVAL_SECONDS = 0
        ai.ATTACK_STREAK_REQUIRED = 2
        ai.RECOVERY_STREAK_REQUIRED = 3
        ai.MIN_CHANGE_INTERVAL_SECONDS = 0
        ai.TOKEN_MIN_HOLD_SECONDS = 0
        ai.TOKEN_EXIT_NON_BURST_STREAK = 3
        ai.BURSTINESS_POINTS = 5
        ai.BURSTINESS_THRESHOLD = 1.3
        ai.DDOS_MULTIPLIER = 2.0

    def tearDown(self):
        for name, value in self._saved.items():
            setattr(ai, name, value)

    def test_switches_from_token_to_sliding_after_two_attack_ticks(self):
        state = ai.RecommendationState()
        now = datetime(2026, 3, 20, tzinfo=timezone.utc)
        history = make_points([100, 102, 101, 103, 100])

        request = ai.LimitConfigRequest(
            observedRps=150,
            rejectedRate=0.2,
            latencyP95=0.4,
            errors5xx=0,
            currentConfig=token_config(),
        )

        first = ai.recommend_config(request, 150.0, history, state, now)
        second = ai.recommend_config(request, 150.0, history, state, now + timedelta(seconds=5))

        self.assertEqual("token", first.algorithm)
        self.assertEqual("sliding", second.algorithm)

    def test_switches_from_token_to_sliding_after_one_attack_tick_when_relaxed(self):
        ai.ATTACK_STREAK_REQUIRED = 1
        state = ai.RecommendationState()
        now = datetime(2026, 3, 20, tzinfo=timezone.utc)
        history = make_points([100, 102, 101, 103, 100])

        request = ai.LimitConfigRequest(
            observedRps=150,
            rejectedRate=0.2,
            latencyP95=0.4,
            errors5xx=0,
            currentConfig=token_config(),
        )

        first = ai.recommend_config(request, 150.0, history, state, now)

        self.assertEqual("sliding", first.algorithm)

    def test_returns_from_sliding_to_token_after_configured_recovery_ticks(self):
        state = ai.RecommendationState(last_algo_switch_at=datetime(2026, 3, 20, tzinfo=timezone.utc))
        history = make_points([40, 41, 40, 39, 40])
        request = ai.LimitConfigRequest(
            observedRps=40,
            rejectedRate=0.0,
            latencyP95=0.1,
            errors5xx=0,
            currentConfig=sliding_config(),
        )

        now = datetime(2026, 3, 20, 0, 0, 20, tzinfo=timezone.utc)
        first = ai.recommend_config(request, 40.0, history, state, now)
        second = ai.recommend_config(request, 40.0, history, state, now + timedelta(seconds=5))
        third = ai.recommend_config(request, 40.0, history, state, now + timedelta(seconds=10))

        self.assertEqual("sliding", first.algorithm)
        self.assertEqual("sliding", second.algorithm)
        self.assertEqual("token", third.algorithm)

    def test_returns_from_sliding_to_token_after_two_recovery_ticks_when_relaxed(self):
        ai.RECOVERY_STREAK_REQUIRED = 2
        ai.TOKEN_EXIT_NON_BURST_STREAK = 2
        state = ai.RecommendationState(last_algo_switch_at=datetime(2026, 3, 20, tzinfo=timezone.utc))
        history = make_points([40, 41, 40, 39, 40])
        request = ai.LimitConfigRequest(
            observedRps=40,
            rejectedRate=0.0,
            latencyP95=0.1,
            errors5xx=0,
            currentConfig=sliding_config(),
        )

        now = datetime(2026, 3, 20, 0, 0, 20, tzinfo=timezone.utc)
        first = ai.recommend_config(request, 40.0, history, state, now)
        second = ai.recommend_config(request, 40.0, history, state, now + timedelta(seconds=5))

        self.assertEqual("sliding", first.algorithm)
        self.assertEqual("token", second.algorithm)

    def test_recovery_uses_observed_signal_not_stale_forecast(self):
        state = ai.RecommendationState(last_algo_switch_at=datetime(2026, 3, 20, tzinfo=timezone.utc))
        history = make_points([40, 41, 40, 39, 40])
        request = ai.LimitConfigRequest(
            observedRps=40,
            rejectedRate=0.0,
            latencyP95=0.1,
            errors5xx=0,
            currentConfig=sliding_config(),
        )

        now = datetime(2026, 3, 20, 0, 0, 20, tzinfo=timezone.utc)
        first = ai.recommend_config(request, 220.0, history, state, now)
        second = ai.recommend_config(request, 180.0, history, state, now + timedelta(seconds=5))
        third = ai.recommend_config(request, 140.0, history, state, now + timedelta(seconds=10))

        self.assertEqual("sliding", first.algorithm)
        self.assertEqual("sliding", second.algorithm)
        self.assertEqual("token", third.algorithm)

    def test_legitimate_burst_without_attack_signals_stays_on_token(self):
        state = ai.RecommendationState()
        history = make_points([40, 40, 42, 40, 120])
        request = ai.LimitConfigRequest(
            observedRps=95,
            rejectedRate=0.0,
            latencyP95=0.1,
            errors5xx=0,
            currentConfig=token_config(),
        )

        first = ai.recommend_config(request, 110.0, history, state, datetime(2026, 3, 20, tzinfo=timezone.utc))
        second = ai.recommend_config(
            request,
            110.0,
            history,
            state,
            datetime(2026, 3, 20, 0, 0, 5, tzinfo=timezone.utc),
        )

        self.assertEqual("token", first.algorithm)
        self.assertEqual("token", second.algorithm)

if __name__ == "__main__":
    unittest.main()
