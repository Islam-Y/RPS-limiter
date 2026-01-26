# load-generator-service

Service A — генератор HTTP-нагрузки для проверки rate limiting.

Документация:
- `RUNBOOK.md` — запуск, конфигурация, мониторинг.
- `specification.md` — требования и форматы.

Быстрый старт:
```bash
./gradlew bootRun
curl http://localhost:8080/test/status
```
