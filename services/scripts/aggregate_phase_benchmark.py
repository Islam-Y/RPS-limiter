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

SCENARIO_ORDER = ["phase_burst_recovery", "phase_ddos_recovery"]
MODE_ORDER = ["static_token", "adaptive", "static_sliding"]
PHASE_ORDER = ["normal", "attack", "recovery"]

RAW_NUMERIC_FIELDS = {
    "repeat",
    "phase_order",
    "phase_duration_s",
    "total_requests",
    "forwarded",
    "rejected",
    "success_percent",
    "reject_percent",
    "effective_rps",
    "loadgen_total",
    "loadgen_errors",
    "error_percent",
    "avg_proxy_latency_ms",
    "p95_proxy_latency_ms",
    "fixed_requests",
    "token_requests",
    "sliding_requests",
    "fixed_share_percent",
    "token_share_percent",
    "sliding_share_percent",
}

SWITCH_NUMERIC_FIELDS = {
    "repeat",
    "switch_count",
    "token_seconds",
    "sliding_seconds",
    "fixed_seconds",
    "unknown_seconds",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Aggregate phased adaptive benchmark results.")
    parser.add_argument("--raw-csv", required=True, type=Path)
    parser.add_argument("--switches-csv", required=True, type=Path)
    parser.add_argument("--summary-csv", required=True, type=Path)
    parser.add_argument("--switch-summary-csv", required=True, type=Path)
    return parser.parse_args()


def to_float(value: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def mean(values: Iterable[float]) -> float:
    items = list(values)
    return sum(items) / len(items) if items else 0.0


def sample_std(values: Iterable[float]) -> float:
    items = list(values)
    if len(items) < 2:
        return 0.0
    center = mean(items)
    return math.sqrt(sum((value - center) ** 2 for value in items) / (len(items) - 1))


def ci95(values: Iterable[float]) -> float:
    items = list(values)
    if len(items) < 2:
        return 0.0
    df = len(items) - 1
    return T_CRIT_95.get(df, 1.96) * sample_std(items) / math.sqrt(len(items))


def load_rows(path: Path, numeric_fields: set[str]) -> List[dict]:
    rows: List[dict] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            parsed = dict(row)
            for field in numeric_fields:
                if field in parsed:
                    parsed[field] = to_float(parsed[field])
            rows.append(parsed)
    return rows


def ordered(items: Iterable[str], order: List[str]) -> List[str]:
    known = [item for item in order if item in items]
    rest = sorted(item for item in items if item not in order)
    return known + rest


def dominant_algorithm(row: dict) -> str:
    shares = {
        "token": row["mean_token_share_percent"],
        "sliding": row["mean_sliding_share_percent"],
        "fixed": row["mean_fixed_share_percent"],
    }
    return max(shares, key=shares.get)


def write_csv(path: Path, columns: List[str], rows: List[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            formatted = {}
            for key in columns:
                value = row.get(key, "")
                if isinstance(value, float):
                    formatted[key] = f"{value:.3f}" if key.endswith("_ms") or "rps" in key or key.endswith("_seconds") else f"{value:.2f}"
                else:
                    formatted[key] = value
            writer.writerow(formatted)


def main() -> None:
    args = parse_args()
    raw_rows = load_rows(args.raw_csv, RAW_NUMERIC_FIELDS)
    switch_rows = load_rows(args.switches_csv, SWITCH_NUMERIC_FIELDS)

    summary_rows: List[dict] = []
    raw_grouped: Dict[Tuple[str, str, str], List[dict]] = defaultdict(list)
    for row in raw_rows:
        raw_grouped[(row["scenario"], row["mode"], row["phase_name"])].append(row)

    scenarios = ordered({row["scenario"] for row in raw_rows}, SCENARIO_ORDER)
    modes = ordered({row["mode"] for row in raw_rows}, MODE_ORDER)
    phases = ordered({row["phase_name"] for row in raw_rows}, PHASE_ORDER)

    for scenario in scenarios:
        for phase in phases:
            for mode in modes:
                items = raw_grouped.get((scenario, mode, phase), [])
                if not items:
                    continue
                row = {
                    "scenario": scenario,
                    "mode": mode,
                    "phase_name": phase,
                    "phase_order": int(mean(item["phase_order"] for item in items)),
                    "runs": len(items),
                    "mean_success_percent": mean(item["success_percent"] for item in items),
                    "ci95_success_percent": ci95(item["success_percent"] for item in items),
                    "mean_reject_percent": mean(item["reject_percent"] for item in items),
                    "ci95_reject_percent": ci95(item["reject_percent"] for item in items),
                    "mean_effective_rps": mean(item["effective_rps"] for item in items),
                    "ci95_effective_rps": ci95(item["effective_rps"] for item in items),
                    "mean_error_percent": mean(item["error_percent"] for item in items),
                    "ci95_error_percent": ci95(item["error_percent"] for item in items),
                    "mean_avg_latency_ms": mean(item["avg_proxy_latency_ms"] for item in items),
                    "ci95_avg_latency_ms": ci95(item["avg_proxy_latency_ms"] for item in items),
                    "mean_p95_latency_ms": mean(item["p95_proxy_latency_ms"] for item in items),
                    "ci95_p95_latency_ms": ci95(item["p95_proxy_latency_ms"] for item in items),
                    "mean_token_share_percent": mean(item["token_share_percent"] for item in items),
                    "mean_sliding_share_percent": mean(item["sliding_share_percent"] for item in items),
                    "mean_fixed_share_percent": mean(item["fixed_share_percent"] for item in items),
                }
                row["dominant_algorithm"] = dominant_algorithm(row)
                summary_rows.append(row)

    switch_summary_rows: List[dict] = []
    switch_grouped: Dict[Tuple[str, str], List[dict]] = defaultdict(list)
    for row in switch_rows:
        switch_grouped[(row["scenario"], row["mode"])].append(row)

    for scenario in scenarios:
        for mode in modes:
            items = switch_grouped.get((scenario, mode), [])
            if not items:
                continue
            switch_summary_rows.append(
                {
                    "scenario": scenario,
                    "mode": mode,
                    "runs": len(items),
                    "mean_switch_count": mean(item["switch_count"] for item in items),
                    "ci95_switch_count": ci95(item["switch_count"] for item in items),
                    "mean_token_seconds": mean(item["token_seconds"] for item in items),
                    "mean_sliding_seconds": mean(item["sliding_seconds"] for item in items),
                    "mean_fixed_seconds": mean(item["fixed_seconds"] for item in items),
                    "mean_unknown_seconds": mean(item["unknown_seconds"] for item in items),
                }
            )

    summary_rows.sort(key=lambda row: (SCENARIO_ORDER.index(row["scenario"]), row["phase_order"], MODE_ORDER.index(row["mode"])))
    switch_summary_rows.sort(key=lambda row: (SCENARIO_ORDER.index(row["scenario"]), MODE_ORDER.index(row["mode"])))

    write_csv(
        args.summary_csv,
        [
            "scenario",
            "mode",
            "phase_order",
            "phase_name",
            "runs",
            "mean_success_percent",
            "ci95_success_percent",
            "mean_reject_percent",
            "ci95_reject_percent",
            "mean_effective_rps",
            "ci95_effective_rps",
            "mean_error_percent",
            "ci95_error_percent",
            "mean_avg_latency_ms",
            "ci95_avg_latency_ms",
            "mean_p95_latency_ms",
            "ci95_p95_latency_ms",
            "mean_token_share_percent",
            "mean_sliding_share_percent",
            "mean_fixed_share_percent",
            "dominant_algorithm",
        ],
        summary_rows,
    )
    write_csv(
        args.switch_summary_csv,
        [
            "scenario",
            "mode",
            "runs",
            "mean_switch_count",
            "ci95_switch_count",
            "mean_token_seconds",
            "mean_sliding_seconds",
            "mean_fixed_seconds",
            "mean_unknown_seconds",
        ],
        switch_summary_rows,
    )
    print(f"Wrote {len(summary_rows)} summary rows to {args.summary_csv}")
    print(f"Wrote {len(switch_summary_rows)} switch summary rows to {args.switch_summary_csv}")


if __name__ == "__main__":
    main()
