#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd


SCENARIO_LABELS = {
    "phase_burst_recovery": "Burst -> Recovery",
    "phase_ddos_recovery": "DDoS -> Recovery",
}
MODE_LABELS = {
    "static_token": "Static Token",
    "adaptive": "Adaptive",
    "static_sliding": "Static Sliding",
}
MODE_ORDER = ["static_token", "adaptive", "static_sliding"]
PHASE_ORDER = ["normal", "attack", "recovery"]
ALGO_VALUES = {"token": 1, "sliding": 2, "fixed": 0, "unknown": -1}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate phased adaptive benchmark PNGs.")
    parser.add_argument("--summary-csv", required=True, type=Path)
    parser.add_argument("--timeline-csv", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    return parser.parse_args()


def build_phase_reject_plot(summary: pd.DataFrame, output_dir: Path) -> Path:
    summary = summary.copy()
    summary["mode"] = pd.Categorical(summary["mode"], categories=MODE_ORDER, ordered=True)
    summary["phase_name"] = pd.Categorical(summary["phase_name"], categories=PHASE_ORDER, ordered=True)
    summary = summary.sort_values(["scenario", "phase_name", "mode"])

    fig, axes = plt.subplots(1, 2, figsize=(13, 5), sharey=True)
    bar_width = 0.22
    x_positions = range(len(PHASE_ORDER))

    for axis, scenario in zip(axes, SCENARIO_LABELS):
        subset = summary.loc[summary["scenario"] == scenario]
        for index, mode in enumerate(MODE_ORDER):
            mode_subset = subset.loc[subset["mode"] == mode].set_index("phase_name").reindex(PHASE_ORDER)
            offset = (index - 1) * bar_width
            bars = axis.bar(
                [x + offset for x in x_positions],
                mode_subset["mean_reject_percent"],
                width=bar_width,
                yerr=mode_subset["ci95_reject_percent"],
                capsize=4,
                label=MODE_LABELS[mode],
            )
            for bar, value in zip(bars, mode_subset["mean_reject_percent"]):
                axis.annotate(
                    f"{value:.1f}",
                    (bar.get_x() + bar.get_width() / 2.0, bar.get_height()),
                    textcoords="offset points",
                    xytext=(0, 4),
                    ha="center",
                    fontsize=8,
                )
        axis.set_title(SCENARIO_LABELS[scenario])
        axis.set_xticks(list(x_positions))
        axis.set_xticklabels(["Normal", "Attack", "Recovery"])
        axis.grid(axis="y", linestyle="--", alpha=0.4)
        axis.set_ylim(0, 100)

    axes[0].set_ylabel("Reject, %")
    axes[1].legend(loc="upper right")
    fig.suptitle("Figure 3.2d. Phased comparison: reject by mode and phase", y=1.02)
    fig.tight_layout()
    out = output_dir / "fig_3_2d_phase_reject.png"
    fig.savefig(out, dpi=180, bbox_inches="tight")
    plt.close(fig)
    return out


def build_timeline_plot(timeline: pd.DataFrame, output_dir: Path) -> Path:
    adaptive = timeline.loc[timeline["mode"] == "adaptive"].copy()
    adaptive = adaptive.sort_values(["scenario", "repeat", "elapsed_seconds"])
    fig, axes = plt.subplots(2, 1, figsize=(12, 6), sharex=True)

    for axis, scenario in zip(axes, SCENARIO_LABELS):
        subset = adaptive.loc[adaptive["scenario"] == scenario]
        if subset.empty:
            continue
        repeat = subset["repeat"].min()
        run = subset.loc[subset["repeat"] == repeat].copy()
        run["algorithm_value"] = run["algorithm"].map(ALGO_VALUES).fillna(-1)
        axis.step(run["elapsed_seconds"], run["algorithm_value"], where="post", linewidth=2)
        axis.axvspan(0, 30, color="#d9edf7", alpha=0.35)
        axis.axvspan(30, 60, color="#f2dede", alpha=0.35)
        axis.axvspan(60, 90, color="#dff0d8", alpha=0.35)
        axis.set_title(f"{SCENARIO_LABELS[scenario]} (adaptive, repeat {int(repeat)})")
        axis.set_yticks([1, 2])
        axis.set_yticklabels(["token", "sliding"])
        axis.set_ylim(0.5, 2.5)
        axis.grid(axis="x", linestyle="--", alpha=0.4)

    axes[-1].set_xlabel("Elapsed time, s")
    fig.suptitle("Figure 3.2e. Adaptive algorithm timeline across phases", y=1.02)
    fig.tight_layout()
    out = output_dir / "fig_3_2e_adaptive_timeline.png"
    fig.savefig(out, dpi=180, bbox_inches="tight")
    plt.close(fig)
    return out


def write_readme(output_dir: Path, files: list[Path], summary_csv: Path, timeline_csv: Path) -> Path:
    path = output_dir / "README.md"
    lines = [
        "# Adaptive phased benchmark figures",
        "",
        f"- Summary CSV: `{summary_csv}`",
        f"- Timeline CSV: `{timeline_csv}`",
        "",
        "Generated figures:",
    ]
    for file in files:
        lines.append(f"- `{file.name}`")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    summary = pd.read_csv(args.summary_csv)
    timeline = pd.read_csv(args.timeline_csv)

    generated = [
        build_phase_reject_plot(summary, args.output_dir),
        build_timeline_plot(timeline, args.output_dir),
    ]
    readme = write_readme(args.output_dir, generated, args.summary_csv, args.timeline_csv)

    print("Generated files:")
    for path in generated + [readme]:
        print(path)


if __name__ == "__main__":
    main()
