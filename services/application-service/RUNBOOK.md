# RUNBOOK - application-service (Service B target)

Этот runbook описывает, как запускать application-service, проверять его работоспособность
и подключать мониторинг (Prometheus + Grafana). Также приведена рекомендуемая последовательность
старта всей платформы.

## Назначение сервиса
- Целевой сервис ("Service B"), который получает HTTP-трафик через limiter/proxy (Service C).
- Экспортирует health и Prometheus-метрики через Spring Boot Actuator.
- Может имитировать задержку обработки для моделирования нагрузки.

## Порты и эндпоинты по умолчанию
- Порт приложения: 8081
- Тестовый эндпоинт: /api/test
- Health: /actuator/health
- Prometheus metrics: /actuator/prometheus

## Конфигурация
Конфигурация находится в `src/main/resources/application.yaml`.
Ключевые свойства:
- server.port: 8081
- app.processing-delay-ms: 0 (задержка обработки в мс)
- management.endpoints.web.exposure.include: health, prometheus

Переопределение через переменные окружения:
- APP_PROCESSING_DELAY_MS=50
- SERVER_PORT=8081

## Последовательность запуска (вся платформа)
Рекомендуемый порядок при запуске всей платформы:
1) Redis (нужен Service C)
2) application-service (Service B)
3) limiter/proxy сервис (Service C)
4) Prometheus + Grafana (мониторинг)
5) load-generator сервис (Service A)

Примечание: Prometheus и Grafana можно запускать раньше, но перед тестами убедитесь, что они запущены.

## Локальный запуск (Gradle)
```bash
./gradlew bootRun
```

## Запуск собранного JAR
```bash
./gradlew build
java -jar build/libs/*.jar
```

## Запуск в Docker
```bash
./gradlew build
docker build -t application-service:local .
docker run --rm -p 8081:8081 application-service:local
```

## Быстрая проверка
```bash
curl http://localhost:8081/actuator/health
curl http://localhost:8081/api/test
curl http://localhost:8081/actuator/prometheus
```

Примечание:
- На /actuator/prometheus появится больше HTTP-метрик после хотя бы одного запроса к /api/test.

## Конфигурация Prometheus (пример)
Добавьте job в `prometheus.yml`:
```yaml
scrape_configs:
  - job_name: "application-service"
    metrics_path: /actuator/prometheus
    static_configs:
      - targets: ["application-service:8081"]
```

Если запускаете локально без Docker, используйте `localhost:8081` как target.

## Grafana (быстрый старт)
1) Добавьте Prometheus как источник данных.
2) Создайте дашборд с панелями:
   - RPS: rate(http_server_requests_seconds_count{uri="/api/test"}[1m])
   - p95 задержки: histogram_quantile(0.95, sum by (le) (rate(http_server_requests_seconds_bucket{uri="/api/test"}[5m])))
   - Ошибки: rate(http_server_requests_seconds_count{status=~"5.."}[1m])
3) При необходимости добавьте JVM-метрики:
   - jvm_memory_used_bytes
   - jvm_gc_pause_seconds_count

## Troubleshooting
- Порт 8081 занят: измените `server.port` или остановите конфликтующий процесс.
- /actuator/prometheus пустой: сделайте запрос к /api/test.
- Медленная отдача: уменьшите `app.processing-delay-ms` или проверьте лимиты CPU.

## Остановка
- Локально: Ctrl+C в терминале.
- Docker: `docker stop <container_id>`.
