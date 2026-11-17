#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Semantisk søgning i konklusionerne.

DNA 3. nov 2026: uden dette fik jeg de otte NYESTE konklusioner, uanset hvad
vi talte om. Nu finder vi de otte der LIGNER det der bliver spurgt om.

Sådan virker det:
  1. bge-m3 oversætter hver konklusion til 1024 tal (én gang, når den er ny)
  2. et spørgsmål oversættes til 1024 tal på samme måde
  3. de konklusioner hvis tal ligger nærmest, er de mest relevante

Skriver intet andet end vektoren på konklusionen.
"""
from __future__ import annotations

import json
import os
import urllib.request

DSN = os.environ.get(
    "KONKLUSION_DSN",
    "host=127.0.0.1 port=5432 dbname=hjerne user=hjerne password=skift-mig",
)
OLLAMA = os.environ.get("EMBEDDING_BASE_URL", "http://127.0.0.1:11434")
MODEL = os.environ.get("EMBEDDING_MODEL", "bge-m3")
DIM = 1024


def vektor(tekst: str, timeout: int = 20) -> list[float] | None:
    """Oversæt tekst til 1024 tal med bge-m3. None hvis den ikke svarer."""
    if not tekst or not tekst.strip():
        return None
    try:
        krop = json.dumps({"model": MODEL, "prompt": tekst[:2000]}).encode()
        req = urllib.request.Request(
            OLLAMA + "/api/embeddings", data=krop,
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read())
        v = d.get("embedding") or []
        return v if len(v) == DIM else None
    except Exception as e:  # noqa: BLE001
        print(f"[soeg] bge-m3 svarede ikke: {e}", flush=True)
        return None


def sikr_skema(con):
    """Kolonnen og indekset. Kører hver gang — billigt."""
    with con.cursor() as cur:
        cur.execute(f"ALTER TABLE konklusion ADD COLUMN IF NOT EXISTS vektor vector({DIM})")
        cur.execute("""
            CREATE INDEX IF NOT EXISTS konklusion_vektor_idx
            ON konklusion USING hnsw (vektor vector_cosine_ops)
        """)
        con.commit()


def indekser(con, graense: int = 500, parti: int = 25) -> int:
    """Giv vektorer til konklusioner der mangler. Returnerer antallet.

    Ét kald pr. konklusion tog over et minut i alt fordi Ollama skal svare
    hver gang. Her sendes de i portioner, og der skrives efter hver portion,
    så et afbrudt gennemløb ikke starter forfra (DNA 3. nov 2026).
    """
    with con.cursor() as cur:
        cur.execute("""
            SELECT id, emne || ' ' || egenskab || ' ' || coalesce(vaerdi, '')
            FROM konklusion
            WHERE vektor IS NULL
            ORDER BY oprettet DESC
            LIMIT %s
        """, (graense,))
        raekker = cur.fetchall()

    n = 0
    for i in range(0, len(raekker), parti):
        portion = raekker[i:i + parti]
        opdateringer = []
        for kid, tekst in portion:
            v = vektor(tekst)
            if v:
                opdateringer.append(
                    ("[" + ",".join(f"{x:.6f}" for x in v) + "]", kid))
        if not opdateringer:
            continue
        with con.cursor() as cur:
            for vlit, kid in opdateringer:
                cur.execute("UPDATE konklusion SET vektor = %s::vector WHERE id = %s",
                            (vlit, kid))
        con.commit()
        n += len(opdateringer)
        print(f"[soeg] {n}/{len(raekker)} indekseret", flush=True)
    return n


def soeg(con, spoergsmaal: str, antal: int = 8, ejer: str | None = None) -> list[dict]:
    """Find de konklusioner der ligner spørgsmålet mest.

    ejer: filtrér på hvem der ejer dem (en gæst må ikke se DNA's sager).
    """
    v = vektor(spoergsmaal)
    if not v:
        return []
    vlit = "[" + ",".join(f"{x:.6f}" for x in v) + "]"
    sql = """
        SELECT emne, egenskab, coalesce(vaerdi, ''), bevis,
               1 - (vektor <=> %s::vector) AS lighed
        FROM konklusion
        WHERE vektor IS NOT NULL
          AND ugyldig = false
    """
    par = [vlit]
    if ejer:
        sql += " AND (ejer = %s OR ejer IS NULL)"
        par.append(ejer)
    sql += " ORDER BY vektor <=> %s::vector LIMIT %s"
    par += [vlit, antal]

    with con.cursor() as cur:
        cur.execute(sql, par)
        return [{"emne": r[0], "egenskab": r[1], "vaerdi": r[2],
                 "bevis": r[3], "lighed": round(float(r[4]), 3)}
                for r in cur.fetchall()]


# ---------------------------------------------------------------- selvtest
def _selvtest():
    import psycopg
    con = psycopg.connect(DSN, autocommit=True)
    sikr_skema(con)
    nye = indekser(con, 50)
    print(f"indekseret: {nye}")

    for spoergsmaal in ("børnesagen om Dio", "hvilken bil kører Danny", "hvilken port"):
        print(f"\nSPØRGSMÅL: {spoergsmaal}")
        for t in soeg(con, spoergsmaal, 3):
            print(f"  [{t['lighed']}] {t['emne']} · {t['egenskab']} = {t['vaerdi'][:40]}")
    con.close()


if __name__ == "__main__":
    _selvtest()
