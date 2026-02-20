#!/bin/bash
# authorize_pending_members.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/.env"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Env file not found at $ENV_FILE"
  echo "Copy infra/zerotier/.env.sample to $ENV_FILE and set values."
  exit 1
fi

set -a
source "$ENV_FILE"
set +a

# Check required environment variables
for var in AIRTABLE_API_KEY AIRTABLE_BASE_ID AIRTABLE_TABLE_NAME ZEROTIER_NETWORK; do
  if [[ -z "${!var:-}" ]]; then
    echo "Missing required env var: $var in $ENV_FILE" >&2
    exit 1
  fi
done

# Check if jq is installed for JSON parsing
if ! command -v jq &> /dev/null; then
  echo "Error: jq is required but not installed." >&2
  echo "Install with: brew install jq (macOS) or apt-get install jq (Linux)" >&2
  exit 1
fi

# Parse arguments
FILTER_STATUS="approved"
MAX_ENTRIES=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --retry-errors)
      FILTER_STATUS="error"
      shift
      ;;
    --max-entries)
      if [[ -z "${2:-}" || "$2" =~ ^- ]]; then
        echo "Error: --max-entries requires a numeric value" >&2
        exit 1
      fi
      MAX_ENTRIES="$2"
      shift 2
      ;;
    *)
      echo "Unknown option: $1" >&2
      echo "Usage: $0 [--retry-errors] [--max-entries N]" >&2
      exit 1
      ;;
  esac
done

if [[ "$FILTER_STATUS" == "error" ]]; then
  echo "Retry mode: fetching records with status 'error'..."
else
  echo "Fetching approved records from Airtable..."
fi

# Build Airtable API URL
AIRTABLE_URL="https://api.airtable.com/v0/${AIRTABLE_BASE_ID}/${AIRTABLE_TABLE_NAME}?filterByFormula=%7BStatus%7D+%3D+%27${FILTER_STATUS}%27&sort%5B0%5D%5Bfield%5D=Created&sort%5B0%5D%5Bdirection%5D=asc"
if [[ -n "$MAX_ENTRIES" ]]; then
  AIRTABLE_URL="${AIRTABLE_URL}&maxRecords=${MAX_ENTRIES}"
fi

# Fetch records from Airtable with error handling
RESPONSE=$(curl -sf "$AIRTABLE_URL" \
  -H "Authorization: Bearer $AIRTABLE_API_KEY" 2>&1) || {
  echo "Error: Failed to fetch data from Airtable" >&2
  echo "$RESPONSE" >&2
  exit 1
}

# Validate JSON response
if ! echo "$RESPONSE" | jq empty 2>/dev/null; then
  echo "Error: Invalid JSON response from Airtable" >&2
  echo "$RESPONSE" >&2
  exit 1
fi

# Extract approved records
APPROVED_RECORDS=$(echo "$RESPONSE" | jq -c ".records[] | select(.fields.Status == \"$FILTER_STATUS\")")

if [[ -z "$APPROVED_RECORDS" ]]; then
  echo "No records with status '$FILTER_STATUS' found."
  exit 0
fi

echo "Found records with status '$FILTER_STATUS'. Processing..."

# Track successes and failures
SUCCESS_COUNT=0
FAILURE_COUNT=0

# Process each approved record
while IFS= read -r record; do
  RECORD_ID=$(echo "$record" | jq -r '.id')
  NODE_ID=$(echo "$record" | jq -r '.fields["Node ID"]')
  EMAIL=$(echo "$record" | jq -r '.fields.Email // "N/A"')
  
  echo ""
  echo "Processing: Email=$EMAIL, Node ID=$NODE_ID, Record ID=$RECORD_ID"
  
  # Authorize the member and capture output
  AUTH_ERROR=0
  AUTH_OUTPUT=$("${SCRIPT_DIR}/authorize_zt_member.sh" "$ZEROTIER_NETWORK" "$NODE_ID" 2>&1) || AUTH_ERROR=$?


  if [[ ${AUTH_ERROR:-0} -eq 0 ]]; then
    # Authorization succeeded
    echo "✓ Authorization succeeded"

    # Update Airtable status to "authorized"
    echo "Updating Airtable status to 'authorized'..."
    UPDATE_RESPONSE=$(curl -sf -X PATCH \
      "https://api.airtable.com/v0/${AIRTABLE_BASE_ID}/${AIRTABLE_TABLE_NAME}/$RECORD_ID" \
      -H "Authorization: Bearer $AIRTABLE_API_KEY" \
      -H "Content-Type: application/json" \
      -d "{\"fields\": {\"Status\": \"authorized\", \"Error Message\": \"\"}}" 2>&1) || {
      echo "✗ Failed to update Airtable record $RECORD_ID to authorized" >&2
      echo "$UPDATE_RESPONSE" >&2
      FAILURE_COUNT=$((FAILURE_COUNT + 1))
      continue
    }
    
    echo "✓ Successfully updated record $RECORD_ID to 'authorized'"
    SUCCESS_COUNT=$((SUCCESS_COUNT + 1))
  else
    # Authorization failed
    echo "✗ Authorization failed with exit code $AUTH_ERROR"
    
    # Escape the error message for JSON (keep the quotes)
    ERROR_MSG=$(echo "$AUTH_OUTPUT" | jq -Rs .)
    
    # Update Airtable status to "error" with error message
    echo "Updating Airtable status to 'error'..."
    UPDATE_RESPONSE=$(curl -sf -X PATCH \
      "https://api.airtable.com/v0/${AIRTABLE_BASE_ID}/${AIRTABLE_TABLE_NAME}/$RECORD_ID" \
      -H "Authorization: Bearer $AIRTABLE_API_KEY" \
      -H "Content-Type: application/json" \
      -d "{\"fields\": {\"Status\": \"error\", \"Error Message\": $ERROR_MSG}}" 2>&1) || {
      echo "✗ Failed to update Airtable record $RECORD_ID to error status" >&2
      echo "$UPDATE_RESPONSE" >&2
      FAILURE_COUNT=$((FAILURE_COUNT + 1))
      continue
    }
    
    echo "✓ Updated record $RECORD_ID to 'error' status"
    FAILURE_COUNT=$((FAILURE_COUNT + 1))
  fi
  
done <<< "$APPROVED_RECORDS"

echo ""
echo "========================================"
echo "Processing complete!"
echo "Successfully processed: $SUCCESS_COUNT"
echo "Failed: $FAILURE_COUNT"
echo "========================================"

if [[ $FAILURE_COUNT -gt 0 ]]; then
  exit 1
fi

