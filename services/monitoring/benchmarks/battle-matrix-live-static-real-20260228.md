| Scenario | fixed | sliding | token | Winner |
|---|---:|---:|---:|---|
| constant_low | 75.0 (S100/P100/L0) | 94.1 (S100/P100/L76) | 100.0 (S100/P100/L100) | token |
| sinusoidal | 75.0 (S100/P100/L0) | 100.0 (S100/P100/L100) | 82.7 (S100/P100/L31) | sliding |
| poisson | 97.9 (S100/P95/L100) | 67.8 (S100/P22/L96) | 69.5 (S100/P86/L0) | fixed |
| constant_high | 81.9 (S100/P90/L44) | 70.9 (S100/P27/L100) | 70.2 (S100/P88/L0) | fixed |
| burst | 93.3 (S100/P100/L73) | 100.0 (S100/P100/L100) | 75.0 (S100/P100/L0) | sliding |
| ddos | 75.7 (S100/P98/L7) | 68.2 (S100/P21/L100) | 71.2 (S100/P91/L0) | fixed |
| **Avg Overall** | **83.16** | **83.50** | **78.13** | **sliding** |
| **Rank** | 2 | 1 | 3 | sliding > fixed > token |
