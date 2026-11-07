#!/bin/bash
# Helix Super Light Brain — entrypoint.
#
# Rækkefølgen betyder noget:
#   1. Rejs Postgres (hvis data-mappen er tom, køres init.sql automatisk)
#   2. Vent til den svarer
#   3. Hent BGE-M3 hvis den ikke ligger i modellaget
#   4. Start resten (Ollama, Konklusionsmotoren, Drømmen, Viewer, Hukommelsen)
#
# ALT logges med tidsstempel og del-navn, så containerens log er fyldestgørende:
# hvad der starter, hvad der venter, hvad der fejler og hvorfor.
set -e

log() { printf '%s [%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" "$2"; }

export PATH="/usr/lib/postgresql/18/bin:$PATH"
PGDATA=${PGDATA:-/var/lib/postgresql/data}
POSTGRES_DB=${POSTGRES_DB:-hjerne}

log START "Helix Super Light Brain rejses"
log START "Postgres $(postgres --version 2>/dev/null | awk '{print $3}') | data: $PGDATA"

mkdir -p "$PGDATA" /var/run/postgresql
chown -R postgres:postgres "$PGDATA" /var/run/postgresql

# Kun de udvidelser der faktisk findes må stå i preload — ellers nægter
# Postgres at starte. Vi tjekker først og skriver hvad vi valgte.
PRELOAD="pg_stat_statements"
if [ -f /usr/lib/postgresql/18/lib/pgaudit.so ]; then
  PRELOAD="pgaudit,$PRELOAD"
  log DB "preload: $PRELOAD"
else
  log DB "advarsel: pgaudit.so mangler — kører uden revisionslog"
fi

if [ ! -s "$PGDATA/PG_VERSION" ]; then
  log DB "tom data-mappe — rejser ny base"
  su postgres -c "initdb -D $PGDATA --encoding=UTF-8 --locale=C" >/dev/null
  log DB "initdb færdig"
  printf 'host all all 127.0.0.1/32 trust\nhost all all ::1/128 trust\nlocal all all trust\n' >> "$PGDATA/pg_hba.conf"
  su postgres -c "pg_ctl -D $PGDATA -o '-c shared_preload_libraries=$PRELOAD -c shared_buffers=256MB' -l /tmp/pg.log start" >/dev/null
  for i in $(seq 1 30); do
    su postgres -c "pg_isready -q" 2>/dev/null && break
    sleep 1
  done
  su postgres -c "createdb $POSTGRES_DB" 2>/dev/null && log DB "database $POSTGRES_DB oprettet"
  su postgres -c "psql -q -d postgres -c \"CREATE ROLE hjerne LOGIN SUPERUSER\"" 2>/dev/null && log DB "rolle hjerne oprettet"
  su postgres -c "psql -q -d postgres -c \"ALTER DATABASE $POSTGRES_DB OWNER TO hjerne\"" 2>/dev/null
  log DB "indlæser udvidelser (hver linje vises nedenfor)"
  su postgres -c "psql -d $POSTGRES_DB -f /opt/lillehjerne/init.sql" 2>&1 | \
    grep -oE "NOTICE:  (UDVIDELSE[^\"]*|=== UDVIDELSER[^\"]*)|WARNING:  (UDVIDELSE[^\"]*)" | \
    sed 's/^/ /' || log DB "init havde fejl — se /tmp/init.log"
  su postgres -c "psql -d $POSTGRES_DB -f /opt/lillehjerne/init.sql" >/tmp/init.log 2>&1 || \
    log DB "init.log skrevet"
else
  log DB "eksisterende data-mappe — genstarter"
  su postgres -c "pg_ctl -D $PGDATA -o '-c shared_preload_libraries=$PRELOAD -c shared_buffers=256MB' -l /tmp/pg.log start" >/dev/null
fi

for i in $(seq 1 40); do
  if su postgres -c "pg_isready -q" 2>/dev/null; then break; fi
  sleep 1
done
if ! su postgres -c "pg_isready -q" 2>/dev/null; then
  log FEJL "Postgres startede ikke — sidste linjer fra /tmp/pg.log:"
  tail -20 /tmp/pg.log 2>/dev/null | sed 's/^/   /'
  exit 1
fi
ANTAL=$(su postgres -c "psql -tAd $POSTGRES_DB -c 'SELECT count(*) FROM pg_extension'" 2>/dev/null)
log DB "klar — $ANTAL udvidelser aktive"

# BGE-M3 — den eneste model i containeren
if ollama list 2>/dev/null | grep -q bge-m3; then
  log MODEL "bge-m3 findes lokalt"
else
  log MODEL "henter bge-m3 (engangsarbejde, ca. 1,2 GB)"
  ollama serve >/tmp/ollama-boot.log 2>&1 &
  BOOT_PID=$!
  sleep 5
  if ollama pull bge-m3 2>&1 | tail -3 | sed 's/^/   /'; then
    log MODEL "bge-m3 hentet"
  else
    log FEJL "kunne ikke hente bge-m3 — kører uden embedding"
  fi
  kill $BOOT_PID 2>/dev/null || true
  sleep 2
fi

log START "starter tjenester: ollama, konklusion(6305), drom(6304), viewer(6301), hukommelse(6302)"
exec python3 /opt/lillehjerne/start.py
