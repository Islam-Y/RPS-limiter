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
