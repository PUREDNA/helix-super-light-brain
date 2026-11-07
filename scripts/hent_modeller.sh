#!/usr/bin/env bash
# -*- coding: utf-8 -*-
# Henter hjernens to modeller fra nettet — KUN hvis de mangler.
#
# Version 1.2 har ingen modeller i image'et. Denne fil henter dem ved start
# og lægger dem i containerens Ollama-lager, som i 1.2 er et VOLUME:
#
#   taleren      recall-honcho-8b Q4_K_M  fra Hugging Face (dman1011 /
#                mradermacher). Finjusteret Qwen3-8B — den model vi selv
#                bruger. Kontrolsummen efterprøves, så vi ikke kører en
#                anden vægt end den, der er målt på.
#   indlejringen bge-m3                  fra Ollamas eget register.
#
# Scriptet er selvhelende: det tjekker navnene i Ollama først, og gør intet
# hvis de svarer. Det kan derfor kaldes ved hver opstart.
set -u

NAVN="${OLLAMA_MODEL:-super-brain:1.1}"
HOST="${OLLAMA_HOST:-http://127.0.0.1:11434}"
LAGER="${OLLAMA_MODELS:-/opt/hjerne/ollama/models}"
GGUF="$LAGER/gguf/recall-honcho-8b.Q4_K_M.gguf"
URL="https://huggingface.co/mradermacher/recall-honcho-8b-GGUF/resolve/main/recall-honcho-8b.Q4_K_M.gguf"
SHA="91f9fee5e9b8aa3a78d09500d90c24be400dd4a7570eee40d980291b3143c12f"
INDBED="${EMBEDDING_MODEL:-bge-m3:latest}"
MODELFILE="/tmp/hentet-taler.Modelfile"

log() { echo "[modeller] $*"; }

# 0. Vent på den indre Ollama (supervisor starter den)
for i in $(seq 1 60); do
    if curl -sf --max-time 3 "$HOST/api/tags" >/dev/null 2>&1; then break; fi
    sleep 2
done
if ! curl -sf --max-time 3 "$HOST/api/tags" >/dev/null 2>&1; then
    log "FEJL: Ollama svarer ikke på $HOST — kan ikke hente modeller"
    exit 1
fi

har() { curl -sf --max-time 5 "$HOST/api/tags" 2>/dev/null | grep -q "\"$1"; }

# 1. Taleren
if har "$NAVN"; then
    log "taleren '$NAVN' er på plads"
else
    log "taleren mangler — hentes fra Hugging Face (4,7 GB, tager tid første gang)"
    mkdir -p "$(dirname "$GGUF")"
    if [ ! -f "$GGUF" ] || [ "$(sha256sum "$GGUF" 2>/dev/null | cut -d' ' -f1)" != "$SHA" ]; then
        rm -f "$GGUF"
        if ! curl -fL --retry 3 --retry-delay 5 -C - -o "$GGUF" "$URL"; then
            log "FEJL: kunne ikke hente $URL"
            log "  tjek nettet, eller læg filen på plads manuelt: $GGUF"
            exit 1
        fi
    fi
    FIK="$(sha256sum "$GGUF" | cut -d' ' -f1)"
    if [ "$FIK" != "$SHA" ]; then
        log "FEJL: kontrolsummen stemmer ikke (fik $FIK)"
        log "  filen er slettet igen, så en forkert vægt ikke kan køre"
        rm -f "$GGUF"
        exit 1
    fi
    log "kontrolsum OK ($SHA)"
    cat > "$MODELFILE" <<'SLUT'
FROM __GGUF__
PARAMETER num_ctx 16384
PARAMETER temperature 0
PARAMETER repeat_penalty 1.1
PARAMETER repeat_last_n 256
PARAMETER top_p 0.8
PARAMETER top_k 20
SLUT
    sed -i "s|__GGUF__|$GGUF|" "$MODELFILE"
    if ollama create "$NAVN" -f "$MODELFILE"; then
        log "taleren '$NAVN' er lagt ind"
    else
        log "FEJL: ollama create fejlede"
        rm -f "$MODELFILE"
        exit 1
    fi
    rm -f "$MODELFILE"
fi

# 2. Indlejringen
if har "$INDBED"; then
    log "indlejringen '$INDBED' er på plads"
else
    log "indlejringen mangler — hentes fra Ollamas register (1,2 GB)"
    if ollama pull "$INDBED"; then
        log "indlejringen '$INDBED' er hentet"
    else
        log "FEJL: kunne ikke hente $INDBED"
        exit 1
    fi
fi

log "begge modeller er klar"
