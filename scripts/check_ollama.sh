#!/usr/bin/env bash
# Quick Ollama check from the host.
#   scripts/check_ollama.sh                 # Ollama at 192.168.10.176:11434, and what the sim has seen
#   OLLAMA=http://host:11434 scripts/check_ollama.sh
#   SIM=http://localhost:8000 scripts/check_ollama.sh
OLLAMA="${OLLAMA:-http://192.168.10.176:11434}"
SIM="${SIM:-http://localhost:8000}"

echo "== Ollama server: $OLLAMA"
if out=$(curl -sS -m 5 -w '\n%{time_total}' "$OLLAMA/api/tags" 2>&1); then
  t=$(echo "$out" | tail -1)
  echo "   UP (answered /api/tags in ${t}s)"
  echo "$out" | head -n -1 | python3 -c 'import sys,json; [print("   model:", m["name"]) for m in json.load(sys.stdin).get("models",[])]' 2>/dev/null
else
  echo "   DOWN: $out"
fi

echo "== As the simulation sees it: $SIM/admin/ollama_status"
curl -sS -m 10 "$SIM/admin/ollama_status" | python3 -m json.tool 2>/dev/null || echo "   (the sim is not answering)"
