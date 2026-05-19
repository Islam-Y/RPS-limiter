#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Polygon, Rectangle


NAVY = "#18324f"
INK = "#14253d"
BLUE = "#dfeef8"
GREEN = "#e5f3e5"
YELLOW = "#fff4d6"
PINK = "#f8e3ea"
LILAC = "#eee6f7"
GRAY = "#eef1f4"


def configure_axes(ax: plt.Axes, width: float, height: float) -> None:
    ax.set_xlim(0, width)
    ax.set_ylim(0, height)
    ax.axis("off")


def box(
    ax: plt.Axes,
    x: float,
    y: float,
    width: float,
    height: float,
    text: str,
    *,
    fill: str,
    fontsize: int = 14,
    radius: float = 0.18,
    weight: str = "normal",
) -> None:
    patch = FancyBboxPatch(
        (x, y),
        width,
        height,
        boxstyle=f"round,pad=0.03,rounding_size={radius}",
        linewidth=1.7,
        edgecolor=NAVY,
        facecolor=fill,
    )
    ax.add_patch(patch)
    ax.text(
        x + width / 2,
        y + height / 2,
        text,
        ha="center",
        va="center",
        fontsize=fontsize,
        color=INK,
        fontweight=weight,
    )


def arrow(
    ax: plt.Axes,
    start: tuple[float, float],
    end: tuple[float, float],
    *,
    text: str | None = None,
    fontsize: int = 11,
    text_offset: tuple[float, float] = (0.0, 0.0),
    connectionstyle: str = "arc3",
) -> None:
    patch = FancyArrowPatch(
        start,
        end,
        arrowstyle="-|>",
        mutation_scale=15,
        linewidth=1.7,
        color=INK,
        connectionstyle=connectionstyle,
    )
    ax.add_patch(patch)
    if text:
        x = (start[0] + end[0]) / 2 + text_offset[0]
        y = (start[1] + end[1]) / 2 + text_offset[1]
        ax.text(x, y, text, ha="center", va="center", fontsize=fontsize, color=NAVY)


def draw_bucket(ax: plt.Axes, x: float, y: float, *, title: str, leak: bool) -> None:
    ax.text(x + 1.85, y + 3.8, title, ha="center", va="center", fontsize=17, color=INK, fontweight="bold")
    bucket = Polygon(
        [(x + 1.15, y + 1.1), (x + 2.55, y + 1.1), (x + 2.35, y + 2.55), (x + 1.35, y + 2.55)],
        closed=True,
        facecolor=BLUE if not leak else GREEN,
        edgecolor=NAVY,
        linewidth=1.8,
    )
    ax.add_patch(bucket)
    for row in range(3):
        ax.add_patch(Rectangle((x + 1.47, y + 1.35 + row * 0.34), 0.55, 0.2, color="#4c78a8", alpha=0.75))
    ax.text(x + 1.85, y + 0.82, "ёмкость b", ha="center", va="center", fontsize=12, color=INK)
    if leak:
        arrow(ax, (x + 1.85, y + 3.4), (x + 1.85, y + 2.62), text="входной поток", text_offset=(1.05, 0.0))
        arrow(ax, (x + 1.85, y + 1.0), (x + 1.85, y + 0.35), text="выход с\nпостоянной скоростью", text_offset=(1.45, -0.04))
        arrow(ax, (x + 1.12, y + 2.35), (x + 0.35, y + 2.35), text="переполнение ->\nотклонение", text_offset=(-0.05, 0.46))
    else:
        arrow(ax, (x + 1.85, y + 3.4), (x + 1.85, y + 2.62), text="пополнение\nr токенов/с", text_offset=(1.2, 0.0))
        arrow(ax, (x + 0.18, y + 1.85), (x + 1.08, y + 1.85), text="запрос", text_offset=(0.0, 0.42))
        arrow(ax, (x + 2.62, y + 1.85), (x + 3.5, y + 1.85), text="пропуск,\nесли токен есть", text_offset=(0.42, 0.46))


def build_rate_limiting_compare(output_dir: Path) -> Path:
    fig, ax = plt.subplots(figsize=(14, 6))
    configure_axes(ax, 14, 6)
    ax.text(7, 5.45, "Сравнение логики Token Bucket и Leaky Bucket", ha="center", fontsize=20, fontweight="bold")
    draw_bucket(ax, 1.0, 0.6, title="Token Bucket", leak=False)
    draw_bucket(ax, 8.0, 0.6, title="Leaky Bucket", leak=True)
    ax.plot([7, 7], [0.65, 4.85], color="#bcc7d4", linewidth=1.2, linestyle="--")
    out = output_dir / "fig_2_rate_limiting_compare.png"
    fig.tight_layout()
    fig.savefig(out, dpi=180)
    plt.close(fig)
    return out


def build_gateway_architecture(output_dir: Path) -> Path:
    fig, ax = plt.subplots(figsize=(14, 7))
    configure_axes(ax, 14, 7)
    ax.text(7, 6.45, "API-шлюз с контуром ограничения запросов", ha="center", fontsize=20, fontweight="bold")
    box(ax, 0.7, 3.65, 2.3, 1.05, "Клиент /\nинтеграция", fill=BLUE)
    box(ax, 4.0, 3.65, 2.4, 1.05, "API-шлюз", fill=YELLOW, weight="bold")
    box(ax, 10.2, 3.65, 2.55, 1.05, "Целевой API", fill=GREEN)
    box(ax, 4.0, 1.55, 2.4, 1.05, "Политика\nлимитирования", fill=PINK)
    box(ax, 7.15, 1.55, 2.15, 1.05, "Redis:\nсчётчики и окна", fill=LILAC)
    box(ax, 10.2, 1.55, 2.55, 1.05, "Метрики:\n429, задержка", fill=GRAY)
    arrow(ax, (3.0, 4.18), (4.0, 4.18), text="HTTP-запрос", text_offset=(0, 0.34))
    arrow(ax, (6.4, 4.18), (10.2, 4.18), text="пропуск или 429", text_offset=(0, 0.34))
    arrow(ax, (5.2, 3.65), (5.2, 2.6), text="проверка\nлимита", text_offset=(0.82, 0))
    arrow(ax, (6.4, 2.08), (7.15, 2.08), text="состояние", text_offset=(0, 0.34))
    arrow(ax, (11.45, 3.65), (11.45, 2.6), text="наблюдение", text_offset=(1.1, 0))
    arrow(
        ax,
        (9.3, 2.08),
        (10.2, 2.08),
        text="агрегация",
        text_offset=(0, 0.34),
    )
    ax.text(
        7,
        0.6,
        "Схема показывает именно исследуемый контур: точка входа, лимитер, состояние и наблюдаемость.",
        ha="center",
        fontsize=12,
        color=NAVY,
    )
    out = output_dir / "fig_3_api_gateway_wikimedia.png"
    fig.tight_layout()
    fig.savefig(out, dpi=180)
    plt.close(fig)
    return out


def build_results_structure(output_dir: Path) -> Path:
    fig, ax = plt.subplots(figsize=(16, 8))
    configure_axes(ax, 16, 8)
    ax.text(8, 7.45, "Структура обработки экспериментальных результатов", ha="center", fontsize=20, fontweight="bold")
    box(
        ax,
        0.55,
        5.05,
        3.45,
        1.65,
        "Сценарии нагрузки\nнизкая постоянная\nсинусоидальная / Пуассон\nвсплеск / DDoS",
        fill=BLUE,
        fontsize=13,
    )
    box(
        ax,
        5.1,
        5.22,
        3.7,
        1.3,
        "Сырые CSV-данные\nвсего / пропущено / отклонено\nзадержка, ошибки",
        fill=YELLOW,
        fontsize=13,
    )
    box(
        ax,
        10.05,
        5.05,
        4.55,
        1.65,
        "Агрегация результатов\nсводка, общая статистика, CI95\nповторы = 10",
        fill=GREEN,
        fontsize=13,
    )
    box(ax, 5.1, 2.85, 3.7, 1.25, "Таблицы раздела 3.2\nскорость / надёжность", fill=LILAC, fontsize=13)
    box(
        ax,
        10.05,
        2.85,
        4.55,
        1.25,
        "PNG-графики\nзадержка / надёжность\nтепловая карта / адаптивный режим",
        fill=PINK,
        fontsize=13,
    )
    box(
        ax,
        5.1,
        0.7,
        9.5,
        1.05,
        "Интерпретация: выбор политики по измеренным метрикам,\nа не по одному итоговому показателю",
        fill=GRAY,
        fontsize=13,
    )
    arrow(ax, (4.0, 5.88), (5.1, 5.88))
    arrow(ax, (8.8, 5.88), (10.05, 5.88))
    arrow(ax, (6.95, 5.22), (6.95, 4.1))
    arrow(ax, (12.33, 5.05), (12.33, 4.1))
    arrow(ax, (6.95, 2.85), (6.95, 1.75))
    arrow(ax, (12.33, 2.85), (12.33, 1.75))
    ax.text(2.28, 4.55, "скрипт прогонов", ha="center", fontsize=11, color=NAVY)
    ax.text(12.33, 4.55, "скрипт построения графиков", ha="center", fontsize=11, color=NAVY)
    out = output_dir / "fig_4_results_structure.png"
    fig.tight_layout()
    fig.savefig(out, dpi=180)
    plt.close(fig)
    return out


def build_experiment_stand(output_dir: Path) -> Path:
    fig, ax = plt.subplots(figsize=(16, 8))
    configure_axes(ax, 16, 8)
    ax.text(8, 7.45, "Схема экспериментального стенда RPS-limiter", ha="center", fontsize=20, fontweight="bold")
    box(ax, 0.65, 4.65, 3.25, 1.25, "Генератор нагрузки\nсценарии нагрузки", fill=BLUE, fontsize=13)
    box(ax, 5.45, 4.65, 3.5, 1.25, "Сервис лимитирования\nFixed / Sliding / Token", fill=YELLOW, fontsize=13)
    box(ax, 11.2, 4.65, 3.25, 1.25, "Целевой сервис\nобработка запросов", fill=GREEN, fontsize=13)
    box(ax, 1.15, 2.1, 3.25, 1.25, "Аналитический модуль\nрекомендации режима", fill=LILAC, fontsize=13)
    box(ax, 5.45, 2.1, 3.5, 1.25, "Redis\nсостояние лимитов", fill=PINK, fontsize=13)
    box(ax, 11.2, 2.1, 3.25, 1.25, "Prometheus + Grafana\nметрики и дашборды", fill=GRAY, fontsize=13)
    arrow(ax, (3.9, 5.28), (5.45, 5.28), text="HTTP / RPS", text_offset=(0, 0.33))
    arrow(ax, (8.95, 5.28), (11.2, 5.28), text="пропущенные\nзапросы", text_offset=(0, 0.45))
    arrow(ax, (7.2, 4.65), (7.2, 3.35), text="состояние", text_offset=(0.82, 0))
    arrow(ax, (12.82, 4.65), (12.82, 3.35), text="/actuator", text_offset=(0.8, 0))
    arrow(ax, (4.4, 2.74), (5.45, 4.65), text="рекомендация\nрежима", text_offset=(-0.58, 0.12))
    arrow(ax, (8.95, 2.74), (11.2, 2.74), text="сбор /\nвизуализация", text_offset=(0, 0.46))
    arrow(
        ax,
        (7.2, 4.65),
        (4.4, 3.0),
        text="телеметрия",
        text_offset=(0.18, -0.15),
        connectionstyle="arc3,rad=0.0",
    )
    ax.text(
        8,
        0.65,
        "Стенд воспроизводит сервисы проекта, управляющий контур и измерение реальных метрик.",
        ha="center",
        fontsize=12,
        color=NAVY,
    )
    out = output_dir / "fig_5_experiment_stand.png"
    fig.tight_layout()
    fig.savefig(out, dpi=180)
    plt.close(fig)
    return out


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate dissertation diagrams with Russian labels.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("monitoring/benchmarks/figures-ci-20260228"),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    generated = [
        build_rate_limiting_compare(args.output_dir),
        build_gateway_architecture(args.output_dir),
        build_results_structure(args.output_dir),
        build_experiment_stand(args.output_dir),
    ]
    print("Generated diagrams:")
    for path in generated:
        print(path)


if __name__ == "__main__":
    main()
