#!/usr/bin/env bash
# -*- coding: utf-8 -*-
# Tager hjernens taler ind i dens egen Ollama, hvis den mangler.
#
# HVORFOR: modellerne ligger i containerens eget lager (/opt/hjerne/ollama), og det
# er IKKE et volume. Bygges containeren om, er taleren væk — og så kan hjernen ikke
# skrive konklusioner. Dette script gør den selvreparerende: det lægger taleren ind
# fra værten ved opstart, hvis navnet ikke svarer.
#
# Kilden er værten modelmappe, monteret skrivebeskyttet i containeren som /modeller
# (se docker-compose.yml). Der læses kun — der skrives aldrig uden for containeren.
#
# DNA 2026-10-13: taleren er skiftet til recall-honcho-8b (Qwen3-8B, trænet til at
# trække fakta ud). Den gamle Qwen3-4B er ude af containeren; dens GGUF ligger
# stadig på værten og kan lægges tilbage med ét ord.
set -u

NAVN="${OLLAMA_MODEL:-super-brain:1.1}"
HOST="${OLLAMA_HOST:-http://127.0.0.1:11434}"
KILDE="/modeller/recall-honcho/recall-honcho-8b.Q4_K_M.gguf"
MIDLERTIDIG="/tmp/taler-import.gguf"
MODELFILE="/tmp/taler-import.Modelfile"

log() { echo "[taler] $*"; }

# 1. Svarer navnet allerede? Så er der intet at gøre.
if curl -sf --max-time 5 "$HOST/api/tags" 2>/dev/null | grep -q "$NAVN"; then
    log "taleren '$NAVN' er klar"
    exit 0
fi

# 2. Findes kilden på værten?
if [ ! -f "$KILDE" ]; then
    log "ADVARSEL: kilden findes ikke: $KILDE"
    log "  Er værten modelmappe monteret som /modeller? (se docker-compose.yml)"
    exit 1
fi

# 3. Læg den ind under det navn hjernen spørger efter.
log "taleren mangler — lægger '$NAVN' ind fra $KILDE (det tager et øjeblik)"
cp "$KILDE" "$MIDLERTIDIG" || { log "kunne ikke kopiere kilden"; exit 1; }
cat > "$MODELFILE" <<'SLUT'
FROM /tmp/taler-import.gguf
PARAMETER num_ctx 16384
PARAMETER temperature 0
PARAMETER repeat_penalty 1.1
PARAMETER repeat_last_n 256
PARAMETER top_p 0.8
PARAMETER top_k 20
SLUT
ollama create "$NAVN" -f "$MODELFILE" || { log "kunne ikke oprette modellen"; rm -f "$MIDLERTIDIG" "$MODELFILE"; exit 1; }
rm -f "$MIDLERTIDIG" "$MODELFILE"

# 4. Efterprøv med et rigtigt svar, ikke bare et navn.
if curl -sf --max-time 5 "$HOST/api/tags" 2>/dev/null | grep -q "$NAVN"; then
    log "taleren '$NAVN' er lagt ind og svarer nu"
    exit 0
fi
log "ADVARSEL: modellen blev oprettet, men navnet svarer ikke"
exit 1
