#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import math
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List


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
    parser = argparse.ArgumentParser(description="Aggregate repeated battle-matrix runs with CI95.")
    parser.add_argument("--raw", required=True, type=Path, help="Raw per-run CSV")
    parser.add_argument("--summary", required=True, type=Path, help="Output summary CSV")
    parser.add_argument("--overall", required=True, type=Path, help="Output overall CSV")
    parser.add_argument("--scored", required=True, type=Path, help="Output scored CSV")
    parser.add_argument("--markdown", required=True, type=Path, help="Output markdown table")
    parser.add_argument(
        "--scenarios",
        required=True,
        help="Comma-separated scenario order (e.g. constant_low,sinusoidal,poisson,constant_high,burst,ddos)",
    )
    return parser.parse_args()


def to_float(value: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


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
        "expected_reject_percent",
        "stability_score",
        "protection_score",
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


def mean(values: Iterable[float]) -> float:
    values = list(values)
    return sum(values) / len(values) if values else 0.0


def sample_std(values: Iterable[float]) -> float:
    values = list(values)
    n = len(values)
    if n < 2:
        return 0.0
    avg = mean(values)
    return math.sqrt(sum((v - avg) ** 2 for v in values) / (n - 1))


def ci95(values: Iterable[float]) -> float:
    values = list(values)
    n = len(values)
    if n < 2:
        return 0.0
    std = sample_std(values)
    df = n - 1
    t_value = T_CRIT_95[df] if df in T_CRIT_95 else 1.96
    return t_value * std / math.sqrt(n)


def scenario_algo_groups(rows: List[dict]) -> Dict[tuple, List[dict]]:
    groups: Dict[tuple, List[dict]] = defaultdict(list)
    for row in rows:
        groups[(row["scenario"], row["algorithm"])].append(row)
    return groups


def ordered_algorithms(found_algos: Iterable[str]) -> List[str]:
    found = list(dict.fromkeys(found_algos))
    known = [algo for algo in ALGO_ORDER if algo in found]
    other = [algo for algo in found if algo not in ALGO_ORDER]
    return known + sorted(other)


def format_row(values: Dict[str, float], columns: List[str]) -> dict:
    formatted = {}
    for col in columns:
        value = values.get(col, "")
        if isinstance(value, float):
            if col.endswith("_ms") or "percent" in col or col.endswith("_score") or col.endswith("_rps") or col.endswith("_delta"):
                formatted[col] = f"{value:.3f}" if col.endswith("_ms") or col.endswith("_rps") else f"{value:.2f}"
            else:
                formatted[col] = f"{value:.6f}"
        else:
            formatted[col] = value
    return formatted


def write_csv(path: Path, rows: List[dict], columns: List[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow(format_row(row, columns))


def aggregate_summary(rows: List[dict], scenarios: List[str]) -> List[dict]:
    groups = scenario_algo_groups(rows)
    algos = ordered_algorithms(row["algorithm"] for row in rows)
    result: List[dict] = []

    for scenario in scenarios:
        for algo in algos:
            items = groups.get((scenario, algo), [])
            if not items:
                continue
            total_sum = sum(i["total_requests"] for i in items)
            forwarded_sum = sum(i["forwarded"] for i in items)
            rejected_sum = sum(i["rejected"] for i in items)
            success_percent = (forwarded_sum * 100.0 / total_sum) if total_sum > 0 else 0.0
            result.append(
                {
                    "scenario": scenario,
                    "algorithm": algo,
                    "runs": float(len(items)),
                    "total_requests_sum": total_sum,
                    "forwarded_sum": forwarded_sum,
                    "rejected_sum": rejected_sum,
                    "success_percent": success_percent,
                    "mean_reject_percent": mean(i["reject_percent"] for i in items),
                    "ci95_reject_percent": ci95(i["reject_percent"] for i in items),
                    "mean_effective_rps": mean(i["effective_rps"] for i in items),
                    "ci95_effective_rps": ci95(i["effective_rps"] for i in items),
                    "mean_error_percent": mean(i["error_percent"] for i in items),
                    "ci95_error_percent": ci95(i["error_percent"] for i in items),
                    "mean_avg_proxy_latency_ms": mean(i["avg_proxy_latency_ms"] for i in items),
                    "ci95_avg_proxy_latency_ms": ci95(i["avg_proxy_latency_ms"] for i in items),
                    "mean_p95_proxy_latency_ms": mean(i["p95_proxy_latency_ms"] for i in items),
                    "ci95_p95_proxy_latency_ms": ci95(i["p95_proxy_latency_ms"] for i in items),
                    "mean_p99_proxy_latency_ms": mean(i["p99_proxy_latency_ms"] for i in items),
                    "ci95_p99_proxy_latency_ms": ci95(i["p99_proxy_latency_ms"] for i in items),
                    "mean_expected_reject_percent": mean(i["expected_reject_percent"] for i in items),
                    "mean_stability_score": mean(i["stability_score"] for i in items),
                    "mean_protection_score": mean(i["protection_score"] for i in items),
                    "mean_algo_counter_delta": mean(i["algo_counter_delta"] for i in items),
                    "mean_foreign_algo_delta": mean(i["foreign_algo_delta"] for i in items),
                }
            )
    return result


def aggregate_scored(summary_rows: List[dict], scenarios: List[str]) -> List[dict]:
    by_scenario: Dict[str, List[dict]] = defaultdict(list)
    for row in summary_rows:
        by_scenario[row["scenario"]].append(row)

    scored: List[dict] = []
    for scenario in scenarios:
        items = by_scenario.get(scenario, [])
        if not items:
            continue
        latencies = [item["mean_avg_proxy_latency_ms"] for item in items]
        min_lat = min(latencies)
        max_lat = max(latencies)
        for item in items:
            if abs(max_lat - min_lat) < 1e-12:
                latency_score = 100.0
            else:
                latency_score = ((max_lat - item["mean_avg_proxy_latency_ms"]) / (max_lat - min_lat)) * 100.0
            overall_score = (
                0.35 * item["mean_stability_score"]
                + 0.40 * item["mean_protection_score"]
                + 0.25 * latency_score
            )
            scored.append(
                {
                    "scenario": item["scenario"],
                    "algorithm": item["algorithm"],
                    "runs": item["runs"],
                    "stability_score": item["mean_stability_score"],
                    "protection_score": item["mean_protection_score"],
                    "latency_score": latency_score,
                    "overall_score": overall_score,
                    "mean_reject_percent": item["mean_reject_percent"],
                    "ci95_reject_percent": item["ci95_reject_percent"],
                    "mean_error_percent": item["mean_error_percent"],
                    "ci95_error_percent": item["ci95_error_percent"],
                    "mean_avg_proxy_latency_ms": item["mean_avg_proxy_latency_ms"],
                    "ci95_avg_proxy_latency_ms": item["ci95_avg_proxy_latency_ms"],
                    "mean_p95_proxy_latency_ms": item["mean_p95_proxy_latency_ms"],
                    "ci95_p95_proxy_latency_ms": item["ci95_p95_proxy_latency_ms"],
                    "mean_p99_proxy_latency_ms": item["mean_p99_proxy_latency_ms"],
                    "ci95_p99_proxy_latency_ms": item["ci95_p99_proxy_latency_ms"],
                    "mean_effective_rps": item["mean_effective_rps"],
                    "ci95_effective_rps": item["ci95_effective_rps"],
                }
            )
    return scored


def aggregate_overall(rows: List[dict]) -> List[dict]:
    result: List[dict] = []
    by_algo: Dict[str, List[dict]] = defaultdict(list)
    for row in rows:
        by_algo[row["algorithm"]].append(row)

    for algo in ordered_algorithms(by_algo.keys()):
        items = by_algo.get(algo, [])
        normal = [r for r in items if r["scenario"] != "ddos"]
        ddos = [r for r in items if r["scenario"] == "ddos"]
        total_normal = sum(r["total_requests"] for r in normal)
        forwarded_normal = sum(r["forwarded"] for r in normal)
        success_vals = [
            (r["forwarded"] * 100.0 / r["total_requests"]) if r["total_requests"] > 0 else 0.0
            for r in normal
        ]
        result.append(
            {
                "algorithm": algo,
                "runs_all": float(len(items)),
                "runs_normal": float(len(normal)),
                "runs_ddos": float(len(ddos)),
                "mean_avg_latency_all_ms": mean(r["avg_proxy_latency_ms"] for r in items),
                "ci95_avg_latency_all_ms": ci95(r["avg_proxy_latency_ms"] for r in items),
                "mean_p95_latency_all_ms": mean(r["p95_proxy_latency_ms"] for r in items),
                "ci95_p95_latency_all_ms": ci95(r["p95_proxy_latency_ms"] for r in items),
                "mean_p99_latency_all_ms": mean(r["p99_proxy_latency_ms"] for r in items),
                "ci95_p99_latency_all_ms": ci95(r["p99_proxy_latency_ms"] for r in items),
                "mean_avg_latency_ddos_ms": mean(r["avg_proxy_latency_ms"] for r in ddos),
                "ci95_avg_latency_ddos_ms": ci95(r["avg_proxy_latency_ms"] for r in ddos),
                "success_normal_percent": (forwarded_normal * 100.0 / total_normal) if total_normal > 0 else 0.0,
                "ci95_success_normal_percent": ci95(success_vals),
                "mean_reject_normal_percent": mean(r["reject_percent"] for r in normal),
                "ci95_reject_normal_percent": ci95(r["reject_percent"] for r in normal),
                "mean_reject_ddos_percent": mean(r["reject_percent"] for r in ddos),
                "ci95_reject_ddos_percent": ci95(r["reject_percent"] for r in ddos),
                "mean_error_percent": mean(r["error_percent"] for r in items),
                "ci95_error_percent": ci95(r["error_percent"] for r in items),
                "mean_effective_rps": mean(r["effective_rps"] for r in items),
                "ci95_effective_rps": ci95(r["effective_rps"] for r in items),
                "mean_foreign_algo_delta": mean(r["foreign_algo_delta"] for r in items),
            }
        )
    return result


def write_markdown(path: Path, scored_rows: List[dict], scenarios: List[str]) -> None:
    by_scenario_algo: Dict[tuple, dict] = {(r["scenario"], r["algorithm"]): r for r in scored_rows}
    algos = ordered_algorithms(r["algorithm"] for r in scored_rows)

    avg_overall_by_algo: Dict[str, float] = {}
    for algo in algos:
        vals = [r["overall_score"] for r in scored_rows if r["algorithm"] == algo]
        avg_overall_by_algo[algo] = mean(vals)

    ranked = sorted(avg_overall_by_algo.items(), key=lambda kv: kv[1], reverse=True)
    rank_order = [algo for algo, _ in ranked]

    lines = [
        "| Scenario | " + " | ".join(algos) + " | Winner |",
        "|---|" + "|".join(["---:"] * len(algos)) + "|---|",
    ]

    for scenario in scenarios:
        cells = []
        best_algo = None
        best_score = -1.0
        for algo in algos:
            row = by_scenario_algo.get((scenario, algo))
            if not row:
                cells.append("n/a")
                continue
            score = row["overall_score"]
            cell = f"{score:.1f} (S{row['stability_score']:.0f}/P{row['protection_score']:.0f}/L{row['latency_score']:.0f})"
            cells.append(cell)
            if score > best_score:
                best_score = score
                best_algo = algo
        lines.append("| " + scenario + " | " + " | ".join(cells) + f" | {best_algo or 'n/a'} |")

    avg_row = ["**Avg Overall**"]
    for algo in algos:
        avg_row.append(f"**{avg_overall_by_algo.get(algo, 0.0):.2f}**")
    winner = rank_order[0] if rank_order else "n/a"
    lines.append("| " + " | ".join(avg_row) + f" | **{winner}** |")

    rank_cells = []
    for algo in algos:
        rank_cells.append(str(rank_order.index(algo) + 1) if algo in rank_order else "n/a")
    lines.append(
        "| **Rank** | " + " | ".join(rank_cells) + " | " + " > ".join(rank_order) + " |"
    )

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    scenarios = [s.strip() for s in args.scenarios.split(",") if s.strip()]
    rows = load_rows(args.raw)

    summary_rows = aggregate_summary(rows, scenarios)
    scored_rows = aggregate_scored(summary_rows, scenarios)
    overall_rows = aggregate_overall(rows)

    summary_columns = [
        "scenario",
        "algorithm",
        "runs",
        "total_requests_sum",
        "forwarded_sum",
        "rejected_sum",
        "success_percent",
        "mean_reject_percent",
        "ci95_reject_percent",
        "mean_effective_rps",
        "ci95_effective_rps",
        "mean_error_percent",
        "ci95_error_percent",
        "mean_avg_proxy_latency_ms",
        "ci95_avg_proxy_latency_ms",
        "mean_p95_proxy_latency_ms",
        "ci95_p95_proxy_latency_ms",
        "mean_p99_proxy_latency_ms",
        "ci95_p99_proxy_latency_ms",
        "mean_expected_reject_percent",
        "mean_stability_score",
        "mean_protection_score",
        "mean_algo_counter_delta",
        "mean_foreign_algo_delta",
    ]
    scored_columns = [
        "scenario",
        "algorithm",
        "runs",
        "stability_score",
        "protection_score",
        "latency_score",
        "overall_score",
        "mean_reject_percent",
        "ci95_reject_percent",
        "mean_error_percent",
        "ci95_error_percent",
        "mean_avg_proxy_latency_ms",
        "ci95_avg_proxy_latency_ms",
        "mean_p95_proxy_latency_ms",
        "ci95_p95_proxy_latency_ms",
        "mean_p99_proxy_latency_ms",
        "ci95_p99_proxy_latency_ms",
        "mean_effective_rps",
        "ci95_effective_rps",
    ]
    overall_columns = [
        "algorithm",
        "runs_all",
        "runs_normal",
        "runs_ddos",
        "mean_avg_latency_all_ms",
        "ci95_avg_latency_all_ms",
        "mean_p95_latency_all_ms",
        "ci95_p95_latency_all_ms",
        "mean_p99_latency_all_ms",
        "ci95_p99_latency_all_ms",
        "mean_avg_latency_ddos_ms",
        "ci95_avg_latency_ddos_ms",
        "success_normal_percent",
        "ci95_success_normal_percent",
        "mean_reject_normal_percent",
        "ci95_reject_normal_percent",
        "mean_reject_ddos_percent",
        "ci95_reject_ddos_percent",
        "mean_error_percent",
        "ci95_error_percent",
        "mean_effective_rps",
        "ci95_effective_rps",
        "mean_foreign_algo_delta",
    ]

    write_csv(args.summary, summary_rows, summary_columns)
    write_csv(args.scored, scored_rows, scored_columns)
    write_csv(args.overall, overall_rows, overall_columns)
    write_markdown(args.markdown, scored_rows, scenarios)

    print("Summary rows:", len(summary_rows))
    print("Scored rows:", len(scored_rows))
    print("Overall rows:", len(overall_rows))


if __name__ == "__main__":
    main()
