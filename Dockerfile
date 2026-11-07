FROM postgres:17

# Helix Super Light Brain — databasen.
#
# Samme Postgres 17 som Super Brain, men uden LLM. Udvidelserne tændes her
# i image'et, ikke i et Python-lag ovenpå.
#
# Nogle udvidelser (pg_walinspect, pg_surgery, pg_visibility, pgstattuple,
# pageinspect, amcheck, pg_freespacemap, pgrowlocks) ligger i
# postgresql-contrib-17. pg_stat_statements kommer også med contrib,
# plpython3u med postgresql-plpython3-17.

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      postgresql-contrib-17 \
      postgresql-plpython3-17 \
      postgresql-17-age \
      postgresql-17-pgvector \
      postgresql-17-plr \
      postgresql-17-http \
      postgresql-17-jsquery \
      postgresql-17-pg-wait-sampling \
      postgresql-17-pg-uuidv7 \
      postgresql-17-partman \
      postgresql-17-hypopg \
      postgresql-17-hll \
      postgresql-17-tdigest \
      postgresql-17-roaringbitmap \
      postgresql-17-show-plans \
      postgresql-17-pg-stat-plans \
 && rm -rf /var/lib/apt/lists/*

COPY init.sql /docker-entrypoint-initdb.d/00-lillehjerne.sql
# ---------- Den danske læser (DNA 2. nov 2026) ----------
# spaCy + den store danske model bages ind, så containeren er sin egen enhed:
# den kan læse dansk uden at hente noget udefra. Modellen lægges ind fra
# spacy-models-udgaven der passer til spaCy 3.8 (Python 3.13).
#
# Rækkefølgen er ikke ligegyldig: numpy skal ned under 2 FØR spaCy, ellers
# knækker thinc-binæren med "numpy.dtype size changed" (målt under tørkørslen).
RUN pip install --no-cache-dir --break-system-packages \
      "numpy<2" \
      "spacy>=3.8,<3.9" \
 && pip install --no-cache-dir --break-system-packages \
      https://github.com/explosion/spacy-models/releases/download/da_core_news_lg-3.8.0/da_core_news_lg-3.8.0-py3-none-any.whl

# Bevis ved build: modellen skal kunne indlæses, ellers fejler bygget her —
# ikke i drift kl. 3 om natten.
RUN python3 -c "import spacy; n=spacy.load('da_core_news_lg'); print('dansk model OK', n.meta['version'])"
