#!/usr/bin/env bash
set -euo pipefail

# Offline evaluation of pre-computed SPAR results against ground truth.
# No API keys or network access required.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_DIR"

GT_DIR="$PROJECT_DIR/data/ground_truths"
RESULTS_DIR="$PROJECT_DIR/data/packaged_results"

shopt -s nullglob
RESULT_DIRS=("$RESULTS_DIR"/*/)
shopt -u nullglob

if [ ${#RESULT_DIRS[@]} -eq 0 ]; then
  echo "ERROR: No pre-computed results found in $RESULTS_DIR."
  exit 1
fi

# Build a lookup: normalized ground-truth name -> actual filename
declare -A GT_MAP
for gt in "$GT_DIR"/*.3d; do
  name=$(basename "$gt" .3d)
  norm=$(echo "$name" | tr '[:upper:]' '[:lower:]' | tr -d '-')
  GT_MAP["$norm"]="$name"
done

TOTAL=0
PASSED=0
declare -a SCORES=()

for dir in "${RESULT_DIRS[@]}"; do
  dir_name=$(basename "$dir")
  proto_prefix=$(echo "$dir_name" | sed -E 's/_[0-9a-f]{8}$//')
  norm=$(echo "$proto_prefix" | tr '[:upper:]' '[:lower:]' | tr -d '-')

  gt_name="${GT_MAP[$norm]:-}"
  if [ -z "$gt_name" ]; then
    echo "SKIP: $proto_prefix — no matching ground truth found"
    echo
    continue
  fi

  GT_FILE="$GT_DIR/$gt_name.3d"
  GEN_FILE=$(find "$dir" -maxdepth 1 -name "*.3d" ! -name "initial_*" | head -1)

  if [ -z "$GEN_FILE" ]; then
    echo "SKIP: $proto_prefix — no .3d file found"
    echo
    continue
  fi

  echo "═══════════════════════════════════════"
  echo "  $proto_prefix"
  echo "  Ground truth: $GT_FILE"
  echo "  Generated:    $GEN_FILE"
  echo "═══════════════════════════════════════"

  OUTPUT=$(uv run python eval_3d.py --ground-truth "$GT_FILE" --generated "$GEN_FILE" 2>/dev/null)
  echo "$OUTPUT"
  echo

  TOTAL=$((TOTAL + 1))
  SCORE=$(echo "$OUTPUT" | grep -oP 'Overall score:\s*\K[\d.]+' || echo "ERR")
  STRICT=$(echo "$OUTPUT" | grep -oP 'Strict pass:\s*\K\w+' || echo "ERR")

  if [ "$STRICT" = "True" ]; then
    PASSED=$((PASSED + 1))
  fi

  if [ "$SCORE" = "ERR" ]; then
    SCORES+=("ERR    $proto_prefix")
  else
    SCORES+=("$SCORE $proto_prefix  (strict: $STRICT)")
  fi
done

echo "═══════════════════════════════════════"
echo "  Summary"
echo "═══════════════════════════════════════"
for s in "${SCORES[@]}"; do
  printf "  %s\n" "$s"
done
echo "───────────────────────────────────────"
echo "  $TOTAL protocols, $PASSED strict pass"
echo "═══════════════════════════════════════"
