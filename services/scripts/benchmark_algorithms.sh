#!/usr/bin/env bash
set -euo pipefail

A_URL="${A_URL:-http://localhost:8080}"
C_URL="${C_URL:-http://localhost:8082}"
TARGET_URL="${TARGET_URL:-http://rate-limiter-service:8082/api/test}"
DURATION_SECONDS=20
SCENARIOS_CSV="constant_low,burst,sinusoidal,ddos"
BASE_RPS_LIMIT="${BASE_RPS_LIMIT:-100}"
WINDOW_SECONDS="${WINDOW_SECONDS:-10}"
OUTPUT_FILE=""
DISABLE_ADAPTIVE=0

usage() {
  cat <<'EOF'
Compare rate-limiting algorithms (fixed/sliding/token) across load scenarios.

Usage:
  scripts/benchmark_algorithms.sh [options]

Options:
  --duration <seconds>        Test duration per run (default: 20)
  --scenarios <csv>           Scenarios to run (default: constant_low,burst,sinusoidal,ddos)
  --base-rps-limit <rps>      Common limit budget for all algorithms (default: 100)
  --window <seconds>          Window for fixed/sliding (default: 10)
  --output <path>             CSV output path (default: ./benchmark-YYYYmmdd-HHMMSS.csv)
  --disable-adaptive          Restart rate-limiter with ADAPTIVE_ENABLED=false before benchmark
  --help                      Show this help

Scenarios:
  constant_low, burst, sinusoidal, ddos, constant_high
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

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Required command not found: $1" >&2
    exit 1
  }
}

require_cmd curl
require_cmd awk
require_cmd sed

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

if [[ -z "$OUTPUT_FILE" ]]; then
  OUTPUT_FILE="./benchmark-$(date +%Y%m%d-%H%M%S).csv"
fi

if (( DISABLE_ADAPTIVE == 1 )); then
  require_cmd docker
  echo "Restarting rate-limiter with ADAPTIVE_ENABLED=false for fair algorithm comparison..."
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

stop_test_if_running() {
  curl -s -X POST "$A_URL/test/stop" >/dev/null 2>&1 || true
}

configure_algorithm() {
  local algo="$1"
  local window="$WINDOW_SECONDS"
  local limit=$(( BASE_RPS_LIMIT * window ))
  local fill_rate="$BASE_RPS_LIMIT"
  local capacity=$(( BASE_RPS_LIMIT * 2 ))
  local payload

  case "$algo" in
    fixed|sliding)
      payload=$(cat <<EOF
{"algorithm":"$algo","limit":$limit,"window":$window,"capacity":$capacity,"fillRate":$fill_rate}
EOF
)
      ;;
    token)
      payload=$(cat <<EOF
{"algorithm":"token","limit":$limit,"window":$window,"capacity":$capacity,"fillRate":$fill_rate}
EOF
)
      ;;
    *)
      echo "Unsupported algorithm: $algo" >&2
      return 1
      ;;
  esac

  curl_call -X POST "$C_URL/config/limits" \
    -H 'Content-Type: application/json' \
    -d "$payload" >/dev/null
}

snapshot_metrics_text() {
  curl_call "$C_URL/actuator/prometheus"
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

append_csv_line() {
  local scenario="$1"
  local algo="$2"
  local total="$3"
  local forwarded="$4"
  local rejected="$5"
  local reject_pct="$6"
  local effective_rps="$7"
  local algo_delta="$8"
  local foreign_delta="$9"
  printf "%s,%s,%s,%s,%s,%s,%s,%s,%s\n" \
    "$scenario" "$algo" "$total" "$forwarded" "$rejected" \
    "$reject_pct" "$effective_rps" "$algo_delta" "$foreign_delta" >>"$OUTPUT_FILE"
}

echo "scenario,algorithm,total_requests,forwarded,rejected,reject_percent,effective_rps,algo_counter_delta,foreign_algo_delta" >"$OUTPUT_FILE"

IFS=',' read -r -a scenarios <<<"$SCENARIOS_CSV"
algorithms=(fixed sliding token)

echo "Running benchmark..."
echo "A_URL=$A_URL"
echo "C_URL=$C_URL"
echo "TARGET_URL=$TARGET_URL"
echo "duration=${DURATION_SECONDS}s base_rps_limit=$BASE_RPS_LIMIT window=${WINDOW_SECONDS}s"
echo

for scenario in "${scenarios[@]}"; do
  profile_json="$(scenario_profile_json "$scenario")" || {
    echo "Unsupported scenario: $scenario" >&2
    exit 1
  }

  for algo in "${algorithms[@]}"; do
    stop_test_if_running
    configure_algorithm "$algo"

    before="$(snapshot_metrics_text)"
    f0="$(metric_from_text "$before" 'ratelimiter_requests_total{decision="forwarded"}')"
    r0="$(metric_from_text "$before" 'ratelimiter_requests_total{decision="rejected"}')"
    a0="$(metric_from_text "$before" "ratelimiter_requests_by_algorithm_total{algorithm=\"$algo\"}")"

    start_response="$(start_test "$profile_json")"
    if ! echo "$start_response" | grep -q '"status":"started"'; then
      echo "Failed to start test for scenario=$scenario algorithm=$algo: $start_response" >&2
      exit 1
    fi

    if ! wait_test_finished; then
      echo "Test timeout for scenario=$scenario algorithm=$algo" >&2
      stop_test_if_running
      exit 1
    fi

    after="$(snapshot_metrics_text)"
    f1="$(metric_from_text "$after" 'ratelimiter_requests_total{decision="forwarded"}')"
    r1="$(metric_from_text "$after" 'ratelimiter_requests_total{decision="rejected"}')"
    a1="$(metric_from_text "$after" "ratelimiter_requests_by_algorithm_total{algorithm=\"$algo\"}")"

    forwarded="$(delta_value "$f0" "$f1")"
    rejected="$(delta_value "$r0" "$r1")"
    total="$(awk -v f="$forwarded" -v r="$rejected" 'BEGIN {printf "%.6f", f+r}')"
    algo_delta="$(delta_value "$a0" "$a1")"
    foreign_delta="$(awk -v t="$total" -v a="$algo_delta" 'BEGIN {d=t-a; if (d<0) d=0; printf "%.6f", d}')"
    reject_pct="$(awk -v r="$rejected" -v t="$total" 'BEGIN {if (t<=0) printf "0.00"; else printf "%.2f", (r*100.0)/t}')"
    effective_rps="$(awk -v t="$total" -v d="$DURATION_SECONDS" 'BEGIN {printf "%.3f", t/d}')"

    append_csv_line "$scenario" "$algo" "$total" "$forwarded" "$rejected" \
      "$reject_pct" "$effective_rps" "$algo_delta" "$foreign_delta"

    printf "scenario=%-12s algorithm=%-7s total=%8.0f rejected=%8.0f reject%%=%6.2f eff_rps=%8.2f foreign=%8.0f\n" \
      "$scenario" "$algo" "$total" "$rejected" "$reject_pct" "$effective_rps" "$foreign_delta"
  done
done

echo
echo "CSV report written to: $OUTPUT_FILE"
echo "Hint: foreign_algo_delta > 0 means another algorithm handled part of the run (adaptive mode or mid-test switch)."
