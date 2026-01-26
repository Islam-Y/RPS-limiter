from __future__ import annotations

import json
import logging
import math
import os
import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Deque, List, Optional, Union

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, validator
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

try:
    from prophet import Prophet
    import pandas as pd

    PROPHET_AVAILABLE = True
except Exception:
    Prophet = None
    pd = None
    PROPHET_AVAILABLE = False

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s %(levelname)s %(message)s")

HISTORY_WINDOW_SECONDS = int(os.getenv("HISTORY_WINDOW_SECONDS", "3600"))
MAX_HISTORY_POINTS = int(os.getenv("MAX_HISTORY_POINTS", "5000"))
MIN_HISTORY_POINTS = int(os.getenv("MIN_HISTORY_POINTS", "10"))
FORECAST_SECONDS = int(os.getenv("FORECAST_SECONDS", "60"))
FALLBACK_WINDOW_POINTS = int(os.getenv("FALLBACK_WINDOW_POINTS", "5"))

MIN_CHANGE_INTERVAL_SECONDS = int(os.getenv("MIN_CHANGE_INTERVAL_SECONDS", "30"))
MIN_RELATIVE_CHANGE = float(os.getenv("MIN_RELATIVE_CHANGE", "0.1"))
INCREASE_THRESHOLD = float(os.getenv("INCREASE_THRESHOLD", "0.1"))
DECREASE_THRESHOLD = float(os.getenv("DECREASE_THRESHOLD", "0.2"))
INCREASE_HEADROOM = float(os.getenv("INCREASE_HEADROOM", "0.05"))
DECREASE_FACTOR = float(os.getenv("DECREASE_FACTOR", "0.7"))

MIN_RPS = float(os.getenv("MIN_RPS", "1"))
MAX_RPS = float(os.getenv("MAX_RPS", "10000"))

REJECTED_RATE_THRESHOLD = float(os.getenv("REJECTED_RATE_THRESHOLD", "0.1"))
LATENCY_P95_THRESHOLD = float(os.getenv("LATENCY_P95_THRESHOLD", "1.0"))
ERRORS_5XX_THRESHOLD = int(os.getenv("ERRORS_5XX_THRESHOLD", "1"))
DDOS_MULTIPLIER = float(os.getenv("DDOS_MULTIPLIER", "2.0"))

DEFAULT_WINDOW_SECONDS = int(os.getenv("DEFAULT_WINDOW_SECONDS", "60"))
TOKEN_CAPACITY_SECONDS = float(os.getenv("TOKEN_CAPACITY_SECONDS", "2.0"))
MAX_CAPACITY = int(os.getenv("MAX_CAPACITY", "0"))

ALLOW_ALGO_SWITCH = os.getenv("ALLOW_ALGO_SWITCH", "false").lower() == "true"
MIN_ALGO_SWITCH_INTERVAL_SECONDS = int(
    os.getenv("MIN_ALGO_SWITCH_INTERVAL_SECONDS", "300")
)
BURSTINESS_THRESHOLD = float(os.getenv("BURSTINESS_THRESHOLD", "1.5"))
BURSTINESS_POINTS = int(os.getenv("BURSTINESS_POINTS", "10"))

ALLOWED_ALGORITHMS = {"fixed", "sliding", "token"}

REQUESTS_TOTAL = Counter(
    "ai_limit_config_requests_total",
    "Total /v1/limit-config requests",
    ["result"],
)
FORECAST_DURATION_SECONDS = Histogram(
    "ai_forecast_duration_seconds",
    "Time spent generating forecast",
)
LAST_OBSERVED_RPS = Gauge(
    "ai_last_observed_rps",
    "Last observed RPS from input",
)
LAST_PREDICTED_RPS = Gauge(
    "ai_last_predicted_rps",
    "Last predicted RPS",
)
LAST_RECOMMENDED_RPS = Gauge(
    "ai_last_recommended_rps",
    "Last recommended RPS derived from response",
)
LAST_RECOMMENDED_LIMIT = Gauge(
    "ai_last_recommended_limit",
    "Last recommended limit for fixed/sliding algorithms",
)
LAST_RECOMMENDED_WINDOW_SECONDS = Gauge(
    "ai_last_recommended_window_seconds",
    "Last recommended window size in seconds",
)
LAST_RECOMMENDED_CAPACITY = Gauge(
    "ai_last_recommended_capacity",
    "Last recommended token bucket capacity",
)
LAST_RECOMMENDED_FILL_RATE = Gauge(
    "ai_last_recommended_fill_rate",
    "Last recommended token bucket fill rate",
)
LAST_VALID_FOR_SECONDS = Gauge(
    "ai_last_valid_for_seconds",
    "Last validFor value from response",
)
LAST_ALGORITHM = Gauge(
    "ai_last_algorithm",
    "Last recommended algorithm (1=active)",
    ["algorithm"],
)
HISTORY_POINTS = Gauge(
    "ai_history_points",
    "Number of points in history window",
)


class LimitConfigIn(BaseModel):
    algorithm: str = Field(..., description="fixed|sliding|token")
    limit: Optional[float] = Field(None, ge=0)
    window: Optional[int] = Field(None, gt=0)
    capacity: Optional[int] = Field(None, ge=0)
    fillRate: Optional[float] = Field(None, ge=0)

    class Config:
        extra = "ignore"

    @validator("algorithm", pre=True)
    def _normalize_algorithm(cls, value: str) -> str:
        if not isinstance(value, str):
            return value
        normalized = value.strip().lower()
        if normalized in ("token_bucket", "tokenbucket"):
            return "token"
        return normalized


class LimitConfigRequest(BaseModel):
    timestamp: Optional[Union[str, float, int]] = None
    observedRps: float = Field(..., ge=0)
    rejectedRate: Optional[float] = Field(None, ge=0, le=1)
    latencyP95: Optional[float] = Field(None, ge=0)
    errors5xx: Optional[int] = Field(None, ge=0)
    currentConfig: LimitConfigIn

    class Config:
        extra = "ignore"


class LimitConfigResponse(BaseModel):
    algorithm: str
    limit: Optional[int] = None
    window: Optional[int] = None
    capacity: Optional[int] = None
    fillRate: Optional[float] = None
    predictedRps: Optional[float] = None
    validFor: Optional[int] = None

    class Config:
        extra = "ignore"


@dataclass(frozen=True)
class TimePoint:
    ts: datetime
    rps: float


class DataCollector:
    def __init__(self, window_seconds: int, max_points: int) -> None:
        self._window_seconds = max(1, window_seconds)
        self._max_points = max(2, max_points)
        self._points: Deque[TimePoint] = deque()
        self._lock = threading.Lock()

    def add_point(self, ts: datetime, rps: float) -> None:
        with self._lock:
            if self._points and ts <= self._points[-1].ts:
                ts = self._points[-1].ts + timedelta(microseconds=1)
            self._points.append(TimePoint(ts=ts, rps=rps))
            self._trim()

    def snapshot(self) -> List[TimePoint]:
        with self._lock:
            return list(self._points)

    def _trim(self) -> None:
        if not self._points:
            return
        cutoff = self._points[-1].ts - timedelta(seconds=self._window_seconds)
        while self._points and self._points[0].ts < cutoff:
            self._points.popleft()
        while len(self._points) > self._max_points:
            self._points.popleft()


class Forecaster:
    def __init__(self, horizon_seconds: int, min_points: int) -> None:
        self._horizon_seconds = max(1, horizon_seconds)
        self._min_points = max(2, min_points)

    def forecast(self, points: List[TimePoint]) -> Optional[float]:
        if not points:
            return None
        if PROPHET_AVAILABLE and len(points) >= self._min_points:
            try:
                frame = pd.DataFrame(
                    {"ds": [point.ts for point in points], "y": [point.rps for point in points]}
                )
                model = Prophet(
                    daily_seasonality=False,
                    weekly_seasonality=False,
                    yearly_seasonality=False,
                )
                model.fit(frame)
                future = pd.DataFrame(
                    {"ds": [points[-1].ts + timedelta(seconds=self._horizon_seconds)]}
                )
                forecast = model.predict(future)
                predicted = float(forecast["yhat"].iloc[-1])
                return max(0.0, predicted)
            except Exception as exc:
                logging.exception("Prophet forecast failed: %s", exc)
        return fallback_forecast(points, self._horizon_seconds)


@dataclass
class RecommendationState:
    last_change_at: Optional[datetime] = None
    last_algo_switch_at: Optional[datetime] = None
    last_good_recommendation: Optional[LimitConfigResponse] = None
    last_good_config: Optional[LimitConfigIn] = None
    last_predicted_rps: Optional[float] = None


def parse_timestamp(value: Optional[Union[str, float, int]]) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, datetime):
        ts = value
        if ts.tzinfo is None:
            return ts.replace(tzinfo=timezone.utc)
        return ts
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    if isinstance(value, str):
        try:
            normalized = value.replace("Z", "+00:00")
            ts = datetime.fromisoformat(normalized)
            if ts.tzinfo is None:
                return ts.replace(tzinfo=timezone.utc)
            return ts
        except ValueError:
            try:
                return datetime.fromtimestamp(float(value), tz=timezone.utc)
            except ValueError:
                return datetime.now(timezone.utc)
    return datetime.now(timezone.utc)


def fallback_forecast(points: List[TimePoint], horizon_seconds: int) -> float:
    if not points:
        return 0.0
    window = points[-max(1, min(len(points), FALLBACK_WINDOW_POINTS)) :]
    if len(window) == 1:
        return window[-1].rps
    start = window[0]
    end = window[-1]
    total_seconds = (end.ts - start.ts).total_seconds()
    if total_seconds <= 0:
        return end.rps
    slope = (end.rps - start.rps) / total_seconds
    return max(0.0, end.rps + slope * horizon_seconds)


def clamp(value: float, minimum: float, maximum: Optional[float]) -> float:
    if maximum is None:
        return max(minimum, value)
    return max(minimum, min(value, maximum))


def validate_current_config(config: LimitConfigIn) -> Optional[str]:
    if config.algorithm not in ALLOWED_ALGORITHMS:
        return "Unsupported algorithm"
    if config.algorithm in ("fixed", "sliding"):
        if config.limit is None or config.window is None:
            return "limit and window are required for fixed/sliding"
        if config.limit <= 0 or config.window <= 0:
            return "limit/window must be positive"
    if config.algorithm == "token":
        if config.capacity is None or config.fillRate is None:
            return "capacity and fillRate are required for token"
        if config.capacity <= 0 or config.fillRate <= 0:
            return "capacity/fillRate must be positive"
    return None


def keep_current_response(
    config: LimitConfigIn, predicted_rps: Optional[float]
) -> LimitConfigResponse:
    return LimitConfigResponse(
        algorithm=config.algorithm,
        limit=int(config.limit) if config.limit is not None else None,
        window=int(config.window) if config.window is not None else None,
        capacity=int(config.capacity) if config.capacity is not None else None,
        fillRate=float(config.fillRate) if config.fillRate is not None else None,
        predictedRps=predicted_rps,
        validFor=FORECAST_SECONDS,
    )


def coerce_current_config(
    payload: object, fallback: Optional[LimitConfigIn]
) -> Optional[LimitConfigIn]:
    if not isinstance(payload, dict):
        return fallback
    raw_config = payload.get("currentConfig")
    if not isinstance(raw_config, dict):
        return fallback
    merged: dict = {}
    if fallback is not None:
        merged.update(fallback.dict(exclude_none=True))
    for key, value in raw_config.items():
        if value is not None:
            merged[key] = value
    if not merged:
        return fallback
    try:
        candidate = LimitConfigIn(**merged)
    except Exception:
        return fallback
    if validate_current_config(candidate) is not None:
        return fallback
    return candidate


def parse_optional_float(value: object) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def default_fallback_config() -> LimitConfigIn:
    window = max(1, DEFAULT_WINDOW_SECONDS)
    limit = max(1, int(math.ceil(MIN_RPS * window)))
    max_rps = MAX_RPS if MAX_RPS > 0 else None
    if max_rps is not None:
        max_limit = int(math.floor(max_rps * window))
        if max_limit < 1:
            window = max(window, int(math.ceil(1 / max_rps)))
            max_limit = int(math.floor(max_rps * window))
        if max_limit >= 1:
            limit = min(limit, max_limit)
        limit = max(1, limit)
    return LimitConfigIn(algorithm="fixed", limit=limit, window=window)


def recommendation_rps(recommendation: LimitConfigResponse) -> Optional[float]:
    if recommendation.algorithm in ("fixed", "sliding"):
        if recommendation.limit is None or recommendation.window in (None, 0):
            return None
        return float(recommendation.limit) / float(recommendation.window)
    if recommendation.algorithm == "token" and recommendation.fillRate is not None:
        return float(recommendation.fillRate)
    return None


def update_algorithm_gauge(algorithm: str) -> None:
    if algorithm not in ALLOWED_ALGORITHMS:
        return
    for algo in ALLOWED_ALGORITHMS:
        LAST_ALGORITHM.labels(algorithm=algo).set(1.0 if algo == algorithm else 0.0)


def update_metrics(
    request: LimitConfigRequest,
    predicted_rps: float,
    recommendation: LimitConfigResponse,
    history_len: int,
    result: str,
) -> None:
    REQUESTS_TOTAL.labels(result=result).inc()
    LAST_OBSERVED_RPS.set(float(request.observedRps))
    LAST_PREDICTED_RPS.set(float(predicted_rps))
    HISTORY_POINTS.set(float(history_len))
    LAST_VALID_FOR_SECONDS.set(float(recommendation.validFor or 0))

    rec_rps = recommendation_rps(recommendation)
    if rec_rps is not None:
        LAST_RECOMMENDED_RPS.set(float(rec_rps))
    update_algorithm_gauge(recommendation.algorithm)

    if recommendation.algorithm in ("fixed", "sliding"):
        LAST_RECOMMENDED_LIMIT.set(float(recommendation.limit or 0))
        LAST_RECOMMENDED_WINDOW_SECONDS.set(float(recommendation.window or 0))
        LAST_RECOMMENDED_CAPACITY.set(0.0)
        LAST_RECOMMENDED_FILL_RATE.set(0.0)
    elif recommendation.algorithm == "token":
        LAST_RECOMMENDED_LIMIT.set(0.0)
        LAST_RECOMMENDED_WINDOW_SECONDS.set(0.0)
        LAST_RECOMMENDED_CAPACITY.set(float(recommendation.capacity or 0))
        LAST_RECOMMENDED_FILL_RATE.set(float(recommendation.fillRate or 0))


def set_gauge_value(gauge, value: Optional[float]) -> None:
    if value is None:
        gauge.set(math.nan)
        return
    gauge.set(float(value))


def update_metrics_from_response(
    recommendation: LimitConfigResponse,
    observed_rps: Optional[float],
    predicted_rps: Optional[float],
    history_len: Optional[int],
    result: str,
) -> None:
    REQUESTS_TOTAL.labels(result=result).inc()
    set_gauge_value(LAST_OBSERVED_RPS, observed_rps)
    set_gauge_value(LAST_PREDICTED_RPS, predicted_rps)
    if history_len is None:
        set_gauge_value(HISTORY_POINTS, None)
    else:
        HISTORY_POINTS.set(float(history_len))
    LAST_VALID_FOR_SECONDS.set(float(recommendation.validFor or 0))

    rec_rps = recommendation_rps(recommendation)
    set_gauge_value(LAST_RECOMMENDED_RPS, rec_rps)
    update_algorithm_gauge(recommendation.algorithm)

    if recommendation.algorithm in ("fixed", "sliding"):
        LAST_RECOMMENDED_LIMIT.set(float(recommendation.limit or 0))
        LAST_RECOMMENDED_WINDOW_SECONDS.set(float(recommendation.window or 0))
        LAST_RECOMMENDED_CAPACITY.set(0.0)
        LAST_RECOMMENDED_FILL_RATE.set(0.0)
    elif recommendation.algorithm == "token":
        LAST_RECOMMENDED_LIMIT.set(0.0)
        LAST_RECOMMENDED_WINDOW_SECONDS.set(0.0)
        LAST_RECOMMENDED_CAPACITY.set(float(recommendation.capacity or 0))
        LAST_RECOMMENDED_FILL_RATE.set(float(recommendation.fillRate or 0))


def current_rps_limit(config: LimitConfigIn) -> float:
    if config.algorithm in ("fixed", "sliding"):
        return float(config.limit) / float(config.window)
    return float(config.fillRate)


def is_bursty(points: List[TimePoint]) -> bool:
    if len(points) < max(2, BURSTINESS_POINTS):
        return False
    sample = [point.rps for point in points[-BURSTINESS_POINTS:]]
    mean = sum(sample) / len(sample)
    if mean <= 0:
        return False
    return max(sample) / mean >= BURSTINESS_THRESHOLD


def build_response(
    algorithm: str,
    target_rps: float,
    current_config: LimitConfigIn,
    predicted_rps: Optional[float],
) -> LimitConfigResponse:
    max_rps = MAX_RPS if MAX_RPS > 0 else None
    if algorithm in ("fixed", "sliding"):
        window = int(current_config.window or DEFAULT_WINDOW_SECONDS)
        limit = int(math.ceil(target_rps * window))
        min_limit = int(math.ceil(MIN_RPS * window))
        limit = max(limit, min_limit)
        if max_rps is not None:
            limit = min(limit, int(math.floor(max_rps * window)))
        return LimitConfigResponse(
            algorithm=algorithm,
            limit=limit,
            window=window,
            predictedRps=predicted_rps,
            validFor=FORECAST_SECONDS,
        )
    fill_rate = clamp(target_rps, MIN_RPS, max_rps)
    capacity = int(math.ceil(fill_rate * TOKEN_CAPACITY_SECONDS))
    capacity = max(capacity, int(math.ceil(MIN_RPS * TOKEN_CAPACITY_SECONDS)))
    if capacity < fill_rate:
        capacity = int(math.ceil(fill_rate))
    if MAX_CAPACITY > 0:
        capacity = min(capacity, MAX_CAPACITY)
    return LimitConfigResponse(
        algorithm=algorithm,
        capacity=capacity,
        fillRate=round(fill_rate, 3),
        predictedRps=predicted_rps,
        validFor=FORECAST_SECONDS,
    )


def configs_equal(current: LimitConfigIn, recommended: LimitConfigResponse) -> bool:
    if current.algorithm != recommended.algorithm:
        return False
    if current.algorithm in ("fixed", "sliding"):
        return int(current.limit) == recommended.limit and int(current.window) == recommended.window
    return (
        int(current.capacity) == recommended.capacity
        and abs(float(current.fillRate) - float(recommended.fillRate)) < 1e-6
    )


def recommend_config(
    request: LimitConfigRequest,
    predicted_rps: float,
    history_points: List[TimePoint],
    state: RecommendationState,
    now: datetime,
) -> LimitConfigResponse:
    current_config = request.currentConfig
    current_limit = current_rps_limit(current_config)
    max_rps = MAX_RPS if MAX_RPS > 0 else None
    predicted_rps = clamp(predicted_rps, 0.0, max_rps)

    overload = False
    if request.rejectedRate is not None and request.rejectedRate >= REJECTED_RATE_THRESHOLD:
        overload = True
    if request.latencyP95 is not None and request.latencyP95 >= LATENCY_P95_THRESHOLD:
        overload = True
    if request.errors5xx is not None and request.errors5xx >= ERRORS_5XX_THRESHOLD:
        overload = True

    spike = predicted_rps >= current_limit * DDOS_MULTIPLIER
    target_rps = current_limit

    if overload or spike:
        target_rps = current_limit * DECREASE_FACTOR
    elif predicted_rps > current_limit * (1 + INCREASE_THRESHOLD):
        target_rps = predicted_rps * (1 + INCREASE_HEADROOM)
    elif predicted_rps < current_limit * (1 - DECREASE_THRESHOLD):
        target_rps = predicted_rps

    target_rps = clamp(target_rps, MIN_RPS, max_rps)
    if not math.isfinite(target_rps):
        target_rps = current_limit

    desired_algorithm = current_config.algorithm
    algo_switch_allowed = ALLOW_ALGO_SWITCH and (
        state.last_algo_switch_at is None
        or (now - state.last_algo_switch_at).total_seconds() >= MIN_ALGO_SWITCH_INTERVAL_SECONDS
    )
    if algo_switch_allowed and is_bursty(history_points):
        desired_algorithm = "token"
    elif algo_switch_allowed and not is_bursty(history_points):
        if desired_algorithm == "token":
            desired_algorithm = "sliding"

    recommendation = build_response(
        desired_algorithm, target_rps, current_config, round(predicted_rps, 3)
    )

    change_ratio = 0.0
    if current_limit > 0:
        change_ratio = abs(target_rps - current_limit) / current_limit

    recent_change_block = (
        state.last_change_at is not None
        and (now - state.last_change_at).total_seconds() < MIN_CHANGE_INTERVAL_SECONDS
    )

    if configs_equal(current_config, recommendation):
        return recommendation
    if desired_algorithm == current_config.algorithm and change_ratio < MIN_RELATIVE_CHANGE:
        return build_response(
            current_config.algorithm,
            current_limit,
            current_config,
            round(predicted_rps, 3),
        )
    if recent_change_block:
        return build_response(
            current_config.algorithm,
            current_limit,
            current_config,
            round(predicted_rps, 3),
        )

    state.last_change_at = now
    if desired_algorithm != current_config.algorithm:
        state.last_algo_switch_at = now
    return recommendation


app = FastAPI(title="AI Rate Limit Recommender", version="1.0.0")

collector = DataCollector(HISTORY_WINDOW_SECONDS, MAX_HISTORY_POINTS)
forecaster = Forecaster(FORECAST_SECONDS, MIN_HISTORY_POINTS)
state = RecommendationState()
state_lock = threading.Lock()

if not PROPHET_AVAILABLE:
    logging.warning("Prophet not available, using fallback forecast.")


@app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    if request.url.path != "/v1/limit-config":
        return JSONResponse(status_code=422, content={"detail": exc.errors()})
    logging.warning("Request validation failed: %s", exc.errors())
    payload = None
    try:
        body = await request.body()
        if body:
            payload = json.loads(body)
    except Exception:
        payload = None
    observed_rps = None
    if isinstance(payload, dict):
        observed_rps = parse_optional_float(payload.get("observedRps"))
    with state_lock:
        fallback_config = state.last_good_config
        fallback_recommendation = state.last_good_recommendation
        last_predicted_rps = state.last_predicted_rps
    history_len = len(collector.snapshot())
    current_config = coerce_current_config(payload, fallback_config)
    if current_config is not None:
        logging.warning("Keeping current configuration after validation error.")
        recommendation = keep_current_response(current_config, last_predicted_rps)
        update_metrics_from_response(
            recommendation,
            observed_rps,
            recommendation.predictedRps,
            history_len,
            "validation_error",
        )
        return JSONResponse(
            status_code=200, content=recommendation.dict(exclude_none=True)
        )
    if fallback_recommendation is not None:
        logging.warning("Using last recommendation after validation error.")
        update_metrics_from_response(
            fallback_recommendation,
            observed_rps,
            fallback_recommendation.predictedRps,
            history_len,
            "validation_error",
        )
        return JSONResponse(
            status_code=200, content=fallback_recommendation.dict(exclude_none=True)
        )
    logging.warning("No prior configuration available; using default fallback config.")
    recommendation = keep_current_response(default_fallback_config(), last_predicted_rps)
    update_metrics_from_response(
        recommendation,
        observed_rps,
        recommendation.predictedRps,
        history_len,
        "validation_error",
    )
    return JSONResponse(status_code=200, content=recommendation.dict(exclude_none=True))


@app.get("/health")
async def health() -> dict:
    return {"status": "UP"}


@app.get("/metrics")
async def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/v1/limit-config", response_model=LimitConfigResponse, response_model_exclude_none=True)
async def limit_config(request: LimitConfigRequest) -> LimitConfigResponse:
    received_at = datetime.now(timezone.utc)
    sample_ts = parse_timestamp(request.timestamp)

    collector.add_point(sample_ts, request.observedRps)
    history = collector.snapshot()

    with FORECAST_DURATION_SECONDS.time():
        predicted = forecaster.forecast(history)
    if predicted is None:
        predicted = request.observedRps
    max_rps = MAX_RPS if MAX_RPS > 0 else None
    predicted = clamp(predicted, 0.0, max_rps)
    predicted_rps = round(predicted, 3)
    with state_lock:
        state.last_predicted_rps = predicted_rps

    logging.info(
        "snapshot observed_rps=%.3f rejected_rate=%s latency_p95=%s errors5xx=%s algo=%s",
        request.observedRps,
        request.rejectedRate,
        request.latencyP95,
        request.errors5xx,
        request.currentConfig.algorithm,
    )

    validation_error = validate_current_config(request.currentConfig)
    if validation_error:
        logging.warning(
            "Invalid currentConfig received: %s current_config=%s",
            validation_error,
            request.currentConfig.dict(exclude_none=True),
        )
        with state_lock:
            fallback_config = state.last_good_config
        if fallback_config is None:
            logging.warning("No prior configuration available; using default fallback config.")
            fallback_config = default_fallback_config()
        else:
            logging.warning("Using last known configuration after invalid currentConfig.")
        recommendation = keep_current_response(fallback_config, predicted_rps)
        update_metrics(request, predicted_rps, recommendation, len(history), "invalid_config")
        logging.info(
            "forecast predicted_rps=%.3f recommendation=%s",
            predicted_rps,
            recommendation.dict(exclude_none=True),
        )
        return recommendation

    with state_lock:
        recommendation = recommend_config(request, predicted, history, state, received_at)
        state.last_good_recommendation = recommendation
        state.last_good_config = request.currentConfig
    update_metrics(request, predicted_rps, recommendation, len(history), "ok")
    logging.info(
        "forecast predicted_rps=%.3f current_rps_limit=%.3f recommendation=%s",
        predicted_rps,
        current_rps_limit(request.currentConfig),
        recommendation.dict(exclude_none=True),
    )
    return recommendation
