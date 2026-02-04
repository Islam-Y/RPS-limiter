# Grafana для новичка: как создать дашборды для RPS‑limiter

Ниже — максимально простой пошаговый план: от запуска Grafana до первых графиков.

## 0. Что нужно заранее
- Сервисы A/B/C и AI должны быть запущены.
- Prometheus и Grafana поднимаются через корневой `docker-compose.yml`.
- Актуальный scrape-конфиг Prometheus находится в `monitoring/prometheus.yml`.
- Базовые дашборды уже провиженятся автоматически из `monitoring/grafana/dashboards`.
- Метрики должны открываться в браузере:
  - Service A: `http://localhost:8080/actuator/prometheus`
  - Service B: `http://localhost:8081/actuator/prometheus`
  - Service C: `http://localhost:8082/actuator/prometheus`
  - AI module: `http://localhost:8083/metrics`

## 1. Запусти Prometheus и Grafana
```bash
docker compose up -d
```
Команду запускайте из корня репозитория (`services/`), где лежит общий `docker-compose.yml`.

Открой Grafana:
```text
http://localhost:3000
```
Логин/пароль по умолчанию: `admin` / `admin`.

## 2. Проверь готовые дашборды
После старта compose в Grafana уже должны быть:
1) `RPS Limiter - Platform Overview`
2) `RPS Limiter - Service C Deep Dive`
3) `RPS Limiter - AI Adaptive Control`

Если нужно создать свои панели поверх готовых, используйте datasource `Prometheus` (он также провиженится автоматически).

## 3. Создай свой дашборд (опционально)
1) В левом меню нажми **Dashboards** → **New** → **New Dashboard**.  
2) Нажми **Add visualization** → выбери источник данных **Prometheus**.  
3) Ты попал в редактор панели.

## 4. Первая панель (RPS в rate‑limiter)
В поле запроса вставь:
```promql
sum(rate(ratelimiter_requests_total{job="service-c"}[1m]))
```
Нажми **Run queries** → увидишь график RPS.  

Рекомендации:
- **Visualization**: Time series
- **Unit**: `req/s`
- **Legend**: задай имя серии в поле **Legend** у запроса (например, `RPS`).

## 5. Панель отказов (доля 429)
Показывает долю отклонённых запросов:
```promql
sum(rate(ratelimiter_requests_total{job="service-c",decision="rejected"}[1m]))
/
sum(rate(ratelimiter_requests_total{job="service-c"}[1m]))
```
В **Unit** выбери `percent (0.0-1.0)`.

## 6. Панель p95 задержки (rate‑limiter)
```promql
histogram_quantile(
  0.95,
  sum(rate(ratelimiter_request_duration_seconds_bucket{job="service-c"}[5m])) by (le)
)
```
В **Unit** выбери `seconds (s)`.

## 7. Панели для load‑generator
Текущий RPS:
```promql
loadgen_current_rps{job="service-a"}
```
Ошибки/успехи:
```promql
sum(rate(loadgen_requests_total{job="service-a"}[1m])) by (status)
```
P95 задержки клиента:
```promql
histogram_quantile(
  0.95,
  sum(rate(loadgen_request_duration_seconds_bucket{job="service-a"}[5m])) by (le)
)
```

## 8. Панели для AI‑module
Запросы к AI:
```promql
rate(ai_limit_config_requests_total{job="ai-module"}[1m])
```
Рекомендованный лимит:
```promql
ai_last_recommended_limit{job="ai-module"}
```
Предсказанный RPS:
```promql
ai_last_predicted_rps{job="ai-module"}
```

## 9. Как называть и сохранять
1) В редакторе панели поменяй **Title** (например, `Rate limiter RPS`).  
2) Нажми **Apply** (справа сверху).  
3) На дашборде нажми **Save dashboard** и задай имя.

## 10. Базовые правила Prometheus‑метрик
- **Counter** — только растёт. В графике почти всегда используй `rate(...)`.
- **Gauge** — текущее значение. Можно отображать напрямую.
- **Histogram** — для квантилей используй `histogram_quantile(...)`.

## 11. Мини‑чеклист для новичка
- Есть метрики в Prometheus? Открой `http://localhost:9090/targets`
- Видишь метрики в Explore? Начни с `ratelimiter_` или `loadgen_`.
- Нет данных? Проверь, что сервисы запущены и отдаёт `/actuator/prometheus` или `/metrics`.

## 12. Если хочешь красивый дашборд быстро
Создай 5–8 панелей:
1) RPS (rate‑limiter)  
2) Доля 429  
3) P95 latency  
4) Redis connected  
5) Loadgen current RPS  
6) Loadgen errors  
7) AI predicted RPS  

Пример Redis availability:
```promql
ratelimiter_redis_connected{job="service-c"}
```
