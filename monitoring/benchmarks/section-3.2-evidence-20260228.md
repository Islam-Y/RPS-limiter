# Доказательная база для 3.2 (прогоны 2026-02-28)

## 1) Полная матрица алгоритмов (статический режим, adaptive=off, duration=15s)

| Scenario | fixed | sliding | token | Winner |
|---|---:|---:|---:|---|
| constant_low | 75.0 (S100/P100/L0) | 96.5 (S100/P100/L86) | 100.0 (S100/P100/L100) | token |
| sinusoidal | 95.7 (S100/P100/L83) | 100.0 (S100/P100/L100) | 75.0 (S100/P100/L0) | sliding |
| poisson | 97.7 (S100/P94/L100) | 86.1 (S100/P97/L50) | 67.8 (S100/P82/L0) | fixed |
| constant_high | 64.2 (S100/P73/L0) | 79.1 (S100/P48/L100) | 59.6 (S100/P46/L25) | sliding |
| burst | 100.0 (S100/P100/L100) | 82.5 (S100/P100/L30) | 75.0 (S100/P100/L0) | fixed |
| ddos | 88.9 (S100/P81/L86) | 84.8 (S100/P62/L100) | 52.7 (S100/P44/L0) | fixed |
| **Avg Overall** | **86.92** | **88.18** | **71.68** | **sliding** |
| **Rank** | 2 | 1 | 3 | sliding > fixed > token |

## 2) Сравнение static vs adaptive (длительные прогоны, duration=70s)

| Scenario | Start Algo | Reject Static % | Reject Adaptive % | Delta p.p. | Eff RPS Static | Eff RPS Adaptive | Foreign Delta (adaptive) |
|---|---|---:|---:|---:|---:|---:|---:|
| constant_high | fixed | 17.39 | 11.06 | -6.33 | 47.89 | 40.57 | 0 |
| constant_high | sliding | 82.54 | 30.55 | -51.99 | 110.44 | 131.44 | 7919 |
| constant_high | token | 21.17 | 36.10 | +14.93 | 111.97 | 132.03 | 2355 |
| ddos | fixed | 24.14 | 36.95 | +12.81 | 67.87 | 147.49 | 0 |
| ddos | sliding | 87.18 | 71.48 | -15.70 | 125.03 | 50.24 | 0 |
| ddos | token | 28.01 | 55.05 | +27.04 | 60.59 | 130.16 | 3956 |

Примечание: `Foreign Delta` > 0 означает, что adaptive-контур переключал алгоритм в ходе теста.
