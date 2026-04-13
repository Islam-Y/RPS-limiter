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
    "phase_universal_mix": "Universal Mixed Load",
}
MODE_LABELS = {
    "static_token": "Static Token",
    "adaptive": "Adaptive",
    "static_sliding": "Static Sliding",
}
MODE_ORDER = ["static_token", "adaptive", "static_sliding"]
PHASE_ORDER = ["normal", "attack", "recovery"]
PHASE_LABELS = {
    "normal": "Normal",
    "attack": "Attack",
    "recovery": "Recovery",
    "steady": "Steady",
    "poisson": "Poisson",
    "burst": "Burst",
    "ddos": "DDoS",
}
ALGO_VALUES = {"token": 1, "sliding": 2, "fixed": 0, "unknown": -1}
PHASE_COLORS = {
    "normal": "#d9edf7",
    "steady": "#d9edf7",
    "poisson": "#fcf8e3",
    "attack": "#f2dede",
    "burst": "#f9d5a7",
    "ddos": "#f2b8b5",
    "recovery": "#dff0d8",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate phased adaptive benchmark PNGs.")
    parser.add_argument("--summary-csv", required=True, type=Path)
    parser.add_argument("--timeline-csv", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    return parser.parse_args()


def ordered_index(value: str, order: list[str]) -> tuple[int, str]:
    try:
        return (order.index(value), value)
    except ValueError:
        return (len(order), value)


def scenario_order(summary: pd.DataFrame) -> list[str]:
    scenarios = sorted(summary["scenario"].unique(), key=lambda value: ordered_index(value, list(SCENARIO_LABELS)))
    return scenarios


def phase_order(subset: pd.DataFrame) -> list[str]:
    phase_rows = subset[["phase_name", "phase_order"]].drop_duplicates().sort_values(["phase_order", "phase_name"])
    return phase_rows["phase_name"].tolist()


def build_phase_reject_plot(summary: pd.DataFrame, output_dir: Path) -> Path:
    summary = summary.copy()
    summary["mode"] = pd.Categorical(summary["mode"], categories=MODE_ORDER, ordered=True)
    summary = summary.sort_values(["scenario", "phase_order", "mode"])
    scenarios = scenario_order(summary)

    fig, axes = plt.subplots(1, len(scenarios), figsize=(6.5 * len(scenarios), 5), sharey=True)
    if len(scenarios) == 1:
        axes = [axes]
    bar_width = 0.22

    for axis, scenario in zip(axes, scenarios):
        subset = summary.loc[summary["scenario"] == scenario]
        phases = phase_order(subset)
        x_positions = range(len(phases))
        for index, mode in enumerate(MODE_ORDER):
            mode_subset = subset.loc[subset["mode"] == mode].set_index("phase_name").reindex(phases)
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
        axis.set_title(SCENARIO_LABELS.get(scenario, scenario))
        axis.set_xticks(list(x_positions))
        axis.set_xticklabels([PHASE_LABELS.get(phase, phase) for phase in phases])
        axis.grid(axis="y", linestyle="--", alpha=0.4)
        axis.set_ylim(0, 100)

    axes[0].set_ylabel("Reject, %")
    axes[-1].legend(loc="upper right")
    fig.suptitle("Figure 3.2d. Phased comparison: reject by mode and phase", y=1.02)
    fig.tight_layout()
    out = output_dir / "fig_3_2d_phase_reject.png"
    fig.savefig(out, dpi=180, bbox_inches="tight")
    plt.close(fig)
    return out


def build_timeline_plot(timeline: pd.DataFrame, output_dir: Path) -> Path:
    adaptive = timeline.loc[timeline["mode"] == "adaptive"].copy()
    adaptive = adaptive.sort_values(["scenario", "repeat", "elapsed_seconds"])
    scenarios = scenario_order(adaptive)
    fig, axes = plt.subplots(len(scenarios), 1, figsize=(12, 3 * len(scenarios)), sharex=False)
    if len(scenarios) == 1:
        axes = [axes]

    for axis, scenario in zip(axes, scenarios):
        subset = adaptive.loc[adaptive["scenario"] == scenario]
        if subset.empty:
            continue
        repeat = subset["repeat"].min()
        run = subset.loc[subset["repeat"] == repeat].copy()
        run["algorithm_value"] = run["algorithm"].map(ALGO_VALUES).fillna(-1)
        axis.step(run["elapsed_seconds"], run["algorithm_value"], where="post", linewidth=2)
        phase_spans = []
        current_phase = None
        start_second = 0
        last_second = 0
        for row in run.itertuples(index=False):
            elapsed = int(row.elapsed_seconds)
            if current_phase is None:
                current_phase = row.phase_name
                start_second = elapsed
            elif row.phase_name != current_phase:
                phase_spans.append((current_phase, start_second, elapsed))
                current_phase = row.phase_name
                start_second = elapsed
            last_second = elapsed
        if current_phase is not None:
            phase_spans.append((current_phase, start_second, last_second + 1))
        for phase_name, start, end in phase_spans:
            axis.axvspan(start, end, color=PHASE_COLORS.get(phase_name, "#eeeeee"), alpha=0.35)
        axis.set_title(f"{SCENARIO_LABELS.get(scenario, scenario)} (adaptive, repeat {int(repeat)})")
        y_ticks = sorted({value for value in run["algorithm_value"].tolist() if value >= 0})
        if not y_ticks:
            y_ticks = [1, 2]
        axis.set_yticks(y_ticks)
        reverse_algo_values = {value: name for name, value in ALGO_VALUES.items()}
        axis.set_yticklabels([reverse_algo_values.get(value, str(value)) for value in y_ticks])
        axis.set_ylim(min(y_ticks) - 0.5, max(y_ticks) + 0.5)
        axis.grid(axis="x", linestyle="--", alpha=0.4)
        axis.set_xlabel("Elapsed time, s")

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
