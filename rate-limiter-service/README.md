# rate-limiter-service

Service C — proxy/limiter между генератором нагрузки и целевым сервисом.

Документация:
- `RUNBOOK.md` — запуск, конфигурация, мониторинг.
- `specification.md` — требования и интерфейсы.

Быстрый старт:
```bash
cd ..
docker compose up --build -d
curl http://localhost:8082/actuator/health
```

Локальный запуск без Docker:
```bash
REDIS_HOST=localhost TARGET_URL=http://localhost:8081 ./gradlew bootRun
```
