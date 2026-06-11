#!/usr/bin/env sh
# scripts/ci/scheduled-sweep.sh -- Trigger a full-sweep on the production VM
# from a GitLab CI scheduled job, poll until completion, gate on pass rate.
#
# Required environment (injected by GitLab CI/CD Variables):
#   VM_BASE_URL                   e.g. http://172.20.1.175:7103
#   VM_API_KEY                    bearer key matching the VM's API_KEY env var
#
# Optional environment (with defaults):
#   SWEEP_PASS_RATE_THRESHOLD     0.95   (fail CI if pass rate below this)
#   SWEEP_POLL_INTERVAL_SECONDS   60     (poll every N seconds)
#   SWEEP_REPO_PUSH               true   (auto-commit and push examples)
#   SWEEP_PR_STYLE                per-category
#   SWEEP_PRODUCT                 aspose.pdf
#
# Exits 0 on success (sweep completed AND pass rate >= threshold).
# Exits 1 on any failure path. CI flags the job RED.

set -eu

: "${VM_BASE_URL:?VM_BASE_URL not set}"
: "${VM_API_KEY:?VM_API_KEY not set}"
SWEEP_PASS_RATE_THRESHOLD="${SWEEP_PASS_RATE_THRESHOLD:-0.95}"
SWEEP_POLL_INTERVAL_SECONDS="${SWEEP_POLL_INTERVAL_SECONDS:-60}"
SWEEP_REPO_PUSH="${SWEEP_REPO_PUSH:-true}"
SWEEP_PR_STYLE="${SWEEP_PR_STYLE:-per-category}"
SWEEP_PRODUCT="${SWEEP_PRODUCT:-aspose.pdf}"

log() { printf '[%s] %s\n' "$(date -u +%H:%M:%SZ)" "$1"; }
hr()  { printf -- '─%.0s' $(seq 1 60); echo; }

AUTH_HEADER="X-API-Key: ${VM_API_KEY}"

hr
log "Scheduled sweep starting"
log "  VM_BASE_URL=${VM_BASE_URL}"
log "  pass-rate threshold=${SWEEP_PASS_RATE_THRESHOLD}"
log "  poll interval=${SWEEP_POLL_INTERVAL_SECONDS}s"
log "  repo_push=${SWEEP_REPO_PUSH}, pr_style=${SWEEP_PR_STYLE}"
hr

# ── 1. Pre-flight: VM health ────────────────────────────────────────────────
log "Pre-flight: checking VM deep health..."
HEALTH=$(curl -fsS --max-time 30 "${VM_BASE_URL}/api/health/ready" || true)
if [ -z "${HEALTH}" ]; then
  log "ERROR: VM unreachable at ${VM_BASE_URL}/api/health/ready"
  exit 1
fi
echo "${HEALTH}" | jq .
HEALTH_STATUS=$(echo "${HEALTH}" | jq -r '.status // "unknown"')
case "${HEALTH_STATUS}" in
  healthy)
    log "VM is healthy"
    ;;
  degraded)
    log "WARN: VM is degraded but proceeding"
    ;;
  *)
    log "ERROR: VM status is '${HEALTH_STATUS}' — aborting before starting work"
    exit 1
    ;;
esac

# ── 2. Fetch the category list ──────────────────────────────────────────────
log "Fetching categories for product=${SWEEP_PRODUCT}..."
CATS_RESPONSE=$(curl -fsS -H "${AUTH_HEADER}" --max-time 30 \
  "${VM_BASE_URL}/api/categories?product=${SWEEP_PRODUCT}" || true)
if [ -z "${CATS_RESPONSE}" ]; then
  log "ERROR: Could not fetch categories"
  exit 1
fi

# Extract category names — handles both {items:[...]} and bare list shapes,
# and both string and {name: ...} entries.
CATEGORIES=$(echo "${CATS_RESPONSE}" | jq -c '
  (.categories // .items // .)
  | map(if type == "object" then .name else . end)
  | map(select(. != null and . != ""))
')
CAT_COUNT=$(echo "${CATEGORIES}" | jq 'length')
if [ "${CAT_COUNT}" -eq 0 ]; then
  log "ERROR: Category list is empty"
  exit 1
fi
log "Got ${CAT_COUNT} categories"

# ── 3. Start the sweep ──────────────────────────────────────────────────────
PAYLOAD=$(jq -n \
  --argjson cats "${CATEGORIES}" \
  --argjson push "$( [ "${SWEEP_REPO_PUSH}" = "true" ] && echo true || echo false )" \
  --arg pr_style "${SWEEP_PR_STYLE}" \
  '{categories: $cats, repo_push: $push, pr_style: $pr_style}')

log "Starting sweep..."
START_RESPONSE=$(curl -fsS -X POST \
  -H "${AUTH_HEADER}" \
  -H "Content-Type: application/json" \
  --max-time 60 \
  -d "${PAYLOAD}" \
  "${VM_BASE_URL}/api/start-tasks" || true)
if [ -z "${START_RESPONSE}" ]; then
  log "ERROR: /api/start-tasks did not respond"
  exit 1
fi
echo "${START_RESPONSE}" | jq .

JOB_ID=$(echo "${START_RESPONSE}" | jq -r '.job_id // empty')
TOTAL_TASKS=$(echo "${START_RESPONSE}" | jq -r '.total_tasks // 0')
if [ -z "${JOB_ID}" ]; then
  log "ERROR: Could not extract job_id from start response"
  exit 1
fi
log "Sweep started: job_id=${JOB_ID} total_tasks=${TOTAL_TASKS}"
hr

# ── 4. Poll for completion ──────────────────────────────────────────────────
LAST_LOGGED_PROCESSED=-1
STATE=""
while true; do
  sleep "${SWEEP_POLL_INTERVAL_SECONDS}"

  RAW=$(curl -fsS -H "${AUTH_HEADER}" --max-time 30 \
    "${VM_BASE_URL}/api/status/${JOB_ID}" || true)
  if [ -z "${RAW}" ]; then
    log "WARN: status fetch failed, will retry"
    continue
  fi
  STATE="${RAW}"

  STATUS=$(echo "${STATE}"    | jq -r '.status   // "?"')
  PROCESSED=$(echo "${STATE}" | jq -r '.processed // 0')
  TOTAL=$(echo "${STATE}"     | jq -r '.total     // 0')
  PASSED=$(echo "${STATE}"    | jq -r '.passed_count // 0')
  FAILED=$(echo "${STATE}"    | jq -r '.failed_count // 0')

  if [ "${PROCESSED}" != "${LAST_LOGGED_PROCESSED}" ]; then
    log "status=${STATUS} processed=${PROCESSED}/${TOTAL} passed=${PASSED} failed=${FAILED}"
    LAST_LOGGED_PROCESSED="${PROCESSED}"
  fi

  case "${STATUS}" in
    completed|done)
      log "Sweep completed"
      break
      ;;
    failed)
      log "ERROR: Sweep ended with status 'failed'"
      echo "${STATE}" > sweep_result.json
      exit 1
      ;;
    cancelled)
      log "ERROR: Sweep was cancelled"
      echo "${STATE}" > sweep_result.json
      exit 1
      ;;
  esac
done

# ── 5. Persist final result + evaluate pass rate ────────────────────────────
echo "${STATE}" > sweep_result.json
hr
PASSED=$(echo "${STATE}" | jq -r '.passed_count // 0')
FAILED=$(echo "${STATE}" | jq -r '.failed_count // 0')
PROCESSED=$((PASSED + FAILED))

if [ "${PROCESSED}" -eq 0 ]; then
  log "ERROR: Zero examples processed — something went wrong upstream"
  exit 1
fi

# bc for floating point; awk fallback if bc missing
if command -v bc >/dev/null 2>&1; then
  PASS_RATE=$(printf 'scale=4; %s / %s\n' "${PASSED}" "${PROCESSED}" | bc)
  ABOVE=$(printf '%s >= %s\n' "${PASS_RATE}" "${SWEEP_PASS_RATE_THRESHOLD}" | bc)
else
  PASS_RATE=$(awk "BEGIN { printf \"%.4f\", ${PASSED} / ${PROCESSED} }")
  ABOVE=$(awk "BEGIN { print (${PASS_RATE} >= ${SWEEP_PASS_RATE_THRESHOLD}) ? 1 : 0 }")
fi

log "Final results:"
log "  passed   = ${PASSED}"
log "  failed   = ${FAILED}"
log "  total    = ${PROCESSED}"
log "  rate     = ${PASS_RATE}"
log "  threshold= ${SWEEP_PASS_RATE_THRESHOLD}"
hr

if [ "${ABOVE}" = "1" ]; then
  log "Pass rate meets threshold. Sweep successful."
  exit 0
fi

log "Pass rate ${PASS_RATE} below threshold ${SWEEP_PASS_RATE_THRESHOLD} — failing CI"
exit 1
