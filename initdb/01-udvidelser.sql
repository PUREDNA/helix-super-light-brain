-- ============================================================
--  HELIX SUPER BRAIN — init af hjernen
--  Kører ÉN gang, ved første start på et tomt volume.
--
--  SLÅR ALLE UDVIDELSER TIL. Ingen data. Helt ren.
--
--  Rækkefølgen er vigtig: AGE skal aktiveres FØR der laves
--  graf-objekter, og det gøres i den base der skal bære grafen.
-- ============================================================

-- ---------- Grundlaget (findes i postgres:17 som standard) ----------
CREATE EXTENSION IF NOT EXISTS plpgsql;

-- ---------- Vektorer (hukommelse) ----------
CREATE EXTENSION IF NOT EXISTS vector;          -- pgvector: embedding-søgning

-- ---------- Graf ----------
CREATE EXTENSION IF NOT EXISTS age;             -- Apache AGE: cypher i Postgres

-- ---------- Bro mellem baser ----------
CREATE EXTENSION IF NOT EXISTS postgres_fdw;    -- fremmede tabeller, varigt
CREATE EXTENSION IF NOT EXISTS dblink;          -- engangs-forbindelser

-- ---------- Navne og stavefejl (Helex-problemet) ----------
CREATE EXTENSION IF NOT EXISTS fuzzystrmatch;   -- levenshtein: "Helex" vs "Helix"
CREATE EXTENSION IF NOT EXISTS unaccent;        -- fjern accenter ved søgning
CREATE EXTENSION IF NOT EXISTS pg_trgm;         -- næsten-dubletter
CREATE EXTENSION IF NOT EXISTS citext;          -- tekst uden store/små forskel

-- ---------- Struktur og hierarki ----------
CREATE EXTENSION IF NOT EXISTS ltree;           -- træstruktur (DNA's gren-tanke)
CREATE EXTENSION IF NOT EXISTS intarray;        -- indeks på lister af tal
CREATE EXTENSION IF NOT EXISTS hstore;          -- nøgle/værdi-sæt
CREATE EXTENSION IF NOT EXISTS bloom;           -- signatur-indeks
CREATE EXTENSION IF NOT EXISTS btree_gin;
CREATE EXTENSION IF NOT EXISTS btree_gist;

-- ---------- Drift og overvågning ----------
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;  -- langsomme forespørgsler
CREATE EXTENSION IF NOT EXISTS pg_prewarm;           -- varm cache ved start
CREATE EXTENSION IF NOT EXISTS pg_buffercache;
CREATE EXTENSION IF NOT EXISTS pgstattuple;
CREATE EXTENSION IF NOT EXISTS amcheck;              -- tabel-integritet
CREATE EXTENSION IF NOT EXISTS hypopg;               -- test-indekser uden at bygge dem

-- ---------- Sikkerhed og sporbarhed ----------
CREATE EXTENSION IF NOT EXISTS pgcrypto;        -- hashing, uforfalskelig sporbarhed
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS pg_uuidv7;       -- sorterbare id'er
CREATE EXTENSION IF NOT EXISTS pgaudit;         -- revisionsspor
CREATE EXTENSION IF NOT EXISTS moddatetime;     -- hvornår blev rækken ændret
CREATE EXTENSION IF NOT EXISTS insert_username;

-- ---------- Geografi ----------
CREATE EXTENSION IF NOT EXISTS cube;
CREATE EXTENSION IF NOT EXISTS earthdistance;   -- afstande mellem punkter

-- ---------- Tekst og data ----------
CREATE EXTENSION IF NOT EXISTS tablefunc;       -- krydstabeller
CREATE EXTENSION IF NOT EXISTS dict_int;
CREATE EXTENSION IF NOT EXISTS jsquery;         -- JSON-forespørgselssprog
CREATE EXTENSION IF NOT EXISTS tdigest;         -- percentiler på store mængder
CREATE EXTENSION IF NOT EXISTS pg_partman;      -- partitionering (control-filen hedder pg_partman)

-- ---------- Filer ----------
CREATE EXTENSION IF NOT EXISTS file_fdw;        -- læs filer som tabeller

-- ============================================================
--  GRAFEN — tom, klar til at blive fyldt
--  Apache AGE kræver at grafen oprettes i ag_catalog.
-- ============================================================
LOAD 'age';
SET search_path = ag_catalog, "$user", public;
SELECT create_graph('hjerne');

-- Nulstil søgestien, så vores EGNE tabeller havner i public — ikke i ag_catalog.
SET search_path = public;

CREATE TABLE IF NOT EXISTS sporbarhed (
    id          bigserial PRIMARY KEY,
    kilde_peer  text,                       -- hvem sagde det
    kilde_peers jsonb DEFAULT '{}'::jsonb, -- fordeling hvis flere
    message_ids jsonb DEFAULT '[]'::jsonb, -- hvilke beskeder
    oprettet    timestamptz DEFAULT now()
);
COMMENT ON TABLE sporbarhed IS 'Hver konklusion bærer sin egen kilde — så sandhed kan veje tungere end gammelt.';

-- ============================================================
--  NPLL-SCORE — tallet på kanten
--  Odin/NPLL skriver hertil; alle baser læser det via FDW.
-- ============================================================
CREATE TABLE IF NOT EXISTS kant_score (
    id          bigserial PRIMARY KEY,
    kant_id     text NOT NULL,
    score       real CHECK (score >= 0.0 AND score <= 1.0),
    begrundelse text,
    beregnet    timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS kant_score_id_idx ON kant_score (kant_id);
COMMENT ON TABLE kant_score IS 'Troværdigheden af hver kant, 0.0-1.0. Skrevet af NPLL-scoreren.';

-- ---------- Vektor-indeks (det HC manglede) ----------
-- Laves når der er data:  CREATE INDEX ... USING hnsw (embedding vector_cosine_ops);
