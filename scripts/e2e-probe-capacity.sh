#!/usr/bin/env bash
# Run against .e2e-logs/<run>/compose-logs.txt
L="${1:?usage: probe.sh <compose-logs.txt>}"

echo "=== 1. does the storefront reach the site-authority snapshot at all? ==="
grep -c 'capacity/snapshot' "$L"
grep -oE '"(GET|POST) /api/v1/capacity/[a-z/-]*" [0-9]{3}' "$L" | sort | uniq -c | head

echo
echo "=== 2. the site authority's own view of resources ==="
grep -iE 'capacity/snapshot|resources.*\[\]|snapshot.*(empty|0 )' "$L" | tail -8

echo
echo "=== 3. did anything ever register inventory WITH the site authority? ==="
grep -icE 'capacity/resources|register.*resource|upsert.*resource|site-resource-pools' "$L"
grep -oE '"(GET|POST|PUT) /api/v1/capacity/[a-z/-]*"' "$L" | sort | uniq -c

echo
echo "=== 4. the storefront's own resource import (should have succeeded) ==="
grep -iE '\[ADMIN\] Resource import' "$L" | tail -3

echo
echo "=== 5. the reserve that 409'd — what claim, what answer? ==="
grep -iE 'no_matching_inventory|No available compute VM|reserve.*(claim|matched)' "$L" | tail -6

echo
echo "=== 6. any capacity/site warnings ==="
grep -oE '\[(CAPACITY|CAPACITY_AGGREGATOR|SITE|POOLS)[A-Z_]*\][^"]{0,110}' "$L" | sort | uniq -c | sort -rn | head -12
