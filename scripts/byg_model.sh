#!/usr/bin/env bash
# ============================================================
#  Bygger hjernens taler i Ollama.
#
#  Taleren er en finjusteret Qwen3-4B-Instruct-2507 (navn: super-brain:1.1).
#  Den findes IKKE i Ollamas registry — den kan ikke hentes, kun bygges.
#  Normalt er den allerede lagt ind: Dockerfile trin 6b bager den ind i
#  image'et under build. Dette script er til at bygge den på ny ud fra dens
#  GGUF, fx efter en ny finjustering.
#
#  Den gamle Granite 4.1 3B-vej er FJERNET med vilje: Granite blev målt for
#  svag til formålet (navn/bopæl 5/5, men arbejde/vaner 0/5), og den skrev sin
#  tankestrøm med i svaret. Den bruges ikke længere — heller ikke som reserve.
#
#  Brug:   bash scripts/byg_model.sh [OLLAMA_HOST] [NAVN] [GGUF-STI]
#  Eks.:   bash scripts/byg_model.sh http://127.0.0.1:11434 super-brain:1.1 \
#                /home/dna/models/super-brain-1.1-Q4_K_M.gguf
#
#  Uden GGUF-STI prøves SUPER_BRAIN_GGUF, derefter en fast liste af
#  sandsynlige stier. Findes ingen af dem, STOPPER scriptet med en besked —
#  det henter aldrig en anden model i stedet.
# ============================================================
set -u

HOST="${1:-${OLLAMA_HOST:-http://127.0.0.1:11434}}"
NAVN="${2:-${OLLAMA_MODEL:-super-brain:1.1}}"
GGUF="${3:-${SUPER_BRAIN_GGUF:-}}"

# num_ctx SKAL passe til hvad HC må sende: Honcho foreskriver op til 25.000
# input-tokens til deriveren plus op til 2.500 i svar. Ollama deler vinduet
# mellem samtidige kald (OLLAMA_NUM_PARALLEL), så med parallel=1 får ét kald
# hele vinduet. Er num_ctx mindre end det HC sender, klipper Ollama teksten.
NUM_CTX="${SUPER_BRAIN_NUM_CTX:-32768}"

if [ -z "$GGUF" ]; then
  for kandidat in \
    /home/dna/models/super-brain-1.1-Q4_K_M.gguf \
    "/opt/hjerne/ollama/models/super-brain-1.1-Q4_K_M.gguf"
  do
    if [ -f "$kandidat" ]; then GGUF="$kandidat"; break; fi
  done
fi

if [ -z "$GGUF" ] || [ ! -f "$GGUF" ]; then
  echo "[byg_model] STOP: fandt ikke GGUF'en til taleren."
  echo "  Taleren er finjusteret og kan ikke hentes fra Ollamas registry."
  echo "  Giv stien som 3. argument, eller sæt SUPER_BRAIN_GGUF."
  echo "  Normalt behøver du ikke dette script: den ligger i image'et —"
  echo "  byg det med:  docker compose build"
  exit 1
fi

echo "[byg_model] host:     $HOST"
echo "[byg_model] navn:     $NAVN"
echo "[byg_model] gguf:     $GGUF"
echo "[byg_model] num_ctx:  $NUM_CTX"

curl -sf --max-time 10 "$HOST/api/tags" >/dev/null || {
  echo "[byg_model] STOP: Ollama svarer ikke på $HOST"; exit 1; }

# Ollamas create-API: 'from' er kilden (en GGUF-sti eller et eksisterende tag),
# 'parameters' er de indstillinger der skal gælde for det nye tag.
python3 - "$HOST" "$NAVN" "$GGUF" "$NUM_CTX" <<'PY'
import json, sys, urllib.request, urllib.error
host, navn, gguf, num_ctx = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
krop = {"model": navn, "from": gguf,
        "parameters": {"num_ctx": num_ctx, "temperature": 0,
                       "repeat_penalty": 1.1, "repeat_last_n": 256}}
req = urllib.request.Request(host.rstrip("/") + "/api/create",
                             data=json.dumps(krop).encode("utf-8"),
                             headers={"Content-Type": "application/json"})
try:
    with urllib.request.urlopen(req, timeout=1800) as r:
        r.read()
    print("[byg_model] færdig:", navn)
except urllib.error.HTTPError as e:
    print("[byg_model] FEJL", e.code, e.read().decode()[:300]); sys.exit(1)
PY

echo "[byg_model] klar. Test med:"
echo "  curl -s $HOST/api/generate -d '{\"model\":\"$NAVN\",\"prompt\":\"Sig godmorgen på dansk med æ, ø og å.\",\"stream\":false}'"
