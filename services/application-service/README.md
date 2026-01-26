# application-service

Service B — целевой сервис для проверки устойчивости платформы под нагрузкой.

Документация:
- `RUNBOOK.md` — запуск, проверки, мониторинг.
- `specification.md` — требования и интерфейсы.

Быстрый старт:
```bash
./gradlew bootRun
curl http://localhost:8081/api/test
```
