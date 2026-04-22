from __future__ import annotations

import argparse
import csv
import logging
import math
import random
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from itertools import product
from pathlib import Path
from statistics import mean
from typing import Deque, Dict, Iterable, Iterator, List, Optional, Sequence

import main as ai


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "monitoring" / "benchmarks"
DEFAULT_CONTROL_INTERVAL_SECONDS = 10
DEFAULT_BASE_LIMIT_RPS = 100.0
DEFAULT_WINDOW_SECONDS = 10
DEFAULT_TOKEN_CAPACITY_SECONDS = 2.0
DEFAULT_BACKEND_CAPACITY_RPS = 100.0
DEFAULT_RANDOM_SEED = 20260420

PRODUCTION_BASELINE = {
    "ALLOW_ALGO_SWITCH": True,
    "MIN_ALGO_SWITCH_INTERVAL_SECONDS": 20,
    "ATTACK_STREAK_REQUIRED": 2,
    "RECOVERY_STREAK_REQUIRED": 3,
    "BURSTINESS_POINTS": 5,
    "BURSTINESS_THRESHOLD": 1.3,
    "TOKEN_MIN_HOLD_SECONDS": 20,
    "TOKEN_EXIT_NON_BURST_STREAK": 3,
    "MIN_TOKEN_FILL_RATE": 10.0,
    "DECREASE_FACTOR": 0.9,
    "TOKEN_OVERLOAD_GAIN": 0.0,
    "TOKEN_SMOOTH_CAPACITY_SECONDS": 1.2,
    "TOKEN_DDOS_CAPACITY_SECONDS": 2.0,
    "TOKEN_TUNER_ENABLED": False,
    "TOKEN_TUNER_PROFILE_STREAK": 2,
    "TOKEN_TUNER_NOISY_GAIN": 0.55,
    "TOKEN_TUNER_NOISY_TARGET_RATIO": 0.90,
    "TOKEN_TUNER_NOISY_CAPACITY_SECONDS": 1.35,
    "LATENCY_P95_THRESHOLD": 0.06,
    "MIN_CHANGE_INTERVAL_SECONDS": 20,
    "MAX_STEP_UP_FACTOR": 1.0,
    "MAX_STEP_DOWN_FACTOR": 0.85,
    "ALGORITHM_SCORE_MARGIN": 12.0,
    "ALGORITHM_SCORE_MARGIN_OVERLOAD": 5.0,
    "SELECTOR_STREAK_REQUIRED": 3,
    "FIXED_ESCAPE_STREAK_REQUIRED": 2,
    "MIN_SWITCH_TRAFFIC_RPS": 10.0,
    "RECOMMENDABLE_ALGORITHMS": ("sliding", "token"),
    "FORECAST_SECONDS": 15,
}

SCENARIO_WEIGHTS = {
    "steady": 1.0,
    "poisson": 1.0,
    "burst": 1.0,
    "ddos": 1.0,
    "ddos_recovery": 1.0,
    "universal_mix": 2.0,
}

SUMMARY_COLUMNS = [
    "candidate",
    "mode",
    "weighted_score",
    "weighted_success_percent",
    "weighted_reject_percent",
    "weighted_backend_error_percent",
    "weighted_avg_latency_ms",
    "weighted_p95_latency_ms",
    "weighted_overload_seconds",
    "total_switch_count",
    "total_token_seconds",
    "total_sliding_seconds",
    "total_fixed_seconds",
]

RAW_COLUMNS = [
    "candidate",
    "mode",
    "scenario",
    "duration_seconds",
    "total_demand",
    "total_allowed",
    "total_rejected",
    "total_backend_success",
    "total_backend_errors",
    "success_percent",
    "reject_percent",
    "backend_error_percent",
    "avg_latency_ms",
    "p95_latency_ms",
    "overload_seconds",
    "switch_count",
    "token_seconds",
    "sliding_seconds",
    "fixed_seconds",
    "score",
]


@dataclass(frozen=True)
class ReplayScenario:
    name: str
    demand_rps: tuple[float, ...]

    @property
    def duration_seconds(self) -> int:
        return len(self.demand_rps)


@dataclass(frozen=True)
class Candidate:
    name: str
    mode: str
    adaptive: bool
    start_algorithm: str
    overrides: Dict[str, object]


@dataclass
class ScenarioResult:
    candidate: str
    mode: str
    scenario: str
    duration_seconds: int
    total_demand: float
    total_allowed: float
    total_rejected: float
    total_backend_success: float
    total_backend_errors: float
    success_percent: float
    reject_percent: float
    backend_error_percent: float
    avg_latency_ms: float
    p95_latency_ms: float
    overload_seconds: float
    switch_count: int
    token_seconds: int
    sliding_seconds: int
    fixed_seconds: int
    score: float


class SlidingWindowLimiter:
    def __init__(self, config: ai.LimitConfigIn) -> None:
        self.limit = float(config.limit or 0.0)
        self.window = max(1, int(config.window or 1))
        self.history: Deque[float] = deque()
        self.running_sum = 0.0

    def allow(self, demand: float) -> float:
        remaining = max(0.0, self.limit - self.running_sum)
        allowed = min(demand, remaining)
        self.history.append(allowed)
        self.running_sum += allowed
        while len(self.history) > self.window:
            self.running_sum -= self.history.popleft()
        return allowed

    def update(self, config: ai.LimitConfigIn) -> None:
        self.limit = float(config.limit or 0.0)
        new_window = max(1, int(config.window or 1))
        if new_window != self.window:
            self.window = new_window
            while len(self.history) > self.window:
                self.running_sum -= self.history.popleft()


class FixedWindowLimiter:
    def __init__(self, config: ai.LimitConfigIn) -> None:
        self.limit = float(config.limit or 0.0)
        self.window = max(1, int(config.window or 1))
        self.window_tick = 0
        self.used = 0.0

    def allow(self, demand: float, tick: int) -> float:
        window_tick = tick // self.window
        if window_tick != self.window_tick:
            self.window_tick = window_tick
            self.used = 0.0
        remaining = max(0.0, self.limit - self.used)
        allowed = min(demand, remaining)
        self.used += allowed
        return allowed

    def update(self, config: ai.LimitConfigIn) -> None:
        self.limit = float(config.limit or 0.0)
        new_window = max(1, int(config.window or 1))
        if new_window != self.window:
            self.window = new_window
            self.window_tick = 0
            self.used = 0.0


class TokenBucketLimiter:
    def __init__(self, config: ai.LimitConfigIn) -> None:
        self.capacity = float(config.capacity or 0.0)
        self.fill_rate = float(config.fillRate or 0.0)
        self.tokens = self.capacity

    def allow(self, demand: float) -> float:
        self.tokens = min(self.capacity, self.tokens + self.fill_rate)
        allowed = min(demand, self.tokens)
        self.tokens -= allowed
        return allowed

    def update(self, config: ai.LimitConfigIn) -> None:
        self.capacity = float(config.capacity or 0.0)
        self.fill_rate = float(config.fillRate or 0.0)
        self.tokens = min(self.capacity, self.tokens)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Offline replay/tuning harness for adaptive rate-limit selector."
    )
    parser.add_argument(
        "--search",
        action="store_true",
        help="Run parameter grid-search for adaptive candidates.",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=10,
        help="How many ranked candidates to print (default: 10).",
    )
    parser.add_argument(
        "--output-prefix",
        type=Path,
        default=None,
        help="Write results to <prefix>.summary.csv and <prefix>.raw.csv.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_RANDOM_SEED,
        help="Deterministic seed for synthetic workloads.",
    )
    parser.add_argument(
        "--backend-capacity-rps",
        type=float,
        default=DEFAULT_BACKEND_CAPACITY_RPS,
        help="Simulated downstream safe capacity in RPS (default: 100).",
    )
    return parser.parse_args()


def format_value(value: float) -> str:
    if isinstance(value, int) or float(value).is_integer():
        return str(int(value))
    return f"{value:.3f}"


def write_csv(path: Path, columns: Sequence[str], rows: Sequence[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns))
        writer.writeheader()
        for row in rows:
            formatted = {}
            for key in columns:
                value = row.get(key, "")
                if isinstance(value, float):
                    formatted[key] = format_value(value)
                else:
                    formatted[key] = value
            writer.writerow(formatted)


@contextmanager
def temporary_ai_globals(overrides: Dict[str, object]) -> Iterator[None]:
    saved = {name: getattr(ai, name) for name in overrides}
    try:
        for name, value in overrides.items():
            setattr(ai, name, value)
        yield
    finally:
        for name, value in saved.items():
            setattr(ai, name, value)


def percentile(values: Sequence[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = max(0, min(len(ordered) - 1, math.ceil(quantile * len(ordered)) - 1))
    return ordered[position]


def deterministic_noise(
    rng: random.Random, center: float, spread: float, minimum: float = 0.0
) -> float:
    return max(minimum, rng.gauss(center, spread))


def make_scenarios(seed: int) -> List[ReplayScenario]:
    return [
        ReplayScenario("steady", tuple(build_steady(seed))),
        ReplayScenario("poisson", tuple(build_poisson(seed))),
        ReplayScenario("burst", tuple(build_burst(seed))),
        ReplayScenario("ddos", tuple(build_ddos(seed))),
        ReplayScenario("ddos_recovery", tuple(build_ddos_recovery(seed))),
        ReplayScenario("universal_mix", tuple(build_universal_mix(seed))),
    ]


def build_steady(seed: int) -> List[float]:
    rng = random.Random(seed + 11)
    return [deterministic_noise(rng, 40.0, 2.5, 10.0) for _ in range(60)]


def build_poisson(seed: int) -> List[float]:
    rng = random.Random(seed + 23)
    trace: List[float] = []
    for second in range(60):
        center = 135.0 + 8.0 * math.sin(second / 6.0)
        trace.append(deterministic_noise(rng, center, 18.0, 40.0))
    return trace


def build_burst(seed: int) -> List[float]:
    rng = random.Random(seed + 37)
    trace: List[float] = []
    for second in range(60):
        if second % 8 in (4, 5):
            trace.append(deterministic_noise(rng, 220.0, 15.0, 120.0))
        else:
            trace.append(deterministic_noise(rng, 24.0, 4.0, 5.0))
    return trace


def build_ddos(seed: int) -> List[float]:
    rng = random.Random(seed + 41)
    trace: List[float] = []
    for second in range(60):
        ramp = min(1.0, second / 20.0)
        center = 150.0 + 90.0 * ramp
        if second % 5 == 0:
            center += 60.0
        trace.append(deterministic_noise(rng, center, 22.0, 80.0))
    return trace


def build_ddos_recovery(seed: int) -> List[float]:
    rng = random.Random(seed + 53)
    attack = build_ddos(seed + 3)[:30]
    recovery: List[float] = []
    for second in range(60):
        center = 42.0 + 4.0 * math.sin(second / 7.0)
        recovery.append(deterministic_noise(rng, center, 3.0, 20.0))
    return attack + recovery


def build_universal_mix(seed: int) -> List[float]:
    return (
        build_steady(seed + 5)[:30]
        + build_poisson(seed + 5)[:30]
        + build_burst(seed + 5)[:30]
        + build_ddos(seed + 5)[:30]
        + build_ddos_recovery(seed + 5)[30:60]
    )


def initial_config(algorithm: str) -> ai.LimitConfigIn:
    if algorithm == "sliding":
        return ai.LimitConfigIn(
            algorithm="sliding",
            limit=int(DEFAULT_BASE_LIMIT_RPS * DEFAULT_WINDOW_SECONDS),
            window=DEFAULT_WINDOW_SECONDS,
        )
    if algorithm == "fixed":
        return ai.LimitConfigIn(
            algorithm="fixed",
            limit=int(DEFAULT_BASE_LIMIT_RPS * DEFAULT_WINDOW_SECONDS),
            window=DEFAULT_WINDOW_SECONDS,
        )
    return ai.LimitConfigIn(
        algorithm="token",
        capacity=int(DEFAULT_BASE_LIMIT_RPS * DEFAULT_TOKEN_CAPACITY_SECONDS),
        fillRate=DEFAULT_BASE_LIMIT_RPS,
    )


def build_limiter(config: ai.LimitConfigIn):
    if config.algorithm == "fixed":
        return FixedWindowLimiter(config)
    if config.algorithm == "sliding":
        return SlidingWindowLimiter(config)
    return TokenBucketLimiter(config)


def update_or_replace_limiter(limiter, current: ai.LimitConfigIn, updated: ai.LimitConfigIn):
    if current.algorithm != updated.algorithm or limiter is None:
        return build_limiter(updated)
    limiter.update(updated)
    return limiter


def simulate_backend(
    algorithm: str, allowed_rps: float, backend_capacity_rps: float
) -> tuple[float, float, float]:
    safe_capacity = max(1.0, backend_capacity_rps)
    utilization = allowed_rps / safe_capacity
    overload = max(0.0, utilization - 1.0)
    base_latency = 0.010
    algorithm_bias = {"fixed": 0.000, "sliding": 0.001, "token": 0.002}.get(
        algorithm, 0.0
    )
    error_rate = ai.clamp01(overload / 0.8) * 0.60
    backend_errors = allowed_rps * error_rate
    backend_success = max(0.0, allowed_rps - backend_errors)
    latency_p95 = (
        base_latency
        + algorithm_bias
        + 0.008 * min(1.0, utilization)
        + 0.050 * overload
        + 0.090 * error_rate
    )
    return backend_success, backend_errors, latency_p95


def aggregate_interval(
    observed_window: Sequence[float],
    allowed_window: Sequence[float],
    latency_window: Sequence[float],
    backend_error_window: Sequence[float],
) -> tuple[float, float, float, float, float, float]:
    observed_sum = sum(observed_window)
    allowed_sum = sum(allowed_window)
    rejected_sum = max(0.0, observed_sum - allowed_sum)
    observed_rps = observed_sum / max(1, len(observed_window))
    allowed_rps = allowed_sum / max(1, len(allowed_window))
    rejected_rps = rejected_sum / max(1, len(observed_window))
    rejected_rate = ai.safe_ratio(rejected_sum, observed_sum, 0.0)
    latency_p95 = percentile(latency_window, 0.95)
    errors_5xx = int(round(sum(backend_error_window)))
    return (
        observed_rps,
        allowed_rps,
        rejected_rps,
        rejected_rate,
        latency_p95,
        errors_5xx,
    )


def score_result(result: ScenarioResult) -> float:
    return (
        result.success_percent
        - 0.35 * result.p95_latency_ms
        - 0.15 * result.overload_seconds
        - 0.10 * result.switch_count
    )


def run_static_scenario(
    scenario: ReplayScenario,
    config: ai.LimitConfigIn,
    candidate: Candidate,
    backend_capacity_rps: float,
) -> ScenarioResult:
    limiter = build_limiter(config)
    latencies: List[float] = []
    total_demand = 0.0
    total_allowed = 0.0
    total_backend_success = 0.0
    total_backend_errors = 0.0

    for second, demand in enumerate(scenario.demand_rps):
        if config.algorithm == "fixed":
            allowed = limiter.allow(demand, second)
        else:
            allowed = limiter.allow(demand)
        backend_success, backend_errors, latency_p95 = simulate_backend(
            config.algorithm, allowed, backend_capacity_rps
        )
        total_demand += demand
        total_allowed += allowed
        total_backend_success += backend_success
        total_backend_errors += backend_errors
        latencies.append(latency_p95)

    total_rejected = max(0.0, total_demand - total_allowed)
    result = ScenarioResult(
        candidate=candidate.name,
        mode=candidate.mode,
        scenario=scenario.name,
        duration_seconds=scenario.duration_seconds,
        total_demand=total_demand,
        total_allowed=total_allowed,
        total_rejected=total_rejected,
        total_backend_success=total_backend_success,
        total_backend_errors=total_backend_errors,
        success_percent=ai.safe_ratio(total_backend_success, total_demand, 0.0) * 100.0,
        reject_percent=ai.safe_ratio(total_rejected, total_demand, 0.0) * 100.0,
        backend_error_percent=ai.safe_ratio(total_backend_errors, total_demand, 0.0)
        * 100.0,
        avg_latency_ms=mean(latencies) * 1000.0,
        p95_latency_ms=percentile(latencies, 0.95) * 1000.0,
        overload_seconds=sum(1 for value in latencies if value >= 0.06),
        switch_count=0,
        token_seconds=scenario.duration_seconds if config.algorithm == "token" else 0,
        sliding_seconds=scenario.duration_seconds if config.algorithm == "sliding" else 0,
        fixed_seconds=scenario.duration_seconds if config.algorithm == "fixed" else 0,
        score=0.0,
    )
    result.score = score_result(result)
    return result


def run_adaptive_scenario(
    scenario: ReplayScenario,
    candidate: Candidate,
    backend_capacity_rps: float,
    control_interval_seconds: int = DEFAULT_CONTROL_INTERVAL_SECONDS,
) -> ScenarioResult:
    with temporary_ai_globals({**PRODUCTION_BASELINE, **candidate.overrides}):
        state = ai.RecommendationState()
        current_config = initial_config(candidate.start_algorithm)
        limiter = build_limiter(current_config)
        history_points: List[ai.TimePoint] = []
        observed_window: List[float] = []
        allowed_window: List[float] = []
        latency_window: List[float] = []
        backend_error_window: List[float] = []
        algorithm_trace: List[str] = []
        latencies: List[float] = []
        total_demand = 0.0
        total_allowed = 0.0
        total_backend_success = 0.0
        total_backend_errors = 0.0
        switch_count = 0
        base_time = datetime(2026, 4, 20, tzinfo=timezone.utc)

        for second, demand in enumerate(scenario.demand_rps):
            if current_config.algorithm == "fixed":
                allowed = limiter.allow(demand, second)
            else:
                allowed = limiter.allow(demand)
            backend_success, backend_errors, latency_p95 = simulate_backend(
                current_config.algorithm, allowed, backend_capacity_rps
            )

            observed_window.append(demand)
            allowed_window.append(allowed)
            latency_window.append(latency_p95)
            backend_error_window.append(backend_errors)
            algorithm_trace.append(current_config.algorithm)
            latencies.append(latency_p95)
            total_demand += demand
            total_allowed += allowed
            total_backend_success += backend_success
            total_backend_errors += backend_errors

            history_points.append(
                ai.TimePoint(ts=base_time + timedelta(seconds=second), rps=demand)
            )

            if (second + 1) % control_interval_seconds != 0:
                continue

            (
                observed_rps,
                allowed_rps,
                rejected_rps,
                rejected_rate,
                interval_latency_p95,
                errors_5xx,
            ) = aggregate_interval(
                observed_window,
                allowed_window,
                latency_window,
                backend_error_window,
            )
            predicted_slice = scenario.demand_rps[
                second + 1 : second + 1 + control_interval_seconds
            ]
            predicted_rps = mean(predicted_slice) if predicted_slice else observed_rps
            recent_history = history_points[-max(1, ai.BURSTINESS_POINTS * 4) :]
            peak_rps_1s = max(observed_window) if observed_window else observed_rps
            burst_ratio = ai.safe_ratio(peak_rps_1s, observed_rps, 1.0)
            coefficient = ai.coefficient_of_variation(list(observed_window))

            request = ai.LimitConfigRequest(
                timestamp=(base_time + timedelta(seconds=second)).isoformat(),
                observedRps=round(observed_rps, 3),
                allowedRps=round(allowed_rps, 3),
                rejectedRps=round(rejected_rps, 3),
                rejectedRate=round(rejected_rate, 6),
                peakRps1s=round(peak_rps_1s, 3),
                burstRatio=round(burst_ratio, 6),
                coefficientOfVariation=round(coefficient, 6),
                latencyP95=round(interval_latency_p95, 6),
                errors5xx=errors_5xx,
                applyRecommendations=True,
                currentConfig=current_config,
            )
            recommendation = ai.recommend_config(
                request,
                predicted_rps,
                recent_history,
                state,
                base_time + timedelta(seconds=second),
            )
            next_config = ai.config_from_response(recommendation, current_config)
            if next_config.algorithm != current_config.algorithm:
                switch_count += 1
            limiter = update_or_replace_limiter(limiter, current_config, next_config)
            current_config = next_config
            observed_window.clear()
            allowed_window.clear()
            latency_window.clear()
            backend_error_window.clear()

        total_rejected = max(0.0, total_demand - total_allowed)
        result = ScenarioResult(
            candidate=candidate.name,
            mode=candidate.mode,
            scenario=scenario.name,
            duration_seconds=scenario.duration_seconds,
            total_demand=total_demand,
            total_allowed=total_allowed,
            total_rejected=total_rejected,
            total_backend_success=total_backend_success,
            total_backend_errors=total_backend_errors,
            success_percent=ai.safe_ratio(total_backend_success, total_demand, 0.0)
            * 100.0,
            reject_percent=ai.safe_ratio(total_rejected, total_demand, 0.0) * 100.0,
            backend_error_percent=ai.safe_ratio(
                total_backend_errors, total_demand, 0.0
            )
            * 100.0,
            avg_latency_ms=mean(latencies) * 1000.0 if latencies else 0.0,
            p95_latency_ms=percentile(latencies, 0.95) * 1000.0,
            overload_seconds=sum(1 for value in latencies if value >= 0.06),
            switch_count=switch_count,
            token_seconds=sum(1 for algo in algorithm_trace if algo == "token"),
            sliding_seconds=sum(1 for algo in algorithm_trace if algo == "sliding"),
            fixed_seconds=sum(1 for algo in algorithm_trace if algo == "fixed"),
            score=0.0,
        )
        result.score = score_result(result)
        return result


def summarize_candidate(results: Sequence[ScenarioResult]) -> dict:
    weighted_total = 0.0
    accumulator = {
        "weighted_score": 0.0,
        "weighted_success_percent": 0.0,
        "weighted_reject_percent": 0.0,
        "weighted_backend_error_percent": 0.0,
        "weighted_avg_latency_ms": 0.0,
        "weighted_p95_latency_ms": 0.0,
        "weighted_overload_seconds": 0.0,
        "total_switch_count": 0.0,
        "total_token_seconds": 0.0,
        "total_sliding_seconds": 0.0,
        "total_fixed_seconds": 0.0,
    }
    for result in results:
        weight = SCENARIO_WEIGHTS.get(result.scenario, 1.0)
        weighted_total += weight
        accumulator["weighted_score"] += result.score * weight
        accumulator["weighted_success_percent"] += result.success_percent * weight
        accumulator["weighted_reject_percent"] += result.reject_percent * weight
        accumulator["weighted_backend_error_percent"] += (
            result.backend_error_percent * weight
        )
        accumulator["weighted_avg_latency_ms"] += result.avg_latency_ms * weight
        accumulator["weighted_p95_latency_ms"] += result.p95_latency_ms * weight
        accumulator["weighted_overload_seconds"] += result.overload_seconds * weight
        accumulator["total_switch_count"] += result.switch_count
        accumulator["total_token_seconds"] += result.token_seconds
        accumulator["total_sliding_seconds"] += result.sliding_seconds
        accumulator["total_fixed_seconds"] += result.fixed_seconds

    candidate = results[0].candidate
    mode = results[0].mode
    summary = {"candidate": candidate, "mode": mode}
    for key, value in accumulator.items():
        if key.startswith("weighted_"):
            summary[key] = value / max(weighted_total, 1.0)
        else:
            summary[key] = value
    return summary


def build_default_candidates(search: bool) -> List[Candidate]:
    candidates = [
        Candidate(
            name="static_sliding",
            mode="static_sliding",
            adaptive=False,
            start_algorithm="sliding",
            overrides={},
        ),
        Candidate(
            name="static_token",
            mode="static_token",
            adaptive=False,
            start_algorithm="token",
            overrides={},
        ),
        Candidate(
            name="adaptive_baseline",
            mode="adaptive",
            adaptive=True,
            start_algorithm="sliding",
            overrides={"TOKEN_TUNER_ENABLED": False},
        ),
    ]
    if not search:
        return candidates

    for (
        min_switch_interval,
        token_hold,
        min_change_interval,
        overload_gain,
        max_step_up_factor,
    ) in product(
        (20, 30, 45),
        (20, 30, 45),
        (10, 20, 30),
        (0.0, 0.05, 0.10),
        (1.0, 1.02, 1.05),
    ):
        name = (
            "adaptive_profile"
            f"_sw{min_switch_interval}"
            f"_hold{token_hold}"
            f"_chg{min_change_interval}"
            f"_gain{int(overload_gain * 100)}"
            f"_step{int(max_step_up_factor * 100)}"
        )
        candidates.append(
            Candidate(
                name=name,
                mode="adaptive",
                adaptive=True,
                start_algorithm="sliding",
                overrides={
                    "TOKEN_TUNER_ENABLED": False,
                    "MIN_ALGO_SWITCH_INTERVAL_SECONDS": min_switch_interval,
                    "TOKEN_MIN_HOLD_SECONDS": token_hold,
                    "MIN_CHANGE_INTERVAL_SECONDS": min_change_interval,
                    "TOKEN_OVERLOAD_GAIN": overload_gain,
                    "MAX_STEP_UP_FACTOR": max_step_up_factor,
                },
            )
        )
    return candidates


def evaluate_candidates(
    candidates: Sequence[Candidate],
    scenarios: Sequence[ReplayScenario],
    backend_capacity_rps: float,
) -> tuple[List[dict], List[dict]]:
    raw_rows: List[dict] = []
    summary_rows: List[dict] = []

    for candidate in candidates:
        results: List[ScenarioResult] = []
        for scenario in scenarios:
            if candidate.adaptive:
                result = run_adaptive_scenario(
                    scenario,
                    candidate,
                    backend_capacity_rps,
                )
            else:
                result = run_static_scenario(
                    scenario,
                    initial_config(candidate.start_algorithm),
                    candidate,
                    backend_capacity_rps,
                )
            results.append(result)
            raw_rows.append(result.__dict__)
        summary_rows.append(summarize_candidate(results))

    summary_rows.sort(
        key=lambda row: (
            -float(row["weighted_score"]),
            -float(row["weighted_success_percent"]),
            float(row["weighted_p95_latency_ms"]),
        )
    )
    raw_rows.sort(
        key=lambda row: (
            row["candidate"],
            row["scenario"],
        )
    )
    return summary_rows, raw_rows


def print_top(summary_rows: Sequence[dict], top: int) -> None:
    print(
        "rank,candidate,score,success,reject,backend_err,p95_ms,overload_s,switches"
    )
    for index, row in enumerate(summary_rows[:top], start=1):
        print(
            ",".join(
                [
                    str(index),
                    str(row["candidate"]),
                    format_value(float(row["weighted_score"])),
                    format_value(float(row["weighted_success_percent"])),
                    format_value(float(row["weighted_reject_percent"])),
                    format_value(float(row["weighted_backend_error_percent"])),
                    format_value(float(row["weighted_p95_latency_ms"])),
                    format_value(float(row["weighted_overload_seconds"])),
                    format_value(float(row["total_switch_count"])),
                ]
            )
        )


def default_output_prefix() -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return DEFAULT_OUTPUT_DIR / f"offline-adaptive-replay-{timestamp}"


def main() -> None:
    args = parse_args()
    logging.getLogger().setLevel(logging.WARNING)
    scenarios = make_scenarios(args.seed)
    candidates = build_default_candidates(args.search)
    summary_rows, raw_rows = evaluate_candidates(
        candidates,
        scenarios,
        args.backend_capacity_rps,
    )
    print_top(summary_rows, args.top)

    output_prefix = args.output_prefix or default_output_prefix()
    summary_path = Path(f"{output_prefix}.summary.csv")
    raw_path = Path(f"{output_prefix}.raw.csv")
    write_csv(summary_path, SUMMARY_COLUMNS, summary_rows)
    write_csv(raw_path, RAW_COLUMNS, raw_rows)
    print(f"summary_csv={summary_path}")
    print(f"raw_csv={raw_path}")


if __name__ == "__main__":
    main()
