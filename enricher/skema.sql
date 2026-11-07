-- ============================================================
--  BROEN — bogfoeringen
--
--  Koeres af enricher/bro.py ved hver start (CREATE IF NOT EXISTS).
--  Skemaet 'bro' er broens eget: hvad den har set, og hvad den afgjorde.
--  Det ligger ved siden af 'hc' — hukommelsen rorer det ikke.
-- ============================================================

CREATE SCHEMA IF NOT EXISTS bro;

-- Een raekke pr. konklusion der er koert gennem registeret.
-- UNIQUE paa konklusion_id goer koerslen gentagelig: koerer man igen,
-- springes det over der allerede er afgjort.
CREATE TABLE IF NOT EXISTS bro.koersel (
    id            bigserial PRIMARY KEY,
    konklusion_id text UNIQUE NOT NULL,
    niveau        text,
    bevis         text,
    entiteter     int  DEFAULT 0,
    kanter        int  DEFAULT 0,
    resultat      text,
    koert         timestamptz DEFAULT now()
);

-- Een raekke pr. entitet der er slaaet op. Svarer til grafen, men i tabelform,
-- saa man kan se listen uden at kunne Cypher.
CREATE TABLE IF NOT EXISTS bro.entitet (
    navn     text NOT NULL,
    slags    text NOT NULL,
    register text,
    bevis    text,
    kilde    text,
    foerste  timestamptz DEFAULT now(),
    sidste   timestamptz DEFAULT now(),
    PRIMARY KEY (navn, slags)
);

CREATE INDEX IF NOT EXISTS bro_koersel_bevis_idx  ON bro.koersel (bevis);
CREATE INDEX IF NOT EXISTS bro_entitet_bevis_idx  ON bro.entitet (bevis);
