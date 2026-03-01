# Реальная картина: надёжность и скорость (прогоны 2026-02-28, duration=25s)

Источник данных: `monitoring/benchmarks/battle-matrix-live-static-real-20260228.raw.csv`

## Скорость

| Алгоритм | Avg latency all, ms | Avg latency normal, ms | DDoS latency, ms |
|---|---:|---:|---:|
| fixed | 1.773 | 1.919 | 1.038 |
| sliding | 1.534 | 1.691 | 0.752 |
| token | 1.680 | 1.804 | 1.059 |

## Надёжность

| Алгоритм | Success normal (forwarded/total), % | Avg reject normal, % | DDoS reject, % | Avg error, % |
|---|---:|---:|---:|---:|
| fixed | 89.23 | 7.03 | 26.85 | 0.00 |
| sliding | 65.99 | 23.04 | 73.52 | 0.00 |
| token | 92.08 | 5.23 | 32.67 | 0.00 |

Интерпретация:
1. Самый быстрый: `sliding` (минимальная latency).
2. Самый надёжный для штатного трафика: `token` (максимальный success normal, минимальный reject normal).
3. Самая жёсткая anti-DDoS фильтрация: `sliding` (максимальный reject в `ddos`).
