import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import main as ai


def make_points(values):
    base = datetime(2026, 3, 20, tzinfo=timezone.utc)
    return [
        ai.TimePoint(ts=base + timedelta(seconds=index), rps=value)
        for index, value in enumerate(values)
    ]


def fixed_config():
    return ai.LimitConfigIn(algorithm="fixed", limit=1000, window=10)


def sliding_config():
    return ai.LimitConfigIn(algorithm="sliding", limit=1000, window=10)


def token_config():
    return ai.LimitConfigIn(algorithm="token", capacity=200, fillRate=100.0)


class RecommenderSelectorTest(unittest.TestCase):
    def setUp(self):
        self._saved = {
            "ALLOW_ALGO_SWITCH": ai.ALLOW_ALGO_SWITCH,
            "MIN_ALGO_SWITCH_INTERVAL_SECONDS": ai.MIN_ALGO_SWITCH_INTERVAL_SECONDS,
            "TOKEN_MIN_HOLD_SECONDS": ai.TOKEN_MIN_HOLD_SECONDS,
            "MIN_CHANGE_INTERVAL_SECONDS": ai.MIN_CHANGE_INTERVAL_SECONDS,
            "ALGORITHM_SCORE_MARGIN": ai.ALGORITHM_SCORE_MARGIN,
            "ALGORITHM_SCORE_MARGIN_OVERLOAD": ai.ALGORITHM_SCORE_MARGIN_OVERLOAD,
            "SELECTOR_STREAK_REQUIRED": ai.SELECTOR_STREAK_REQUIRED,
            "FIXED_ESCAPE_STREAK_REQUIRED": ai.FIXED_ESCAPE_STREAK_REQUIRED,
            "MIN_SWITCH_TRAFFIC_RPS": ai.MIN_SWITCH_TRAFFIC_RPS,
            "MAX_STEP_UP_FACTOR": ai.MAX_STEP_UP_FACTOR,
            "MAX_STEP_DOWN_FACTOR": ai.MAX_STEP_DOWN_FACTOR,
            "DECREASE_FACTOR": ai.DECREASE_FACTOR,
            "TOKEN_OVERLOAD_GAIN": ai.TOKEN_OVERLOAD_GAIN,
            "TOKEN_SMOOTH_CAPACITY_SECONDS": ai.TOKEN_SMOOTH_CAPACITY_SECONDS,
            "TOKEN_DDOS_CAPACITY_SECONDS": ai.TOKEN_DDOS_CAPACITY_SECONDS,
            "TOKEN_TUNER_ENABLED": ai.TOKEN_TUNER_ENABLED,
            "TOKEN_TUNER_PROFILE_STREAK": ai.TOKEN_TUNER_PROFILE_STREAK,
            "TOKEN_TUNER_NOISY_GAIN": ai.TOKEN_TUNER_NOISY_GAIN,
            "TOKEN_TUNER_NOISY_TARGET_RATIO": ai.TOKEN_TUNER_NOISY_TARGET_RATIO,
            "TOKEN_TUNER_NOISY_CAPACITY_SECONDS": ai.TOKEN_TUNER_NOISY_CAPACITY_SECONDS,
            "RECOVERY_HEADROOM": ai.RECOVERY_HEADROOM,
            "TOKEN_EXIT_UTILIZATION_MAX": ai.TOKEN_EXIT_UTILIZATION_MAX,
            "TOKEN_EXTREME_OVERLOAD_REJECT_RATE": ai.TOKEN_EXTREME_OVERLOAD_REJECT_RATE,
            "TOKEN_EXTREME_OVERLOAD_RATIO": ai.TOKEN_EXTREME_OVERLOAD_RATIO,
            "TOKEN_EXTREME_OVERLOAD_PEAK_RATIO": ai.TOKEN_EXTREME_OVERLOAD_PEAK_RATIO,
            "SLIDING_STARVATION_RATIO": ai.SLIDING_STARVATION_RATIO,
            "SLIDING_STARVATION_REJECT_RATE": ai.SLIDING_STARVATION_REJECT_RATE,
            "RECOMMENDABLE_ALGORITHMS": ai.RECOMMENDABLE_ALGORITHMS,
        }
        ai.ALLOW_ALGO_SWITCH = True
        ai.MIN_ALGO_SWITCH_INTERVAL_SECONDS = 0
        ai.TOKEN_MIN_HOLD_SECONDS = 0
        ai.MIN_CHANGE_INTERVAL_SECONDS = 0
        ai.ALGORITHM_SCORE_MARGIN = 0
        ai.ALGORITHM_SCORE_MARGIN_OVERLOAD = 0
        ai.SELECTOR_STREAK_REQUIRED = 1
        ai.FIXED_ESCAPE_STREAK_REQUIRED = 1
        ai.MIN_SWITCH_TRAFFIC_RPS = 0
        ai.MAX_STEP_UP_FACTOR = 1.15
        ai.MAX_STEP_DOWN_FACTOR = 0.85
        ai.DECREASE_FACTOR = 0.7
        ai.TOKEN_OVERLOAD_GAIN = 0.35
        ai.TOKEN_SMOOTH_CAPACITY_SECONDS = 1.5
        ai.TOKEN_DDOS_CAPACITY_SECONDS = 2.0
        ai.TOKEN_TUNER_ENABLED = True
        ai.TOKEN_TUNER_PROFILE_STREAK = 2
        ai.TOKEN_TUNER_NOISY_GAIN = 0.55
        ai.TOKEN_TUNER_NOISY_TARGET_RATIO = 0.9
        ai.TOKEN_TUNER_NOISY_CAPACITY_SECONDS = 1.35
        ai.RECOVERY_HEADROOM = 1.1
        ai.TOKEN_EXIT_UTILIZATION_MAX = 0.95
        ai.TOKEN_EXTREME_OVERLOAD_REJECT_RATE = 0.9
        ai.TOKEN_EXTREME_OVERLOAD_RATIO = 2.0
        ai.TOKEN_EXTREME_OVERLOAD_PEAK_RATIO = 2.5
        ai.SLIDING_STARVATION_RATIO = 4.0
        ai.SLIDING_STARVATION_REJECT_RATE = 0.95
        ai.RECOMMENDABLE_ALGORITHMS = ai.SUPPORTED_ALGORITHMS

    def tearDown(self):
        for name, value in self._saved.items():
            setattr(ai, name, value)

    def test_prefers_fixed_for_steady_low_variance_traffic(self):
        # Arrange
        state = ai.RecommendationState()
        history = make_points([88, 90, 91, 89, 90])
        request = ai.LimitConfigRequest(
            observedRps=90,
            allowedRps=90,
            rejectedRps=0,
            rejectedRate=0.0,
            peakRps1s=92,
            burstRatio=1.02,
            coefficientOfVariation=0.05,
            latencyP95=0.1,
            errors5xx=0,
            currentConfig=sliding_config(),
        )

        # Act
        recommendation = ai.recommend_config(
            request,
            92.0,
            history,
            state,
            datetime(2026, 3, 20, tzinfo=timezone.utc),
        )

        # Assert
        self.assertEqual("fixed", recommendation.algorithm)

    def test_prefers_token_after_repeated_bursty_signal(self):
        # Arrange
        ai.SELECTOR_STREAK_REQUIRED = 2
        ai.FIXED_ESCAPE_STREAK_REQUIRED = 2
        state = ai.RecommendationState()
        history = make_points([70, 72, 68, 180, 220])
        request = ai.LimitConfigRequest(
            observedRps=95,
            allowedRps=90,
            rejectedRps=5,
            rejectedRate=0.05,
            peakRps1s=220,
            burstRatio=2.32,
            coefficientOfVariation=0.72,
            latencyP95=0.2,
            errors5xx=0,
            currentConfig=fixed_config(),
        )
        start = datetime(2026, 3, 20, tzinfo=timezone.utc)

        # Act
        first = ai.recommend_config(request, 110.0, history, state, start)
        second = ai.recommend_config(request, 112.0, history, state, start + timedelta(seconds=5))

        # Assert
        self.assertEqual("fixed", first.algorithm)
        self.assertEqual("token", second.algorithm)

    def test_escapes_fixed_after_two_overload_windows_with_lower_overload_margin(self):
        # Arrange
        ai.ALGORITHM_SCORE_MARGIN = 12
        ai.ALGORITHM_SCORE_MARGIN_OVERLOAD = 5
        ai.SELECTOR_STREAK_REQUIRED = 3
        ai.FIXED_ESCAPE_STREAK_REQUIRED = 2
        state = ai.RecommendationState()
        history = make_points([180, 180, 179, 180, 180])
        request = ai.LimitConfigRequest(
            observedRps=180,
            allowedRps=126,
            rejectedRps=54,
            rejectedRate=0.30,
            peakRps1s=180,
            burstRatio=1.0,
            coefficientOfVariation=0.20,
            latencyP95=0.05,
            errors5xx=0,
            currentConfig=fixed_config(),
        )
        start = datetime(2026, 3, 20, tzinfo=timezone.utc)

        # Act
        first = ai.recommend_config(request, 125.0, history, state, start)
        second = ai.recommend_config(
            request, 126.0, history, state, start + timedelta(seconds=5)
        )

        # Assert
        self.assertEqual("fixed", first.algorithm)
        self.assertEqual("sliding", second.algorithm)

    def test_prefers_sliding_for_noisy_non_bursty_overload(self):
        # Arrange
        state = ai.RecommendationState()
        history = make_points([90, 110, 95, 120, 105])
        request = ai.LimitConfigRequest(
            observedRps=110,
            allowedRps=95,
            rejectedRps=15,
            rejectedRate=0.14,
            peakRps1s=128,
            burstRatio=1.16,
            coefficientOfVariation=0.32,
            latencyP95=0.7,
            errors5xx=0,
            currentConfig=token_config(),
        )

        # Act
        recommendation = ai.recommend_config(
            request,
            118.0,
            history,
            state,
            datetime(2026, 3, 20, tzinfo=timezone.utc),
        )

        # Assert
        self.assertEqual("sliding", recommendation.algorithm)

    def test_excludes_fixed_from_prod_recommendation_pool(self):
        # Arrange
        ai.RECOMMENDABLE_ALGORITHMS = ("sliding", "token")
        state = ai.RecommendationState()
        history = make_points([88, 90, 91, 89, 90])
        request = ai.LimitConfigRequest(
            observedRps=90,
            allowedRps=90,
            rejectedRps=0,
            rejectedRate=0.0,
            peakRps1s=92,
            burstRatio=1.02,
            coefficientOfVariation=0.05,
            latencyP95=0.1,
            errors5xx=0,
            currentConfig=sliding_config(),
        )

        # Act
        recommendation = ai.recommend_config(
            request,
            92.0,
            history,
            state,
            datetime(2026, 3, 20, tzinfo=timezone.utc),
        )

        # Assert
        self.assertEqual("sliding", recommendation.algorithm)

    def test_fast_switches_to_token_for_true_burst_profile(self):
        # Arrange
        ai.RECOMMENDABLE_ALGORITHMS = ("sliding", "token")
        ai.SELECTOR_STREAK_REQUIRED = 3
        state = ai.RecommendationState()
        history = make_points([20, 22, 18, 240, 242])
        request = ai.LimitConfigRequest(
            observedRps=78,
            allowedRps=78,
            rejectedRps=0,
            rejectedRate=0.0,
            peakRps1s=242,
            burstRatio=3.1,
            coefficientOfVariation=1.05,
            latencyP95=0.06,
            errors5xx=0,
            currentConfig=sliding_config(),
        )

        # Act
        recommendation = ai.recommend_config(
            request,
            52.0,
            history,
            state,
            datetime(2026, 3, 20, tzinfo=timezone.utc),
        )

        # Assert
        self.assertEqual("token", recommendation.algorithm)

    def test_shadow_mode_does_not_start_algo_switch_cooldown(self):
        # Arrange
        ai.RECOMMENDABLE_ALGORITHMS = ("sliding", "token")
        ai.SELECTOR_STREAK_REQUIRED = 3
        ai.MIN_ALGO_SWITCH_INTERVAL_SECONDS = 90
        state = ai.RecommendationState()
        history = make_points([20, 22, 18, 240, 242])
        request = ai.LimitConfigRequest(
            observedRps=78,
            allowedRps=78,
            rejectedRps=0,
            rejectedRate=0.0,
            peakRps1s=242,
            burstRatio=3.1,
            coefficientOfVariation=1.05,
            latencyP95=0.06,
            errors5xx=0,
            applyRecommendations=False,
            currentConfig=sliding_config(),
        )
        start = datetime(2026, 3, 20, tzinfo=timezone.utc)

        # Act
        first = ai.recommend_config(request, 52.0, history, state, start)
        second = ai.recommend_config(
            request, 58.0, history, state, start + timedelta(seconds=5)
        )

        # Assert
        self.assertEqual("token", first.algorithm)
        self.assertEqual("token", second.algorithm)

    def test_shadow_mode_switches_to_token_immediately_for_moderate_overload(self):
        # Arrange
        ai.RECOMMENDABLE_ALGORITHMS = ("sliding", "token")
        ai.SELECTOR_STREAK_REQUIRED = 3
        state = ai.RecommendationState()
        request = ai.LimitConfigRequest(
            observedRps=140,
            allowedRps=100,
            rejectedRps=40,
            rejectedRate=0.29,
            peakRps1s=150,
            burstRatio=1.25,
            coefficientOfVariation=0.43,
            latencyP95=0.05,
            errors5xx=0,
            applyRecommendations=False,
            currentConfig=sliding_config(),
        )
        start = datetime(2026, 3, 20, tzinfo=timezone.utc)

        # Act
        first = ai.recommend_config(request, 86.0, [], state, start)
        second = ai.recommend_config(
            request, 99.0, [], state, start + timedelta(seconds=15)
        )

        # Assert
        self.assertEqual("token", first.algorithm)
        self.assertEqual("token", second.algorithm)

    def test_prefers_token_for_moderate_overload_near_limit(self):
        # Arrange
        ai.RECOMMENDABLE_ALGORITHMS = ("sliding", "token")
        ai.SELECTOR_STREAK_REQUIRED = 3
        state = ai.RecommendationState()
        history = make_points([108, 126, 138, 146, 141])
        request = ai.LimitConfigRequest(
            observedRps=140,
            allowedRps=100,
            rejectedRps=40,
            rejectedRate=0.29,
            peakRps1s=150,
            burstRatio=1.25,
            coefficientOfVariation=0.43,
            latencyP95=0.05,
            errors5xx=0,
            currentConfig=sliding_config(),
        )
        start = datetime(2026, 3, 20, tzinfo=timezone.utc)

        # Act
        first = ai.recommend_config(request, 60.0, history, state, start)
        second = ai.recommend_config(
            request, 86.0, history, state, start + timedelta(seconds=5)
        )

        # Assert
        self.assertEqual("token", first.algorithm)
        self.assertEqual("token", second.algorithm)

    def test_prefers_token_for_flat_sustained_overload(self):
        # Arrange
        ai.RECOMMENDABLE_ALGORITHMS = ("sliding", "token")
        ai.SELECTOR_STREAK_REQUIRED = 3
        state = ai.RecommendationState()
        history = make_points([134, 140, 137, 139, 136])
        request = ai.LimitConfigRequest(
            observedRps=137.368,
            allowedRps=57.237,
            rejectedRps=80.131,
            rejectedRate=0.583,
            peakRps1s=140,
            burstRatio=1.019,
            coefficientOfVariation=0.192,
            latencyP95=0.042,
            errors5xx=0,
            currentConfig=sliding_config(),
        )

        # Act
        recommendation = ai.recommend_config(
            request,
            53.939,
            history,
            state,
            datetime(2026, 3, 20, tzinfo=timezone.utc),
        )

        # Assert
        self.assertEqual("token", recommendation.algorithm)

    def test_prefers_token_for_poisson_onset_before_full_rejects(self):
        # Arrange
        ai.RECOMMENDABLE_ALGORITHMS = ("sliding", "token")
        ai.SELECTOR_STREAK_REQUIRED = 3
        ai.ALGORITHM_SCORE_MARGIN = 12
        ai.ALGORITHM_SCORE_MARGIN_OVERLOAD = 5
        state = ai.RecommendationState()
        history = make_points([132, 136, 140, 138, 135])
        request = ai.LimitConfigRequest(
            observedRps=135.837,
            allowedRps=85.497,
            rejectedRps=50.339,
            rejectedRate=0.371,
            peakRps1s=140,
            burstRatio=1.031,
            coefficientOfVariation=0.271,
            latencyP95=0.044,
            errors5xx=0,
            currentConfig=sliding_config(),
        )

        # Act
        recommendation = ai.recommend_config(
            request,
            50.764,
            history,
            state,
            datetime(2026, 3, 20, tzinfo=timezone.utc),
        )

        # Assert
        self.assertEqual("token", recommendation.algorithm)
        self.assertEqual(100.0, recommendation.fillRate)
        self.assertEqual(200, recommendation.capacity)

    def test_resolves_ddos_token_profile_immediately(self):
        # Arrange
        state = ai.RecommendationState(token_profile="default")
        features = {
            "rejected_rate": 0.21,
            "observed_rps": 220.0,
            "allowed_rps": 180.0,
            "rejected_rps": 40.0,
            "peak_rps_1s": 340.0,
            "burst_ratio": 1.55,
            "coefficient_of_variation": 0.33,
            "peak_to_limit_ratio": 1.7,
            "observed_to_limit_ratio": 1.3,
            "load_ratio": 1.35,
            "latency_p95": 0.04,
            "errors_5xx": 0.0,
        }

        # Act
        profile = ai.resolve_token_profile(state, "token", "token", features)

        # Assert
        self.assertEqual("ddos", profile)
        self.assertEqual("ddos", state.token_profile)

    def test_requires_streak_to_downgrade_token_profile(self):
        # Arrange
        state = ai.RecommendationState(token_profile="ddos")
        features = {
            "rejected_rate": 0.22,
            "observed_rps": 136.0,
            "allowed_rps": 86.0,
            "rejected_rps": 50.0,
            "peak_rps_1s": 140.0,
            "burst_ratio": 1.03,
            "coefficient_of_variation": 0.27,
            "peak_to_limit_ratio": 1.21,
            "observed_to_limit_ratio": 1.16,
            "load_ratio": 1.22,
            "latency_p95": 0.04,
            "errors_5xx": 0.0,
        }

        # Act
        first = ai.resolve_token_profile(state, "token", "token", features)
        second = ai.resolve_token_profile(state, "token", "token", features)
        third = ai.resolve_token_profile(state, "token", "token", features)
        fourth = ai.resolve_token_profile(state, "token", "token", features)

        # Assert
        self.assertEqual("ddos", first)
        self.assertEqual("ddos", second)
        self.assertEqual("ddos", third)
        self.assertEqual("noisy", fourth)
        self.assertEqual("noisy", state.token_profile)

    def test_tunes_token_fill_rate_and_capacity_for_noisy_overload(self):
        # Arrange
        ai.RECOMMENDABLE_ALGORITHMS = ("sliding", "token")
        state = ai.RecommendationState()
        history = make_points([132, 136, 140, 138, 135])
        request = ai.LimitConfigRequest(
            observedRps=135.837,
            allowedRps=85.497,
            rejectedRps=50.339,
            rejectedRate=0.371,
            peakRps1s=140,
            burstRatio=1.031,
            coefficientOfVariation=0.271,
            latencyP95=0.044,
            errors5xx=0,
            currentConfig=ai.LimitConfigIn(
                algorithm="token",
                capacity=200,
                fillRate=100.0,
            ),
        )

        # Act
        recommendation = ai.recommend_config(
            request,
            50.764,
            history,
            state,
            datetime(2026, 3, 20, tzinfo=timezone.utc),
        )

        # Assert
        self.assertEqual("token", recommendation.algorithm)
        self.assertAlmostEqual(122.253, recommendation.fillRate, places=3)
        self.assertEqual(166, recommendation.capacity)

    def test_keeps_token_during_active_overload_even_if_sliding_scores_higher(self):
        # Arrange
        ai.RECOMMENDABLE_ALGORITHMS = ("sliding", "token")
        ai.ALGORITHM_SCORE_MARGIN = 12
        ai.ALGORITHM_SCORE_MARGIN_OVERLOAD = 5
        state = ai.RecommendationState(last_algo_switch_at=datetime(2026, 3, 20, tzinfo=timezone.utc))
        history = make_points([210, 236, 239, 205, 210])
        request = ai.LimitConfigRequest(
            observedRps=210.474,
            allowedRps=168.280,
            rejectedRps=42.194,
            rejectedRate=0.200,
            peakRps1s=320,
            burstRatio=1.520,
            coefficientOfVariation=0.370,
            latencyP95=0.035,
            errors5xx=0,
            currentConfig=ai.LimitConfigIn(
                algorithm="token",
                capacity=331,
                fillRate=165.306,
            ),
        )

        # Act
        recommendation = ai.recommend_config(
            request,
            214.748,
            history,
            state,
            datetime(2026, 3, 20, tzinfo=timezone.utc) + timedelta(seconds=70),
        )

        # Assert
        self.assertEqual("token", recommendation.algorithm)
        self.assertEqual(183.048, recommendation.fillRate)
        self.assertEqual(367, recommendation.capacity)

    def test_holds_token_in_recovery_until_sliding_has_headroom(self):
        # Arrange
        ai.RECOMMENDABLE_ALGORITHMS = ("sliding", "token")
        state = ai.RecommendationState(
            last_algo_switch_at=datetime(2026, 3, 20, tzinfo=timezone.utc),
            recovery_streak=5,
            token_non_burst_streak=5,
        )
        history = make_points([40, 40, 40, 40, 40])
        request = ai.LimitConfigRequest(
            observedRps=40.0,
            allowedRps=40.0,
            rejectedRps=0.0,
            rejectedRate=0.0,
            peakRps1s=40,
            burstRatio=1.0,
            coefficientOfVariation=0.2,
            latencyP95=0.134,
            errors5xx=0,
            currentConfig=ai.LimitConfigIn(
                algorithm="token",
                capacity=80,
                fillRate=39.741,
            ),
        )

        # Act
        recommendation = ai.recommend_config(
            request,
            171.151,
            history,
            state,
            datetime(2026, 3, 20, tzinfo=timezone.utc) + timedelta(seconds=70),
        )

        # Assert
        self.assertEqual("token", recommendation.algorithm)
        self.assertAlmostEqual(44.0, recommendation.fillRate, places=3)
        self.assertEqual(88, recommendation.capacity)

    def test_switches_to_sliding_after_recovery_headroom_is_restored(self):
        # Arrange
        ai.RECOMMENDABLE_ALGORITHMS = ("sliding", "token")
        state = ai.RecommendationState(
            last_algo_switch_at=datetime(2026, 3, 20, tzinfo=timezone.utc),
            recovery_streak=5,
            token_non_burst_streak=5,
        )
        history = make_points([40, 40, 40, 40, 40])
        request = ai.LimitConfigRequest(
            observedRps=40.0,
            allowedRps=40.0,
            rejectedRps=0.0,
            rejectedRate=0.0,
            peakRps1s=40,
            burstRatio=1.0,
            coefficientOfVariation=0.2,
            latencyP95=0.134,
            errors5xx=0,
            currentConfig=ai.LimitConfigIn(
                algorithm="token",
                window=10,
                capacity=89,
                fillRate=44.5,
            ),
        )

        # Act
        recommendation = ai.recommend_config(
            request,
            151.419,
            history,
            state,
            datetime(2026, 3, 20, tzinfo=timezone.utc) + timedelta(seconds=70),
        )

        # Assert
        self.assertEqual("sliding", recommendation.algorithm)
        self.assertEqual(445, recommendation.limit)
        self.assertEqual(10, recommendation.window)

    def test_preserves_rate_floor_when_switching_to_token_on_overload(self):
        # Arrange
        ai.RECOMMENDABLE_ALGORITHMS = ("sliding", "token")
        ai.SELECTOR_STREAK_REQUIRED = 3
        state = ai.RecommendationState()
        history = make_points([134, 140, 137, 139, 136])
        request = ai.LimitConfigRequest(
            observedRps=137.368,
            allowedRps=57.237,
            rejectedRps=80.131,
            rejectedRate=0.583,
            peakRps1s=140,
            burstRatio=1.019,
            coefficientOfVariation=0.192,
            latencyP95=0.042,
            errors5xx=0,
            currentConfig=sliding_config(),
        )

        # Act
        recommendation = ai.recommend_config(
            request,
            53.939,
            history,
            state,
            datetime(2026, 3, 20, tzinfo=timezone.utc),
        )

        # Assert
        self.assertEqual("token", recommendation.algorithm)
        self.assertEqual(100.0, recommendation.fillRate)
        self.assertEqual(200, recommendation.capacity)

    def test_keeps_sliding_recovery_floor_during_forecast_lag(self):
        # Arrange
        ai.RECOMMENDABLE_ALGORITHMS = ("sliding", "token")
        state = ai.RecommendationState()
        history = make_points([40, 40, 40, 40, 40])
        request = ai.LimitConfigRequest(
            observedRps=40.0,
            allowedRps=40.0,
            rejectedRps=0.0,
            rejectedRate=0.0,
            peakRps1s=40,
            burstRatio=1.0,
            coefficientOfVariation=0.2,
            latencyP95=0.134,
            errors5xx=0,
            currentConfig=ai.LimitConfigIn(
                algorithm="sliding",
                limit=360,
                window=10,
            ),
        )

        # Act
        recommendation = ai.recommend_config(
            request,
            151.289,
            history,
            state,
            datetime(2026, 3, 20, tzinfo=timezone.utc),
        )

        # Assert
        self.assertEqual("sliding", recommendation.algorithm)
        self.assertEqual(440, recommendation.limit)
        self.assertEqual(10, recommendation.window)

    def test_keeps_sliding_floor_under_flat_full_reject_starvation(self):
        # Arrange
        ai.ALLOW_ALGO_SWITCH = False
        ai.RECOMMENDABLE_ALGORITHMS = ("sliding", "token")
        state = ai.RecommendationState()
        history = make_points([40, 40, 40, 40, 40])
        request = ai.LimitConfigRequest(
            observedRps=40.145,
            allowedRps=0.0,
            rejectedRps=40.145,
            rejectedRate=1.0,
            peakRps1s=40.0,
            burstRatio=0.996,
            coefficientOfVariation=0.121,
            latencyP95=0.07,
            errors5xx=0,
            currentConfig=ai.LimitConfigIn(
                algorithm="sliding",
                limit=15,
                window=10,
            ),
        )

        # Act
        recommendation = ai.recommend_config(
            request,
            143.624,
            history,
            state,
            datetime(2026, 3, 20, tzinfo=timezone.utc),
        )

        # Assert
        self.assertEqual("sliding", recommendation.algorithm)
        self.assertEqual(442, recommendation.limit)
        self.assertEqual(10, recommendation.window)

    def test_emergency_switches_starved_sliding_back_to_token(self):
        # Arrange
        ai.RECOMMENDABLE_ALGORITHMS = ("sliding", "token")
        state = ai.RecommendationState()
        history = make_points([40, 40, 40, 40, 40])
        request = ai.LimitConfigRequest(
            observedRps=40.145,
            allowedRps=0.0,
            rejectedRps=40.145,
            rejectedRate=1.0,
            peakRps1s=40.0,
            burstRatio=0.996,
            coefficientOfVariation=0.121,
            latencyP95=0.07,
            errors5xx=0,
            currentConfig=ai.LimitConfigIn(
                algorithm="sliding",
                limit=15,
                window=10,
            ),
        )

        # Act
        recommendation = ai.recommend_config(
            request,
            143.624,
            history,
            state,
            datetime(2026, 3, 20, tzinfo=timezone.utc),
        )

        # Assert
        self.assertEqual("token", recommendation.algorithm)
        self.assertAlmostEqual(44.16, recommendation.fillRate, places=2)
        self.assertEqual(89, recommendation.capacity)

    def test_prefers_token_for_extreme_ddos_overload_from_sliding(self):
        # Arrange
        ai.RECOMMENDABLE_ALGORITHMS = ("sliding", "token")
        state = ai.RecommendationState()
        history = make_points([158, 220, 211, 234, 242])
        request = ai.LimitConfigRequest(
            observedRps=219.743,
            allowedRps=0.0,
            rejectedRps=219.743,
            rejectedRate=1.0,
            peakRps1s=320.0,
            burstRatio=1.456,
            coefficientOfVariation=0.469,
            latencyP95=0.127,
            errors5xx=0,
            currentConfig=ai.LimitConfigIn(
                algorithm="sliding",
                limit=893,
                window=10,
            ),
        )

        # Act
        recommendation = ai.recommend_config(
            request,
            94.45,
            history,
            state,
            datetime(2026, 3, 20, tzinfo=timezone.utc),
        )

        # Assert
        self.assertEqual("token", recommendation.algorithm)
        self.assertAlmostEqual(109.871, recommendation.fillRate, places=2)
        self.assertEqual(220, recommendation.capacity)

    def test_keeps_token_for_managed_ddos_pressure_after_rejects_drop(self):
        # Arrange
        ai.RECOMMENDABLE_ALGORITHMS = ("sliding", "token")
        state = ai.RecommendationState(
            last_algo_switch_at=datetime(2026, 3, 20, tzinfo=timezone.utc)
        )
        history = make_points([208, 226, 240, 182, 180])
        request = ai.LimitConfigRequest(
            observedRps=182.113,
            allowedRps=179.329,
            rejectedRps=2.783,
            rejectedRate=0.015,
            peakRps1s=291.0,
            burstRatio=1.598,
            coefficientOfVariation=0.457,
            latencyP95=0.071,
            errors5xx=0,
            currentConfig=ai.LimitConfigIn(
                algorithm="token",
                capacity=347,
                fillRate=173.357,
            ),
        )

        # Act
        recommendation = ai.recommend_config(
            request,
            238.395,
            history,
            state,
            datetime(2026, 3, 20, tzinfo=timezone.utc) + timedelta(seconds=70),
        )

        # Assert
        self.assertEqual("token", recommendation.algorithm)
        self.assertAlmostEqual(199.361, recommendation.fillRate, places=3)
        self.assertEqual(399, recommendation.capacity)

    def test_does_not_exit_token_to_sliding_until_recovery_window_is_stable(self):
        # Arrange
        ai.RECOMMENDABLE_ALGORITHMS = ("sliding", "token")
        state = ai.RecommendationState(
            last_algo_switch_at=datetime(2026, 3, 20, tzinfo=timezone.utc),
            recovery_streak=6,
            token_non_burst_streak=6,
        )
        history = make_points([218, 226, 230, 227, 230])
        request = ai.LimitConfigRequest(
            observedRps=230.399,
            allowedRps=230.399,
            rejectedRps=0.0,
            rejectedRate=0.0,
            peakRps1s=320.0,
            burstRatio=1.389,
            coefficientOfVariation=0.448,
            latencyP95=0.041,
            errors5xx=0,
            currentConfig=ai.LimitConfigIn(
                algorithm="token",
                capacity=452,
                fillRate=225.943,
            ),
        )

        # Act
        recommendation = ai.recommend_config(
            request,
            262.790,
            history,
            state,
            datetime(2026, 3, 20, tzinfo=timezone.utc) + timedelta(seconds=131),
        )

        # Assert
        self.assertEqual("token", recommendation.algorithm)
        self.assertAlmostEqual(225.943, recommendation.fillRate, places=3)
        self.assertEqual(452, recommendation.capacity)

    def test_keeps_token_for_burst_pressure_without_rejects(self):
        # Arrange
        ai.RECOMMENDABLE_ALGORITHMS = ("sliding", "token")
        state = ai.RecommendationState(
            last_algo_switch_at=datetime(2026, 3, 20, tzinfo=timezone.utc)
        )
        history = make_points([194, 210, 224, 222, 220])
        request = ai.LimitConfigRequest(
            observedRps=221.697,
            allowedRps=221.697,
            rejectedRps=0.0,
            rejectedRate=0.0,
            peakRps1s=340.0,
            burstRatio=1.534,
            coefficientOfVariation=0.433,
            latencyP95=0.04,
            errors5xx=0,
            currentConfig=ai.LimitConfigIn(
                algorithm="token",
                capacity=484,
                fillRate=241.604,
            ),
        )

        # Act
        recommendation = ai.recommend_config(
            request,
            236.032,
            history,
            state,
            datetime(2026, 3, 20, tzinfo=timezone.utc) + timedelta(seconds=119),
        )

        # Assert
        self.assertEqual("token", recommendation.algorithm)
        self.assertAlmostEqual(241.604, recommendation.fillRate, places=3)
        self.assertEqual(484, recommendation.capacity)

    def test_prefers_token_from_sliding_for_ddos_pressure_before_extreme_threshold(self):
        # Arrange
        ai.RECOMMENDABLE_ALGORITHMS = ("sliding", "token")
        state = ai.RecommendationState()
        history = make_points([180, 200, 249, 230, 220])
        request = ai.LimitConfigRequest(
            observedRps=249.263,
            allowedRps=30.564,
            rejectedRps=218.699,
            rejectedRate=0.877,
            peakRps1s=320.0,
            burstRatio=1.284,
            coefficientOfVariation=0.265,
            latencyP95=0.071,
            errors5xx=0,
            currentConfig=ai.LimitConfigIn(
                algorithm="sliding",
                limit=1614,
                window=10,
            ),
        )

        # Act
        recommendation = ai.recommend_config(
            request,
            237.507,
            history,
            state,
            datetime(2026, 3, 20, tzinfo=timezone.utc),
        )

        # Assert
        self.assertEqual("token", recommendation.algorithm)
        self.assertAlmostEqual(211.874, recommendation.fillRate, places=3)
        self.assertEqual(424, recommendation.capacity)

    def test_breaks_sliding_cooldown_for_token_ddos_pressure(self):
        # Arrange
        ai.RECOMMENDABLE_ALGORITHMS = ("sliding", "token")
        state = ai.RecommendationState(
            last_algo_switch_at=datetime(2026, 3, 20, tzinfo=timezone.utc)
        )
        history = make_points([240, 252, 263, 247, 205])
        request = ai.LimitConfigRequest(
            observedRps=263.433,
            allowedRps=3.167,
            rejectedRps=260.266,
            rejectedRate=0.988,
            peakRps1s=320.0,
            burstRatio=1.215,
            coefficientOfVariation=0.26,
            latencyP95=0.04,
            errors5xx=0,
            currentConfig=ai.LimitConfigIn(
                algorithm="sliding",
                limit=2055,
                window=10,
            ),
        )

        # Act
        recommendation = ai.recommend_config(
            request,
            240.538,
            history,
            state,
            datetime(2026, 3, 20, tzinfo=timezone.utc) + timedelta(seconds=40),
        )

        # Assert
        self.assertEqual("token", recommendation.algorithm)
        self.assertAlmostEqual(223.918, recommendation.fillRate, places=3)
        self.assertEqual(448, recommendation.capacity)

    def test_keeps_token_under_peak_pressure_even_when_sliding_scores_higher(self):
        # Arrange
        ai.RECOMMENDABLE_ALGORITHMS = ("sliding", "token")
        state = ai.RecommendationState(
            last_algo_switch_at=datetime(2026, 3, 20, tzinfo=timezone.utc)
        )
        history = make_points([118, 120, 121, 119, 120])
        request = ai.LimitConfigRequest(
            observedRps=118.0,
            allowedRps=118.0,
            rejectedRps=0.0,
            rejectedRate=0.0,
            peakRps1s=320.0,
            burstRatio=1.5,
            coefficientOfVariation=0.45,
            latencyP95=0.05,
            errors5xx=0,
            currentConfig=ai.LimitConfigIn(
                algorithm="token",
                capacity=240,
                fillRate=120.0,
            ),
        )

        # Act
        recommendation = ai.recommend_config(
            request,
            145.0,
            history,
            state,
            datetime(2026, 3, 20, tzinfo=timezone.utc) + timedelta(seconds=70),
        )

        # Assert
        self.assertEqual("token", recommendation.algorithm)

    def test_keeps_token_fill_rate_floor_during_bursty_overload(self):
        # Arrange
        ai.RECOMMENDABLE_ALGORITHMS = ("sliding", "token")
        state = ai.RecommendationState()
        history = make_points([65, 82, 240, 79, 78])
        request = ai.LimitConfigRequest(
            observedRps=78.595,
            allowedRps=66.606,
            rejectedRps=11.989,
            rejectedRate=0.153,
            peakRps1s=240,
            burstRatio=3.054,
            coefficientOfVariation=1.217,
            latencyP95=0.075,
            errors5xx=0,
            currentConfig=token_config(),
        )

        # Act
        recommendation = ai.recommend_config(
            request,
            95.451,
            history,
            state,
            datetime(2026, 3, 20, tzinfo=timezone.utc),
        )

        # Assert
        self.assertEqual("token", recommendation.algorithm)
        self.assertEqual(100.0, recommendation.fillRate)
        self.assertEqual(200, recommendation.capacity)

    def test_keeps_current_algorithm_when_switching_disabled(self):
        # Arrange
        ai.ALLOW_ALGO_SWITCH = False
        state = ai.RecommendationState()
        history = make_points([70, 72, 68, 180, 220])
        request = ai.LimitConfigRequest(
            observedRps=95,
            allowedRps=90,
            rejectedRps=5,
            rejectedRate=0.05,
            peakRps1s=220,
            burstRatio=2.32,
            coefficientOfVariation=0.72,
            latencyP95=0.2,
            errors5xx=0,
            currentConfig=fixed_config(),
        )

        # Act
        recommendation = ai.recommend_config(
            request,
            112.0,
            history,
            state,
            datetime(2026, 3, 20, tzinfo=timezone.utc),
        )

        # Assert
        self.assertEqual("fixed", recommendation.algorithm)

    def test_limits_parameter_change_per_cycle(self):
        # Arrange
        ai.ALLOW_ALGO_SWITCH = False
        ai.MAX_STEP_DOWN_FACTOR = 0.9
        ai.DECREASE_FACTOR = 0.5
        state = ai.RecommendationState()
        history = make_points([120, 122, 121, 119, 118])
        request = ai.LimitConfigRequest(
            observedRps=120,
            allowedRps=80,
            rejectedRps=40,
            rejectedRate=0.33,
            peakRps1s=130,
            burstRatio=1.08,
            coefficientOfVariation=0.08,
            latencyP95=0.9,
            errors5xx=0,
            currentConfig=token_config(),
        )

        # Act
        recommendation = ai.recommend_config(
            request,
            120.0,
            history,
            state,
            datetime(2026, 3, 20, tzinfo=timezone.utc),
        )

        # Assert
        self.assertEqual("token", recommendation.algorithm)
        self.assertEqual(100.0, recommendation.fillRate)


if __name__ == "__main__":
    unittest.main()
