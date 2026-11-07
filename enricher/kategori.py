#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Kategoriseringen — den der giver hver konklusion en kategori og et emne.

    konklusion i grafen
          ↓  ordene afgør sagen (ingen model — den er deterministisk)
    kategori (et af Domena: Grafen / Samtalen / Noterne (Ops) / Projekterne / Maskinen)
          ↓
    emne (det ord der bærer teksten)
          ↓
    hængt op:  MOC → Domene → Emne → Konklusion

Intet flyder løst. Alt har en kategori og et emne. Kan køre igen — det den
allerede har afgjort, springes over (konklusionen har så 'kategori').

Brug (inde i containeren):

    /opt/hjerne/hcvenv/bin/python /opt/hjerne/enricher/kategori.py --engangs --vis
    /opt/hjerne/hcvenv/bin/python /opt/hjerne/enricher/kategori.py          # loekke

Den skriver KUN i grafen. Aldrig i hc-skemaet.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time

try:
    import psycopg
except ImportError:  # pragma: no cover
    psycopg = None

GRAF = os.environ.get("GRAF", "hjerne")

# --- kategorierne: DNA's fem domaener, med de ord der hoerer til --------------
KATEGORIER = {
    "Maskinen": [
        "gpu", "vram", "kort", "cpu", "ram", "disk", "container", "docker",
        "ollama", "model", "modellen", "port", "server", "wsl", "windows",
        "linux", "maskine", "tokens", "hastighed", "ydelse", "temperatur",
        "nvidia", "cuda", "lager", "klyngen", "postgres", "database",
    ],
    "Grafen": [
        "graf", "grafen", "knude", "knuder", "kant", "kanter", "cypher", "age",
        "moc", "indeks", "vektor", "vektorer", "embedding", "entitet", "entiteter",
        "register", "lag", "struktur", "konklusion", "konklusioner", "tabel",
        "skema", "domaene", "domæne", "relation", "relationer", "node", "noder",
    ],
    "Noterne (Ops)": [
        "obsidian", "note", "noter", "ops", "markdown", "vault", "mappe",
        "mapper", "fil", "filer", "dokument", "dokumenter", "skriver", "skrevet",
        "notat", "noteret",
    ],
    "Projekterne": [
        "projekt", "projekter", "sag", "sager", "boernesag", "børnesag",
        "sagsbehandling", "myndighed", "ankestyrelsen", "kommune", "retten",
        "advokat", "klage", "afgoerelse", "afgørelse", "cvr", "virksomhed",
        "efterforskning", "flowsint", "opgave", "opgaver", "plan", "bygger",
        "byggede", "loesning", "løsning", "system", "kode", "program",
    ],
    "Samtalen": [
        "siger", "sagde", "mener", "mente", "spoerger", "spørger", "svarer",
        "svarede", "samtale", "samtalen", "tale", "taler", "lytter", "lyttede",
        "stemme", "ord", "besked", "beskeder", "snakker", "snakkede", "fortalte",
        "forklarede", "lytte", "hoere", "høre", "hoert", "hørt",
    ],
}

# ord der ikke baerer et emne
STOPORD = {
    "dette", "disse", "deres", "vaere", "være", "bliver", "blev", "havde",
    "skal", "ville", "kunne", "meget", "noget", "nogle", "andre", "anden",
    "andet", "efter", "fordi", "altsaa", "altså", "gerne", "maaske", "måske",
    "derfor", "igen", "ogsaa", "også", "heller", "sammen", "mellem", "gennem",
    "hele", "flere", "mange", "lidt", "nemlig", "faktisk", "siger", "mener",
    "vaeret", "været", "kommer", "gaar", "går", "sker", "laver", "lave",
    "tage", "tager", "give", "giver", "sidde", "sidder", "ligger",
}


def esc(s) -> str:
    """Tekst der kan staa i en Cypher-literal."""
    return str(s).replace("\\", "\\\\").replace("'", "\\'")


def cypher(cur, saetning: str, kolonner: str = "(v agtype)"):
    cur.execute(f"SELECT * FROM cypher('{GRAF}', $cy$ {saetning} $cy$) AS t{kolonner}")
    return cur.fetchall()


def ord_i(tekst: str) -> list[str]:
    return re.findall(r"[a-zA-ZæøåÆØÅ][a-zA-ZæøåÆØÅ\-]{2,}", tekst.lower())


def vaelg_kategori(tekst: str) -> tuple[str, int]:
    """Naelste kategori efter hvor mange af dens ord der staar i teksten."""
    ordene = set(ord_i(tekst))
    bedst, bedste_tal = "Samtalen", 0
    for navn, noegleord in KATEGORIER.items():
        tal = sum(1 for o in noegleord if o in ordene)
        if tal > bedste_tal:
            bedst, bedste_tal = navn, tal
    return bedst, bedste_tal


def vaelg_emne(tekst: str, kategori: str) -> str:
    """Emnet: det baerende ord — helst et af kategoriens egne, ellers det laengste."""
    ordene = ord_i(tekst)
    if not ordene:
        return "ukendt"
    for o in KATEGORIER.get(kategori, []):
        if o in ordene:
            return o
    kandidater = [o for o in ordene if o not in STOPORD and len(o) >= 4]
    if not kandidater:
        return "ukendt"
    return max(kandidater, key=len)


def sikr_emne(cur, kategori: str, emne: str, vis: bool) -> None:
    """Emne-knuden: oprettes hvis den ikke findes, og haenges under sin kategori.

    Kanten 'Domene -INDHOLDER-> Emne' tjekkes ogsaa: to konklusioner i samme
    emne gav foer to ens kanter (maalt 2026-10-14: elleve ens 'Grafen -> graf')."""
    findes = cypher(cur, f"MATCH (e:Emne {{navn:'{esc(emne)}'}}) RETURN e.navn")
    if not findes:
        cypher(cur, f"CREATE (e:Emne {{navn:'{esc(emne)}', kategori:'{esc(kategori)}'}}) RETURN e.navn")
        if vis:
            print(f"    nyt emne: {emne}  ({kategori})")
    haengt = cypher(
        cur,
        f"MATCH (d:Domene {{navn:'{esc(kategori)}'}})-[r:INDHOLDER]->"
        f"(e:Emne {{navn:'{esc(emne)}'}}) RETURN r LIMIT 1",
    )
    if haengt:
        return
    cypher(
        cur,
        f"MATCH (d:Domene {{navn:'{esc(kategori)}'}}), (e:Emne {{navn:'{esc(emne)}'}}) "
        f"CREATE (d)-[:INDHOLDER {{indholder: true}}]->(e) RETURN 1",
    )


def sikr_kant(cur, kategori: str, emne: str, konklusion: str) -> None:
    """Findes kanten, bruges den. Ellers laves den.

    Uden tjekket blev 'Domene -INDHOLDER-> Emne' skrevet igen for hver
    konklusion der landede i samme emne (maalt 2026-10-14: elleve ens kanter
    'Grafen -> graf'). Kategoriseringen skal kunne koere igen uden at grafen
    gror."""
    findes = cypher(
        cur,
        f"MATCH (e:Emne {{navn:'{esc(emne)}'}})-[r:INDHOLDER]->"
        f"(k:Konklusion {{navn:'{esc(konklusion)}'}}) RETURN r LIMIT 1",
    )
    if findes:
        return
    cypher(
        cur,
        f"MATCH (e:Emne {{navn:'{esc(emne)}'}}), (k:Konklusion {{navn:'{esc(konklusion)}'}}) "
        f"CREATE (e)-[:INDHOLDER {{indholder: true}}]->(k) RETURN 1",
    )


def hent_ukategoriserede(cur, graense: int) -> list[tuple]:
    return cypher(
        cur,
        f"MATCH (k:Konklusion) WHERE k.kategori IS NULL "
        f"RETURN k.navn, k.tekst LIMIT {int(graense)}",
        "(navn agtype, tekst agtype)",
    )


def koer_igennem(forbindelse, graense: int, vis: bool) -> dict:
    tal = {"set": 0, "Maskinen": 0, "Grafen": 0, "Noterne (Ops)": 0,
           "Projekterne": 0, "Samtalen": 0}
    while True:
        with forbindelse.cursor() as cur:
            cur.execute("LOAD 'age'")
            cur.execute("SET search_path = ag_catalog, \"$user\", public")
            raekker = hent_ukategoriserede(cur, graense)
        if not raekker:
            break
        for navn, tekst in raekker:
            navn = str(navn).strip('"')
            tekst = str(tekst).strip('"') if tekst else ""
            if not tekst:
                tekst = navn
            kategori, _ = vaelg_kategori(tekst)
            emne = vaelg_emne(tekst, kategori)
            with forbindelse.cursor() as cur:
                cur.execute("LOAD 'age'")
                cur.execute("SET search_path = ag_catalog, \"$user\", public")
                cypher(cur, (
                    f"MATCH (k:Konklusion {{navn:'{esc(navn)}'}}) "
                    f"SET k.kategori = '{esc(kategori)}', k.emne = '{esc(emne)}' RETURN 1"
                ))
                sikr_emne(cur, kategori, emne, vis)
                sikr_kant(cur, kategori, emne, navn)
            forbindelse.commit()
            tal["set"] += 1
            tal[kategori] += 1
            if vis:
                print(f"  [{kategori:<15}] emne: {emne:<22} {tekst[:52]!r}")
        if vis:
            print(f"  ... {tal['set']} kategoriseret")
    return tal


def main() -> int:
    ap = argparse.ArgumentParser(description="Kategoriseringen — konklusion → kategori → emne")
    ap.add_argument("--engangs", action="store_true", help="koer én gang og stop")
    ap.add_argument("--vis", action="store_true", help="skriv hvad der sker")
    ap.add_argument("--parti", type=int, default=200, help="hvor mange ad gangen")
    ap.add_argument("--soevn", type=int, default=60, help="sekunder mellem runder")
    a = ap.parse_args()

    if psycopg is None:
        print("psycopg mangler i dette miljoe", file=sys.stderr)
        return 2

    dsn = (f"host=127.0.0.1 port=5432 dbname={os.environ.get('POSTGRES_DB', 'hjerne')} "
           f"user={os.environ.get('POSTGRES_USER', 'hjerne')} "
           f"password={os.environ.get('POSTGRES_PASSWORD', '')}")

    print(f"[kategori] grafen '{GRAF}' — kategorier: " + ", ".join(KATEGORIER))
    while True:
        try:
            with psycopg.connect(dsn) as fb:
                tal = koer_igennem(fb, a.parti, a.vis)
        except Exception as fejl:
            print(f"[kategori] fejl: {type(fejl).__name__}: {fejl}", file=sys.stderr)
            if a.engangs:
                return 1
            time.sleep(max(a.soevn, 15))
            continue
        if a.engangs:
            print(f"[kategori] faerdig: {tal}")
            return 0
        if tal["set"] == 0:
            time.sleep(a.soevn)
        else:
            print(f"[kategori] runde: {tal}")


if __name__ == "__main__":
    raise SystemExit(main())
