# Демонстрации стенда

## 1. Подготовка

Требования:
- Docker и Docker Compose.
- Свободные порты: `3000`, `6379`, `8080`, `8081`, `8082`, `8083`, `9090`.

Работать из корня проекта:

```bash
cd /Users/islam/IdeaProjects/RPS-limiter
export A_URL=http://localhost:8080
export B_URL=http://localhost:8081
export C_URL=http://localhost:8082
export AI_URL=http://localhost:8083
```

## 2. Запуск всего стенда

```bash
ADAPTIVE_APPLY_RECOMMENDATIONS=true TOKEN_TUNER_ENABLED=true docker compose up --build -d
docker compose ps
```

- `load-generator-service` генерирует разные профили нагрузки.
- `application-service` имитирует целевой сервис.
- `rate-limiter-service` стоит между ними как proxy и ограничитель RPS.
- `AI-RPS-limiter` анализирует метрики и рекомендует алгоритм/лимиты.
- Redis хранит состояние rate limiter.
- Prometheus и Grafana показывают метрики.

## 3. Проверка доступности

```bash
for u in "$A_URL/actuator/health" "$B_URL/actuator/health" "$C_URL/actuator/health" "$AI_URL/health"; do
  echo "$u"
  curl -s "$u"
  echo
done
```

Ожидание: у Java-сервисов `{"status":"UP"}`, у AI-модуля `{"status":"UP"}`.

## 4. Быстрая проверка, что limiter реально режет трафик

```bash
curl -s -X POST "$C_URL/config/limits" \
  -H 'Content-Type: application/json' \
  -d '{"algorithm":"fixed","limit":2,"window":60,"capacity":10,"fillRate":10}'

for i in {1..8}; do
  curl -s -o /dev/null -w "%{http_code}\n" "$C_URL/api/test"
done
```

Сначала будут `200`, затем появятся `429`.

Это ручной фиксированный лимит. Он доказывает, что Service C не просто проксирует запросы, а реально принимает решение пропускать или отклонять запрос.

## 5. Подготовка adaptive-режима

```bash
curl -s -X POST "$C_URL/config/limits" \
  -H 'Content-Type: application/json' \
  -d '{"algorithm":"sliding","limit":1000,"window":10,"capacity":200,"fillRate":100}'

curl -s "$C_URL/config/limits"
```

Стартовый алгоритм `sliding`, auto-apply уже включен через `ADAPTIVE_APPLY_RECOMMENDATIONS=true`.

## 6. Открыть Grafana

URL:

```text
http://localhost:3000
```

Логин/пароль:

```text
admin / admin
```

Показать готовые дашборды:
- `RPS Limiter - Platform Overview`
- `RPS Limiter - Service C Deep Dive`
- `RPS Limiter - AI Adaptive Control`

На что смотреть:
- текущий RPS;
- доля `429`;
- `Current Algorithm`;
- `Algorithm Switches`;
- `Config Applies`;
- AI observed/predicted/recommended RPS;
- AI selector signals.

## 7. Основная демонстрация adaptive-контура

Запустить нагрузку `normal -> burst -> recovery`:

```bash
curl -s -X POST "$A_URL/test/start" \
  -H 'Content-Type: application/json' \
  -d '{
    "targetUrl":"http://rate-limiter-service:8082/api/test",
    "duration":"PT90S",
    "concurrency":256,
    "profile":{
      "type":"phased",
      "params":{
        "phases":[
          {"name":"normal","duration":"PT30S","type":"constant","params":{"rps":40}},
          {"name":"burst","duration":"PT30S","type":"burst","params":{"baseRps":40,"spikeRps":280,"spikeDuration":"PT2S","spikePeriod":"PT6S"}},
          {"name":"recovery","duration":"PT30S","type":"constant","params":{"rps":40}}
        ]
      }
    }
  }'
```

Во втором терминале:

```bash
while true; do
  date '+%H:%M:%S'
  curl -s "$A_URL/test/status"
  echo
  curl -s "$C_URL/config/limits"
  echo
  curl -s "$C_URL/actuator/prometheus" | grep -E '^(ratelimiter_current_algorithm|ratelimiter_algorithm_switch_total|ratelimiter_config_applied_total|ratelimiter_adaptive_apply_enabled|ratelimiter_adaptive_recommendations_total|ratelimiter_requests_total)'
  sleep 5
done
```

Ожидание:
- на фазе `normal` система стабильно работает в `sliding`;
- на фазе `burst` AI видит всплеск и рекомендует более подходящую конфигурацию, обычно переход в `token`;
- Service C применяет рекомендацию, что видно по `ratelimiter_algorithm_switch_total` и `ratelimiter_config_applied_total`;
- на фазе `recovery` контур стабилизируется.

> В эксперименте меняется профиль нагрузки. Rate limiter собирает телеметрию, AI-модуль каждые несколько секунд получает агрегированные признаки, выбирает подходящий алгоритм и рекомендует параметры. В apply-режиме Service C применяет эти рекомендации без ручного вмешательства. На графиках видно, как при всплеске меняется конфигурация, а после восстановления контур возвращается к стабильной обработке.

## 8. Формальные цифры

Быстрый воспроизводимый benchmark:

```bash
TOKEN_TUNER_ENABLED=true bash scripts/adaptive_phase_benchmark.sh \
  --scenarios phase_universal_mix \
  --phase-seconds 30 \
  --repeats 1 \
  --adaptive-start-algorithm sliding \
  --output-prefix monitoring/benchmarks/defense-universal-$(date +%Y%m%d-%H%M%S)
```

Он дольше живой демонстрации, но создаёт артефакты:
- `*.raw.csv`
- `*.summary.csv`
- `*.switch-summary.csv`
- `*.timeline.csv`
- `*.figures/`

## 9. fallback

Если Grafana или benchmark не отвечают:

```bash
curl -s "$C_URL/config/limits"
curl -s "$A_URL/test/status"
curl -s "$C_URL/actuator/prometheus" | grep -E '^(ratelimiter_requests_total|ratelimiter_current_algorithm|ratelimiter_algorithm_switch_total|ratelimiter_config_applied_total)'
curl -s "$AI_URL/metrics" | grep -E '^(ai_limit_config_requests_total|ai_last_algorithm|ai_recommendation_switch_total|ai_selector_signal_active)'
```

Это доказывает:
- нагрузка идет через Service A;
- Service C считает forwarded/rejected;
- AI-модуль получает запросы;
- adaptive-рекомендации и переключения отражаются в метриках.

## 10. Остановка и возврат в безопасный режим

```bash
curl -s -X POST "$A_URL/test/stop" || true
ADAPTIVE_APPLY_RECOMMENDATIONS=false docker compose up -d rate-limiter-service
docker compose down
```

Если нужно удалить данные Prometheus/Grafana:

```bash
docker compose down -v
```
