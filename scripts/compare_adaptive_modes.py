#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import math
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Tuple


T_CRIT_95 = {
    1: 12.706,
    2: 4.303,
    3: 3.182,
    4: 2.776,
    5: 2.571,
    6: 2.447,
    7: 2.365,
    8: 2.306,
    9: 2.262,
    10: 2.228,
    11: 2.201,
    12: 2.179,
    13: 2.160,
    14: 2.145,
    15: 2.131,
    16: 2.120,
    17: 2.110,
    18: 2.101,
    19: 2.093,
    20: 2.086,
    21: 2.080,
    22: 2.074,
    23: 2.069,
    24: 2.064,
    25: 2.060,
    26: 2.056,
    27: 2.052,
    28: 2.048,
    29: 2.045,
    30: 2.042,
}

ALGO_ORDER = ["fixed", "sliding", "token"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Join static/adaptive benchmark runs with CI95.")
    parser.add_argument("--static-csv", required=True, type=Path)
    parser.add_argument("--adaptive-csv", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--scenarios", default="constant_high,ddos")
    return parser.parse_args()


def to_float(value: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def mean(values: Iterable[float]) -> float:
    values = list(values)
    return sum(values) / len(values) if values else 0.0


def sample_std(values: Iterable[float]) -> float:
    values = list(values)
    n = len(values)
    if n < 2:
        return 0.0
    m = mean(values)
    return math.sqrt(sum((v - m) ** 2 for v in values) / (n - 1))


def ci95(values: Iterable[float]) -> float:
    values = list(values)
    n = len(values)
    if n < 2:
        return 0.0
    df = n - 1
    t_value = T_CRIT_95[df] if df in T_CRIT_95 else 1.96
    return t_value * sample_std(values) / math.sqrt(n)


def load_rows(path: Path) -> List[dict]:
    rows: List[dict] = []
    numeric_fields = {
        "repeat",
        "order_pos",
        "total_requests",
        "forwarded",
        "rejected",
        "reject_percent",
        "effective_rps",
        "loadgen_total",
        "loadgen_errors",
        "error_percent",
        "avg_proxy_latency_ms",
        "p95_proxy_latency_ms",
        "p99_proxy_latency_ms",
        "algo_counter_delta",
        "foreign_algo_delta",
    }
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            parsed = dict(row)
            for field in numeric_fields:
                if field in parsed:
                    parsed[field] = to_float(parsed[field])
            rows.append(parsed)
    return rows


def grouped(rows: List[dict]) -> Dict[Tuple[str, str], List[dict]]:
    result: Dict[Tuple[str, str], List[dict]] = defaultdict(list)
    for row in rows:
        result[(row["scenario"], row["algorithm"])].append(row)
    return result


def ordered_algos(algorithms: Iterable[str]) -> List[str]:
    found = list(dict.fromkeys(algorithms))
    known = [a for a in ALGO_ORDER if a in found]
    rest = [a for a in found if a not in ALGO_ORDER]
    return known + sorted(rest)


def main() -> None:
    args = parse_args()
    static_rows = load_rows(args.static_csv)
    adaptive_rows = load_rows(args.adaptive_csv)

    by_static = grouped(static_rows)
    by_adaptive = grouped(adaptive_rows)

    scenarios = [s.strip() for s in args.scenarios.split(",") if s.strip()]
    algos = ordered_algos([row["algorithm"] for row in (static_rows + adaptive_rows)])

    out_rows: List[dict] = []
    for scenario in scenarios:
        for algo in algos:
            s_items = by_static.get((scenario, algo), [])
            a_items = by_adaptive.get((scenario, algo), [])
            if not s_items and not a_items:
                continue

            s_reject = [r["reject_percent"] for r in s_items]
            a_reject = [r["reject_percent"] for r in a_items]
            s_rps = [r["effective_rps"] for r in s_items]
            a_rps = [r["effective_rps"] for r in a_items]
            s_lat = [r["avg_proxy_latency_ms"] for r in s_items]
            a_lat = [r["avg_proxy_latency_ms"] for r in a_items]
            s_p95 = [r["p95_proxy_latency_ms"] for r in s_items]
            a_p95 = [r["p95_proxy_latency_ms"] for r in a_items]
            s_p99 = [r["p99_proxy_latency_ms"] for r in s_items]
            a_p99 = [r["p99_proxy_latency_ms"] for r in a_items]
            s_err = [r["error_percent"] for r in s_items]
            a_err = [r["error_percent"] for r in a_items]
            a_foreign = [r["foreign_algo_delta"] for r in a_items]

            reject_static_mean = mean(s_reject)
            reject_adaptive_mean = mean(a_reject)
            eff_rps_static_mean = mean(s_rps)
            eff_rps_adaptive_mean = mean(a_rps)
            lat_static_mean = mean(s_lat)
            lat_adaptive_mean = mean(a_lat)

            out_rows.append(
                {
                    "scenario": scenario,
                    "algorithm": algo,
                    "runs_static": len(s_items),
                    "runs_adaptive": len(a_items),
                    "reject_static_mean": reject_static_mean,
                    "reject_static_ci95": ci95(s_reject),
                    "reject_adaptive_mean": reject_adaptive_mean,
                    "reject_adaptive_ci95": ci95(a_reject),
                    "reject_delta_pp": reject_adaptive_mean - reject_static_mean,
                    "eff_rps_static_mean": eff_rps_static_mean,
                    "eff_rps_static_ci95": ci95(s_rps),
                    "eff_rps_adaptive_mean": eff_rps_adaptive_mean,
                    "eff_rps_adaptive_ci95": ci95(a_rps),
                    "eff_rps_delta": eff_rps_adaptive_mean - eff_rps_static_mean,
                    "latency_static_mean_ms": lat_static_mean,
                    "latency_static_ci95_ms": ci95(s_lat),
                    "latency_adaptive_mean_ms": lat_adaptive_mean,
                    "latency_adaptive_ci95_ms": ci95(a_lat),
                    "latency_delta_ms": lat_adaptive_mean - lat_static_mean,
                    "p95_static_mean_ms": mean(s_p95),
                    "p95_adaptive_mean_ms": mean(a_p95),
                    "p99_static_mean_ms": mean(s_p99),
                    "p99_adaptive_mean_ms": mean(a_p99),
                    "error_static_mean": mean(s_err),
                    "error_adaptive_mean": mean(a_err),
                    "foreign_algo_delta_adaptive_mean": mean(a_foreign),
                }
            )

    columns = [
        "scenario",
        "algorithm",
        "runs_static",
        "runs_adaptive",
        "reject_static_mean",
        "reject_static_ci95",
        "reject_adaptive_mean",
        "reject_adaptive_ci95",
        "reject_delta_pp",
        "eff_rps_static_mean",
        "eff_rps_static_ci95",
        "eff_rps_adaptive_mean",
        "eff_rps_adaptive_ci95",
        "eff_rps_delta",
        "latency_static_mean_ms",
        "latency_static_ci95_ms",
        "latency_adaptive_mean_ms",
        "latency_adaptive_ci95_ms",
        "latency_delta_ms",
        "p95_static_mean_ms",
        "p95_adaptive_mean_ms",
        "p99_static_mean_ms",
        "p99_adaptive_mean_ms",
        "error_static_mean",
        "error_adaptive_mean",
        "foreign_algo_delta_adaptive_mean",
    ]

    with args.output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in out_rows:
            formatted = {}
            for key in columns:
                value = row.get(key, "")
                if isinstance(value, float):
                    formatted[key] = f"{value:.3f}" if key.endswith("_ms") or "rps" in key else f"{value:.2f}"
                else:
                    formatted[key] = value
            writer.writerow(formatted)

    print(f"Wrote {len(out_rows)} rows to {args.output}")


if __name__ == "__main__":
    main()
