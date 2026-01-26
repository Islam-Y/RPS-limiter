# RUNBOOK: запуск и мониторинг (локально)

Ниже приведена практическая последовательность запуска сервисов и мониторинга для локальной машины. Команды ориентированы на окружение разработки и могут адаптироваться под Docker/оркестратор.

## Предпосылки и порты по умолчанию

Предпосылки:
- Java 21 (для сервисов на Spring Boot).
- Redis (локально или в Docker).
- Prometheus и Grafana (для мониторинга).

Порты по умолчанию:
- Сервис A (генератор нагрузки): 8080.
- Сервис B (целевой сервис): 8081.
- Сервис C (rate-limiter, этот сервис): 8082.
- Redis: 6379.
- Prometheus: 9090.
- Grafana: 3000.

## Рекомендуемая последовательность запуска

Минимальная зависимостная последовательность:
1) Redis (нужен для лимитера; без Redis сервис C перейдет в fail-open).
2) Сервис B (цель; иначе сервис C будет отдавать 502 при проксировании).
3) Сервис C (rate-limiter).
4) (Опционально) AI-модуль, если включен адаптивный режим.
5) Сервис A (генератор нагрузки).

Prometheus и Grafana можно запускать параллельно; чтобы не потерять метрики с начала эксперимента, лучше стартовать их до пункта 5.

## Запуск Redis

Через Docker:

```bash
docker run --name rps-redis -p 6379:6379 redis:7-alpine
```

## Запуск сервиса C (rate-limiter)

Из директории `services/rate-limiter-service`:

```bash
./gradlew bootRun
```

Полезные переменные окружения (переопределяют значения из `application.yaml`):
- `SERVER_PORT` (по умолчанию 8082).
- `REDIS_HOST`, `REDIS_PORT` (по умолчанию redis:6379).
- `TARGET_URL` (по умолчанию http://service-b:8081).
- `RATE_LIMIT_ALGORITHM` (fixed | sliding | token | token_bucket).
- `RATE_LIMIT_LIMIT` (по умолчанию 100).
- `RATE_LIMIT_WINDOW_SECONDS` (по умолчанию 60).
- `RATE_LIMIT_CAPACITY` (по умолчанию 200).
- `RATE_LIMIT_FILL_RATE` (по умолчанию 50).
- `ADAPTIVE_ENABLED` (false | true).
- `ADAPTIVE_URL` (URL AI-модуля, принимающего POST).
- `ADAPTIVE_INTERVAL` (например, 30s).
- `ADAPTIVE_TIMEOUT` (например, 5s).

Пример запуска локально:

```bash
REDIS_HOST=localhost \
REDIS_PORT=6379 \
TARGET_URL=http://localhost:8081 \
RATE_LIMIT_ALGORITHM=fixed \
RATE_LIMIT_LIMIT=200 \
./gradlew bootRun
```

Проверка доступности:
- `GET http://localhost:8082/actuator/health`
- `GET http://localhost:8082/actuator/prometheus`

## Конфигурация лимитера во время работы

Смена лимитов:
```bash
curl -X POST http://localhost:8082/config/limits \
  -H "Content-Type: application/json" \
  -d '{"algorithm":"fixed","limit":200,"windowSeconds":60,"capacity":200,"fillRate":50}'
```

Смена алгоритма:
```bash
curl -X POST "http://localhost:8082/config/algorithm?algorithm=sliding"
```

Получение текущей конфигурации:
```bash
curl http://localhost:8082/config/limits
```

## Мониторинг: Prometheus + Grafana

Сервис C уже публикует метрики на `/actuator/prometheus`. Основные метрики:
- `ratelimiter_requests_total{decision="forwarded|rejected"}`
- `ratelimiter_requests_by_algorithm_total{algorithm="fixed|sliding|token"}`
- `ratelimiter_request_duration_seconds_*` (гистограмма)
- `ratelimiter_redis_request_duration_seconds_*` (гистограмма)
- `ratelimiter_redis_errors_total`
- `ratelimiter_current_limit`, `ratelimiter_window_seconds`, `ratelimiter_bucket_capacity`, `ratelimiter_token_fill_rate`
- `ratelimiter_redis_connected` (1/0)
- `ratelimiter_mode{type="failopen"}` (1/0)

Сохраните следующий пример как `prometheus.yml` в текущей директории (рядом с `RUNBOOK.md`).

```yaml
global:
  scrape_interval: 5s

scrape_configs:
  - job_name: "rate-limiter"
    metrics_path: /actuator/prometheus
    static_configs:
      - targets: ["localhost:8082"]
  - job_name: "service-b"
    metrics_path: /actuator/prometheus
    static_configs:
      - targets: ["localhost:8081"]
  - job_name: "loadgen"
    metrics_path: /actuator/prometheus
    static_configs:
      - targets: ["localhost:8080"]
```

Запуск Prometheus через Docker:

```bash
docker run --name rps-prometheus -p 9090:9090 \
  -v "$PWD/prometheus.yml:/etc/prometheus/prometheus.yml:ro" \
  prom/prometheus
```

Запуск Grafana через Docker:

```bash
docker run --name rps-grafana -p 3000:3000 grafana/grafana
```

В Grafana:
- Добавьте источник данных Prometheus (URL: `http://host.docker.internal:9090` на macOS).
- Постройте базовые панели:
  - RPS: `rate(ratelimiter_requests_total[1m])`
  - % отклонений: `rate(ratelimiter_requests_total{decision="rejected"}[1m]) / rate(ratelimiter_requests_total[1m])`
  - p95 latency: `histogram_quantile(0.95, sum(rate(ratelimiter_request_duration_seconds_bucket[5m])) by (le))`
  - Redis ошибки: `rate(ratelimiter_redis_errors_total[5m])`

## Минимальный smoke test

1) Убедитесь, что сервис B отвечает на `http://localhost:8081/`.
2) Вызовите сервис C: `curl -i http://localhost:8082/` — запрос должен проксироваться в B.
3) Проверьте рост метрик в Prometheus и графиках Grafana.
