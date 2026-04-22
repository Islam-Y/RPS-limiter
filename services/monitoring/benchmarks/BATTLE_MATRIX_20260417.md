# Battle Matrix 2026-04-17

Source artifacts:
- `adaptive-phase-universal-tokenexitfix2-20260417-173010.summary.csv`
- `adaptive-phase-battle-tokenexitfix2-20260417-175734.summary.csv`
- `adaptive-ddos-recovery-soak-20260417-162138-tokenexitfix2.phases.csv`

Method: 6 short scenarios from phased benchmarks (`30s`, `3 repeats`) plus a separate long soak sanity check. Protection uses `mean_success_percent`. Latency proxy uses `mean_p95_latency_ms`. Stability uses raw `ci95_success_percent` and `mean_switch_count`; lower is better.

## Scenario Matrix

| Scenario | adaptive | static_token | static_sliding | Protection winner |
|---|---:|---:|---:|---|
| Steady low load | 100.00% / p95 7.484 ms | 100.00% / p95 4.622 ms | 100.00% / p95 3.036 ms | `static_sliding` |
| Poisson noisy overload | 65.47% / p95 6.398 ms | 75.05% / p95 4.474 ms | 20.36% / p95 2.565 ms | `static_token` |
| Burst attack | 79.99% / p95 8.306 ms | 75.23% / p95 8.985 ms | 24.23% / p95 3.704 ms | `adaptive` |
| DDoS attack | 66.00% / p95 8.637 ms | 45.74% / p95 5.993 ms | 10.68% / p95 3.348 ms | `adaptive` |
| Recovery after burst | 100.00% / p95 4.117 ms | 100.00% / p95 3.687 ms | 98.13% / p95 2.542 ms | `static_token` |
| Recovery after DDoS | 100.00% / p95 3.334 ms | 100.00% / p95 2.776 ms | 76.01% / p95 2.587 ms | `static_token` |

## Final Rating

| Algorithm | Protection avg success | Stability avg ci95 | Stability avg switches | Latency avg p95 | Protection rank | Stability rank | Latency rank | Operational note |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| `adaptive` | 85.24% | 7.62 | 1.22 | 6.379 ms | 1 | 3 | 3 | Default for mixed/hostile traffic |
| `static_token` | 82.67% | 0.54 | 0.00 | 5.090 ms | 2 | 1 | 2 | Best conservative static baseline |
| `static_sliding` | 54.90% | 6.17 | 0.00 | 2.964 ms | 3 | 2 | 1 | Latency-only calm traffic niche |

## Long Soak Check

- artifact: `adaptive-ddos-recovery-soak-20260417-162138-tokenexitfix2.phases.csv` / `adaptive-ddos-recovery-soak-20260417-162138-tokenexitfix2.switch-summary.csv`
- ddos success: 91.31%
- recovery success: 100.00%
- switch_count: 4
- sequence: `1:sliding|10:token|624:sliding|716:token|776:sliding`

## Verdict

- `adaptive` wins on protection in mixed/adversarial conditions and is the recommended default for mixed traffic.
- `static_token` remains the best conservative static baseline because it is the most predictable and still strong on protection.
- `static_sliding` wins only on latency proxy; as a universal limiter it loses too much protection.
