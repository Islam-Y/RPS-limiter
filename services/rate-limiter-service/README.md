# rate-limiter-service

Service C — proxy/limiter между генератором нагрузки и целевым сервисом.

Документация:
- `RUNBOOK.md` — запуск, конфигурация, мониторинг.
- `specification.md` — требования и интерфейсы.

Быстрый старт:
```bash
docker compose up --build
curl http://localhost:8082/actuator/health
```

Локальный запуск без Docker:
```bash
./gradlew bootRun
```
