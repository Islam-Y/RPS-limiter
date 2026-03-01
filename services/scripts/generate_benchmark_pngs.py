#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


ALGO_ORDER = ["fixed", "token", "sliding"]
SCENARIO_ORDER = [
    "constant_low",
    "sinusoidal",
    "poisson",
    "constant_high",
    "burst",
    "ddos",
]


def ordered(series: pd.Series, order: list[str]) -> pd.Series:
    return pd.Categorical(series, categories=order, ordered=True)


def annotate_bars(ax: plt.Axes, bars, fmt: str = "{:.2f}") -> None:
    for bar in bars:
        height = bar.get_height()
        ax.annotate(
            fmt.format(height),
            (bar.get_x() + bar.get_width() / 2.0, height),
            textcoords="offset points",
            xytext=(0, 4),
            ha="center",
            fontsize=8,
        )


def build_speed_plot(raw: pd.DataFrame, output_dir: Path) -> Path:
    lat_all = raw.groupby("algorithm", as_index=False)["avg_proxy_latency_ms"].mean()
    lat_ddos = raw.loc[raw["scenario"] == "ddos", ["algorithm", "avg_proxy_latency_ms"]].rename(
        columns={"avg_proxy_latency_ms": "ddos_latency_ms"}
    )
    df = lat_all.merge(lat_ddos, on="algorithm", how="left")
    df["algorithm"] = ordered(df["algorithm"], ALGO_ORDER)
    df = df.sort_values("algorithm")

    x = np.arange(len(df))
    width = 0.35

    fig, ax = plt.subplots(figsize=(10, 5))
    bars_all = ax.bar(x - width / 2, df["avg_proxy_latency_ms"], width, label="Avg latency (all scenarios)")
    bars_ddos = ax.bar(x + width / 2, df["ddos_latency_ms"], width, label="Latency in DDoS")

    annotate_bars(ax, bars_all, "{:.3f}")
    annotate_bars(ax, bars_ddos, "{:.3f}")

    ax.set_title("Figure 3.2a. Speed: proxy latency by algorithm")
    ax.set_ylabel("Latency, ms")
    ax.set_xticks(x)
    ax.set_xticklabels(df["algorithm"])
    ax.grid(axis="y", linestyle="--", alpha=0.4)
    ax.legend()

    fig.tight_layout()
    out = output_dir / "fig_3_2a_speed_latency.png"
    fig.savefig(out, dpi=180)
    plt.close(fig)
    return out


def build_reliability_plot(raw: pd.DataFrame, output_dir: Path) -> Path:
    normal = raw.loc[raw["scenario"] != "ddos"].copy()
    agg = (
        normal.groupby("algorithm", as_index=False)
        .agg(forwarded=("forwarded", "sum"), total=("total_requests", "sum"))
        .assign(success_normal_percent=lambda d: 100.0 * d["forwarded"] / d["total"])
    )
    ddos = raw.loc[raw["scenario"] == "ddos", ["algorithm", "reject_percent"]].rename(
        columns={"reject_percent": "reject_ddos_percent"}
    )
    df = agg.merge(ddos, on="algorithm", how="left")
    df["algorithm"] = ordered(df["algorithm"], ALGO_ORDER)
    df = df.sort_values("algorithm")

    x = np.arange(len(df))
    width = 0.35

    fig, ax = plt.subplots(figsize=(10, 5))
    bars_success = ax.bar(
        x - width / 2,
        df["success_normal_percent"],
        width,
        label="Success in normal traffic",
    )
    bars_ddos = ax.bar(
        x + width / 2,
        df["reject_ddos_percent"],
        width,
        label="Reject in DDoS",
    )

    annotate_bars(ax, bars_success)
    annotate_bars(ax, bars_ddos)

    ax.set_title("Figure 3.2b. Reliability split: normal success vs DDoS filtering")
    ax.set_ylabel("Percent, %")
    ax.set_xticks(x)
    ax.set_xticklabels(df["algorithm"])
    ax.set_ylim(0, 100)
    ax.grid(axis="y", linestyle="--", alpha=0.4)
    ax.legend()

    fig.tight_layout()
    out = output_dir / "fig_3_2b_reliability_split.png"
    fig.savefig(out, dpi=180)
    plt.close(fig)
    return out


def build_heatmap_plot(raw: pd.DataFrame, output_dir: Path) -> Path:
    pivot = raw.pivot_table(
        index="scenario",
        columns="algorithm",
        values="reject_percent",
        aggfunc="mean",
    )
    pivot = pivot.reindex(index=SCENARIO_ORDER, columns=ALGO_ORDER)

    fig, ax = plt.subplots(figsize=(9, 5))
    im = ax.imshow(pivot.values, cmap="YlOrRd", aspect="auto", vmin=0, vmax=100)
    cbar = fig.colorbar(im, ax=ax)
    cbar.set_label("Reject, %")

    ax.set_title("Figure 3.2c. Reject rate by scenario and algorithm")
    ax.set_xticks(np.arange(len(pivot.columns)))
    ax.set_xticklabels(pivot.columns)
    ax.set_yticks(np.arange(len(pivot.index)))
    ax.set_yticklabels(pivot.index)

    for i in range(len(pivot.index)):
        for j in range(len(pivot.columns)):
            value = pivot.values[i, j]
            ax.text(j, i, f"{value:.1f}", ha="center", va="center", fontsize=8, color="black")

    fig.tight_layout()
    out = output_dir / "fig_3_2c_reject_heatmap.png"
    fig.savefig(out, dpi=180)
    plt.close(fig)
    return out


def build_adaptive_plot(adaptive: pd.DataFrame, output_dir: Path) -> Path:
    adaptive = adaptive.copy()
    # Support both legacy joined schema and CI-based joined schema.
    if "reject_delta_pp" in adaptive.columns:
        delta_col = "reject_delta_pp"
        ci_col = None
    elif "reject_delta_pp_mean" in adaptive.columns:
        delta_col = "reject_delta_pp_mean"
        ci_col = "reject_delta_pp_ci95" if "reject_delta_pp_ci95" in adaptive.columns else None
    elif "reject_adaptive_mean" in adaptive.columns and "reject_static_mean" in adaptive.columns:
        adaptive["reject_delta_pp"] = adaptive["reject_adaptive_mean"] - adaptive["reject_static_mean"]
        delta_col = "reject_delta_pp"
        ci_col = None
    else:
        raise ValueError("Adaptive CSV schema is unsupported: no reject delta columns found")

    adaptive["scenario"] = ordered(adaptive["scenario"], ["constant_high", "ddos"])
    adaptive["algorithm"] = ordered(adaptive["algorithm"], ALGO_ORDER)
    adaptive = adaptive.sort_values(["scenario", "algorithm"])
    adaptive["label"] = adaptive["scenario"].astype(str) + "\n" + adaptive["algorithm"].astype(str)

    colors = ["#2ca02c" if v < 0 else "#d62728" for v in adaptive[delta_col]]

    fig, ax = plt.subplots(figsize=(11, 5))
    yerr = adaptive[ci_col] if ci_col else None
    bars = ax.bar(adaptive["label"], adaptive[delta_col], color=colors, yerr=yerr, capsize=4)
    annotate_bars(ax, bars)

    ax.axhline(0, color="black", linewidth=1)
    ax.set_title("Figure 3.2d. Adaptive mode effect on reject (delta, p.p.)")
    ax.set_ylabel("Delta reject, p.p. (adaptive - static)")
    ax.grid(axis="y", linestyle="--", alpha=0.4)

    fig.tight_layout()
    out = output_dir / "fig_3_2d_adaptive_delta.png"
    fig.savefig(out, dpi=180)
    plt.close(fig)
    return out


def write_readme(output_dir: Path, generated: list[Path], raw_csv: Path, adaptive_csv: Path) -> Path:
    readme = output_dir / "README.md"
    lines = [
        "# Benchmark figures for dissertation section 3.2",
        "",
        f"- Source raw CSV: `{raw_csv}`",
        f"- Source adaptive CSV: `{adaptive_csv}`",
        "",
        "Generated PNG files:",
    ]
    for path in generated:
        lines.append(f"- `{path.name}`")
    readme.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return readme


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate PNG charts from benchmark CSV files.")
    parser.add_argument(
        "--raw-csv",
        type=Path,
        default=Path("monitoring/benchmarks/battle-matrix-ci-real-20260228.raw.csv"),
    )
    parser.add_argument(
        "--adaptive-csv",
        type=Path,
        default=Path("monitoring/benchmarks/adaptive-compare-joined-ci-20260228.csv"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("monitoring/benchmarks/figures-ci-20260228"),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    raw_csv = args.raw_csv
    adaptive_csv = args.adaptive_csv
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    raw = pd.read_csv(raw_csv)
    adaptive = pd.read_csv(adaptive_csv)

    generated = [
        build_speed_plot(raw, output_dir),
        build_reliability_plot(raw, output_dir),
        build_heatmap_plot(raw, output_dir),
        build_adaptive_plot(adaptive, output_dir),
    ]
    readme = write_readme(output_dir, generated, raw_csv, adaptive_csv)

    print("Generated files:")
    for path in generated + [readme]:
        print(path)


if __name__ == "__main__":
    main()
