-- Ret de gamle klumpede modsigelser (DNA 2. nov 2026).
-- Hver "A | B" bliver til en læsbar sætning i kilde_tekst, vaerdi bliver NULL,
-- og de linjer der er uenige får et fælles modsigelse_id.
-- Beviset bevares: intet slettes, kun omformes.

BEGIN;

-- 1. Én fælles uuid pr. (emne, egenskab) for de klumpede rækker.
CREATE TEMP TABLE klump AS
SELECT id, emne, split_part(egenskab, ':', 2) AS egenskab, vaerdi
FROM konklusion
WHERE vaerdi LIKE '% | %';

-- 2. Omform hver klump til en læsbar sætning i kilde_tekst, vaerdi = NULL.
UPDATE konklusion k
SET vaerdi = NULL,
    kilde_tekst = k.emne || '.' || split_part(k.egenskab, ':', 2) || ' har ' ||
                  (length(k.vaerdi) - length(replace(k.vaerdi, '|', '')) + 1) ||
                  ' forskellige værdier: ' ||
                  regexp_replace(
                      regexp_replace(k.vaerdi, '\s*\|\s*', '«; «', 'g'),
                      '^(.*)$', '«\1»'),
    modsigelse_id = md5(k.emne || '|' || split_part(k.egenskab, ':', 2))::uuid
WHERE k.vaerdi LIKE '% | %';

-- 3. De linjer der ikke er klumper men hører til samme emne+egenskab
--    får samme modsigelse_id, så uenigheden kan ses fra begge sider.
UPDATE konklusion k
SET modsigelse_id = md5(k.emne || '|' || split_part(k.egenskab, ':', 2))::uuid
FROM klump
WHERE k.emne = klump.emne
  AND split_part(k.egenskab, ':', 2) = klump.egenskab
  AND k.form <> 'modsiger';

SELECT count(*) AS klumper_rettet FROM klump;
SELECT count(*) AS med_modsigelse_id FROM konklusion WHERE modsigelse_id IS NOT NULL;

COMMIT;
