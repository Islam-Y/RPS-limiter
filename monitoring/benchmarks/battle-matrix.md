| Scenario | fixed | sliding | token | Winner |
|---|---:|---:|---:|---|
| constant_low | 75.0 (S100/P100/L0) | 100.0 (S100/P100/L100) | 83.1 (S100/P100/L32) | sliding |
| sinusoidal | 100.0 (S100/P100/L100) | 75.0 (S100/P100/L0) | 92.2 (S100/P100/L69) | fixed |
| poisson | 65.9 (S100/P77/L0) | 87.5 (S100/P69/L100) | 76.0 (S100/P75/L44) | sliding |
| constant_high | 62.5 (S100/P40/L46) | 59.0 (S100/P60/L0) | 88.8 (S100/P72/L100) | token |
| burst | 86.0 (S100/P100/L44) | 75.0 (S100/P100/L0) | 100.0 (S100/P100/L100) | token |
| ddos | 72.6 (S100/P77/L28) | 96.5 (S100/P91/L100) | 66.0 (S100/P77/L0) | sliding |
| **Avg Overall** | **77.00** | **82.15** | **84.34** | **token** |
| **Rank** | 3 | 2 | 1 | token > sliding > fixed |
