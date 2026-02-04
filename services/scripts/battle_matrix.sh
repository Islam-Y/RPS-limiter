#!/usr/bin/env bash
set -euo pipefail

A_URL="${A_URL:-http://localhost:8080}"
C_URL="${C_URL:-http://localhost:8082}"
TARGET_URL="${TARGET_URL:-http://rate-limiter-service:8082/api/test}"

DURATION_SECONDS=12
SCENARIOS_CSV="constant_low,sinusoidal,poisson,constant_high,burst,ddos"
BASE_RPS_LIMIT="${BASE_RPS_LIMIT:-100}"
WINDOW_SECONDS="${WINDOW_SECONDS:-10}"
DISABLE_ADAPTIVE=0
OUTPUT_PREFIX="${OUTPUT_PREFIX:-battle-matrix-$(date +%Y%m%d-%H%M%S)}"

RAW_CSV=""
SCORED_CSV=""
MD_FILE=""

usage() {
  cat <<'EOF'
Build a "battle matrix" for fixed/sliding/token with scenario-by-scenario scores.

Usage:
  scripts/battle_matrix.sh [options]

Options:
  --duration <seconds>        Test duration per run (default: 12)
  --scenarios <csv>           Scenarios (default: constant_low,sinusoidal,poisson,constant_high,burst,ddos)
  --base-rps-limit <rps>      Base budget for fair config (default: 100)
  --window <seconds>          Window for fixed/sliding (default: 10)
  --disable-adaptive          Run with ADAPTIVE_ENABLED=false
  --output-prefix <prefix>    Output files prefix (default: battle-matrix-<timestamp>)
  --help                      Show help

Scenarios:
  constant_low, sinusoidal, poisson, constant_high, burst, ddos
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
    --disable-adaptive)
      DISABLE_ADAPTIVE=1
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
require_cmd mktemp
require_cmd sort
require_cmd cut

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
  if (( DISABLE_ADAPTIVE == 1 )); then
    docker compose up -d rate-limiter-service >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

if (( DISABLE_ADAPTIVE == 1 )); then
  require_cmd docker
  echo "Restarting rate-limiter with ADAPTIVE_ENABLED=false..."
  ADAPTIVE_ENABLED=false docker compose up -d --build rate-limiter-service >/dev/null
fi

wait_for_http "$A_URL/actuator/health" "load-generator-service"
wait_for_http "$C_URL/actuator/health" "rate-limiter-service"

RAW_CSV="${OUTPUT_PREFIX}.raw.csv"
SCORED_CSV="${OUTPUT_PREFIX}.scored.csv"
MD_FILE="${OUTPUT_PREFIX}.md"

echo "scenario,algorithm,total_requests,forwarded,rejected,reject_percent,effective_rps,loadgen_total,loadgen_errors,error_percent,avg_proxy_latency_ms,expected_reject_percent,stability_score,protection_score" >"$RAW_CSV"

scenario_profile_json() {
  case "$1" in
    constant_low)
      echo '{"type":"constant","params":{"rps":40}}'
      ;;
    sinusoidal)
      echo '{"type":"sinusoidal","params":{"minRps":15,"maxRps":170,"period":"PT12S"}}'
      ;;
    poisson)
      echo '{"type":"poisson","params":{"averageRps":140}}'
      ;;
    constant_high)
      echo '{"type":"constant","params":{"rps":180}}'
      ;;
    burst)
      echo '{"type":"burst","params":{"baseRps":20,"spikeRps":240,"spikeDuration":"PT2S","spikePeriod":"PT8S"}}'
      ;;
    ddos)
      echo '{"type":"ddos","params":{"minRps":35,"maxRps":320,"maxSpikeDuration":"PT2S","minIdleTime":"PT0S","maxIdleTime":"PT1S"}}'
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
  local timeout=$(( DURATION_SECONDS + 50 ))
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

IFS=',' read -r -a scenarios <<<"$SCENARIOS_CSV"
algorithms=(fixed sliding token)

echo "Running battle matrix..."
echo "duration=${DURATION_SECONDS}s scenarios=${SCENARIOS_CSV}"
echo "base_rps_limit=${BASE_RPS_LIMIT} window=${WINDOW_SECONDS}s"
echo

for scenario in "${scenarios[@]}"; do
  profile_json="$(scenario_profile_json "$scenario")" || {
    echo "Unsupported scenario: $scenario" >&2
    exit 1
  }

  for algo in "${algorithms[@]}"; do
    stop_test_if_running
    configure_algorithm "$algo"

    before_c="$(curl_call "$C_URL/actuator/prometheus")"
    before_a="$(curl_call "$A_URL/actuator/prometheus")"

    f0="$(metric_from_text "$before_c" 'ratelimiter_requests_total{decision="forwarded"}')"
    r0="$(metric_from_text "$before_c" 'ratelimiter_requests_total{decision="rejected"}')"
    dsum0="$(metric_from_text "$before_c" 'ratelimiter_request_duration_seconds_sum')"
    dcnt0="$(metric_from_text "$before_c" 'ratelimiter_request_duration_seconds_count')"

    as0="$(metric_from_text "$before_a" 'loadgen_requests_total{status="success"}')"
    ar0="$(metric_from_text "$before_a" 'loadgen_requests_total{status="rate_limited"}')"
    ae0="$(metric_from_text "$before_a" 'loadgen_requests_total{status="error"}')"

    start_resp="$(start_test "$profile_json")"
    if ! echo "$start_resp" | grep -q '"status":"started"'; then
      echo "Failed to start test for scenario=$scenario algorithm=$algo: $start_resp" >&2
      exit 1
    fi
    if ! wait_test_finished; then
      echo "Timed out waiting for test completion scenario=$scenario algorithm=$algo" >&2
      exit 1
    fi

    after_c="$(curl_call "$C_URL/actuator/prometheus")"
    after_a="$(curl_call "$A_URL/actuator/prometheus")"

    f1="$(metric_from_text "$after_c" 'ratelimiter_requests_total{decision="forwarded"}')"
    r1="$(metric_from_text "$after_c" 'ratelimiter_requests_total{decision="rejected"}')"
    dsum1="$(metric_from_text "$after_c" 'ratelimiter_request_duration_seconds_sum')"
    dcnt1="$(metric_from_text "$after_c" 'ratelimiter_request_duration_seconds_count')"

    as1="$(metric_from_text "$after_a" 'loadgen_requests_total{status="success"}')"
    ar1="$(metric_from_text "$after_a" 'loadgen_requests_total{status="rate_limited"}')"
    ae1="$(metric_from_text "$after_a" 'loadgen_requests_total{status="error"}')"

    forwarded="$(delta_value "$f0" "$f1")"
    rejected="$(delta_value "$r0" "$r1")"
    total="$(awk -v f="$forwarded" -v r="$rejected" 'BEGIN {printf "%.6f", f+r}')"
    reject_pct="$(awk -v r="$rejected" -v t="$total" 'BEGIN {if (t<=0) printf "0.00"; else printf "%.2f", (r*100.0)/t}')"
    effective_rps="$(awk -v t="$total" -v d="$DURATION_SECONDS" 'BEGIN {printf "%.3f", t/d}')"

    dsum="$(delta_value "$dsum0" "$dsum1")"
    dcnt="$(delta_value "$dcnt0" "$dcnt1")"
    avg_latency_ms="$(awk -v s="$dsum" -v c="$dcnt" 'BEGIN {if (c<=0) printf "0.000"; else printf "%.3f", (s/c)*1000.0}')"

    ls="$(delta_value "$as0" "$as1")"
    lr="$(delta_value "$ar0" "$ar1")"
    le="$(delta_value "$ae0" "$ae1")"
    load_total="$(awk -v s="$ls" -v r="$lr" -v e="$le" 'BEGIN {printf "%.6f", s+r+e}')"
    error_pct="$(awk -v e="$le" -v t="$load_total" 'BEGIN {if (t<=0) printf "0.00"; else printf "%.2f", (e*100.0)/t}')"

    expected_reject_pct="$(awk -v erps="$effective_rps" -v base="$BASE_RPS_LIMIT" 'BEGIN {
      if (erps<=0 || erps<=base) printf "0.00";
      else printf "%.2f", ((erps-base)/erps)*100.0;
    }')"

    stability_score="$(awk -v ep="$error_pct" 'BEGIN {
      # error_pct is already in percent units (0..100), so subtract directly.
      s = 100.0 - ep;
      if (s<0) s=0;
      if (s>100) s=100;
      printf "%.2f", s;
    }')"

    protection_score="$(awk -v rp="$reject_pct" -v expected="$expected_reject_pct" 'BEGIN {
      if (expected <= 0.01) {
        p = 100.0 - rp*5.0;
      } else {
        p = 100.0 - ( (rp>expected ? rp-expected : expected-rp) * 2.0 );
      }
      if (p<0) p=0;
      if (p>100) p=100;
      printf "%.2f", p;
    }')"

    echo "$scenario,$algo,$total,$forwarded,$rejected,$reject_pct,$effective_rps,$load_total,$le,$error_pct,$avg_latency_ms,$expected_reject_pct,$stability_score,$protection_score" >>"$RAW_CSV"

    printf "scenario=%-13s algo=%-7s reject%%=%6.2f latency=%7.3fms stab=%6.2f prot=%6.2f\n" \
      "$scenario" "$algo" "$reject_pct" "$avg_latency_ms" "$stability_score" "$protection_score"
  done
done

awk -F, '
BEGIN { OFS="," }
NR==1 { next }
{
  scenario[++n]=$1
  algorithm[n]=$2
  rejectPct[n]=$6+0
  effRps[n]=$7+0
  errorPct[n]=$10+0
  latency[n]=$11+0
  expected[n]=$12+0
  stability[n]=$13+0
  protection[n]=$14+0

  key=$1
  if (!(key in minLat) || latency[n] < minLat[key]) minLat[key]=latency[n]
  if (!(key in maxLat) || latency[n] > maxLat[key]) maxLat[key]=latency[n]
}
END {
  print "scenario,algorithm,stability_score,protection_score,latency_score,overall_score,reject_percent,error_percent,avg_proxy_latency_ms,effective_rps,expected_reject_percent"
  for (i=1; i<=n; i++) {
    key=scenario[i]
    min=minLat[key]
    max=maxLat[key]
    if (max-min < 1e-9) latScore=100.0
    else latScore=((max-latency[i])/(max-min))*100.0

    overall=0.35*stability[i] + 0.40*protection[i] + 0.25*latScore
    printf "%s,%s,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%.3f,%.3f,%.2f\n",
      scenario[i], algorithm[i], stability[i], protection[i], latScore, overall,
      rejectPct[i], errorPct[i], latency[i], effRps[i], expected[i]
  }
}
' "$RAW_CSV" >"$SCORED_CSV"

avg_fixed="$(awk -F, 'NR>1 && $2=="fixed" {s+=$6;n++} END {if(n==0) print "0.00"; else printf "%.2f", s/n}' "$SCORED_CSV")"
avg_sliding="$(awk -F, 'NR>1 && $2=="sliding" {s+=$6;n++} END {if(n==0) print "0.00"; else printf "%.2f", s/n}' "$SCORED_CSV")"
avg_token="$(awk -F, 'NR>1 && $2=="token" {s+=$6;n++} END {if(n==0) print "0.00"; else printf "%.2f", s/n}' "$SCORED_CSV")"

ranked="$(printf "fixed,%s\nsliding,%s\ntoken,%s\n" "$avg_fixed" "$avg_sliding" "$avg_token" | sort -t, -k2,2nr)"
rank1="$(echo "$ranked" | sed -n '1p' | cut -d, -f1)"
rank2="$(echo "$ranked" | sed -n '2p' | cut -d, -f1)"
rank3="$(echo "$ranked" | sed -n '3p' | cut -d, -f1)"

{
  echo "| Scenario | fixed | sliding | token | Winner |"
  echo "|---|---:|---:|---:|---|"
  for sc in "${scenarios[@]}"; do
    fixed_cell="$(awk -F, -v s="$sc" '$1==s && $2=="fixed" {printf "%.1f (S%.0f/P%.0f/L%.0f)", $6,$3,$4,$5}' "$SCORED_CSV")"
    sliding_cell="$(awk -F, -v s="$sc" '$1==s && $2=="sliding" {printf "%.1f (S%.0f/P%.0f/L%.0f)", $6,$3,$4,$5}' "$SCORED_CSV")"
    token_cell="$(awk -F, -v s="$sc" '$1==s && $2=="token" {printf "%.1f (S%.0f/P%.0f/L%.0f)", $6,$3,$4,$5}' "$SCORED_CSV")"
    winner="$(awk -F, -v s="$sc" '
      $1==s {score[$2]=$6+0}
      END {
        best="fixed"; b=score["fixed"];
        if (score["sliding"]>b) {best="sliding"; b=score["sliding"]}
        if (score["token"]>b) {best="token"; b=score["token"]}
        printf "%s", best
      }' "$SCORED_CSV")"
    echo "| $sc | $fixed_cell | $sliding_cell | $token_cell | $winner |"
  done
  echo "| **Avg Overall** | **$avg_fixed** | **$avg_sliding** | **$avg_token** | **$rank1** |"
  echo "| **Rank** | $( [[ "$rank1" == "fixed" ]] && echo 1 || ([[ "$rank2" == "fixed" ]] && echo 2 || echo 3) ) | $( [[ "$rank1" == "sliding" ]] && echo 1 || ([[ "$rank2" == "sliding" ]] && echo 2 || echo 3) ) | $( [[ "$rank1" == "token" ]] && echo 1 || ([[ "$rank2" == "token" ]] && echo 2 || echo 3) ) | $rank1 > $rank2 > $rank3 |"
} >"$MD_FILE"

echo
echo "Matrix ready:"
echo "- Raw metrics:    $RAW_CSV"
echo "- Scored metrics: $SCORED_CSV"
echo "- Markdown table: $MD_FILE"
echo
cat "$MD_FILE"
