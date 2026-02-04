# Specification — платформа RPS‑limiter (Service A/B/C + AI)

## 1. Общий обзор и назначение
Платформа предназначена для исследования устойчивости сервисов под нагрузкой и сравнительного анализа алгоритмов rate limiting. Система состоит из генератора нагрузки (Service A), прокси‑лимитера (Service C), целевого сервиса (Service B) и опционального интеллектуального модуля (AI), который предлагает адаптивные настройки лимитов.

## 2. Состав и роли компонентов
- **Service A (load‑generator)** — генерирует HTTP‑нагрузку по заданному профилю.
- **Service B (application‑service)** — целевой сервис, на котором измеряются метрики устойчивости.
- **Service C (rate‑limiter)** — прокси между A и B, применяет алгоритмы лимитирования, хранит состояние в Redis.
- **AI‑module** — прогнозирует нагрузку и выдаёт рекомендации по конфигурации лимитов.
- **Redis** — хранилище счётчиков/токенов и конфигурации лимитера.
- **Prometheus/Grafana** — мониторинг и визуализация.

## 3. Взаимодействие
1) Service A отправляет трафик в Service C.
2) Service C принимает решение: пропустить в B или отклонить (429).
3) Service C хранит состояние лимитов в Redis.
4) (Опционально) Service C периодически обращается к AI‑module за рекомендациями.
5) Метрики всех сервисов собираются Prometheus.

## 4. API (сводно)
### Service A (load‑generator)
- `POST /test/start` — запуск теста.
- `POST /test/stop` — остановка.
- `GET /test/status` — статус.
- `GET /actuator/health`, `GET /actuator/prometheus`.

#### Формат TestConfig
```json
{
  "targetUrl": "http://rate-limiter-service:8082/api/test",
  "duration": "PT60S",
  "profile": {
    "type": "constant",
    "params": { "rps": 100 }
  },
  "concurrency": 50
}
```
- `duration`: число (сек), строка с единицами (`ms/s/m/h/d`) или ISO‑8601 (`PT30S`).
- Для локального тестирования рекомендуется ISO‑8601 формат (`PT30S`/`PT60S`).
- `profile.type`: `constant|burst|sinusoidal|poisson|ddos`.
- `concurrency`: ограничение параллельных запросов.
- Метод запроса фиксирован (GET), тело не используется.

### Service B (application‑service)
- `GET /api/test` → `200 OK`.
- `GET /actuator/health`.
- `GET /actuator/prometheus`.

### Service C (rate‑limiter)
- Прокси‑эндпоинт: `/**`, методы GET/POST/PUT/DELETE/PATCH/HEAD/OPTIONS.
- `POST /config/limits` — применить конфигурацию.
- `GET /config/limits` — получить конфигурацию.
- `POST /config/algorithm` — переключить алгоритм.

#### Формат конфигурации лимитов
```json
{
  "algorithm": "fixed|sliding|token",
  "limit": 100,
  "window": 60,
  "capacity": 200,
  "fillRate": 50
}
```
- `token_bucket` и `token-bucket` поддерживаются как alias для `token`.
- Для `fixed`/`sliding` обязательны `limit` и `window`.
- Для `token` обязательны `capacity` и `fillRate`.
- `burst` поддерживается как alias к `capacity`.

### AI‑module
- `POST /v1/limit-config` — рекомендация по лимитам.
- `GET /health`.
- `GET /metrics`.

#### Формат запроса к AI‑module
```json
{
  "timestamp": "2026-02-04T18:00:00Z",
  "observedRps": 120.5,
  "rejectedRate": 0.12,
  "latencyP95": 0.45,
  "errors5xx": 2,
  "currentConfig": {
    "algorithm": "fixed",
    "limit": 100,
    "window": 60
  }
}
```
- `timestamp`: рекомендуется ISO‑8601 (`2026-02-04T18:00:00Z`) или Unix epoch в секундах.

#### Формат ответа AI‑module
```json
{
  "algorithm": "fixed",
  "limit": 120,
  "window": 60,
  "predictedRps": 132.0,
  "validFor": 60
}
```

## 5. Алгоритмы rate limiting
- **Fixed Window** — счётчик запросов в фиксированном окне. Простая реализация, возможен «эффект границы окна».
- **Sliding Window** — сглаживание на основе текущего и предыдущего окна (взвешенная оценка).
- **Token Bucket** — допускает краткие bursts до `capacity`, средняя скорость `fillRate`.

## 6. Адаптивный режим
- Service C периодически отправляет телеметрию в AI‑module.
- AI‑module прогнозирует нагрузку и рекомендует изменения.
- При недоступности AI Service C продолжает с последними лимитами.
- Ограничения на частоту изменений: минимальный интервал и порог изменения.

## 7. Конфигурация (ключевые параметры)
### Service A
- `loadgen.tick`, `loadgen.log-interval`, `loadgen.http.*`, `loadgen.default-concurrency`, `loadgen.config-file`.

### Service B
- `app.processing-delay-ms`, `server.port`.

### Service C
- `ratelimiter.target-url`, `ratelimiter.algorithm`, `ratelimiter.limit`, `ratelimiter.window-seconds`,
  `ratelimiter.capacity`, `ratelimiter.fill-rate`, `ratelimiter.fail-open`.
- `ratelimiter.redis-health-interval`, `ratelimiter.config-refresh-interval`.
- `ratelimiter.bounds.*` (ограничения значений).
- `ratelimiter.adaptive.*` (URL, interval, timeout, enabled).

### AI‑module (ENV)
- `HISTORY_WINDOW_SECONDS`, `MAX_HISTORY_POINTS`, `MIN_HISTORY_POINTS`, `FORECAST_SECONDS`.
- `MIN_CHANGE_INTERVAL_SECONDS`, `MIN_RELATIVE_CHANGE`.
- `MIN_RPS`, `MAX_RPS`, `REJECTED_RATE_THRESHOLD`, `LATENCY_P95_THRESHOLD`, `ERRORS_5XX_THRESHOLD`.
- `ALLOW_ALGO_SWITCH`, `MIN_ALGO_SWITCH_INTERVAL_SECONDS`.
- `BURSTINESS_THRESHOLD`, `BURSTINESS_POINTS`.
- `TOKEN_MIN_HOLD_SECONDS`, `TOKEN_EXIT_NON_BURST_STREAK`, `MIN_TOKEN_FILL_RATE`.

## 8. Метрики
### Service A
- `loadgen_requests_total{status="success|rate_limited|error"}`
- `loadgen_request_duration_seconds_*`
- `loadgen_current_rps`, `loadgen_active_threads`, `loadgen_test_running`

### Service B
- `http_server_requests_seconds_*`, `service_b_test`

### Service C
- `ratelimiter_requests_total{decision="forwarded|rejected"}`
- `ratelimiter_requests_by_algorithm_total{algorithm="fixed|sliding|token"}`
- `ratelimiter_request_duration_seconds_*`
- `ratelimiter_redis_request_duration_seconds_*`
- `ratelimiter_redis_errors_total`
- `ratelimiter_current_limit`, `ratelimiter_window_seconds`, `ratelimiter_bucket_capacity`, `ratelimiter_token_fill_rate`
- `ratelimiter_redis_connected`, `ratelimiter_mode{type="failopen"}`

### AI‑module
- `ai_limit_config_requests_total{result="ok|invalid_config|validation_error"}`
- `ai_forecast_duration_seconds`
- `ai_last_observed_rps`, `ai_last_predicted_rps`, `ai_last_recommended_rps`
- `ai_last_recommended_limit`, `ai_last_recommended_window_seconds`
- `ai_last_recommended_capacity`, `ai_last_recommended_fill_rate`
- `ai_last_valid_for_seconds`, `ai_last_algorithm{algorithm="fixed|sliding|token"}`
- `ai_history_points`

## 9. Отказоустойчивость
- При недоступности Redis Service C может работать в режиме fail‑open.
- Переходы в fail‑open логируются; восстановление Redis фиксируется и возвращает лимитирование.
- Ошибки AI‑module не останавливают Service C.

## 10. Производительность и масштабирование
- Все сервисы stateless и допускают горизонтальное масштабирование.
- Redis рекомендуется размещать рядом с Service C для минимизации RTT.
- Целевая накладная задержка на лимитер — миллисекунды.

## 11. Сценарии тестирования и критерии приемки
### Сценарий 1: равномерная нагрузка
- Нагрузка ниже лимита.
- 429 ≈ 0, latency стабильна, 5xx отсутствуют.

### Сценарий 2: кратковременные всплески
- Проверить Fixed/Sliding/Token.
- Оценивать 429/latency в сравнении алгоритмов с одинаковым бюджетом (`limit/window` и `capacity/fillRate`).
- Поведение зависит от тюнинга параметров: Token обычно лучше переносит короткие bursts, Sliding снижает эффект границы окна.

### Сценарий 3: аномальная нагрузка (DDoS)
- Доля 429 высокая, Service B остаётся доступным.

### Сценарий 4: сбой Redis
- Service C переходит в fail‑open.
- После восстановления Redis лимитирование возвращается.

Критерии приемки:
- Все эндпоинты здоровья доступны.
- Лимитер корректно пропускает/отклоняет трафик.
- Метрики доступны и корректно отражают состояние.
- AI‑module даёт рекомендации без сбоев системы.
