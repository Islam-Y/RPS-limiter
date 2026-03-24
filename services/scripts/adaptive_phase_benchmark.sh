#!/usr/bin/env bash
set -euo pipefail

A_URL="${A_URL:-http://localhost:8080}"
C_URL="${C_URL:-http://localhost:8082}"
TARGET_URL="${TARGET_URL:-http://rate-limiter-service:8082/api/test}"

PHASE_SECONDS=30
DURATION_SECONDS=$(( PHASE_SECONDS * 3 ))
SCENARIOS_CSV="phase_burst_recovery,phase_ddos_recovery"
BASE_RPS_LIMIT="${BASE_RPS_LIMIT:-100}"
WINDOW_SECONDS="${WINDOW_SECONDS:-10}"
BENCHMARK_CONCURRENCY="${BENCHMARK_CONCURRENCY:-256}"
REPEATS=6
OUTPUT_PREFIX="${OUTPUT_PREFIX:-monitoring/benchmarks/adaptive-phase-$(date +%Y%m%d-%H%M%S)}"
BENCHMARK_BUILD="${BENCHMARK_BUILD:-false}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGGREGATOR_SCRIPT="$SCRIPT_DIR/aggregate_phase_benchmark.py"
PLOT_SCRIPT="$SCRIPT_DIR/generate_phase_benchmark_pngs.py"

RAW_CSV=""
SUMMARY_CSV=""
SWITCHES_CSV=""
SWITCH_SUMMARY_CSV=""
TIMELINE_CSV=""
FIGURES_DIR=""

usage() {
  cat <<'EOF'
Run phased adaptive benchmarks for static_token, static_sliding and adaptive modes.

Usage:
  scripts/adaptive_phase_benchmark.sh [options]

Options:
  --phase-seconds <seconds>   Seconds per phase (default: 30)
  --scenarios <csv>           phase_burst_recovery,phase_ddos_recovery
  --base-rps-limit <rps>      Base budget for fair config (default: 100)
  --window <seconds>          Window for sliding algorithm (default: 10)
  --repeats <n>               Repeats per scenario/mode (default: 6)
  --build                     Rebuild images before benchmark start
  --output-prefix <prefix>    Output prefix (default: monitoring/benchmarks/adaptive-phase-<timestamp>)
  --help                      Show help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --phase-seconds)
      PHASE_SECONDS="$2"
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

DURATION_SECONDS=$(( PHASE_SECONDS * 3 ))

if ! [[ "$PHASE_SECONDS" =~ ^[0-9]+$ ]] || (( PHASE_SECONDS <= 0 )); then
  echo "--phase-seconds must be a positive integer" >&2
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

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Required command not found: $1" >&2
    exit 1
  }
}

require_cmd curl
require_cmd awk
require_cmd sed
require_cmd python3
require_cmd docker

if [[ ! -f "$AGGREGATOR_SCRIPT" ]]; then
  echo "Required script not found: $AGGREGATOR_SCRIPT" >&2
  exit 1
fi
if [[ ! -f "$PLOT_SCRIPT" ]]; then
  echo "Required script not found: $PLOT_SCRIPT" >&2
  exit 1
fi

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

set_adaptive_mode() {
  local enabled="$1"
  ADAPTIVE_ENABLED="$enabled" docker compose up -d rate-limiter-service >/dev/null
  wait_for_http "$C_URL/actuator/health" "rate-limiter-service"
}

reset_adaptive_services() {
  ADAPTIVE_ENABLED=true docker compose up -d rate-limiter-service >/dev/null
  docker compose restart ai-module rate-limiter-service >/dev/null
  wait_for_http "$C_URL/actuator/health" "rate-limiter-service"
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
    with open(path, "r", encoding="utf-8") as handle:
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

total = deltas.get("+Inf", 0.0)
if total <= 0:
    print("0.000")
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

print(f"{quantile_value(0.95) * 1000.0:.3f}")
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

phase_name_for_elapsed() {
  local elapsed="$1"
  if (( elapsed < PHASE_SECONDS )); then
    echo "normal"
  elif (( elapsed < PHASE_SECONDS * 2 )); then
    echo "attack"
  else
    echo "recovery"
  fi
}

scenario_profile_json() {
  case "$1" in
    phase_burst_recovery)
      cat <<EOF
{"type":"phased","params":{"phases":[
  {"name":"normal","duration":"PT${PHASE_SECONDS}S","type":"constant","params":{"rps":40}},
  {"name":"attack","duration":"PT${PHASE_SECONDS}S","type":"burst","params":{"baseRps":40,"spikeRps":280,"spikeDuration":"PT2S","spikePeriod":"PT6S"}},
  {"name":"recovery","duration":"PT${PHASE_SECONDS}S","type":"constant","params":{"rps":40}}
]}}
EOF
      ;;
    phase_ddos_recovery)
      cat <<EOF
{"type":"phased","params":{"phases":[
  {"name":"normal","duration":"PT${PHASE_SECONDS}S","type":"constant","params":{"rps":40}},
  {"name":"attack","duration":"PT${PHASE_SECONDS}S","type":"ddos","params":{"minRps":35,"maxRps":320,"maxSpikeDuration":"PT2S","minIdleTime":"PT0S","maxIdleTime":"PT1S"}},
  {"name":"recovery","duration":"PT${PHASE_SECONDS}S","type":"constant","params":{"rps":40}}
]}}
EOF
      ;;
    *)
      return 1
      ;;
  esac
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
  local timeout=$(( target + 45 ))
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
  local timeout=$(( DURATION_SECONDS + 60 ))
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

start_test() {
  local profile_json="$1"
  local body
  body=$(cat <<EOF
{
  "targetUrl": "$TARGET_URL",
  "duration": "PT${DURATION_SECONDS}S",
  "profile": $profile_json,
  "concurrency": $BENCHMARK_CONCURRENCY
}
EOF
)
  curl_call -X POST "$A_URL/test/start" \
    -H 'Content-Type: application/json' \
    -d "$body"
}

sample_timeline() {
  local scenario="$1"
  local mode="$2"
  local repeat="$3"
  local out="$4"
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
          printf "%s,%s,%d,%d,%s,%s\n" \
            "$scenario" "$mode" "$repeat" "$(( last_elapsed + 1 ))" "$phase" "$algorithm" >>"$out"
        fi
      fi
      break
    fi
    if [[ "$elapsed" != "$last_elapsed" ]]; then
      config=$(curl_call "$C_URL/config/limits" 2>/dev/null || echo '{}')
      algorithm="$(algorithm_from_json "$config")"
      phase="$(phase_name_for_elapsed "$elapsed")"
      printf "%s,%s,%d,%s,%s,%s\n" \
        "$scenario" "$mode" "$repeat" "$elapsed" "$phase" "$algorithm" >>"$out"
      last_elapsed="$elapsed"
      last_algorithm="$algorithm"
    fi
    sleep 1
  done
}

summarize_timeline_run() {
  local timeline_file="$1"
  local scenario="$2"
  local mode="$3"
  local repeat="$4"
  python3 - "$timeline_file" "$scenario" "$mode" "$repeat" <<'PY'
import csv
import sys
from collections import defaultdict

path, scenario, mode, repeat = sys.argv[1:5]
rows = []
with open(path, "r", encoding="utf-8", newline="") as handle:
    reader = csv.DictReader(handle)
    for row in reader:
        rows.append(row)

seconds = defaultdict(float)
switch_count = 0
sequence = []
previous = None
for row in rows:
    algorithm = row["algorithm"]
    seconds[algorithm] += 1.0
    if previous != algorithm:
        if previous is not None:
            switch_count += 1
        sequence.append(f'{row["elapsed_seconds"]}:{algorithm}')
        previous = algorithm

print(
    ",".join(
        [
            scenario,
            mode,
            repeat,
            str(switch_count),
            f'{seconds["token"]:.0f}',
            f'{seconds["sliding"]:.0f}',
            f'{seconds["fixed"]:.0f}',
            f'{seconds["unknown"]:.0f}',
            "|".join(sequence),
        ]
    )
)
PY
}

append_phase_row() {
  local scenario="$1"
  local mode="$2"
  local repeat="$3"
  local phase_order="$4"
  local phase_name="$5"
  local phase_duration="$6"
  local start_algorithm="$7"
  local end_algorithm="$8"
  local before_c="$9"
  local before_a="${10}"
  local before_hist="${11}"
  local after_c="${12}"
  local after_a="${13}"
  local after_hist="${14}"

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

  printf "%s,%s,%d,%d,%s,%d,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s\n" \
    "$scenario" "$mode" "$repeat" "$phase_order" "$phase_name" "$phase_duration" \
    "$total" "$forwarded" "$rejected" "$success_pct" "$reject_pct" "$effective_rps" \
    "$load_total" "$load_errors" "$error_pct" "$avg_latency_ms" "$p95_latency_ms" \
    "$start_algorithm" "$end_algorithm" "$fixed_delta" "$token_delta" "$sliding_delta" \
    "$fixed_share" "$token_share" "$sliding_share" >>"$RAW_CSV"
}

cleanup() {
  stop_test_if_running || true
}
trap cleanup EXIT

prepare_stack
wait_for_http "$A_URL/actuator/health" "load-generator-service"
wait_for_http "$C_URL/actuator/health" "rate-limiter-service"

RAW_CSV="${OUTPUT_PREFIX}.raw.csv"
SUMMARY_CSV="${OUTPUT_PREFIX}.summary.csv"
SWITCHES_CSV="${OUTPUT_PREFIX}.switches.csv"
SWITCH_SUMMARY_CSV="${OUTPUT_PREFIX}.switch-summary.csv"
TIMELINE_CSV="${OUTPUT_PREFIX}.timeline.csv"
FIGURES_DIR="${OUTPUT_PREFIX}.figures"

echo "scenario,mode,repeat,phase_order,phase_name,phase_duration_s,total_requests,forwarded,rejected,success_percent,reject_percent,effective_rps,loadgen_total,loadgen_errors,error_percent,avg_proxy_latency_ms,p95_proxy_latency_ms,start_algorithm,end_algorithm,fixed_requests,token_requests,sliding_requests,fixed_share_percent,token_share_percent,sliding_share_percent" >"$RAW_CSV"
echo "scenario,mode,repeat,switch_count,token_seconds,sliding_seconds,fixed_seconds,unknown_seconds,sequence" >"$SWITCHES_CSV"
echo "scenario,mode,repeat,elapsed_seconds,phase_name,algorithm" >"$TIMELINE_CSV"

IFS=',' read -r -a scenarios <<<"$SCENARIOS_CSV"
modes=("static_token" "static_sliding" "adaptive")

echo "Running adaptive phase benchmark..."
echo "duration=${DURATION_SECONDS}s phase_seconds=${PHASE_SECONDS}s scenarios=${SCENARIOS_CSV} repeats=${REPEATS}"
echo "base_rps_limit=${BASE_RPS_LIMIT} window=${WINDOW_SECONDS}s concurrency=${BENCHMARK_CONCURRENCY}"
echo

current_mode=""

for scenario in "${scenarios[@]}"; do
  profile_json="$(scenario_profile_json "$scenario")" || {
    echo "Unsupported scenario: $scenario" >&2
    exit 1
  }

  for mode in "${modes[@]}"; do
    if [[ "$mode" == "adaptive" ]]; then
      current_mode="adaptive"
    elif [[ "$current_mode" != "static" ]]; then
      set_adaptive_mode false
      current_mode="static"
    fi

    for repeat in $(seq 1 "$REPEATS"); do
      reset_load_generator
      stop_test_if_running
      if [[ "$mode" == "adaptive" ]]; then
        reset_adaptive_services
        configure_limits token
      elif [[ "$mode" == "static_token" ]]; then
        configure_limits token
      else
        configure_limits sliding
      fi

      before_c="$(curl_call "$C_URL/actuator/prometheus")"
      before_c_hist="$(mktemp)"
      printf '%s\n' "$before_c" >"$before_c_hist"

      start_response="$(start_test "$profile_json")"
      if ! echo "$start_response" | grep -q '"status":"started"'; then
        echo "Failed to start test scenario=$scenario mode=$mode repeat=$repeat: $start_response" >&2
        rm -f "$before_c_hist"
        exit 1
      fi

      sleep 0.2
      before_a="$(curl_call "$A_URL/actuator/prometheus")"
      phase_start_alg="$(algorithm_from_json "$(curl_call "$C_URL/config/limits")")"

      timeline_tmp=""
      timeline_pid=""
      if [[ "$mode" == "adaptive" ]]; then
        timeline_tmp="$(mktemp)"
        echo "scenario,mode,repeat,elapsed_seconds,phase_name,algorithm" >"$timeline_tmp"
        sample_timeline "$scenario" "$mode" "$repeat" "$timeline_tmp" &
        timeline_pid="$!"
      fi

      wait_until_elapsed "$PHASE_SECONDS" || {
        echo "Phase boundary timeout scenario=$scenario mode=$mode repeat=$repeat phase=normal" >&2
        rm -f "$before_c_hist" "$timeline_tmp"
        exit 1
      }
      after_c="$(curl_call "$C_URL/actuator/prometheus")"
      after_a="$(curl_call "$A_URL/actuator/prometheus")"
      after_c_hist="$(mktemp)"
      printf '%s\n' "$after_c" >"$after_c_hist"
      phase_end_alg="$(algorithm_from_json "$(curl_call "$C_URL/config/limits")")"
      append_phase_row "$scenario" "$mode" "$repeat" 1 "normal" "$PHASE_SECONDS" \
        "$phase_start_alg" "$phase_end_alg" "$before_c" "$before_a" "$before_c_hist" "$after_c" "$after_a" "$after_c_hist"
      rm -f "$before_c_hist"
      before_c="$after_c"
      before_a="$after_a"
      before_c_hist="$after_c_hist"
      phase_start_alg="$phase_end_alg"

      wait_until_elapsed "$(( PHASE_SECONDS * 2 ))" || {
        echo "Phase boundary timeout scenario=$scenario mode=$mode repeat=$repeat phase=attack" >&2
        rm -f "$before_c_hist" "$timeline_tmp"
        exit 1
      }
      after_c="$(curl_call "$C_URL/actuator/prometheus")"
      after_a="$(curl_call "$A_URL/actuator/prometheus")"
      after_c_hist="$(mktemp)"
      printf '%s\n' "$after_c" >"$after_c_hist"
      phase_end_alg="$(algorithm_from_json "$(curl_call "$C_URL/config/limits")")"
      append_phase_row "$scenario" "$mode" "$repeat" 2 "attack" "$PHASE_SECONDS" \
        "$phase_start_alg" "$phase_end_alg" "$before_c" "$before_a" "$before_c_hist" "$after_c" "$after_a" "$after_c_hist"
      rm -f "$before_c_hist"
      before_c="$after_c"
      before_a="$after_a"
      before_c_hist="$after_c_hist"
      phase_start_alg="$phase_end_alg"

      wait_test_finished || {
        echo "Test timeout scenario=$scenario mode=$mode repeat=$repeat" >&2
        rm -f "$before_c_hist" "$timeline_tmp"
        exit 1
      }
      after_c="$(curl_call "$C_URL/actuator/prometheus")"
      after_a="$(curl_call "$A_URL/actuator/prometheus")"
      after_c_hist="$(mktemp)"
      printf '%s\n' "$after_c" >"$after_c_hist"
      phase_end_alg="$(algorithm_from_json "$(curl_call "$C_URL/config/limits")")"
      append_phase_row "$scenario" "$mode" "$repeat" 3 "recovery" "$PHASE_SECONDS" \
        "$phase_start_alg" "$phase_end_alg" "$before_c" "$before_a" "$before_c_hist" "$after_c" "$after_a" "$after_c_hist"
      rm -f "$before_c_hist" "$after_c_hist"

      if [[ "$mode" == "adaptive" ]]; then
        wait "$timeline_pid"
        tail -n +2 "$timeline_tmp" >>"$TIMELINE_CSV"
        summarize_timeline_run "$timeline_tmp" "$scenario" "$mode" "$repeat" >>"$SWITCHES_CSV"
        rm -f "$timeline_tmp"
      else
        if [[ "$mode" == "static_token" ]]; then
          echo "$scenario,$mode,$repeat,0,$DURATION_SECONDS,0,0,0,0:token" >>"$SWITCHES_CSV"
        else
          echo "$scenario,$mode,$repeat,0,0,$DURATION_SECONDS,0,0,0:sliding" >>"$SWITCHES_CSV"
        fi
      fi

      printf "scenario=%-22s mode=%-14s repeat=%d completed\n" "$scenario" "$mode" "$repeat"
    done
  done
done

python3 "$AGGREGATOR_SCRIPT" \
  --raw-csv "$RAW_CSV" \
  --switches-csv "$SWITCHES_CSV" \
  --summary-csv "$SUMMARY_CSV" \
  --switch-summary-csv "$SWITCH_SUMMARY_CSV"

python3 "$PLOT_SCRIPT" \
  --summary-csv "$SUMMARY_CSV" \
  --timeline-csv "$TIMELINE_CSV" \
  --output-dir "$FIGURES_DIR"

echo
echo "Raw CSV: $RAW_CSV"
echo "Summary CSV: $SUMMARY_CSV"
echo "Switches CSV: $SWITCHES_CSV"
echo "Switch summary CSV: $SWITCH_SUMMARY_CSV"
echo "Timeline CSV: $TIMELINE_CSV"
echo "Figures dir: $FIGURES_DIR"
