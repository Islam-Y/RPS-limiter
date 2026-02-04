# RUNBOOK — платформа RPS‑limiter (Service A/B/C + AI)

## 1. Назначение
Этот runbook описывает запуск и проверку всей платформы RPS‑limiter. Файлы `RUNBOOK.md` и `specification.md` одинаковы во всех сервисах и описывают систему целиком. Детали конкретного сервиса — в его `README.md`.

## 2. Предпосылки
- JDK 21 (для сервисов на Spring Boot: A, B, C).
- Python 3.x (для AI‑модуля).
- Redis (локально или в Docker).
- Docker (опционально, для контейнерного запуска).
- Prometheus + Grafana (опционально, для мониторинга).

## 3. Порты по умолчанию
- Service A (load‑generator): `8080`
- Service B (target): `8081`
- Service C (rate‑limiter): `8082`
- AI‑module: `8083`
- Redis: `6379`
- Prometheus: `9090`
- Grafana: `3000`

## 4. Рекомендуемая последовательность запуска
1) Service C (rate‑limiter/proxy).
2) Service B (целевой сервис).
3) AI‑module (если включён adaptive режим).
4) Prometheus/Grafana (опционально).
5) Service A (генератор нагрузки).

## 5. Запуск компонентов
Ниже — типовые команды. Конкретные варианты запуска и Docker‑инструкции смотрите в README каждого сервиса.

### 5.1 Service C (rate-limiter-service)
```bash
docker compose up
```

### 5.2 Service B (application-service)
```bash
./gradlew bootRun
```

### 5.3 AI‑module
```bash
uvicorn main:app --host 0.0.0.0 --port 8083
```

### 5.4 Service A (load-generator-service)
```bash
./gradlew bootRun
```

### 5.5 Мониторинг (Prometheus + Grafana)
```bash
cd AI-RPS-limiter
docker compose up -d
```
Grafana UI: http://localhost:3000 (default: admin/admin)

## 6. Минимальная конфигурация
### Service C (rate‑limiter)
- `REDIS_HOST`, `REDIS_PORT`
- `TARGET_URL` (обычно `http://localhost:8081`)
- `RATE_LIMIT_ALGORITHM` (`fixed|sliding|token|token_bucket`)
- `RATE_LIMIT_LIMIT`, `RATE_LIMIT_WINDOW_SECONDS`
- `RATE_LIMIT_CAPACITY`, `RATE_LIMIT_FILL_RATE`
- `ADAPTIVE_ENABLED`, `ADAPTIVE_URL` (если используется AI)

### Service A (load‑generator)
- `LOADGEN_CONFIG_FILE` (опционально, автозапуск теста)

## 7. Быстрые проверки
### Health/metrics
```bash
curl http://localhost:8081/actuator/health
curl http://localhost:8082/actuator/health
curl http://localhost:8080/actuator/health
curl http://localhost:8083/health
```

### Пробный запуск нагрузки
```bash
curl -X POST http://localhost:8080/test/start \
  -H 'Content-Type: application/json' \
  -d '{
    "targetUrl": "http://localhost:8082/api/test",
    "duration": "30s",
    "profile": { "type": "constant", "params": { "rps": 50 } }
  }'
```

### Проверка лимитов
- Запросы ниже лимита → 2xx от Service B.
- Запросы выше лимита → 429 от Service C.

## 8. Мониторинг (Prometheus + Grafana)
Пример `prometheus.yml`:
```yaml
global:
  scrape_interval: 5s

scrape_configs:
  - job_name: "service-a"
    metrics_path: /actuator/prometheus
    static_configs:
      - targets: ["localhost:8080"]
  - job_name: "service-b"
    metrics_path: /actuator/prometheus
    static_configs:
      - targets: ["localhost:8081"]
  - job_name: "service-c"
    metrics_path: /actuator/prometheus
    static_configs:
      - targets: ["localhost:8082"]
  - job_name: "ai-module"
    metrics_path: /metrics
    static_configs:
      - targets: ["localhost:8083"]
```

Grafana (примеры запросов):
- RPS: `rate(ratelimiter_requests_total[1m])`
- % отклонений: `rate(ratelimiter_requests_total{decision="rejected"}[1m]) / rate(ratelimiter_requests_total[1m])`
- p95 latency: `histogram_quantile(0.95, sum(rate(ratelimiter_request_duration_seconds_bucket[5m])) by (le))`
- Loadgen RPS: `loadgen_current_rps`

## 9. Тест‑кейсы системы
### AI‑module
- Health endpoint: GET `/health` → `{"status":"UP"}`.
- Metrics endpoint: GET `/metrics` → `ai_*`.
- Валидный запрос: POST `/v1/limit-config` → 200 и корректная конфигурация.
- Некорректный `currentConfig` → fallback‑ответ с безопасной конфигурацией.

### Service C (rate‑limiter)
- Config API: установить лимиты (fixed/sliding/token) и прочитать их.
- Ниже лимита: запросы проходят (2xx).
- Выше лимита: 429.
- Fail‑open Redis: отключить Redis → трафик пропускается.
- AI доступен: рекомендации применяются.
- AI недоступен: используется последняя валидная конфигурация.

### Service B (target)
- Health endpoint отвечает OK.
- Отвечает на проксируемые GET со стабильной задержкой при нормальной нагрузке.

### Service A (load‑generator)
- `/test/start` и `/test/stop` управляют нагрузкой.
- Постоянный/всплесковый/синусоидальный/пуассоновский/DDoS профили отрабатывают ожидаемо.

## 10. Troubleshooting
- 502 от Service C: проверьте `TARGET_URL` и доступность Service B.
- Нет метрик: проверьте `/actuator/prometheus` и конфиг Prometheus.
- Redis недоступен: Service C переходит в fail‑open (ожидаемо).
- AI модуль недоступен: Service C продолжает с последними лимитами.

## 11. Остановка
- Локально: `Ctrl+C` в терминалах сервисов.
- Docker: `docker stop <container_id>`.
