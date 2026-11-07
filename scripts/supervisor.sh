#!/usr/bin/env bash
# ============================================================
#  HELIX SUPER BRAIN — supervisor
#  Starter begge motorer i ÉN container og holder dem i live.
#
#  1. PostgreSQL 17  (hjernen)
#  3. NPLL-scorer    (dømmekraften, valgfri — kan slås fra)
#
#  Alt uden data i image'et. Data lever i de monterede volumes.
# ============================================================
set -u

log() { echo "[super-brain $(date +%H:%M:%S)] $*"; }

# ---------- Miljøvariabler (alt kan overskrives ved start) ----------
export POSTGRES_USER="${POSTGRES_USER:-hjerne}"
export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-skift-mig}"
export POSTGRES_DB="${POSTGRES_DB:-hjerne}"
export PGDATA="${PGDATA:-/var/lib/postgresql/data}"

NPLL_ENABLED="${NPLL_ENABLED:-true}"
NPLL_PORT="${NPLL_PORT:-6080}"
# Ops — mellemhukommelsen. Vaulten er den mappe med Markdown-filer der
# mountes ind. Uden mount svarer tjenesten, men viser ingenting.
OPS_VAULT="${OPS_VAULT:-/vault}"
OPS_PORT="${OPS_PORT:-6122}"
VIEWER_PORT="${VIEWER_PORT:-6123}"
# HC (Honcho) — hukommelsesmotoren. Deler database med hjernen (eget skema).
HC_ENABLED="${HC_ENABLED:-true}"
HC_PORT="${HC_PORT:-8100}"
HC_SCHEMA="${HC_SCHEMA:-hc}"

# ---------- Indlejringen — hukommelsens øje ----------
# bge-m3 ligger i imagets modelmappe og BLIVER liggende. Selve Ollama-SERVEREN
# kører ude på værten (se nedenfor), så der kun findes ÉN server i systemet.
# Modellerne i containeren er hjernens egen reserve-kopi, urørt.
EMBED_MODEL="${EMBEDDING_MODEL:-bge-m3:latest}"
EMBED_PORT="${EMBEDDING_PORT:-11434}"
# Hold modellen varm på grafikkortet. "24h" = den bliver liggende, saa foerste
# soegning efter en pause ogsaa er hurtig. Saet til "5m" hvis andre skal laane
# kortet.
EMBED_KEEP_ALIVE="${EMBEDDING_KEEP_ALIVE:-24h}"
# Samme for TALEREN. Uden keep-alive smider Ollama også taleren ud af kortet
# efter 5 minutter, og så tager den første replik et koldt load på flere
# sekunder — CPU-koldstart, som let læses forkert som "den kører på CPU".
OLLAMA_KEEP_ALIVE="${OLLAMA_KEEP_ALIVE:-24h}"

# ---------- 0. Ollama — hjernens EGEN server, inde i containeren ----------
# Hjernen er selvkørende: taleren OG indlejringen ligger i image'et, og serveren
# kører HER — ikke ude på værten. Parametrene nedenfor er en del af containeren,
# så de følger med den og ikke skal sættes nogen andre steder (ingen systemd, ingen
# root). Værtens Ollama bruges kun som reserve hvis vores egen ikke svarer.
OLLAMA_MODELS="${OLLAMA_MODELS:-/opt/lillehjerne/ollama/models}"
OLLAMA_HOST="${OLLAMA_HOST:-http://127.0.0.1:11434}"
# Ét kald ad gangen => ét kald får HELE vinduet. Deler man vinduet mellem to
# samtidige kald (parallel=2), får hvert kald kun det halve — målt: num_ctx 32768
# gav kun 16.386 læste tokens, og slutningen af teksten blev klippet væk.
OLLAMA_NUM_PARALLEL="${OLLAMA_NUM_PARALLEL:-1}"
# KV-cachen i q8_0 halverer hukommelsen til vinduet, så ctx 32768 kan ligge på et
# 12 GB-kort uden at skubbe lag ud på CPU'en. Kræver flash attention.
OLLAMA_KV_CACHE_TYPE="${OLLAMA_KV_CACHE_TYPE:-q8_0}"
OLLAMA_FLASH_ATTENTION="${OLLAMA_FLASH_ATTENTION:-1}"
OLLAMA_CONTEXT_LENGTH="${OLLAMA_CONTEXT_LENGTH:-32768}"
export OLLAMA_MODELS OLLAMA_NUM_PARALLEL OLLAMA_KV_CACHE_TYPE
# Én model i hukommelsen ad gangen. Containeren har kun bge-m3; en grænse på 1
# gør at der aldrig kan ligge to modeller og slås om de 12 GB (DNA 2. nov 2026).
OLLAMA_MAX_LOADED_MODELS="${OLLAMA_MAX_LOADED_MODELS:-1}"
export OLLAMA_MAX_LOADED_MODELS
# KORTENE (DNA 3. nov 2026): maskinen har 23 GB i to kort, og der er rigeligt.
# Problemet var ikke plads, men at Ollama ikke fik besked om HVOR. bge-m3 fylder
# under 1 GB og skal blive paa ÉT kort — deler man den over to, gaar tiden til
# at flytte data mellem kortene i stedet for at regne.
OLLAMA_SCHED_SPREAD="${OLLAMA_SCHED_SPREAD:-0}"
export OLLAMA_SCHED_SPREAD
export OLLAMA_FLASH_ATTENTION OLLAMA_CONTEXT_LENGTH
# CUDA 12, ikke 13 (DNA 4. nov 2026): det lille kort er en GTX 1080 Ti med
# compute 6.1. Ollamas CUDA 13 kraever 7.0 og springer derfor kortet over — den
# tog RTX 3060 i stedet, selvom vi pegede paa det lille. Containeren har begge
# CUDA-versioner installeret, saa vi vaelger 12.
# Her er det ligegyldigt at CUDA 12 er aeldre: lillehjernen korer KUN bge-m3,
# den bliver aldrig byttet ud, og den kommer ikke i kontakt med andre modeller.
OLLAMA_LLM_LIBRARY="${OLLAMA_LLM_LIBRARY:-cuda_v12}"
export OLLAMA_LLM_LIBRARY

OLLAMA_MODEL="${OLLAMA_MODEL:-super-brain:1.1}"
PROVIDER="${PROVIDER:-ollama}"
# Indlejringen skal pege SAMME sted hen som taleren — ellers peger hjernen to
# forskellige veje, og så kan en af dem vise sig at være forkert.
EMBED_BASE="${EMBEDDING_BASE_URL:-$OLLAMA_HOST}"

# "To stik": find selv Ollama. Prøver de sandsynlige adresser i rækkefølge —
# er OLLAMA_HOST sat, prøves den først. Virker den, kører bussen.
# BEMÆRK: 127.0.0.1 springes over her — det er os selv (se nedenfor).
find_ollama() {
  local kandidater=()
  [ -n "$OLLAMA_HOST" ] && kandidater+=("$OLLAMA_HOST")
  kandidater+=(
    "http://host.docker.internal:11434"   # værten (WSL/Docker Desktop)
    "http://172.17.0.1:11434"             # docker-broen
    "http://172.23.0.1:11434"             # WSL2-adressen
    "http://ollama:11434"                 # hvis Ollama kører som søster-container
  )
  for k in "${kandidater[@]}"; do
    if curl -sf --max-time 3 "$k/api/tags" >/dev/null 2>&1; then
      OLLAMA_HOST="$k"
      return 0
    fi
  done
  return 1
}

tjek_ollama() {
  # Har man valgt en sky-udbyder (openai, gemini, ...), skal vi ikke lede
  # efter Ollama overhovedet — så er stemmen et sted på internettet.
  if [ "${PROVIDER:-ollama}" != "ollama" ]; then
    log "stemmen hentes fra udbyderen '${PROVIDER}' (ikke Ollama)"
    case "$PROVIDER" in
      openai)     [ -n "${OPENAI_API_KEY:-}" ] || log "  ADVARSEL: OPENAI_API_KEY mangler" ;;
      gemini)     [ -n "${GEMINI_API_KEY:-}" ] || log "  ADVARSEL: GEMINI_API_KEY mangler" ;;
      openrouter) [ -n "${OPENROUTER_API_KEY:-}" ] || log "  ADVARSEL: OPENROUTER_API_KEY mangler" ;;
      groq)       [ -n "${GROQ_API_KEY:-}" ] || log "  ADVARSEL: GROQ_API_KEY mangler" ;;
      custom)     [ -n "${CUSTOM_BASE_URL:-}" ] || log "  ADVARSEL: CUSTOM_BASE_URL mangler" ;;
    esac
    return 0
  fi
  if ! find_ollama; then
    log "──────────────────────────────────────────────────────────"
    log "ADVARSEL: fandt ingen Ollama. Prøvede:"
    log "  host.docker.internal:11434, 172.17.0.1:11434, 127.0.0.1:11434"
    log "  1) Installér Ollama på værten (https://ollama.com)"
    log "  2) Sørg for at taleren 'super-brain:1.1' findes der (den bages ind i image'et ved build — kør 'docker compose build')"
    log "  3) sæt OLLAMA_HOST i .env hvis den kører et andet sted"
    log "  Motoren kører fint uden — men uden stemme kan den ikke tale."
    log "──────────────────────────────────────────────────────────"
    return 1
  fi
  log "fandt Ollama på $OLLAMA_HOST"
  if curl -sf --max-time 5 "$OLLAMA_HOST/api/tags" 2>/dev/null | grep -q "$OLLAMA_MODEL"; then
    log "modellen '$OLLAMA_MODEL' er klar"
  else
    # Taleren er en finjusteret Qwen3-4B (super-brain:1.1). Den findes IKKE i
    # Ollamas registry og kan ikke hentes — den bages ind i image'et ved build
    # (Dockerfile trin 6b) og ligger desuden i hjernens egen modelmappe.
    # Den gamle Granite-vej er fjernet: den hentede og byggede Granite 4.1 3B,
    # som er målt for svag til formålet.
    log "ADVARSEL: taleren '$OLLAMA_MODEL' findes ikke på $OLLAMA_HOST"
    log "  Forsøger at lægge den ind fra værten (scripts/ta_imod_taler.sh) …"
    if bash /opt/lillehjerne/scripts/ta_imod_taler.sh; then
      log "  Taleren er lagt ind — hjernen kan skrive konklusioner igen."
    else
      log "  Kunne ikke lægge den ind. Byg image'et (docker compose build),"
      log "  eller læg den ind fra dens GGUF på værten."
    fi
  fi
  return 0
}

# (Den gamle byg_model-funktion er fjernet sammen med Granite-vejen: den byggede
#  Granite 4.1 3B ud fra modelfile/Granite-Super-Brain.Modelfile. Taleren er nu
#  en finjusteret Qwen3-4B, som lægges ind ved image-build — se byg_model.sh.)

# ---------- 0a. Hjernens EGEN Ollama startes FØRST ----------
# Rækkefølgen er afgørende: søgningen nedenfor tager den FØRSTE server der
# svarer. Står vores egen ikke op først, finder den værtens Ollama — og så
# peger hjernen udad igen, og parametrene her i containeren gælder ikke.
if curl -sf --max-time 3 "http://127.0.0.1:11434/api/tags" >/dev/null 2>&1; then
  log "hjernens egen Ollama svarer allerede paa 127.0.0.1:11434"
else
  log "starter hjernens EGEN Ollama (parallel=$OLLAMA_NUM_PARALLEL, kv=$OLLAMA_KV_CACHE_TYPE, ctx=$OLLAMA_CONTEXT_LENGTH)"
  # Bind-adressen sættes EKSPLICIT: OLLAMA_HOST kan være arvet fra miljøet og pege
  # ud på værten, og så kan serveren ikke binde ("cannot assign requested address").
  # Hvilket grafikkort? (DNA 4. nov 2026)
  # Er der flere kort, tages det MINDSTE — det store skal staa frit til den
  # tunge sprogmodel. Er der kun ét, tages det. Er der ingen, koerer Ollama
  # paa CPU som foer. Kan nvidia-smi ikke svare, roeres intet.
  # Saettes som CUDA_VISIBLE_DEVICES, saa Ollama kun ser det ene kort.
  if [ -z "${CUDA_VISIBLE_DEVICES:-}" ] && command -v nvidia-smi >/dev/null 2>&1; then
    # OBS (maalt 4. nov 2026): Ollamas CUDA-nummerering er OMVENDT af
    # nvidia-smis. nvidia-smi siger 0=1080Ti, 1=RTX 3060; Ollama bytter dem.
    # Derfor regnes der tilbage fra antallet af kort, saa det mindste kort
    # rammes uanset hvordan driveren nummererer.
    _antal=$(nvidia-smi --list-gpus 2>/dev/null | wc -l)
    _idx=$(nvidia-smi --query-gpu=index,memory.total --format=csv,noheader,nounits 2>/dev/null \
           | sort -t, -k2 -n | head -1 | cut -d, -f1 | tr -d " ")
    if [ -n "$_idx" ] && [ "$_antal" -gt 0 ]; then
      _kort=$(( _antal - 1 - _idx ))
    else
      _kort=""
    fi
    if [ -n "$_kort" ]; then
      export CUDA_VISIBLE_DEVICES="$_kort"
      log "  grafikkort: bruger index $_kort (det mindste af $(nvidia-smi --list-gpus 2>/dev/null | wc -l))"
    fi
  fi

  OLLAMA_HOST="http://127.0.0.1:11434" \
    nohup ollama serve > /opt/lillehjerne/ollama/ollama-server.log 2>&1 &
  for i in $(seq 1 30); do
    sleep 2
    curl -sf --max-time 3 "http://127.0.0.1:11434/api/tags" >/dev/null 2>&1 && break
  done
  if curl -sf --max-time 3 "http://127.0.0.1:11434/api/tags" >/dev/null 2>&1; then
    log "  hjernens egen Ollama kører — den laaner grafikkortet"
  else
    log "  ADVARSEL: hjernens egen Ollama kom ikke op — se /opt/lillehjerne/ollama/ollama-server.log"
  fi
fi

tjek_ollama || true

# ---------- 0a-2. Sikkerhedsnet for indlejringen ----------
# Peger EMBED_BASE paa en DØD adresse (fx en gammel miljøvariabel fra en
# tidligere container, der stadig siger 127.0.0.1), så brug den samme server
# som taleren i stedet. Ellers peger hjernen to veje — og indlejringen fejler,
# så der ikke kan huskes noget. Nu rettes det af sig selv ved hver start.
if [ "${PROVIDER:-ollama}" = "ollama" ] && [ -n "$OLLAMA_HOST" ]; then
  if ! curl -sf --max-time 4 "$EMBED_BASE/api/tags" >/dev/null 2>&1; then
    if curl -sf --max-time 4 "$OLLAMA_HOST/api/tags" >/dev/null 2>&1; then
      log "indlejringen pegede paa $EMBED_BASE (svarer ikke) — rettes til $OLLAMA_HOST"
      EMBED_BASE="$OLLAMA_HOST"
    fi
  fi
fi

# ---------- 0b. Ollama-SERVEREN — bevidst IKKE startet i containeren ----------
# Der skal kun findes ÉN Ollama-server i systemet: den på værten. Containerens
# egen server startes derfor ikke. Modellerne i /opt/lillehjerne/ollama/models
# BLIVER liggende urørt — de er hjernens egen kopi og røres ikke.
#
# Det er med vilje at denne funktion ikke gør noget: skal man senere køre
# hjernen helt uden værten, sætter man blot OLLAMA_HOST til
# http://127.0.0.1:11434 i .env og genindfører starteren herunder.
start_indre_ollama() {
  # Svarer vores egen server allerede, er der intet at gøre.
  if curl -sf --max-time 3 "http://127.0.0.1:11434/api/tags" >/dev/null 2>&1; then
    log "hjernens egen Ollama svarer paa 127.0.0.1:11434"
  else
    log "starter hjernens EGEN Ollama (parallel=$OLLAMA_NUM_PARALLEL, kv=$OLLAMA_KV_CACHE_TYPE, ctx=$OLLAMA_CONTEXT_LENGTH)"
    # Bind-adressen sættes EKSPLICIT: OLLAMA_HOST kan være arvet fra miljøet og
    # pege ud på værten — og så kan serveren ikke binde ("cannot assign requested
    # address"). Klienterne i containeren bruger 127.0.0.1.
    OLLAMA_HOST="http://127.0.0.1:11434" \
      nohup ollama serve > /opt/lillehjerne/ollama/ollama-server.log 2>&1 &
    for i in $(seq 1 30); do
      sleep 2
      if curl -sf --max-time 3 "http://127.0.0.1:11434/api/tags" >/dev/null 2>&1; then break; fi
    done
    if ! curl -sf --max-time 3 "http://127.0.0.1:11434/api/tags" >/dev/null 2>&1; then
      log "  ADVARSEL: hjernens egen Ollama kom ikke op — se /opt/lillehjerne/ollama/ollama-server.log"
      return 1
    fi
    log "  hjernens egen Ollama kører"
  fi
  # Er modellerne der? De ligger i image'et; mangler de, er svaret et nyt build.
  local t
  t=$(curl -sf --max-time 5 "http://127.0.0.1:11434/api/tags" 2>/dev/null || echo "")
  if echo "$t" | grep -q "${OLLAMA_MODEL%%:*}"; then
    log "  taleren '$OLLAMA_MODEL' er klar"
  else
    log "  ADVARSEL: taleren '$OLLAMA_MODEL' findes ikke i hjernens modelmappe"
  fi
  if echo "$t" | grep -q "${EMBED_MODEL%%:*}"; then
    log "  indlejringen '$EMBED_MODEL' er klar"
  else
    log "  ADVARSEL: indlejringen '$EMBED_MODEL' findes ikke i hjernens modelmappe"
  fi
  return 0
}
# (Ollama startes nu i afsnit 0a ovenfor — FØR søgningen. Funktionen herunder er
#  ikke længere kaldt; den bliver stående som reference indtil den er ryddet væk.)
start_indre_ollama || true

# ---------- 1. PostgreSQL ----------
# pgaudit skal indlæses via shared_preload_libraries — det kan ikke gøres i
# et init-script. Vi sender det som et server-argument ved opstart.
log "starter PostgreSQL 17 ..."
/usr/local/bin/docker-entrypoint.sh postgres -c shared_preload_libraries=pgaudit,age &
PG_PID=$!

# vent på at Postgres svarer
for i in $(seq 1 60); do
  if pg_isready -q -U "$POSTGRES_USER" -h 127.0.0.1 2>/dev/null; then
    log "PostgreSQL svarer (efter ${i}s)"
    break
  fi
  sleep 1
done

# ---------- 2. ArangoDB — FJERNET (DNA 2026-10-11) ----------
# Arango blev aldrig brugt: HC, NPLL, Ops og Viewer rørte den ikke, og lageret
# var tomt. Grafen bor i Postgres/AGE (samme motor som hukommelsen).
# DNA's ord: "vi har ikke brug for den, den laver støj."
AR_PID=""

# ---------- 3. NPLL-scorer ----------
if [ "$NPLL_ENABLED" = "true" ] && [ -f /opt/lillehjerne/npll/scorer.py ]; then
  log "starter NPLL-scorer på port $NPLL_PORT ..."
  su postgres -s /bin/bash -c \
    "/opt/lillehjerne/venv/bin/python /opt/lillehjerne/npll/scorer.py --port $NPLL_PORT" &
  NPLL_PID=$!
else
  NPLL_PID=""
fi

# ---------- 4. Ops — mellemhukommelsen (lag 2) ----------
# Obsidian-mappen læses som den er: noter bliver knuder, links bliver kanter.
# Mountes med -v <din mappe>:/vault:ro. Uden mount svarer tjenesten, men tomt.
if [ -f /opt/lillehjerne/ops/ops_tjeneste.py ]; then
  log "starter Ops-tjenesten på port $OPS_PORT ..."
  if [ ! -d "$OPS_VAULT" ]; then
    log "  bemærk: vaulten '$OPS_VAULT' er ikke mountet endnu"
    log "  mount den med:  -v <din Obsidian-mappe>:/vault:ro"
  fi
  # Hjernens EGEN Obsidian (volume, ejet af postgres): derfor kan postgres
  # både læse og skrive noterne. DNA's private mappe er ikke monteret.
  su postgres -s /bin/bash -c \
    "OPS_VAULT='$OPS_VAULT' OPS_PORT='$OPS_PORT' \
     /opt/lillehjerne/venv/bin/python /opt/lillehjerne/ops/ops_tjeneste.py" &
  OPS_PID=$!
else
  OPS_PID=""
fi

# ---------- 5. Viewer — brugerfladen ind i hjernen ----------
# Den interaktive flade: grafen og noterne tegnet som et net. Læsning kun.
if [ -f /opt/lillehjerne/viewer/start_viewer.py ]; then
  # Byg noternes datasæt først, så OPS-visningen er frisk ved start.
  if [ -f /opt/lillehjerne/viewer/byg_ops.py ] && [ -d "$OPS_VAULT" ]; then
    log "bygger noternes datasæt ..."
    su postgres -s /bin/bash -c \
      "OBSIDIAN_VAULT='$OPS_VAULT' \
       OPS_JSON=/opt/lillehjerne/viewer/data/ops.json \
       /opt/lillehjerne/venv/bin/python /opt/lillehjerne/viewer/byg_ops.py" \
      >/dev/null 2>&1 || log "  (kunne ikke bygge noternes datasæt)"
  fi
  # Og den GAMLE graf, så viewer'en ser BEGGE graf-databaser (api/graph +
  # api/efterforskning). Læser juridiske_sager i gammel_graf — kun læsning.
  if [ -f /opt/lillehjerne/viewer/byg_efterforskning.py ]; then
    log "bygger efterforsknings-datasættet (den gamle graf) ..."
    su postgres -s /bin/bash -c \
      "DB_HOST=127.0.0.1 DB_PORT=5432 EFTER_DB_NAME=gammel_graf \
       EFTER_GRAF=juridiske_sager DB_USER='$POSTGRES_USER' \
       DB_PASS='$POSTGRES_PASSWORD' \
       EFTER_JSON=/opt/lillehjerne/viewer/data/efterforskning.json \
       /opt/lillehjerne/venv/bin/python /opt/lillehjerne/viewer/byg_efterforskning.py" \
      >/dev/null 2>&1 || log "  (kunne ikke bygge efterforsknings-datasættet)"
  fi
  log "starter Viewer på port $VIEWER_PORT ..."
  su postgres -s /bin/bash -c \
    "DB_HOST=127.0.0.1 DB_PORT=5432 DB_NAME='$POSTGRES_DB' \
     DB_USER='$POSTGRES_USER' DB_PASS='$POSTGRES_PASSWORD' GRAPH=hjerne \
     OPS_URL=http://127.0.0.1:'$OPS_PORT' \
     OBSIDIAN_VAULT='$OPS_VAULT' VIEWER_PORT='$VIEWER_PORT' \
     /opt/lillehjerne/venv/bin/python /opt/lillehjerne/viewer/start_viewer.py" &
  VIEWER_PID=$!
else
  VIEWER_PID=""
fi

log "klar — motoren kører. Poster: 5432 (PG/AGE), ${NPLL_PORT} (NPLL), ${OPS_PORT} (Ops), ${VIEWER_PORT} (Viewer), ${HC_PORT} (HC)"
log "Taleren (${OLLAMA_MODEL}) OG indlejringen (${EMBED_MODEL}) ligger i image'et og kører i hjernens EGEN Ollama paa 127.0.0.1:11434 — den laaner grafikkortet."
log "Vaertens Ollama bruges kun som reserve, hvis hjernens egen ikke svarer."

# ---------- 6. KONKLUSIONSMOTOREN + DRØMMEN — i stedet for HC ----------
# Trokopi af Super Brain, men HC (Honcho) er byttet ud med vores egen
# konklusionsmotor (6305) og Drømmen (6304). Ingen LLM i dette lag:
# motoren udleder med regler, og Drømmen spørger først 9B'eren på værten
# når den er i tvivl — svaret bliver et FORSLAG, aldrig en konklusion.
if [ -f /opt/lillehjerne/start.py ]; then
  log "starter konklusionsmotoren + Drømmen ..."
  cd /opt/lillehjerne && /usr/bin/python3 start.py >>/var/log/konklusion.log 2>&1 &
  HC_PID=$!
else
  HC_PID=""
fi

# ---------- 6b. DANSK SØGEINDEKS ----------
# Koden søger nu med den danske ordbog ('danish') i stedet for den engelske.
# Et indeks der ALLEREDE er bygget med 'english' skifter ikke af sig selv —
# og HC's egen migration bygger det stadig med engelsk. Derfor bygges det om
# her, én gang, og kun hvis det trænger. Kører i baggrunden, så opstarten ikke
# venter. Tjekkes tre gange, i tilfælde af at HC bygger indekset efter os.
ret_dansk_soegeindeks() {
  local n def findes
  for n in 1 2 3; do
    findes=""
    local i
    for i in $(seq 1 40); do
      findes=$(su postgres -s /bin/bash -c \
        "PGPASSWORD='$POSTGRES_PASSWORD' psql -h 127.0.0.1 -U '$POSTGRES_USER' -d '$POSTGRES_DB' -tAc \"SELECT to_regclass('hc.messages') IS NOT NULL\"" 2>/dev/null)
      [ "$findes" = "t" ] && break
      sleep 3
    done
    if [ "$findes" != "t" ]; then
      log "dansk søgeindeks: hc.messages findes endnu ikke — springer over"
      return 0
    fi
    def=$(su postgres -s /bin/bash -c \
      "PGPASSWORD='$POSTGRES_PASSWORD' psql -h 127.0.0.1 -U '$POSTGRES_USER' -d '$POSTGRES_DB' -tAc \"SELECT indexdef FROM pg_indexes WHERE schemaname='hc' AND indexname='ix_messages_content_gin'\"" 2>/dev/null)
    case "$def" in
      *english*)
        log "bygger søgeindekset om til dansk ordbog (det gamle brugte engelsk) ..."
        if su postgres -s /bin/bash -c \
          "PGPASSWORD='$POSTGRES_PASSWORD' psql -h 127.0.0.1 -U '$POSTGRES_USER' -d '$POSTGRES_DB' -c \"
             DROP INDEX IF EXISTS hc.ix_messages_content_gin;
             CREATE INDEX ix_messages_content_gin ON hc.messages
               USING gin (to_tsvector('danish'::regconfig, content));
           \"" >>/var/log/hc.log 2>&1; then
          log "  søgeindekset er nu dansk"
        else
          log "  ADVARSEL: kunne ikke bygge søgeindekset om — se /var/log/hc.log"
        fi
        ;;
      "")
        log "  dansk søgeindeks: intet indeks endnu — HC bygger det selv" ;;
      *)
        log "  dansk søgeindeks: allerede dansk" ;;
    esac
    sleep 25
  done
}
ret_dansk_soegeindeks &

# ---------- 6c. Broen — enricher-laget ----------
# Konklusion → opslag i registeret → kant i grafen. Deterministisk: der er
# INGEN model i denne tjeneste. Den kan køre i baggrunden, og den kan køre
# igen — det den allerede har afgjort, springes over (bro.koersel).
# Den venter selv på at hc.documents findes, så den maa gerne starte her.
if [ -f /opt/lillehjerne/enricher/bro.py ]; then
  log "starter broen (enricher-laget) ..."
  su postgres -s /bin/bash -c \
    "POSTGRES_USER='$POSTGRES_USER' POSTGRES_PASSWORD='$POSTGRES_PASSWORD' \
     POSTGRES_DB='$POSTGRES_DB' OPS_VAULT='$OPS_VAULT' GRAF=hjerne \
     /opt/lillehjerne/venv/bin/python /opt/lillehjerne/enricher/bro.py --soevn 60" \
    >>/var/log/bro.log 2>&1 &
  BRO_PID=$!
else
  BRO_PID=""
fi

# ---------- 6d. Kategoriseringen — hver konklusion faar kategori og emne ----------
# Konklusion → kategori (et af Domena) → emne → haengt op under Domene.
# Deterministisk som broen: ingen model. Kan koere igen — det den har afgjort,
# springes over (konklusionen har saa 'kategori'). Saa intet flyder loest.
if [ -f /opt/lillehjerne/enricher/kategori.py ]; then
  log "starter kategoriseringen ..."
  su postgres -s /bin/bash -c \
    "POSTGRES_USER='$POSTGRES_USER' POSTGRES_PASSWORD='$POSTGRES_PASSWORD' \
     POSTGRES_DB='$POSTGRES_DB' GRAF=hjerne \
     /opt/lillehjerne/venv/bin/python /opt/lillehjerne/enricher/kategori.py --soevn 60" \
    >>/var/log/kategori.log 2>&1 &
  KAT_PID=$!
else
  KAT_PID=""
fi

# ---------- Hold liv i containeren ----------
trap 'log "stopper ..."; [ -n "${HC_PID:-}" ] && kill $HC_PID 2>/dev/null; [ -n "${VIEWER_PID:-}" ] && kill $VIEWER_PID 2>/dev/null; [ -n "${OPS_PID:-}" ] && kill $OPS_PID 2>/dev/null; [ -n "${AR_PID:-}" ] && kill $AR_PID 2>/dev/null; [ -n "${NPLL_PID:-}" ] && kill $NPLL_PID 2>/dev/null; [ -n "${BRO_PID:-}" ] && kill $BRO_PID 2>/dev/null; [ -n "${KAT_PID:-}" ] && kill $KAT_PID 2>/dev/null; [ -n "${OLLAMA_PID:-}" ] && kill $OLLAMA_PID 2>/dev/null; kill $PG_PID 2>/dev/null; exit 0' TERM INT
wait $PG_PID