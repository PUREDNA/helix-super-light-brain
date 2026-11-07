-- Helix Super Light Brain — init (Postgres 18)
-- Kører én gang, første gang databasen rejses.
--
-- REGEL (DNA 1. november 2026): alle udvidelser tændes. Vi bygger ikke et
-- skib for at bruge et hjørne. Kan en udvidelse ikke tændes, skrives det i
-- loggen med grunden — den springes ikke stille over.

\set ON_ERROR_STOP off

DO $$
DECLARE
  u text;
  fejl text;
  ok int := 0;
  ikke int := 0;
BEGIN
  FOREACH u IN ARRAY ARRAY[
    'age','vector','pg_trgm','fuzzystrmatch','unaccent','dict_int','dict_xsyn',
    'bloom','btree_gin','btree_gist','citext','hstore','jsquery',
    'intarray','intagg','hll','tdigest','roaringbitmap','cube','seg','isn','ltree',
    'earthdistance','tablefunc','xml2','lo','file_fdw','postgres_fdw','dblink','http',
    'pg_uuidv7','uuid-ossp','tcn','moddatetime','insert_username','autoinc','refint',
    'pg_partman','pgaudit','pgcrypto','sslinfo',
    'pg_stat_statements','pg_stat_plans','pg_show_plans','pg_wait_sampling','hypopg',
    'pg_buffercache','pg_prewarm','pg_visibility','pg_freespacemap','pgstattuple',
    'pageinspect','amcheck','pg_surgery','pgrowlocks','pg_walinspect','pg_logicalinspect',
    'tsm_system_rows','tsm_system_time','plr','plpython3u'
  ]
  LOOP
    BEGIN
      EXECUTE format('CREATE EXTENSION IF NOT EXISTS %I CASCADE', u);
      RAISE NOTICE 'UDVIDELSE OK       %', u;
      ok := ok + 1;
    EXCEPTION WHEN OTHERS THEN
      GET STACKED DIAGNOSTICS fejl = MESSAGE_TEXT;
      RAISE WARNING 'UDVIDELSE SPRUNGET % — %', u, fejl;
      ikke := ikke + 1;
    END;
  END LOOP;
  RAISE NOTICE '=== UDVIDELSER: % taendt, % ikke tilgaengelig ===', ok, ikke;
END $$;

-- Oversigt til log og viewer
CREATE OR REPLACE VIEW udvidelser AS
SELECT extname, extversion FROM pg_extension ORDER BY extname;
