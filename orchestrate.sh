#!/bin/bash
# Usage: bash orchestrate.sh "describe your task here"

TASK="${1:-Analyze this project}"
DIR="/tmp/orch_$$" && mkdir -p "$DIR"

echo "[orch] Starting 3 agents in parallel..."

# Agent 1: Web research — WebSearch + WebFetch only
echo "Research this topic thoroughly: $TASK. Return 5 key findings with source URLs." \
  | claude -p --allowedTools "WebSearch,WebFetch" \
  > "$DIR/research.txt" 2>&1 &
PID_RESEARCH=$!

# Agent 2: Code analysis — read local files, grep, glob only
echo "Technical analysis for: $TASK. Scan relevant code in current project. Give 3 concrete code-level recommendations." \
  | claude -p --allowedTools "Read,Grep,Glob" \
  > "$DIR/code.txt" 2>&1 &
PID_CODE=$!

# Agent 3: Local context — read + web validation
echo "Scan local project files for context on: $TASK. Summarize what you find." \
  | claude -p --allowedTools "Read,WebFetch" \
  > "$DIR/local.txt" 2>&1 &
PID_LOCAL=$!

echo "[orch] Waiting for all agents..."
wait $PID_RESEARCH $PID_CODE $PID_LOCAL
echo "[orch] All agents done. Results:"

echo ""
echo "=== Research (web) ==="
cat "$DIR/research.txt"
echo ""
echo "=== Code analysis ==="
cat "$DIR/code.txt"
echo ""
echo "=== Local context ==="
cat "$DIR/local.txt"
