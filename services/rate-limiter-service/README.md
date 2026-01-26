# rate-limiter-service

Service C — proxy/limiter между генератором нагрузки и целевым сервисом.

Документация:
- `RUNBOOK.md` — запуск, конфигурация, мониторинг.
- `specification.md` — требования и интерфейсы.

Быстрый старт:
```bash
./gradlew bootRun
curl http://localhost:8082/actuator/health
```
