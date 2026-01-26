# RUNBOOK: Load Generator Service (Service A)

## Назначение
Сервис генерирует HTTP-нагрузку на целевой URL (обычно на сервис C — прокси/лимитер). Предоставляет REST API для запуска/остановки тестов и метрики Prometheus для мониторинга.

## Быстрые факты
- Порт по умолчанию: `8080`
- Health: `GET /actuator/health`
- Метрики: `GET /actuator/prometheus`
- Control API:
  - `POST /test/start`
  - `POST /test/stop`
  - `GET /test/status`

## Требования
- Docker + Docker Compose **или** JDK 21 для локального запуска.
- Доступный целевой сервис (обычно прокси/лимитер C). Если запускаете всю платформу, сначала должны быть запущены Redis, сервис B и сервис C.

## Последовательность запуска (вся платформа)
1. **Redis** (нужен сервису C).
2. **Service B** (целевое приложение).
3. **Service C** (лимитер/прокси, который форвардит на B).
4. **Prometheus** (снимает метрики с A/B/C).
5. **Grafana** (визуализация метрик).
6. **Load Generator (этот сервис)**.

## Конфигурация
Конфигурация теста — JSON и может быть:
- Передана в `POST /test/start` **или**
- Автоматически загружена на старте через `LOADGEN_CONFIG_FILE`.

### Обязательные поля
- `targetUrl` (string): URL, куда будут отправляться запросы (обычно сервис C).
- `duration` (number или string): длительность теста.
- `profile` (object): описание профиля нагрузки.

### Необязательные поля
- `concurrency` (number): ограничение количества одновременных запросов. Если не задано, используется `loadgen.default-concurrency` (по умолчанию `0` = без ограничения).

### Формат duration
- Число = секунды (например, `60`)
- Строка с единицами: `"250ms"`, `"10s"`, `"2m"`, `"1h"`, `"1d"`
- ISO-8601: `"PT30S"`

### Типы профилей и обязательные параметры
- `constant`: `rps`
- `burst`: `baseRps`, `spikeRps`, `spikeDuration`, `spikePeriod`
- `sinusoidal`: `minRps`, `maxRps`, `period`
- `poisson`: `averageRps`
- `ddos`: `minRps`, `maxRps`, `maxSpikeDuration`, `minIdleTime`, `maxIdleTime`

### Пример конфига
```json
{
  "targetUrl": "http://service-c:8082/api/test",
  "duration": "60s",
  "profile": {
    "type": "constant",
    "params": {
      "rps": 100
    }
  },
  "concurrency": 50
}
```

## Запуск через Docker Compose
Файл `docker-compose.yml` ожидает конфиг по пути `./configs/loadgen.json`.

1) Создайте директорию и файл конфигурации:
```bash
mkdir -p configs
cat > configs/loadgen.json <<'JSON'
{
  "targetUrl": "http://service-c:8082/api/test",
  "duration": "60s",
  "profile": {
    "type": "constant",
    "params": { "rps": 100 }
  }
}
JSON
```

2) Запустите сервис:
```bash
docker-compose up --build
```

Примечания:
- Если `LOADGEN_CONFIG_FILE` задан, но файл не найден, сервис пишет warning и **не** стартует тест автоматически.
- Чтобы отключить автостарт, уберите `LOADGEN_CONFIG_FILE` из `docker-compose.yml` или оставьте файл отсутствующим.

## Локальный запуск (без Docker)
```bash
./gradlew bootRun
```

Необязательные переменные окружения:
- `SERVER_PORT=8080`
- `LOADGEN_CONFIG_FILE=/absolute/path/to/loadgen.json`

Либо собрать jar и запустить:
```bash
./gradlew bootJar
java -jar build/libs/*.jar
```

## Control API (ручной запуск/остановка)
Старт теста:
```bash
curl -X POST http://localhost:8080/test/start \
  -H 'Content-Type: application/json' \
  -d '{
    "targetUrl": "http://service-c:8082/api/test",
    "duration": "30s",
    "profile": { "type": "poisson", "params": { "averageRps": 50 } }
  }'
```

Остановка теста:
```bash
curl -X POST http://localhost:8080/test/stop
```

Проверка статуса:
```bash
curl http://localhost:8080/test/status
```

## Мониторинг (Prometheus + Grafana)
Сервис отдаёт метрики Prometheus по `GET /actuator/prometheus`.

### Пример конфига Prometheus
```yaml
scrape_configs:
  - job_name: 'loadgen'
    metrics_path: /actuator/prometheus
    static_configs:
      - targets: ['loadgen:8080'] # используйте localhost:8080 при локальном запуске
```

### Основные метрики
- `loadgen_requests_total{status="success|rate_limited|error"}`
- `loadgen_current_rps`
- `loadgen_active_threads`
- `loadgen_test_running` (1 = идёт тест, 0 = тест остановлен)
- Таймер: `loadgen_request_duration` (в экспорте Prometheus будет `_seconds` и суффиксы `_count`, `_sum`, `_bucket`)

### Grafana
1) Добавьте Prometheus как источник данных.
2) Создайте панели по метрикам выше (RPS, ошибки, латентность и т.д.).

## Troubleshooting
- **Тест не стартует автоматически**: проверьте, что `LOADGEN_CONFIG_FILE` указывает на существующий файл внутри контейнера (`/app/configs/loadgen.json`).
- **Ошибка валидации**: проверьте `targetUrl` (обязателен `http://` или `https://`) и обязательные параметры профиля.
- **Цель недоступна из контейнера**: убедитесь, что `targetUrl` резолвится из docker-сети (используйте имя сервиса или `host.docker.internal`).
- **Нет метрик**: проверьте, что `GET /actuator/prometheus` возвращает данные и Prometheus смотрит на правильный target.
