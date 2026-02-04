# RUNBOOK — платформа RPS‑limiter (Service A/B/C + AI)

## 1. Назначение
Этот runbook описывает запуск и проверку всей платформы RPS‑limiter. Файлы `RUNBOOK.md` и `specification.md` одинаковы во всех сервисах и описывают систему целиком. Детали конкретного сервиса — в его `README.md`.

## 2. Предпосылки
- Docker + Docker Compose.
- Опционально для ручного запуска без Docker: JDK 21, Python 3.x и Redis.
- Для ручного запуска Service C Redis должен быть доступен на `REDIS_HOST`/`REDIS_PORT` (обычно `localhost:6379`).

## 3. Порты по умолчанию
- Service A (load‑generator): `8080`
- Service B (target): `8081`
- Service C (rate‑limiter): `8082`
- AI‑module: `8083`
- Redis: `6379`
- Prometheus: `9090`
- Grafana: `3000`

## 4. Рекомендуемая последовательность запуска
Для единого запуска через Docker порядок не нужен, всё поднимается одной командой.
Ниже порядок полезен только для ручного запуска без Docker:

1) Service C (rate‑limiter/proxy).
2) Service B (целевой сервис).
3) AI‑module (если включён adaptive режим).
4) Prometheus/Grafana (опционально).
5) Service A (генератор нагрузки).

## 5. Запуск компонентов
### 5.1 Единый запуск всей платформы (рекомендуется)
```bash
docker compose up --build -d
docker compose ps
```

Остановка:
```bash
docker compose down
```

Остановка с удалением томов Prometheus/Grafana:
```bash
docker compose down -v
```

### 5.2 Ручной запуск (без Docker, опционально)
Service C (rate-limiter-service):
```bash
cd rate-limiter-service && REDIS_HOST=localhost TARGET_URL=http://localhost:8081 ./gradlew bootRun
```

Service B (application-service):
```bash
cd application-service && ./gradlew bootRun
```

AI‑module:
```bash
cd AI-RPS-limiter && uvicorn main:app --host 0.0.0.0 --port 8083
```

Service A (load-generator-service):
```bash
cd load-generator-service && ./gradlew bootRun
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

## 7. Пошаговое локальное тестирование (curl + Postman)
Ниже — полный минимально-достаточный тест-план для функциональности из `specification.md`.

### 7.1 Подготовка переменных
```bash
export A_URL=http://localhost:8080
export B_URL=http://localhost:8081
export C_URL=http://localhost:8082
export AI_URL=http://localhost:8083
```

`targetUrl` для запроса в Service A (`/test/start`):
- Docker-запуск всей платформы: `http://rate-limiter-service:8082/api/test`
- Ручной запуск на хосте: `http://localhost:8082/api/test`

Postman (Environment variables):
- `A_URL`, `B_URL`, `C_URL`, `AI_URL`
- `TARGET_FOR_LOAD`:
  - Docker: `http://rate-limiter-service:8082/api/test`
  - Host mode: `http://localhost:8082/api/test`

### 7.2 Этап 1 — health и метрики всех сервисов
curl:
```bash
curl "$A_URL/actuator/health"
curl "$B_URL/actuator/health"
curl "$C_URL/actuator/health"
curl "$AI_URL/health"

curl "$A_URL/actuator/prometheus" | head
curl "$B_URL/actuator/prometheus" | head
curl "$C_URL/actuator/prometheus" | head
curl "$AI_URL/metrics" | head
```
Ожидание: health = `UP`, метрики доступны.

Postman:
- `GET {{A_URL}}/actuator/health`
- `GET {{B_URL}}/actuator/health`
- `GET {{C_URL}}/actuator/health`
- `GET {{AI_URL}}/health`
- `GET {{A_URL}}/actuator/prometheus`
- `GET {{B_URL}}/actuator/prometheus`
- `GET {{C_URL}}/actuator/prometheus`
- `GET {{AI_URL}}/metrics`

### 7.3 Этап 2 — проверка Config API Service C
curl:
```bash
curl "$C_URL/config/limits"

curl -X POST "$C_URL/config/limits" \
  -H 'Content-Type: application/json' \
  -d '{"algorithm":"fixed","limit":100,"window":60,"capacity":200,"fillRate":50}'

curl -X POST "$C_URL/config/algorithm" \
  -H 'Content-Type: application/json' \
  -d '{"algorithm":"sliding"}'

curl -X POST 'http://localhost:8082/config/algorithm?algorithm=token_bucket'
curl "$C_URL/config/limits"
```
Ожидание: алгоритм и параметры корректно применяются и читаются.

Postman:
- `GET {{C_URL}}/config/limits`
- `POST {{C_URL}}/config/limits` (`Content-Type: application/json`, body как выше)
- `POST {{C_URL}}/config/algorithm` (body `{"algorithm":"sliding"}`)
- `POST {{C_URL}}/config/algorithm?algorithm=token_bucket`

### 7.4 Этап 3 — равномерная нагрузка ниже лимита (Scenario 1)
curl:
```bash
curl -X POST "$C_URL/config/limits" \
  -H 'Content-Type: application/json' \
  -d '{"algorithm":"fixed","limit":3000,"window":60,"capacity":200,"fillRate":50}'

curl -X POST "$A_URL/test/start" \
  -H 'Content-Type: application/json' \
  -d '{
    "targetUrl": "http://rate-limiter-service:8082/api/test",
    "duration": "PT15S",
    "profile": { "type": "constant", "params": { "rps": 10 } }
  }'

curl "$A_URL/test/status"
```
Проверка результата:
```bash
curl "$C_URL/actuator/prometheus" | grep 'ratelimiter_requests_total{decision='
curl "$B_URL/actuator/prometheus" | grep 'uri="/api/test"'
```
Ожидание: `forwarded` растет, `rejected` близко к 0, Service B получает запросы.

Postman:
- `POST {{C_URL}}/config/limits`
- `POST {{A_URL}}/test/start`
- `GET {{A_URL}}/test/status`
- `GET {{C_URL}}/actuator/prometheus`
- `GET {{B_URL}}/actuator/prometheus`

### 7.5 Этап 4 — перегрузка / высокий %429 (Scenario 3 DDoS)
curl:
```bash
curl -X POST "$C_URL/config/limits" \
  -H 'Content-Type: application/json' \
  -d '{"algorithm":"fixed","limit":30,"window":60,"capacity":200,"fillRate":50}'

curl -X POST "$A_URL/test/start" \
  -H 'Content-Type: application/json' \
  -d '{
    "targetUrl": "http://rate-limiter-service:8082/api/test",
    "duration": "PT10S",
    "profile": {
      "type": "ddos",
      "params": {
        "minRps": 20,
        "maxRps": 80,
        "maxSpikeDuration": "PT2S",
        "minIdleTime": "PT0S",
        "maxIdleTime": "PT1S"
      }
    }
  }'
```
Проверка 429:
```bash
curl "$C_URL/actuator/prometheus" | grep 'ratelimiter_requests_total{decision='
```
Ожидание: `rejected` растет значительно.

Postman:
- `POST {{C_URL}}/config/limits`
- `POST {{A_URL}}/test/start` (ddos body)
- `GET {{C_URL}}/actuator/prometheus`

### 7.6 Этап 5 — проверка всех профилей нагрузки Service A
Запускать по одному профилю (каждый тест 10-20 секунд), затем `GET /test/status`.

curl (примеры body для `POST $A_URL/test/start`):
```json
{"targetUrl":"http://rate-limiter-service:8082/api/test","duration":"PT15S","profile":{"type":"constant","params":{"rps":20}}}
{"targetUrl":"http://rate-limiter-service:8082/api/test","duration":"PT20S","profile":{"type":"burst","params":{"baseRps":10,"spikeRps":60,"spikeDuration":"PT2S","spikePeriod":"PT5S"}}}
{"targetUrl":"http://rate-limiter-service:8082/api/test","duration":"PT20S","profile":{"type":"sinusoidal","params":{"minRps":5,"maxRps":40,"period":"PT10S"}}}
{"targetUrl":"http://rate-limiter-service:8082/api/test","duration":"PT20S","profile":{"type":"poisson","params":{"averageRps":30}}}
{"targetUrl":"http://rate-limiter-service:8082/api/test","duration":"PT20S","profile":{"type":"ddos","params":{"minRps":15,"maxRps":90,"maxSpikeDuration":"PT3S","minIdleTime":"PT0S","maxIdleTime":"PT1S"}}}
```
Базовый цикл проверки API управления тестом (curl):
```bash
curl -X POST "$A_URL/test/start" \
  -H 'Content-Type: application/json' \
  -d '{
    "targetUrl": "http://rate-limiter-service:8082/api/test",
    "duration": "PT20S",
    "concurrency": 5,
    "profile": { "type": "constant", "params": { "rps": 20 } }
  }'
sleep 3
curl "$A_URL/test/status"
curl -X POST "$A_URL/test/stop"
curl "$A_URL/test/status"
```
Ожидание: `running` переходит `true -> false`, API `/test/start`, `/test/status`, `/test/stop` корректно работает для каждого профиля.

Postman:
- Сделать 5 отдельных `POST {{A_URL}}/test/start` с body выше.
- После каждого запуска: `GET {{A_URL}}/test/status`, затем `POST {{A_URL}}/test/stop`.

### 7.7 Этап 6 — AI API напрямую (Scenario AI-module)
curl:
```bash
curl -X POST "$AI_URL/v1/limit-config" \
  -H 'Content-Type: application/json' \
  -d '{
    "timestamp":"2026-02-04T18:00:00Z",
    "observedRps":120.5,
    "rejectedRate":0.12,
    "latencyP95":0.45,
    "errors5xx":2,
    "currentConfig":{"algorithm":"fixed","limit":100,"window":60}
  }'
```
Негативный пример:
```bash
curl -X POST "$AI_URL/v1/limit-config" \
  -H 'Content-Type: application/json' \
  -d '{
    "observedRps":120.5,
    "currentConfig":{"algorithm":"fixed","limit":0,"window":0}
  }'
```
Ожидание: сервис отвечает стабильно (fallback на некорректных данных).

Postman:
- `POST {{AI_URL}}/v1/limit-config` (валидный body)
- `POST {{AI_URL}}/v1/limit-config` (негативный body)
- `GET {{AI_URL}}/metrics`

### 7.8 Этап 7 — адаптивная коммуникация Service C -> AI (Scenario 6)
curl:
```bash
before=$(curl -s "$AI_URL/metrics" | awk '/^ai_limit_config_requests_total\\{/{s+=$NF} END {print s+0}')
sleep 35
after=$(curl -s "$AI_URL/metrics" | awk '/^ai_limit_config_requests_total\\{/{s+=$NF} END {print s+0}')
echo "$before -> $after"
```
Ожидание: счетчик увеличивается (при `ADAPTIVE_ENABLED=true` и доступном Redis).

Postman:
- `GET {{AI_URL}}/metrics` (до/после 30-40 секунд)
- Проверить рост `ai_limit_config_requests_total`.

### 7.9 Этап 8 — Redis fail-open и восстановление (Scenario 4)
curl/terminal:
```bash
curl -X POST "$C_URL/config/limits" \
  -H 'Content-Type: application/json' \
  -d '{"algorithm":"fixed","limit":1,"window":60,"capacity":200,"fillRate":50}'

for i in {1..10}; do curl -s -o /dev/null -w "%{http_code}\n" "$C_URL/api/test"; done
# ожидание до сбоя Redis: много 429

docker compose stop redis
sleep 8
curl "$C_URL/actuator/prometheus" | grep -E '^ratelimiter_mode|^ratelimiter_redis_connected'
for i in {1..10}; do curl -s -o /dev/null -w "%{http_code}\n" "$C_URL/api/test"; done
# ожидание в fail-open: в основном 200

docker compose up -d redis
sleep 10
curl "$C_URL/actuator/prometheus" | grep -E '^ratelimiter_mode|^ratelimiter_redis_connected'
# ожидание после восстановления: failopen=0, redis_connected=1
```

Postman:
- `POST {{C_URL}}/config/limits`
- `GET {{C_URL}}/actuator/prometheus` (до/после stop redis и после up redis)
- Для трафика можно использовать `Runner` с `GET {{C_URL}}/api/test` (итерации 10+).

### 7.10 Этап 9 — мониторинг и дашборды
curl:
```bash
curl http://localhost:9090/api/v1/targets
curl http://localhost:3000/api/health
```
Ожидание: все targets `up`, Grafana `database: ok`.

Postman:
- `GET http://localhost:9090/api/v1/targets`
- `GET http://localhost:3000/api/health`

### 7.11 Этап 10 — сравнение алгоритмов Fixed/Sliding/Token на burst-нагрузке (Scenario 2)
Цель: на одинаковом burst-профиле сравнить поведение 429 и убедиться, что переключение алгоритма реально влияет на обработку.

curl:
```bash
for algo in fixed sliding token_bucket; do
  echo "=== algorithm: $algo ==="
  curl -X POST "$C_URL/config/limits" \
    -H 'Content-Type: application/json' \
    -d '{"algorithm":"fixed","limit":80,"window":60,"capacity":120,"fillRate":80}'
  curl -X POST "$C_URL/config/algorithm?algorithm='"$algo"'"

  echo "before:"
  curl -s "$C_URL/actuator/prometheus" | grep 'ratelimiter_requests_total{decision='

  curl -X POST "$A_URL/test/start" \
    -H 'Content-Type: application/json' \
    -d '{
      "targetUrl": "http://rate-limiter-service:8082/api/test",
      "duration": "PT20S",
      "profile": {
        "type": "burst",
        "params": { "baseRps": 15, "spikeRps": 120, "spikeDuration": "PT2S", "spikePeriod": "PT5S" }
      }
    }'
  sleep 22

  echo "after:"
  curl -s "$C_URL/actuator/prometheus" | grep 'ratelimiter_requests_total{decision='
  curl -s "$C_URL/actuator/prometheus" | grep 'ratelimiter_requests_by_algorithm_total{algorithm='
done
```
Ожидание: активный алгоритм переключается, растет соответствующий `ratelimiter_requests_by_algorithm_total{algorithm="..."}`. Точное распределение 429 зависит от параметров (`limit/window/capacity/fillRate`) и профиля нагрузки.

Postman:
- Создать 3 прогона с одинаковым body `POST {{A_URL}}/test/start` (burst), перед каждым переключать `POST {{C_URL}}/config/algorithm?algorithm=fixed|sliding|token_bucket`.
- До/после каждого прогона запрашивать `GET {{C_URL}}/actuator/prometheus` и сравнивать `ratelimiter_requests_total` и `ratelimiter_requests_by_algorithm_total`.

### 7.12 Этап 11 — проверка proxy-маршрутизации Service C (`/**`) и негативных ответов API
Цель: подтвердить, что Service C проксирует разные HTTP-методы в Service B, а API валидация дает корректные 4xx.

curl:
```bash
curl -X POST "$C_URL/config/limits" \
  -H 'Content-Type: application/json' \
  -d '{"algorithm":"fixed","limit":10000,"window":60,"capacity":10000,"fillRate":10000}'

curl -i "$C_URL/api/test?source=proxy-check"
curl -I "$C_URL/api/test"
curl -i -X POST "$C_URL/api/test" -H 'Content-Type: application/json' -d '{"x":1}'

curl -i -X POST "$C_URL/config/algorithm" -H 'Content-Type: application/json' -d '{}'
curl -i -X POST "$A_URL/test/start" \
  -H 'Content-Type: application/json' \
  -d '{"targetUrl":"http://rate-limiter-service:8082/api/test","duration":"bad","profile":{"type":"constant","params":{"rps":10}}}'
```
Ожидание:
- Проксирование работает: GET/HEAD/POST доходят до Service B (типичный ответ от B для неподдерживаемого метода — `405`, а не `429`/`502`).
- Валидационные ошибки API дают корректные 4xx с понятным сообщением.

Postman:
- `GET {{C_URL}}/api/test?source=proxy-check`
- `HEAD {{C_URL}}/api/test`
- `POST {{C_URL}}/api/test`
- `POST {{C_URL}}/config/algorithm` с пустым body
- `POST {{A_URL}}/test/start` с невалидной `duration`

### 7.13 Этап 12 — автоматическое сравнение алгоритмов под разной нагрузкой
Цель: получить сопоставимые цифры для `fixed/sliding/token` в нескольких сценариях нагрузки.

Запуск бенчмарка (рекомендуется с отключенным adaptive для честного сравнения):
```bash
scripts/benchmark_algorithms.sh --disable-adaptive --duration 20 --base-rps-limit 100 --window 10 --scenarios constant_low,burst,sinusoidal,ddos
```

Быстрый прогон:
```bash
scripts/benchmark_algorithms.sh --duration 12 --scenarios burst,ddos
```

Построение "боевой матрицы" (5-6 сценариев + итоговый рейтинг в одной markdown-таблице):
```bash
scripts/battle_matrix.sh --disable-adaptive --duration 10
```
Выходные файлы:
- `<prefix>.raw.csv` — сырые метрики.
- `<prefix>.scored.csv` — рассчитанные score.
- `<prefix>.md` — итоговая таблица с колонками `fixed/sliding/token`, winner по сценарию и финальный rank.
- Пример последнего прогона: `monitoring/benchmarks/battle-matrix.md`.

Что делают скрипты:
- `scripts/benchmark_algorithms.sh`:
  - последовательно запускает каждый сценарий для `fixed`, `sliding`, `token`;
  - собирает метрики `forwarded/rejected`, `% rejected`, `effective_rps`;
  - сохраняет CSV-отчет `benchmark-<timestamp>.csv`;
  - пишет `foreign_algo_delta`:
    - `0` = run обработан выбранным алгоритмом;
    - `>0` = алгоритм мог переключиться посреди run (например, из-за adaptive).
- `scripts/battle_matrix.sh`:
  - формирует markdown-таблицу с колонками score и итоговым rank;
  - сохраняет `*.raw.csv`, `*.scored.csv`, `*.md`;
  - использует weighted score:
    - `overall = 0.35 * stability + 0.40 * protection + 0.25 * latency`.
    - `stability = 100 - error_percent`.
    - `protection` сравнивает фактический `%429` с ожидаемым по перегрузке.
    - `latency` нормализуется внутри каждого сценария (лучший latency получает 100).

Итог приемки: тесты из этапов 1-12 закрывают health, API, алгоритмы, профили нагрузки, 429-логику, fail-open/recovery, AI, проксирование методов, мониторинг и количественное сравнение алгоритмов.

## 8. Мониторинг (Prometheus + Grafana)
Единый конфиг Prometheus: `monitoring/prometheus.yml`.
Он используется корневым `docker-compose.yml` и является источником истины для scrape targets.
Готовые дашборды Grafana автоматически подхватываются из `monitoring/grafana/dashboards`.

Grafana (примеры запросов):
- RPS: `rate(ratelimiter_requests_total[1m])`
- % отклонений: `rate(ratelimiter_requests_total{decision="rejected"}[1m]) / rate(ratelimiter_requests_total[1m])`
- p95 latency: `histogram_quantile(0.95, sum(rate(ratelimiter_request_duration_seconds_bucket[5m])) by (le))`
- Loadgen RPS: `loadgen_current_rps`

## 9. Тест‑кейсы системы
Сценарии и критерии для приемки полностью расписаны в разделе 7 (`7.1`–`7.13`) и покрывают:
- Service A: управление тестами и все профили нагрузки.
- Service B: доступность и обработку проксируемого трафика.
- Service C: конфигурирование, алгоритмы, 2xx/429, fail-open и восстановление после Redis.
- AI-module: API рекомендаций, fallback-поведение, adaptive-коммуникацию с Service C.
- Monitoring: сбор метрик Prometheus и отображение Grafana.
- Validation: негативные кейсы API и ожидаемые 4xx.
- Benchmarking: формальное сравнение алгоритмов в разных профилях нагрузки.

## 10. Troubleshooting
- 502 от Service C: проверьте `TARGET_URL` и доступность Service B.
- Нет метрик: проверьте `/actuator/prometheus` и конфиг Prometheus.
- Redis недоступен: Service C переходит в fail‑open (ожидаемо).
- AI модуль недоступен: Service C продолжает с последними лимитами.

## 11. Остановка
- Локально: `Ctrl+C` в терминалах сервисов.
- Docker (единый запуск): `docker compose down`.
