#!/usr/bin/env bash
set -euo pipefail

A_URL="${A_URL:-http://localhost:8080}"
C_URL="${C_URL:-http://localhost:8082}"
TARGET_URL="${TARGET_URL:-http://rate-limiter-service:8082/api/test}"
DDOS_SECONDS="${DDOS_SECONDS:-720}"
RECOVERY_SECONDS="${RECOVERY_SECONDS:-720}"
BASE_RPS_LIMIT="${BASE_RPS_LIMIT:-100}"
WINDOW_SECONDS="${WINDOW_SECONDS:-10}"
BENCHMARK_CONCURRENCY="${BENCHMARK_CONCURRENCY:-256}"
RECOVERY_RPS="${RECOVERY_RPS:-40}"
OUTPUT_PREFIX="${OUTPUT_PREFIX:-monitoring/benchmarks/adaptive-ddos-recovery-soak-$(date +%Y%m%d-%H%M%S)}"
BENCHMARK_BUILD="${BENCHMARK_BUILD:-false}"
START_ALGORITHM="${START_ALGORITHM:-sliding}"
RESTORE_ADAPTIVE_ENABLED="${RESTORE_ADAPTIVE_ENABLED:-true}"
RESTORE_ADAPTIVE_APPLY_RECOMMENDATIONS="${RESTORE_ADAPTIVE_APPLY_RECOMMENDATIONS:-false}"
RESTORE_ALGORITHM="${RESTORE_ALGORITHM:-sliding}"

TIMELINE_CSV=""
PHASES_CSV=""
OVERALL_CSV=""
SWITCH_SUMMARY_CSV=""
ACTIVE_PHASE_NAMES=("ddos" "recovery")

usage() {
  cat <<'USAGE'
Run a long adaptive DDoS -> recovery soak benchmark.

Usage:
  scripts/adaptive_ddos_recovery_soak.sh [options]

Options:
  --ddos-seconds <seconds>      Attack phase duration (default: 720)
  --recovery-seconds <seconds>  Recovery phase duration (default: 720)
  --base-rps-limit <rps>        Rate-limiter budget (default: 100)
  --window <seconds>            Sliding window seconds (default: 10)
  --concurrency <n>             Load-generator concurrency cap (default: 256)
  --recovery-rps <rps>          Constant recovery load (default: 40)
  --start-algorithm <algo>      Initial algorithm: sliding or token (default: sliding)
  --build                       Rebuild images before start
  --output-prefix <prefix>      Output prefix (default: monitoring/benchmarks/adaptive-ddos-recovery-soak-<timestamp>)
  --help                        Show help
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --ddos-seconds)
      DDOS_SECONDS="$2"
      shift 2
      ;;
    --recovery-seconds)
      RECOVERY_SECONDS="$2"
      shift 2
      ;;
    --base-rps-limit)
      BASE_RPS_LIMIT="$2"
      shift 2
      ;;
    --window)
      WINDOW_SECONDS="$2"
      shift 2
      ;;
    --concurrency)
      BENCHMARK_CONCURRENCY="$2"
      shift 2
      ;;
    --recovery-rps)
      RECOVERY_RPS="$2"
      shift 2
      ;;
    --start-algorithm)
      START_ALGORITHM="$2"
      shift 2
      ;;
    --build)
      BENCHMARK_BUILD="true"
      shift
      ;;
    --output-prefix)
      OUTPUT_PREFIX="$2"
      shift 2
      ;;
    --help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      exit 1
      ;;
  esac
done

TOTAL_SECONDS=$(( DDOS_SECONDS + RECOVERY_SECONDS ))

for value_name in DDOS_SECONDS RECOVERY_SECONDS BASE_RPS_LIMIT WINDOW_SECONDS BENCHMARK_CONCURRENCY RECOVERY_RPS; do
  value="${!value_name}"
  if ! [[ "$value" =~ ^[0-9]+$ ]] || (( value <= 0 )); then
    echo "$value_name must be a positive integer" >&2
    exit 1
  fi
done

case "$START_ALGORITHM" in
  sliding|token)
    ;;
  *)
    echo "--start-algorithm must be sliding or token" >&2
    exit 1
    ;;
esac

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Required command not found: $1" >&2
    exit 1
  }
}

require_cmd curl
require_cmd awk
require_cmd python3
require_cmd docker

curl_call() {
  curl --retry 5 --retry-delay 1 --retry-all-errors -fsS "$@"
}

wait_for_http() {
  local url="$1"
  local name="$2"
  local timeout="${3:-90}"
  local waited=0
  while (( waited < timeout )); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
    waited=$(( waited + 1 ))
  done
  echo "Timeout waiting for $name at $url" >&2
  return 1
}

stop_test_if_running() {
  curl -s -X POST "$A_URL/test/stop" >/dev/null 2>&1 || true
}

prepare_stack() {
  if [[ "$BENCHMARK_BUILD" == "true" ]]; then
    docker compose build ai-module rate-limiter-service load-generator-service application-service >/dev/null
  fi
  docker compose up -d redis application-service ai-module load-generator-service >/dev/null
}

reset_load_generator() {
  docker compose restart load-generator-service >/dev/null
  wait_for_http "$A_URL/actuator/health" "load-generator-service"
}

set_rate_limiter_mode() {
  local enabled="$1"
  local apply_recommendations="$2"
  ADAPTIVE_ENABLED="$enabled" ADAPTIVE_APPLY_RECOMMENDATIONS="$apply_recommendations" \
    docker compose up -d rate-limiter-service >/dev/null
  wait_for_http "$C_URL/actuator/health" "rate-limiter-service"
}

reset_adaptive_services() {
  ADAPTIVE_ENABLED=true ADAPTIVE_APPLY_RECOMMENDATIONS=true docker compose up -d rate-limiter-service >/dev/null
  docker compose restart ai-module rate-limiter-service >/dev/null
  wait_for_http "$C_URL/actuator/health" "rate-limiter-service"
}

configure_limits() {
  local algorithm="$1"
  local window="$WINDOW_SECONDS"
  local limit=$(( BASE_RPS_LIMIT * window ))
  local fill_rate="$BASE_RPS_LIMIT"
  local capacity=$(( BASE_RPS_LIMIT * 2 ))
  curl_call -X POST "$C_URL/config/limits" \
    -H 'Content-Type: application/json' \
    -d "{\"algorithm\":\"$algorithm\",\"limit\":$limit,\"window\":$window,\"capacity\":$capacity,\"fillRate\":$fill_rate}" >/dev/null
}

metric_from_text() {
  local text="$1"
  local metric="$2"
  echo "$text" | awk -v m="$metric" '$1==m {print $2; found=1; exit} END {if (!found) print "0"}'
}

delta_value() {
  local start="$1"
  local end="$2"
  awk -v s="$start" -v e="$end" 'BEGIN {d=e-s; if (d<0) d=0; printf "%.6f", d}'
}

latency_percentiles_ms() {
  local before_file="$1"
  local after_file="$2"
  python3 - "$before_file" "$after_file" <<'PY'
import re
import sys

before_path, after_path = sys.argv[1], sys.argv[2]
pattern = re.compile(r'^ratelimiter_request_duration_seconds_bucket\{[^}]*le="([^"]+)"[^}]*\}\s+([0-9eE+.-]+)$')

def parse(path):
    result = {}
    with open(path, 'r', encoding='utf-8') as handle:
        for raw_line in handle:
            line = raw_line.strip()
            match = pattern.match(line)
            if not match:
                continue
            result[match.group(1)] = float(match.group(2))
    return result

before = parse(before_path)
after = parse(after_path)
deltas = {}
for le, value_after in after.items():
    value_before = before.get(le, 0.0)
    delta = value_after - value_before
    if delta < 0:
        delta = 0.0
    deltas[le] = delta

total = deltas.get('+Inf', 0.0)
if total <= 0:
    print('0.000')
    raise SystemExit(0)

finite = []
for le, cumulative in deltas.items():
    if le == '+Inf':
        continue
    try:
        upper = float(le)
    except ValueError:
        continue
    finite.append((upper, cumulative))
finite.sort(key=lambda item: item[0])

def quantile_value(q):
    target = total * q
    prev_cumulative = 0.0
    prev_upper = 0.0
    for upper, cumulative in finite:
        if cumulative >= target:
            bucket_count = cumulative - prev_cumulative
            if bucket_count <= 0:
                return upper
            fraction = (target - prev_cumulative) / bucket_count
            fraction = max(0.0, min(1.0, fraction))
            return prev_upper + (upper - prev_upper) * fraction
        prev_cumulative = cumulative
        prev_upper = upper
    return finite[-1][0]

print(f'{quantile_value(0.95) * 1000.0:.3f}')
PY
}

algorithm_from_json() {
  local payload="$1"
  local algorithm
  algorithm=$(echo "$payload" | sed -n 's/.*"algorithm":"\([^"]*\)".*/\1/p')
  if [[ -z "$algorithm" ]]; then
    algorithm="unknown"
  fi
  echo "$algorithm"
}

status_running_elapsed() {
  local status running elapsed
  status=$(curl_call "$A_URL/test/status")
  running=$(echo "$status" | sed -n 's/.*"running":\([a-z]*\).*/\1/p')
  elapsed=$(echo "$status" | sed -n 's/.*"elapsedTime":\([0-9]*\).*/\1/p')
  [[ -z "$running" ]] && running="false"
  [[ -z "$elapsed" ]] && elapsed="0"
  echo "$running,$elapsed"
}

wait_until_elapsed() {
  local target="$1"
  local timeout=$(( target + 120 ))
  local waited=0
  while (( waited < timeout )); do
    local status running elapsed
    status="$(status_running_elapsed)"
    IFS=',' read -r running elapsed <<<"$status"
    if (( elapsed >= target )); then
      return 0
    fi
    if [[ "$running" != "true" ]] && (( elapsed < target )); then
      return 1
    fi
    sleep 1
    waited=$(( waited + 1 ))
  done
  return 1
}

wait_test_finished() {
  local timeout=$(( TOTAL_SECONDS + 180 ))
  local waited=0
  while (( waited < timeout )); do
    local status running
    status="$(status_running_elapsed)"
    IFS=',' read -r running _ <<<"$status"
    if [[ "$running" != "true" ]]; then
      return 0
    fi
    sleep 1
    waited=$(( waited + 1 ))
  done
  return 1
}

phase_name_for_elapsed() {
  local elapsed="$1"
  if (( elapsed < DDOS_SECONDS )); then
    echo "ddos"
  else
    echo "recovery"
  fi
}

sample_timeline() {
  local out="$1"
  local last_elapsed="-1"
  local last_algorithm="unknown"
  while true; do
    local status running elapsed config algorithm phase
    status="$(status_running_elapsed)"
    IFS=',' read -r running elapsed <<<"$status"
    if [[ "$running" != "true" ]]; then
      if [[ "$last_elapsed" != "-1" ]]; then
        config=$(curl_call "$C_URL/config/limits" 2>/dev/null || echo '{}')
        algorithm="$(algorithm_from_json "$config")"
        if [[ "$algorithm" != "$last_algorithm" ]]; then
          phase="$(phase_name_for_elapsed "$last_elapsed")"
          printf "%d,%s,%s\n" "$(( last_elapsed + 1 ))" "$phase" "$algorithm" >>"$out"
        fi
      fi
      break
    fi
    if [[ "$elapsed" != "$last_elapsed" ]]; then
      config=$(curl_call "$C_URL/config/limits" 2>/dev/null || echo '{}')
      algorithm="$(algorithm_from_json "$config")"
      phase="$(phase_name_for_elapsed "$elapsed")"
      printf "%s,%s,%s\n" "$elapsed" "$phase" "$algorithm" >>"$out"
      last_elapsed="$elapsed"
      last_algorithm="$algorithm"
    fi
    sleep 1
  done
}

append_phase_row() {
  local phase_order="$1"
  local phase_name="$2"
  local phase_duration="$3"
  local before_c="$4"
  local before_a="$5"
  local before_hist="$6"
  local after_c="$7"
  local after_a="$8"
  local after_hist="$9"

  local f0 r0 dsum0 dcnt0 fx0 tk0 sl0
  local f1 r1 dsum1 dcnt1 fx1 tk1 sl1
  local as0 ar0 ae0
  local as1 ar1 ae1

  f0="$(metric_from_text "$before_c" 'ratelimiter_requests_total{decision="forwarded"}')"
  r0="$(metric_from_text "$before_c" 'ratelimiter_requests_total{decision="rejected"}')"
  dsum0="$(metric_from_text "$before_c" 'ratelimiter_request_duration_seconds_sum')"
  dcnt0="$(metric_from_text "$before_c" 'ratelimiter_request_duration_seconds_count')"
  fx0="$(metric_from_text "$before_c" 'ratelimiter_requests_by_algorithm_total{algorithm="fixed"}')"
  tk0="$(metric_from_text "$before_c" 'ratelimiter_requests_by_algorithm_total{algorithm="token"}')"
  sl0="$(metric_from_text "$before_c" 'ratelimiter_requests_by_algorithm_total{algorithm="sliding"}')"
  as0="$(metric_from_text "$before_a" 'loadgen_requests_total{status="success"}')"
  ar0="$(metric_from_text "$before_a" 'loadgen_requests_total{status="rate_limited"}')"
  ae0="$(metric_from_text "$before_a" 'loadgen_requests_total{status="error"}')"

  f1="$(metric_from_text "$after_c" 'ratelimiter_requests_total{decision="forwarded"}')"
  r1="$(metric_from_text "$after_c" 'ratelimiter_requests_total{decision="rejected"}')"
  dsum1="$(metric_from_text "$after_c" 'ratelimiter_request_duration_seconds_sum')"
  dcnt1="$(metric_from_text "$after_c" 'ratelimiter_request_duration_seconds_count')"
  fx1="$(metric_from_text "$after_c" 'ratelimiter_requests_by_algorithm_total{algorithm="fixed"}')"
  tk1="$(metric_from_text "$after_c" 'ratelimiter_requests_by_algorithm_total{algorithm="token"}')"
  sl1="$(metric_from_text "$after_c" 'ratelimiter_requests_by_algorithm_total{algorithm="sliding"}')"
  as1="$(metric_from_text "$after_a" 'loadgen_requests_total{status="success"}')"
  ar1="$(metric_from_text "$after_a" 'loadgen_requests_total{status="rate_limited"}')"
  ae1="$(metric_from_text "$after_a" 'loadgen_requests_total{status="error"}')"

  local forwarded rejected total success_pct reject_pct effective_rps
  local dsum dcnt avg_latency_ms p95_latency_ms
  local load_success load_rate_limited load_errors load_total error_pct
  local fixed_delta token_delta sliding_delta fixed_share token_share sliding_share

  forwarded="$(delta_value "$f0" "$f1")"
  rejected="$(delta_value "$r0" "$r1")"
  total="$(awk -v f="$forwarded" -v r="$rejected" 'BEGIN {printf "%.6f", f+r}')"
  success_pct="$(awk -v f="$forwarded" -v t="$total" 'BEGIN {if (t<=0) printf "0.00"; else printf "%.2f", (f*100.0)/t}')"
  reject_pct="$(awk -v r="$rejected" -v t="$total" 'BEGIN {if (t<=0) printf "0.00"; else printf "%.2f", (r*100.0)/t}')"
  effective_rps="$(awk -v t="$total" -v d="$phase_duration" 'BEGIN {printf "%.3f", t/d}')"
  dsum="$(delta_value "$dsum0" "$dsum1")"
  dcnt="$(delta_value "$dcnt0" "$dcnt1")"
  avg_latency_ms="$(awk -v s="$dsum" -v c="$dcnt" 'BEGIN {if (c<=0) printf "0.000"; else printf "%.3f", (s/c)*1000.0}')"
  p95_latency_ms="$(latency_percentiles_ms "$before_hist" "$after_hist")"

  load_success="$(delta_value "$as0" "$as1")"
  load_rate_limited="$(delta_value "$ar0" "$ar1")"
  load_errors="$(delta_value "$ae0" "$ae1")"
  load_total="$(awk -v s="$load_success" -v r="$load_rate_limited" -v e="$load_errors" 'BEGIN {printf "%.6f", s+r+e}')"
  error_pct="$(awk -v e="$load_errors" -v t="$load_total" 'BEGIN {if (t<=0) printf "0.00"; else printf "%.2f", (e*100.0)/t}')"

  fixed_delta="$(delta_value "$fx0" "$fx1")"
  token_delta="$(delta_value "$tk0" "$tk1")"
  sliding_delta="$(delta_value "$sl0" "$sl1")"
  fixed_share="$(awk -v a="$fixed_delta" -v t="$total" 'BEGIN {if (t<=0) printf "0.00"; else printf "%.2f", (a*100.0)/t}')"
  token_share="$(awk -v a="$token_delta" -v t="$total" 'BEGIN {if (t<=0) printf "0.00"; else printf "%.2f", (a*100.0)/t}')"
  sliding_share="$(awk -v a="$sliding_delta" -v t="$total" 'BEGIN {if (t<=0) printf "0.00"; else printf "%.2f", (a*100.0)/t}')"

  printf "%d,%s,%d,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s\n" \
    "$phase_order" "$phase_name" "$phase_duration" "$total" "$forwarded" "$rejected" \
    "$success_pct" "$reject_pct" "$effective_rps" "$load_total" "$load_errors" "$error_pct" \
    "$avg_latency_ms" "$p95_latency_ms" "$token_share" "$sliding_share" "$fixed_share" >>"$PHASES_CSV"
}

write_switch_summary() {
  local timeline_file="$1"
  python3 - "$timeline_file" "$SWITCH_SUMMARY_CSV" <<'PY'
import csv
import sys
from collections import defaultdict

path, out_path = sys.argv[1], sys.argv[2]
rows = []
with open(path, 'r', encoding='utf-8', newline='') as handle:
    reader = csv.DictReader(handle)
    for row in reader:
        rows.append(row)

seconds = defaultdict(float)
switch_count = 0
sequence = []
previous = None
for row in rows:
    algorithm = row['algorithm']
    seconds[algorithm] += 1.0
    if previous != algorithm:
        if previous is not None:
            switch_count += 1
        sequence.append(f"{row['elapsed_seconds']}:{algorithm}")
        previous = algorithm

with open(out_path, 'w', encoding='utf-8', newline='') as handle:
    writer = csv.writer(handle)
    writer.writerow(['mode', 'switch_count', 'token_seconds', 'sliding_seconds', 'fixed_seconds', 'unknown_seconds', 'sequence'])
    writer.writerow([
        'adaptive_ddos_recovery_soak',
        switch_count,
        f"{seconds['token']:.0f}",
        f"{seconds['sliding']:.0f}",
        f"{seconds['fixed']:.0f}",
        f"{seconds['unknown']:.0f}",
        '|'.join(sequence),
    ])
PY
}

write_overall_summary() {
  local phases_file="$1"
  python3 - "$phases_file" "$OVERALL_CSV" <<'PY'
import csv
import sys

phases_path, out_path = sys.argv[1], sys.argv[2]
rows = []
with open(phases_path, 'r', encoding='utf-8', newline='') as handle:
    reader = csv.DictReader(handle)
    rows.extend(reader)

total_requests = sum(float(row['total_requests']) for row in rows)
forwarded = sum(float(row['forwarded']) for row in rows)
rejected = sum(float(row['rejected']) for row in rows)
weighted_avg_latency = 0.0
weighted_p95_latency = 0.0
if total_requests > 0:
    weighted_avg_latency = sum(float(row['avg_latency_ms']) * float(row['total_requests']) for row in rows) / total_requests
    weighted_p95_latency = sum(float(row['p95_latency_ms']) * float(row['total_requests']) for row in rows) / total_requests
success_percent = 0.0 if total_requests <= 0 else (forwarded * 100.0) / total_requests
reject_percent = 0.0 if total_requests <= 0 else (rejected * 100.0) / total_requests

with open(out_path, 'w', encoding='utf-8', newline='') as handle:
    writer = csv.writer(handle)
    writer.writerow(['mode', 'total_requests', 'forwarded', 'rejected', 'success_percent', 'reject_percent', 'weighted_avg_latency_ms', 'weighted_p95_latency_ms'])
    writer.writerow([
        'adaptive_ddos_recovery_soak',
        f'{total_requests:.0f}',
        f'{forwarded:.0f}',
        f'{rejected:.0f}',
        f'{success_percent:.2f}',
        f'{reject_percent:.2f}',
        f'{weighted_avg_latency:.3f}',
        f'{weighted_p95_latency:.3f}',
    ])
PY
}

start_test() {
  local body
  body=$(cat <<JSON
{
  "targetUrl": "$TARGET_URL",
  "duration": "PT${TOTAL_SECONDS}S",
  "profile": {
    "type": "phased",
    "params": {
      "phases": [
        {
          "name": "ddos",
          "duration": "PT${DDOS_SECONDS}S",
          "type": "ddos",
          "params": {
            "minRps": 35,
            "maxRps": 320,
            "maxSpikeDuration": "PT2S",
            "minIdleTime": "PT0S",
            "maxIdleTime": "PT1S"
          }
        },
        {
          "name": "recovery",
          "duration": "PT${RECOVERY_SECONDS}S",
          "type": "constant",
          "params": {
            "rps": ${RECOVERY_RPS}
          }
        }
      ]
    }
  },
  "concurrency": ${BENCHMARK_CONCURRENCY}
}
JSON
)
  curl_call -X POST "$A_URL/test/start" -H 'Content-Type: application/json' -d "$body"
}

cleanup() {
  stop_test_if_running || true
  ADAPTIVE_ENABLED="$RESTORE_ADAPTIVE_ENABLED" \
  ADAPTIVE_APPLY_RECOMMENDATIONS="$RESTORE_ADAPTIVE_APPLY_RECOMMENDATIONS" \
    docker compose up -d rate-limiter-service >/dev/null 2>&1 || true
  wait_for_http "$C_URL/actuator/health" "rate-limiter-service" 30 || true
  configure_limits "$RESTORE_ALGORITHM" >/dev/null 2>&1 || true
}
trap cleanup EXIT

prepare_stack
wait_for_http "$A_URL/actuator/health" "load-generator-service"
wait_for_http "$C_URL/actuator/health" "rate-limiter-service"
reset_load_generator
stop_test_if_running
set_rate_limiter_mode true true
reset_adaptive_services
configure_limits "$START_ALGORITHM"

TIMELINE_CSV="${OUTPUT_PREFIX}.timeline.csv"
PHASES_CSV="${OUTPUT_PREFIX}.phases.csv"
OVERALL_CSV="${OUTPUT_PREFIX}.overall.csv"
SWITCH_SUMMARY_CSV="${OUTPUT_PREFIX}.switch-summary.csv"

echo "elapsed_seconds,phase_name,algorithm" >"$TIMELINE_CSV"
echo "phase_order,phase_name,duration_s,total_requests,forwarded,rejected,success_percent,reject_percent,effective_rps,loadgen_total,loadgen_errors,error_percent,avg_latency_ms,p95_latency_ms,token_share_percent,sliding_share_percent,fixed_share_percent" >"$PHASES_CSV"

before_c="$(curl_call "$C_URL/actuator/prometheus")"
before_c_hist="$(mktemp)"
printf '%s\n' "$before_c" >"$before_c_hist"

start_response="$(start_test)"
if ! echo "$start_response" | grep -q '"status":"started"'; then
  echo "Failed to start soak test: $start_response" >&2
  rm -f "$before_c_hist"
  exit 1
fi

sleep 0.2
before_a="$(curl_call "$A_URL/actuator/prometheus")"

timeline_tmp="$(mktemp)"
echo "elapsed_seconds,phase_name,algorithm" >"$timeline_tmp"
sample_timeline "$timeline_tmp" &
timeline_pid="$!"

wait_until_elapsed "$DDOS_SECONDS" || {
  echo "DDoS phase timeout" >&2
  rm -f "$before_c_hist" "$timeline_tmp"
  exit 1
}

after_c="$(curl_call "$C_URL/actuator/prometheus")"
after_a="$(curl_call "$A_URL/actuator/prometheus")"
after_c_hist="$(mktemp)"
printf '%s\n' "$after_c" >"$after_c_hist"
append_phase_row 1 ddos "$DDOS_SECONDS" "$before_c" "$before_a" "$before_c_hist" "$after_c" "$after_a" "$after_c_hist"
rm -f "$before_c_hist"
before_c="$after_c"
before_a="$after_a"
before_c_hist="$after_c_hist"

wait_test_finished || {
  echo "Recovery phase timeout" >&2
  rm -f "$before_c_hist" "$timeline_tmp"
  exit 1
}

after_c="$(curl_call "$C_URL/actuator/prometheus")"
after_a="$(curl_call "$A_URL/actuator/prometheus")"
after_c_hist="$(mktemp)"
printf '%s\n' "$after_c" >"$after_c_hist"
append_phase_row 2 recovery "$RECOVERY_SECONDS" "$before_c" "$before_a" "$before_c_hist" "$after_c" "$after_a" "$after_c_hist"
rm -f "$before_c_hist" "$after_c_hist"

wait "$timeline_pid"
tail -n +2 "$timeline_tmp" >>"$TIMELINE_CSV"
rm -f "$timeline_tmp"

write_switch_summary "$TIMELINE_CSV"
write_overall_summary "$PHASES_CSV"

echo "Phases CSV: $PHASES_CSV"
echo "Overall CSV: $OVERALL_CSV"
echo "Switch summary CSV: $SWITCH_SUMMARY_CSV"
echo "Timeline CSV: $TIMELINE_CSV"
