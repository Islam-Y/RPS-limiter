# AI-RPS-limiter

AI модуль для прогнозирования нагрузки и рекомендаций по лимитам Service C.

Документация:
- `RUNBOOK.md` — запуск, проверки, мониторинг.
- `specification.md` — требования и интерфейсы.

Быстрый старт:
```bash
uvicorn main:app --host 0.0.0.0 --port 8083
curl http://localhost:8083/health
```
