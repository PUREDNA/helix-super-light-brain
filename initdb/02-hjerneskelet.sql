-- ============================================================
--  HJERNESKELETTET — den rene struktur
--
--  KUN HJERNE-PLANET. Det er her MOC'en vinder frem for resten af
--  Hermes' struktur: grafen, tankestrukturen, samtalen, projekterne.
--
--  Alt det andet — regler, konventioner, værktøjer, hvordan man
--  bygger en agent — har Hermes allerede sine egne steder til
--  (AGENTS.md, skills, boardet). Det skal IKKE gentages her.
--
--  Der er INGEN personlige data. En agent der installerer
--  containeren læser dette og forstår systemet.
--
--  Bygget 2026-10-07. Formen er hentet fra DNA's eget system,
--  men gjort enkel — uden overflod.
-- ============================================================

LOAD 'age';
SET search_path = ag_catalog, "$user", public;
-- Grafen laves i 01-udvidelser.sql. Her bygges skelettet oveni.

-- ------------------------------------------------------------
--  INDGANGEN — MOC
--  Hovedindgangen. Simpel. Fem grene og ikke mere.
-- ------------------------------------------------------------
SELECT * FROM cypher('hjerne', $$
  CREATE (moc:MOC {
    navn: 'MOC',
    note: 'Hovedindgangen til hjernen. Fem grene: grafen (hvordan ting hænger sammen), samtalen (hvad der blev sagt), noterne (hvad der er skrevet ned), projekterne (hvad der arbejdes på) og maskinen (hvad der kører). Søg her først — i dine egne ord, på betydning.',
    type: 'MOC',
    opdateret: '2026-10-07'
  })
$$) AS (a agtype);

-- ------------------------------------------------------------
--  GREN 1 — GRAFEN: hvordan ting hænger sammen
--  Personen, sagen, dokumentet, institutionen. Det spørgsmål
--  en graf er lavet til: hvem kender hvem, hvad hører til hvad.
-- ------------------------------------------------------------
SELECT * FROM cypher('hjerne', $$
  MATCH (moc:MOC)
  CREATE (g:Domene {
    navn: 'Grafen',
    note: 'Viden gemt som knuder og forbindelser i stedet for som tekst. En knude er en ting — en person, et dokument, en regel. En forbindelse er hvordan to ting hænger sammen. Her svarer systemet på HVORDAN, ikke HVAD: hvilke dokumenter hører til sagen, og hvem optræder i dem. Typer: Person, Sag, Dokument, Institution, Firma, Aftale, Begivenhed.',
    type: 'hjerne-del',
    opdateret: '2026-10-07'
  })
  CREATE (moc)-[:INDHOLDER]->(g)
$$) AS (a agtype);

-- ------------------------------------------------------------
--  GREN 2 — SAMTALEN: hvad der blev sagt
--  Hermes' egen samtalelog. Rå, ord for ord. Kilden til viden.
-- ------------------------------------------------------------
SELECT * FROM cypher('hjerne', $$
  MATCH (moc:MOC)
  CREATE (s:Domene {
    navn: 'Samtalen',
    note: 'Hermes\' egen samtalelog — hver besked i hver samtale, gemt råt og uændret. Det er ikke viden, det er KILDEN til viden. Her finder man ud af hvad der blev sagt hvornår. Læses af systemet selv. Det er herfra transportbåndet trækker data ud til HC.',
    type: 'hjerne-del',
    opdateret: '2026-10-07'
  })
  CREATE (moc)-[:INDHOLDER]->(s)
$$) AS (a agtype);

-- ------------------------------------------------------------
--  GREN 3 — NOTERNE (Ops): hvad der er skrevet ned
--  Obsidian-arbejdsbordet. Menneskets udgave — læsbar og
--  redigerbar. Landingsstationen før viden løftes til grafen.
-- ------------------------------------------------------------
SELECT * FROM cypher('hjerne', $$
  MATCH (moc:MOC)
  CREATE (n:Domene {
    navn: 'Noterne (Ops)',
    note: 'Arbejdsbordet — en mappe med almindelige Markdown-filer, som mennesket kan læse og rette i. Her lander rapporter, undersøgelser og noter fra dagens arbejde, før de løftes videre til grafen. Tjenesten læser mappen som den er: noter bliver knuder, links bliver kanter. Uden dette lag hænger hjernen ikke sammen — en database er god til maskiner, en mappe med tekstfiler er god til mennesker, og begge dele skal der være.',
    type: 'hjerne-del',
    opdateret: '2026-10-07'
  })
  CREATE (moc)-[:INDHOLDER]->(n)
$$) AS (a agtype);

-- ------------------------------------------------------------
--  GREN 4 — PROJEKTERNE: hvad der arbejdes på
-- ------------------------------------------------------------
SELECT * FROM cypher('hjerne', $$
  MATCH (moc:MOC)
  CREATE (p:Domene {
    navn: 'Projekterne',
    note: 'Arbejdets emner og deres tilstand. Hvert projekt er en gren med sine egne børn. Her ses hvad der er i gang, hvad der er færdigt, og hvad der er blokeret.',
    type: 'hjerne-del',
    opdateret: '2026-10-07'
  })
  CREATE (moc)-[:INDHOLDER]->(p)
$$) AS (a agtype);

-- ------------------------------------------------------------
--  GREN 5 — MASKINEN: hvad der kører
--  Denne container og dens dele. Kort — detaljerne hører i
--  Hermes' egen dokumentation, ikke her.
-- ------------------------------------------------------------
SELECT * FROM cypher('hjerne', $$
  MATCH (moc:MOC)
  CREATE (m:Domene {
    navn: 'Maskinen',
    note: 'Hvad der kører og hvor. Denne container samler fem dele: PostgreSQL (hjernen — relationel data OG graf), ArangoDB (graf-lageret), Odin (algoritme-motoren), NPLL-scoreren (dømmekraften, der vejer hver kant 0,0-1,0) og Ops-tjenesten (mellemhukommelsen). Sprogmodellen hentes udefra gennem Ollama og kører på grafikkortet.',
    type: 'hjerne-del',
    opdateret: '2026-10-07'
  })
  CREATE (moc)-[:INDHOLDER]->(m)
$$) AS (a agtype);

-- ------------------------------------------------------------
--  TRANSPORTBÅNDET — hvordan hukommelsen fyldes
--
--  Den vigtigste enkeltregel i hele systemet. Uden den står
--  hjernen stille.
--
--    HØJRE side:  Hermes Agent memory
--    VENSTRE side: HC (Honcho) — modtager, konverterer, gemmer
--    UD:          databaserne → Helix Super Brain
--
--  Det kører LØBENDE. Man tømmer ikke manuelt.
-- ------------------------------------------------------------
SELECT * FROM cypher('hjerne', $$
  CREATE (t:Arbejdsgang {
    navn: 'Transportbåndet',
    note: 'Hermes Agent memory skal sættes op til at sende sin hukommelse til HC, så HC tømmer den LØBENDE — som et transportbånd. Ind fra højre: Hermes Agent memory. Ud til venstre: HC (Honcho), der modtager, konverterer og gemmer i databasen. Derefter er alt synligt i Helix Super Brain. Sæt HC op til dette FØR den tages i brug — ellers samler hukommelsen sig ingen steder.',
    type: 'hjerne-del',
    opdateret: '2026-10-07'
  })
$$) AS (a agtype);

-- ------------------------------------------------------------
--  ARBEJDSGANGEN — de fire lag, kort
-- ------------------------------------------------------------
SELECT * FROM cypher('hjerne', $$
  MATCH (t:Arbejdsgang {navn:'Transportbåndet'})
  CREATE (l1:Lag {
    navn: 'Lag 1 — den korte',
    note: 'Agentens egen hukommelse. Meget lille, lægges ind i hver samtale. Kun det der gælder altid: hvem brugeren er, hvordan han vil have tingene.',
    nr: 1
  })
  CREATE (l2:Lag {
    navn: 'Lag 2 — den mellemlange',
    note: 'Noterne. Landingsstationen hvor rapporter og undersøgelser lander før de løftes videre. Menneskets udgave — læsbar og redigerbar.',
    nr: 2
  })
  CREATE (l3:Lag {
    navn: 'Lag 3 — den lange',
    note: 'Grafen. Viden som knuder og forbindelser, søgbar på betydning. Systemets langtidshukommelse.',
    nr: 3
  })
  CREATE (l4:Lag {
    navn: 'Lag 4 — kilden',
    note: 'Samtaleloggen. Hver besked, råt og uændret. Ikke viden — kilden til viden.',
    nr: 4
  })
  CREATE (t)-[:HAR_LAG]->(l1)
  CREATE (t)-[:HAR_LAG]->(l2)
  CREATE (t)-[:HAR_LAG]->(l3)
  CREATE (t)-[:HAR_LAG]->(l4)
$$) AS (a agtype);

-- ------------------------------------------------------------
--  SYSTEMETS TABELLER
--  Vektortabellen hoerer i ag_catalog — det er DER MOC soeger
--  (DNA 2026-10-03; se plugins/ops-indeks/ og scripts/moc_søg.py).
--  Der laa tidligere en TOM dublet i public som ingen laeste. Den er
--  fjernet, saa der kun findes ÉN tabel til ét formaal: grafen.
--  Resten af vores egne tabeller bliver i public.
-- ------------------------------------------------------------
SET search_path = public;

-- Vektorsystemet — broen der gør grafen søgbar på betydning.
-- Uden dette er grafen en samling noder man selv skal grave i.
CREATE TABLE IF NOT EXISTS ag_catalog.referencer_embeddings (
    id         bigserial PRIMARY KEY,
    node_id    text,
    navn       text,
    tekst      text,
    embedding  vector(1024),
    metadata   jsonb DEFAULT '{}'::jsonb,
    namespace  text DEFAULT 'referencer',
    opdateret  timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS referencer_embeddings_hnsw_idx
    ON ag_catalog.referencer_embeddings
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 200);
-- Soegevejen filtrerer paa namespace — uden indeks bliver hvert
-- MOC-opslag et gennemloeb af hele tabellen.
CREATE INDEX IF NOT EXISTS referencer_embeddings_ns
    ON ag_catalog.referencer_embeddings (namespace);

-- Sporbarhed — hver konklusion bærer sin egen kilde.
CREATE TABLE IF NOT EXISTS public.sporbarhed (
    id          bigserial PRIMARY KEY,
    kilde_peer  text,
    kilde_peers jsonb DEFAULT '{}'::jsonb,
    message_ids jsonb DEFAULT '[]'::jsonb,
    oprettet    timestamptz DEFAULT now()
);

-- Dømmekraften — NPLL-scoren skrives som felt på kanten.
CREATE TABLE IF NOT EXISTS public.kant_score (
    id          bigserial PRIMARY KEY,
    kant_id     text NOT NULL,
    score       real CHECK (score >= 0.0 AND score <= 1.0),
    begrundelse text,
    beregnet    timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS kant_score_id_idx ON public.kant_score (kant_id);
