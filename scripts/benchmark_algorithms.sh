#!/usr/bin/env bash
set -euo pipefail

A_URL="${A_URL:-http://localhost:8080}"
C_URL="${C_URL:-http://localhost:8082}"
TARGET_URL="${TARGET_URL:-http://rate-limiter-service:8082/api/test}"
DURATION_SECONDS=20
SCENARIOS_CSV="constant_low,burst,sinusoidal,ddos"
BASE_RPS_LIMIT="${BASE_RPS_LIMIT:-100}"
WINDOW_SECONDS="${WINDOW_SECONDS:-10}"
REPEATS=10
RANDOMIZE_ORDER=1
SEED="$(date +%s)"
OUTPUT_FILE=""
DISABLE_ADAPTIVE=0

usage() {
  cat <<'EOF'
Compare fixed/sliding/token across load scenarios with repeated runs.

Usage:
  scripts/benchmark_algorithms.sh [options]

Options:
  --duration <seconds>        Test duration per run (default: 20)
  --scenarios <csv>           Scenarios to run (default: constant_low,burst,sinusoidal,ddos)
  --base-rps-limit <rps>      Common limit budget for all algorithms (default: 100)
  --window <seconds>          Window for fixed/sliding (default: 10)
  --repeats <n>               Repeats per scenario (default: 10)
  --seed <int>                Seed for deterministic randomized order
  --no-random-order           Keep fixed order fixed->sliding->token
  --output <path>             CSV output path (default: ./benchmark-YYYYmmdd-HHMMSS.csv)
  --disable-adaptive          Restart rate-limiter with ADAPTIVE_ENABLED=false before benchmark
  --help                      Show this help

Scenarios:
  constant_low, burst, sinusoidal, ddos, constant_high, poisson
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --duration)
      DURATION_SECONDS="$2"
      shift 2
      ;;
    --scenarios)
      SCENARIOS_CSV="$2"
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
    --repeats)
      REPEATS="$2"
      shift 2
      ;;
    --seed)
      SEED="$2"
      shift 2
      ;;
    --no-random-order)
      RANDOMIZE_ORDER=0
      shift
      ;;
    --output)
      OUTPUT_FILE="$2"
      shift 2
      ;;
    --disable-adaptive)
      DISABLE_ADAPTIVE=1
      shift
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

if ! [[ "$DURATION_SECONDS" =~ ^[0-9]+$ ]] || (( DURATION_SECONDS <= 0 )); then
  echo "--duration must be a positive integer" >&2
  exit 1
fi
if ! [[ "$BASE_RPS_LIMIT" =~ ^[0-9]+$ ]] || (( BASE_RPS_LIMIT <= 0 )); then
  echo "--base-rps-limit must be a positive integer" >&2
  exit 1
fi
if ! [[ "$WINDOW_SECONDS" =~ ^[0-9]+$ ]] || (( WINDOW_SECONDS <= 0 )); then
  echo "--window must be a positive integer" >&2
  exit 1
fi
if ! [[ "$REPEATS" =~ ^[0-9]+$ ]] || (( REPEATS <= 0 )); then
  echo "--repeats must be a positive integer" >&2
  exit 1
fi
if ! [[ "$SEED" =~ ^[0-9]+$ ]]; then
  echo "--seed must be a non-negative integer" >&2
  exit 1
fi

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Required command not found: $1" >&2
    exit 1
  }
}

require_cmd curl
require_cmd awk
require_cmd sed
require_cmd mktemp
require_cmd python3

curl_call() {
  curl --retry 5 --retry-delay 1 --retry-all-errors -fsS "$@"
}

wait_for_http() {
  local url="$1"
  local name="$2"
  local timeout="${3:-60}"
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

cleanup() {
  stop_test_if_running || true
}
trap cleanup EXIT

if [[ -z "$OUTPUT_FILE" ]]; then
  OUTPUT_FILE="./benchmark-$(date +%Y%m%d-%H%M%S).csv"
fi

if (( DISABLE_ADAPTIVE == 1 )); then
  require_cmd docker
  echo "Restarting rate-limiter with ADAPTIVE_ENABLED=false for fair comparison..."
  ADAPTIVE_ENABLED=false docker compose up -d --build rate-limiter-service >/dev/null
fi

wait_for_http "$A_URL/actuator/health" "load-generator-service"
wait_for_http "$C_URL/actuator/health" "rate-limiter-service"

scenario_profile_json() {
  case "$1" in
    constant_low)
      echo '{"type":"constant","params":{"rps":40}}'
      ;;
    constant_high)
      echo '{"type":"constant","params":{"rps":180}}'
      ;;
    poisson)
      echo '{"type":"poisson","params":{"averageRps":140}}'
      ;;
    burst)
      echo '{"type":"burst","params":{"baseRps":15,"spikeRps":220,"spikeDuration":"PT2S","spikePeriod":"PT8S"}}'
      ;;
    sinusoidal)
      echo '{"type":"sinusoidal","params":{"minRps":10,"maxRps":180,"period":"PT12S"}}'
      ;;
    ddos)
      echo '{"type":"ddos","params":{"minRps":30,"maxRps":320,"maxSpikeDuration":"PT2S","minIdleTime":"PT0S","maxIdleTime":"PT1S"}}'
      ;;
    *)
      return 1
      ;;
  esac
}

configure_algorithm() {
  local algo="$1"
  local window="$WINDOW_SECONDS"
  local limit=$(( BASE_RPS_LIMIT * window ))
  local fill_rate="$BASE_RPS_LIMIT"
  local capacity=$(( BASE_RPS_LIMIT * 2 ))

  curl_call -X POST "$C_URL/config/limits" \
    -H 'Content-Type: application/json' \
    -d "{\"algorithm\":\"$algo\",\"limit\":$limit,\"window\":$window,\"capacity\":$capacity,\"fillRate\":$fill_rate}" >/dev/null
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

start_test() {
  local profile_json="$1"
  local body
  body=$(cat <<EOF
{
  "targetUrl": "$TARGET_URL",
  "duration": "PT${DURATION_SECONDS}S",
  "profile": $profile_json
}
EOF
)

  curl_call -X POST "$A_URL/test/start" \
    -H 'Content-Type: application/json' \
    -d "$body"
}

wait_test_finished() {
  local timeout=$(( DURATION_SECONDS + 45 ))
  local waited=0
  while (( waited < timeout )); do
    local status
    status=$(curl_call "$A_URL/test/status")
    local running
    running=$(echo "$status" | sed -n 's/.*"running":\([a-z]*\).*/\1/p')
    if [[ "$running" != "true" ]]; then
      return 0
    fi
    sleep 1
    waited=$(( waited + 1 ))
  done
  return 1
}

algorithm_order_csv() {
  local repeat="$1"
  local scenario_index="$2"
  if (( RANDOMIZE_ORDER == 0 )); then
    echo "fixed,sliding,token"
    return 0
  fi
  python3 - "$SEED" "$repeat" "$scenario_index" <<'PY'
import random
import sys

seed = int(sys.argv[1])
repeat = int(sys.argv[2])
scenario_index = int(sys.argv[3])
algos = ["fixed", "sliding", "token"]
rng = random.Random(seed + repeat * 1009 + scenario_index * 9176)
rng.shuffle(algos)
print(",".join(algos))
PY
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
    with open(path, "r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            match = pattern.match(line)
            if not match:
                continue
            le = match.group(1)
            value = float(match.group(2))
            result[le] = value
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

total = deltas.get("+Inf", 0.0)
if total <= 0:
    print("0.000,0.000")
    sys.exit(0)

finite = []
for le, cumulative in deltas.items():
    if le == "+Inf":
        continue
    try:
        upper = float(le)
    except ValueError:
        continue
    finite.append((upper, cumulative))
finite.sort(key=lambda item: item[0])

if not finite:
    print("0.000,0.000")
    sys.exit(0)

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
            if fraction < 0:
                fraction = 0
            if fraction > 1:
                fraction = 1
            return prev_upper + (upper - prev_upper) * fraction
        prev_cumulative = cumulative
        prev_upper = upper
    return finite[-1][0]

p95_ms = quantile_value(0.95) * 1000.0
p99_ms = quantile_value(0.99) * 1000.0
print(f"{p95_ms:.3f},{p99_ms:.3f}")
PY
}

echo "scenario,repeat,order_pos,algorithm,total_requests,forwarded,rejected,reject_percent,effective_rps,loadgen_total,loadgen_errors,error_percent,avg_proxy_latency_ms,p95_proxy_latency_ms,p99_proxy_latency_ms,algo_counter_delta,foreign_algo_delta" >"$OUTPUT_FILE"

IFS=',' read -r -a scenarios <<<"$SCENARIOS_CSV"

echo "Running benchmark..."
echo "A_URL=$A_URL"
echo "C_URL=$C_URL"
echo "TARGET_URL=$TARGET_URL"
echo "duration=${DURATION_SECONDS}s base_rps_limit=$BASE_RPS_LIMIT window=${WINDOW_SECONDS}s repeats=$REPEATS"
echo "randomize_order=$RANDOMIZE_ORDER seed=$SEED"
echo

for scenario_index in "${!scenarios[@]}"; do
  scenario="${scenarios[$scenario_index]}"
  profile_json="$(scenario_profile_json "$scenario")" || {
    echo "Unsupported scenario: $scenario" >&2
    exit 1
  }

  for repeat in $(seq 1 "$REPEATS"); do
    order_csv="$(algorithm_order_csv "$repeat" "$scenario_index")"
    IFS=',' read -r -a run_algorithms <<<"$order_csv"
    order_pos=0

    for algo in "${run_algorithms[@]}"; do
      order_pos=$(( order_pos + 1 ))
      stop_test_if_running
      configure_algorithm "$algo"

      before="$(curl_call "$C_URL/actuator/prometheus")"
      before_hist_file="$(mktemp)"
      after_hist_file="$(mktemp)"
      printf '%s\n' "$before" >"$before_hist_file"

      f0="$(metric_from_text "$before" 'ratelimiter_requests_total{decision="forwarded"}')"
      r0="$(metric_from_text "$before" 'ratelimiter_requests_total{decision="rejected"}')"
      a0="$(metric_from_text "$before" "ratelimiter_requests_by_algorithm_total{algorithm=\"$algo\"}")"
      dsum0="$(metric_from_text "$before" 'ratelimiter_request_duration_seconds_sum')"
      dcnt0="$(metric_from_text "$before" 'ratelimiter_request_duration_seconds_count')"

      start_response="$(start_test "$profile_json")"
      if ! echo "$start_response" | grep -q '"status":"started"'; then
        echo "Failed to start test for scenario=$scenario repeat=$repeat algorithm=$algo: $start_response" >&2
        rm -f "$before_hist_file" "$after_hist_file"
        exit 1
      fi

      # The load-generator resets counters at test start, so baseline must be captured after start.
      sleep 0.2
      before_a="$(curl_call "$A_URL/actuator/prometheus")"
      as0="$(metric_from_text "$before_a" 'loadgen_requests_total{status="success"}')"
      ar0="$(metric_from_text "$before_a" 'loadgen_requests_total{status="rate_limited"}')"
      ae0="$(metric_from_text "$before_a" 'loadgen_requests_total{status="error"}')"

      if ! wait_test_finished; then
        echo "Test timeout for scenario=$scenario repeat=$repeat algorithm=$algo" >&2
        rm -f "$before_hist_file" "$after_hist_file"
        stop_test_if_running
        exit 1
      fi

      after="$(curl_call "$C_URL/actuator/prometheus")"
      after_a="$(curl_call "$A_URL/actuator/prometheus")"
      printf '%s\n' "$after" >"$after_hist_file"

      f1="$(metric_from_text "$after" 'ratelimiter_requests_total{decision="forwarded"}')"
      r1="$(metric_from_text "$after" 'ratelimiter_requests_total{decision="rejected"}')"
      a1="$(metric_from_text "$after" "ratelimiter_requests_by_algorithm_total{algorithm=\"$algo\"}")"
      dsum1="$(metric_from_text "$after" 'ratelimiter_request_duration_seconds_sum')"
      dcnt1="$(metric_from_text "$after" 'ratelimiter_request_duration_seconds_count')"

      as1="$(metric_from_text "$after_a" 'loadgen_requests_total{status="success"}')"
      ar1="$(metric_from_text "$after_a" 'loadgen_requests_total{status="rate_limited"}')"
      ae1="$(metric_from_text "$after_a" 'loadgen_requests_total{status="error"}')"

      forwarded="$(delta_value "$f0" "$f1")"
      rejected="$(delta_value "$r0" "$r1")"
      total="$(awk -v f="$forwarded" -v r="$rejected" 'BEGIN {printf "%.6f", f+r}')"
      algo_delta="$(delta_value "$a0" "$a1")"
      foreign_delta="$(awk -v t="$total" -v a="$algo_delta" 'BEGIN {d=t-a; if (d<0) d=0; printf "%.6f", d}')"
      reject_pct="$(awk -v r="$rejected" -v t="$total" 'BEGIN {if (t<=0) printf "0.00"; else printf "%.2f", (r*100.0)/t}')"
      effective_rps="$(awk -v t="$total" -v d="$DURATION_SECONDS" 'BEGIN {printf "%.3f", t/d}')"

      dsum="$(delta_value "$dsum0" "$dsum1")"
      dcnt="$(delta_value "$dcnt0" "$dcnt1")"
      avg_latency_ms="$(awk -v s="$dsum" -v c="$dcnt" 'BEGIN {if (c<=0) printf "0.000"; else printf "%.3f", (s/c)*1000.0}')"
      percentiles_ms="$(latency_percentiles_ms "$before_hist_file" "$after_hist_file")"
      p95_latency_ms="$(echo "$percentiles_ms" | cut -d, -f1)"
      p99_latency_ms="$(echo "$percentiles_ms" | cut -d, -f2)"
      rm -f "$before_hist_file" "$after_hist_file"

      ls="$(delta_value "$as0" "$as1")"
      lr="$(delta_value "$ar0" "$ar1")"
      le="$(delta_value "$ae0" "$ae1")"
      load_total="$(awk -v s="$ls" -v r="$lr" -v e="$le" 'BEGIN {printf "%.6f", s+r+e}')"
      error_pct="$(awk -v e="$le" -v t="$load_total" 'BEGIN {if (t<=0) printf "0.00"; else printf "%.2f", (e*100.0)/t}')"

      printf "%s,%d,%d,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s\n" \
        "$scenario" "$repeat" "$order_pos" "$algo" "$total" "$forwarded" "$rejected" \
        "$reject_pct" "$effective_rps" "$load_total" "$le" "$error_pct" \
        "$avg_latency_ms" "$p95_latency_ms" "$p99_latency_ms" "$algo_delta" "$foreign_delta" >>"$OUTPUT_FILE"

      printf "scenario=%-12s repeat=%2d algorithm=%-7s order=%d reject%%=%6.2f eff_rps=%8.2f lat=%7.3fms p95=%7.3fms p99=%7.3fms foreign=%8.0f\n" \
        "$scenario" "$repeat" "$algo" "$order_pos" "$reject_pct" "$effective_rps" "$avg_latency_ms" "$p95_latency_ms" "$p99_latency_ms" "$foreign_delta"
    done
  done
done

echo
echo "CSV report written to: $OUTPUT_FILE"
echo "Hint: foreign_algo_delta > 0 means another algorithm handled part of the run (adaptive mode or mid-test switch)."
