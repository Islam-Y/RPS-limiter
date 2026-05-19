# Grafana для новичка: как создать дашборды для RPS‑limiter

Ниже — максимально простой пошаговый план: от запуска Grafana до первых графиков.

## 0. Что нужно заранее
- Сервисы A/B/C и AI должны быть запущены.
- Prometheus и Grafana поднимаются через корневой `docker-compose.yml`.
- Актуальный scrape-конфиг Prometheus находится в `monitoring/prometheus.yml`.
- Базовые дашборды уже провиженятся автоматически из `monitoring/grafana/dashboards`.
- Метрики должны открываться в браузере:
  - Service A: `http://localhost:8080/actuator/prometheus`
  - Service B: `http://localhost:8081/actuator/prometheus`
  - Service C: `http://localhost:8082/actuator/prometheus`
  - AI module: `http://localhost:8083/metrics`

## 1. Запусти Prometheus и Grafana
```bash
docker compose up -d
```
Команду запускайте из корня репозитория (`services/`), где лежит общий `docker-compose.yml`.

Открой Grafana:
```text
http://localhost:3000
```
Логин/пароль по умолчанию: `admin` / `admin`.

## 2. Проверь готовые дашборды
После старта compose в Grafana уже должны быть:
1) `RPS Limiter - Platform Overview`
2) `RPS Limiter - Service C Deep Dive`
3) `RPS Limiter - AI Adaptive Control`

Если нужно создать свои панели поверх готовых, используйте datasource `Prometheus` (он также провиженится автоматически).

Какой дашборд для чего нужен:
- `RPS Limiter - Platform Overview` — общая картина: RPS, 429, Redis, AI requests, базовые AI recommended values.
- `RPS Limiter - Service C Deep Dive` — фактическое состояние limiter: requests by decision, requests by algorithm, current limit/window/capacity/fill rate, текущий алгоритм, applied config и реальные switch counters.
- `RPS Limiter - AI Adaptive Control` — внутреннее состояние AI-модуля: observed/predicted/recommended RPS, selector score, recommended config, active algorithm внутри AI, selector signals и recommendation switches.

### 2.1 Что сейчас считается нормой для adaptive
Для текущего подтвержденного профиля стенда:
- adaptive-пул ограничен `sliding,token`;
- `fixed` должен оставаться доступным только для ручных тестов и benchmark-сравнения, но не должен регулярно появляться в adaptive recommendation counters;
- safe baseline стартует с `TOKEN_TUNER_ENABLED=false`;
- validated mixed-optimized candidate для benchmark / controlled rollout требует `TOKEN_TUNER_ENABLED=true`;
- при включенном tuner должен быть виден noisy entry boost на входе в `token`, а для `ddos`-входа должен удерживаться exit guard до устойчивого recovery;
- по умолчанию стенд стартует в `shadow mode`, поэтому в метриках обычно видно:
  - `ratelimiter_adaptive_apply_enabled = 0`
  - растут только `ratelimiter_adaptive_recommendations_total{mode="shadow"}`
  - `ratelimiter_adaptive_recommendations_total{mode="applied"}` остается `0`, пока явно не включен apply mode.

## 3. Создай свой дашборд (опционально)
1) В левом меню нажми **Dashboards** → **New** → **New Dashboard**.  
2) Нажми **Add visualization** → выбери источник данных **Prometheus**.  
3) Ты попал в редактор панели.

## 4. Первая панель (RPS в rate‑limiter)
В поле запроса вставь:
```promql
sum(rate(ratelimiter_requests_total{job="service-c"}[1m]))
```
Нажми **Run queries** → увидишь график RPS.  

Рекомендации:
- **Visualization**: Time series
- **Unit**: `req/s`
- **Legend**: задай имя серии в поле **Legend** у запроса (например, `RPS`).

## 5. Панель отказов (доля 429)
Показывает долю отклонённых запросов:
```promql
sum(rate(ratelimiter_requests_total{job="service-c",decision="rejected"}[1m]))
/
sum(rate(ratelimiter_requests_total{job="service-c"}[1m]))
```
В **Unit** выбери `percent (0.0-1.0)`.

## 6. Панель p95 задержки (rate‑limiter)
```promql
histogram_quantile(
  0.95,
  sum(rate(ratelimiter_request_duration_seconds_bucket{job="service-c"}[5m])) by (le)
)
```
В **Unit** выбери `seconds (s)`.

## 7. Панели для load‑generator
Текущий RPS:
```promql
loadgen_current_rps{job="service-a"}
```
Ошибки/успехи:
```promql
sum(rate(loadgen_requests_total{job="service-a"}[1m])) by (status)
```
P95 задержки клиента:
```promql
histogram_quantile(
  0.95,
  sum(rate(loadgen_request_duration_seconds_bucket{job="service-a"}[5m])) by (le)
)
```

## 8. Панели для AI‑module
Запросы к AI:
```promql
rate(ai_limit_config_requests_total{job="ai-module"}[1m])
```
Selector score по алгоритмам:
```promql
ai_algorithm_score{job="ai-module"}
```
Burst ratio:
```promql
ai_last_burst_ratio{job="ai-module"}
```
Peak 1s RPS:
```promql
ai_last_peak_rps_1s{job="ai-module"}
```
Рекомендованный лимит:
```promql
ai_last_recommended_limit{job="ai-module"}
```
Предсказанный RPS:
```promql
ai_last_predicted_rps{job="ai-module"}
```
Последний активный алгоритм внутри AI:
```promql
ai_last_algorithm{job="ai-module"}
```
Активные selector signals:
```promql
ai_selector_signal_active{job="ai-module"}
```
Счетчик recommendation switches:
```promql
sum by (mode, from_algorithm, to_algorithm) (increase(ai_recommendation_switch_total{job="ai-module"}[15m]))
```

## 8.1 Панели для adaptive shadow/apply mode
Включён ли auto-apply:
```promql
ratelimiter_adaptive_apply_enabled{job="service-c"}
```
Количество рекомендаций по режимам:
```promql
sum by (mode) (rate(ratelimiter_adaptive_recommendations_total{job="service-c"}[5m]))
```
Общее количество shadow/applied рекомендаций:
```promql
rate(ratelimiter_adaptive_recommendations_total{job="service-c"}[5m])
```
Распределение рекомендаций по алгоритмам и режимам:
```promql
sum by (algorithm, mode) (increase(ratelimiter_adaptive_recommendations_by_algorithm_total{job="service-c"}[15m]))
```
Распределение рекомендаций по алгоритмам только в shadow mode:
```promql
sum by (algorithm) (increase(ratelimiter_adaptive_recommendations_by_algorithm_total{job="service-c",mode="shadow"}[15m]))
```
Распределение рекомендаций по алгоритмам только в apply mode:
```promql
sum by (algorithm) (increase(ratelimiter_adaptive_recommendations_by_algorithm_total{job="service-c",mode="applied"}[15m]))
```
Последняя рекомендация adaptive:
```promql
ratelimiter_adaptive_recommended_algorithm{job="service-c"}
```
Какой лимит рекомендует adaptive:
```promql
ratelimiter_adaptive_recommended_limit{job="service-c"}
```
Какой fill rate рекомендует adaptive:
```promql
ratelimiter_adaptive_recommended_fill_rate{job="service-c"}
```

Практические замечания:
- `ratelimiter_adaptive_recommended_algorithm` показывает только последнюю рекомендацию, а не всю историю переключений;
- для анализа реального поведения adaptive надежнее смотреть в связке:
  - `recommendations_total`
  - `recommendations_by_algorithm_total`
  - `algorithm_switch_total`
  - `config_applied_total`
  - `requests_by_algorithm_total`
  - текущий конфиг через `Service C Deep Dive`;
- если adaptive-профиль выставлен правильно, в counters по алгоритмам `fixed` не должен быть рабочим winner в продовом adaptive-контуре.

## 8.2 Панели для controlled rollout (`ddos -> recovery`)
Если включен `ADAPTIVE_APPLY_RECOMMENDATIONS=true`, для контрольного phased-прогона удобнее всего одновременно открыть:
1) `RPS Limiter - Platform Overview`
2) `RPS Limiter - Service C Deep Dive`
3) `RPS Limiter - AI Adaptive Control`

Минимальный набор панелей для наблюдения:
1) `429 Ratio`
2) `Requests by Algorithm`
3) `Current Algorithm`
4) `Current Limit`
5) `Token Fill Rate`
6) `Config Applies (15m)`
7) `Algorithm Switches (15m)`
8) `AI RPS: Observed vs Predicted vs Recommended`
9) `Selector Signals`
10) `Recommendation Switches`

Если делаешь свой дашборд, добавь такие PromQL:

Фактическая доля алгоритмов в Service C:
```promql
sum(rate(ratelimiter_requests_by_algorithm_total{job="service-c"}[1m])) by (algorithm)
```

Фактический текущий лимит:
```promql
ratelimiter_current_limit{job="service-c"}
```

Фактический fill rate:
```promql
ratelimiter_token_fill_rate{job="service-c"}
```

Фактическая current window:
```promql
ratelimiter_window_seconds{job="service-c"}
```

Фактическая bucket capacity:
```promql
ratelimiter_bucket_capacity{job="service-c"}
```

Фактический текущий алгоритм:
```promql
ratelimiter_current_algorithm{job="service-c"}
```

Сколько раз реально применялся конфиг за окно:
```promql
sum by (source, algorithm) (increase(ratelimiter_config_applied_total{job="service-c"}[15m]))
```
Это счетчик всех apply событий, не только смен алгоритма.

Сколько было реальных алгоритмических переключений:
```promql
sum by (source, from_algorithm, to_algorithm) (increase(ratelimiter_algorithm_switch_total{job="service-c"}[15m]))
```

Что ожидается на успешном `ddos -> recovery` прогоне:
- в фазе `ddos` должен вырасти share `token` в `Requests by Algorithm`;
- в фазе `recovery` контур должен вернуться в `sliding`;
- на хорошем коротком контрольном прогоне последовательность обычно читается как `sliding -> token -> sliding`, без длинной oscillation туда-сюда.

Reference-артефакты:
- baseline до исправления: `monitoring/benchmarks/adaptive-ddos-recovery-soak-20260417-135103.phases.csv`
  - `ddos success = 41.60%`
- консервативный long-soak reference:
  - `monitoring/benchmarks/adaptive-ddos-recovery-soak-20260420-retuned.overall.csv`
  - `monitoring/benchmarks/adaptive-ddos-recovery-soak-20260420-retuned.switch-summary.csv`
  - `ddos success = 96.32%`
  - `recovery success = 100.00%`
  - `weighted p95 latency = 6.966 ms`
  - `switch_count = 2`
  - sequence: `0:sliding|9:token|756:sliding`
- текущий mixed-optimized candidate (`TOKEN_TUNER_ENABLED=true`):
  - `monitoring/benchmarks/adaptive-ddos-recovery-soak-v7-target103-tuneron-20260424.overall.csv`
  - `monitoring/benchmarks/adaptive-ddos-recovery-soak-v7-target103-tuneron-20260424.switch-summary.csv`
  - `ddos success = 97.93%`
  - `recovery success = 100.00%`
  - `weighted p95 latency = 9.351 ms`
  - `switch_count = 2`
  - sequence: `0:sliding|9:token|787:sliding`
- reference mixed benchmark для текущего candidate:
  - `monitoring/benchmarks/adaptive-phase-universal-v7-target103-tuneron-r3-20260424.summary.csv`
  - `adaptive mean success = 92.42%`
  - `static_token mean success = 80.10%`
  - `poisson success = 91.41%`
  - `burst success = 96.23%`
  - `ddos success = 74.48%`
  - `recovery success = 100.00%`

Важно:
- только по одному gauge `ratelimiter_adaptive_recommended_algorithm` нельзя делать вывод, что adaptive действительно переключал контур;
- подтверждение реального переключения ищется по `Requests by Algorithm`, `Current Algorithm`, `Current Limit/Fill Rate`, `ratelimiter_algorithm_switch_total` и counters applied recommendations.
- текущий mixed-optimized candidate лучше подходит для universal mixed и `poisson` onset; если цель — минимальный p95 на чистом long `ddos -> recovery`, `20260420-retuned` остается более быстрым latency reference.

## 9. Как называть и сохранять
1) В редакторе панели поменяй **Title** (например, `Rate limiter RPS`).  
2) Нажми **Apply** (справа сверху).  
3) На дашборде нажми **Save dashboard** и задай имя.

## 10. Базовые правила Prometheus‑метрик
- **Counter** — только растёт. В графике почти всегда используй `rate(...)`.
- **Gauge** — текущее значение. Можно отображать напрямую.
- **Histogram** — для квантилей используй `histogram_quantile(...)`.

## 11. Мини‑чеклист для новичка
- Есть метрики в Prometheus? Открой `http://localhost:9090/targets`
- Видишь метрики в Explore? Начни с `ratelimiter_` или `loadgen_`.
- Нет данных? Проверь, что сервисы запущены и отдаёт `/actuator/prometheus` или `/metrics`.

## 12. Если хочешь красивый дашборд быстро
Создай 5–8 панелей:
1) RPS (rate‑limiter)  
2) Доля 429  
3) P95 latency  
4) Redis connected  
5) Loadgen current RPS  
6) Loadgen errors  
7) AI predicted RPS  
8) Adaptive shadow/applied recommendations

Для adaptive-отладки лучше расширить набор до 10 панелей:
9) Requests by Algorithm
10) Recommended Algorithm / Recommended Fill Rate / Current Fill Rate

Для apply-mode на практике полезнее расширить до 13 панелей:
11) Current Algorithm
12) Config Applies (15m)
13) Algorithm Switches (15m)

Пример Redis availability:
```promql
ratelimiter_redis_connected{job="service-c"}
```
