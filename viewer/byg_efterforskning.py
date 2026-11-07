#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Bygger viewerens EFTERFORSKNINGS-datasæt ud fra den gamle graf.

Vieweren er bygget til at se BEGGE graf-databaser:

    api/graph          — hjernens egen graf ('hjerne' i databasen hjerne)
    api/efterforskning — DEN GAMLE GRAF ('juridiske_sager' i gammel_graf)

Denne fil læser den gamle graf og skriver den som det datasæt, viewer'en
tegner. Kun læsning — den skriver intet i grafen.

Brug (inde i containeren):
    /opt/hjerne/venv/bin/python /opt/hjerne/viewer/byg_efterforskning.py
"""
from __future__ import annotations

import json
import os
import sys

try:
    import psycopg2
except ImportError:  # pragma: no cover
    psycopg2 = None

HER = os.path.dirname(os.path.abspath(__file__))
UD = os.environ.get("EFTER_JSON", os.path.join(HER, "data", "efterforskning.json"))
GRAF = os.environ.get("EFTER_GRAF", "juridiske_sager")


def forbind():
    return dict(
        host=os.environ.get("DB_HOST", "127.0.0.1"),
        port=int(os.environ.get("DB_PORT", "5432")),
        dbname=os.environ.get("EFTER_DB_NAME", "gammel_graf"),
        user=os.environ.get("DB_USER", "hjerne"),
        password=os.environ.get("DB_PASS", ""),
    )


def ren(x) -> str:
    """agtype-tekst -> almindelig tekst (fjern citationstegn omkring)."""
    s = str(x).strip()
    return s[1:-1] if len(s) > 1 and s[0] == '"' and s[-1] == '"' else s


def cypher(cur, saetning: str, antal: int):
    ali = ", ".join(f"c{i} agtype" for i in range(antal))
    cur.execute(f"SELECT * FROM cypher('{GRAF}', $cy$ {saetning} $cy$) AS t({ali})")
    return cur.fetchall()


def main() -> int:
    if psycopg2 is None:
        print("psycopg2 mangler i dette miljø", file=sys.stderr)
        return 2

    try:
        with psycopg2.connect(**forbind()) as fb:
            with fb.cursor() as cur:
                cur.execute("LOAD 'age'")
                cur.execute("SET search_path = ag_catalog, \"$user\", public")
                noder_raa = cypher(cur, "MATCH (n) RETURN label(n), id(n), properties(n)", 3)
                kanter_raa = cypher(cur, "MATCH (a)-[r]->(b) RETURN id(a), id(b), label(r)", 3)
    except Exception as fejl:
        print(f"[efterforskning] kunne ikke læse grafen: {type(fejl).__name__}: {fejl}",
              file=sys.stderr)
        return 1

    noder = []
    id_kort = {}
    for etiket, nid, props in noder_raa:
        etiket, nid = ren(etiket), ren(nid)
        try:
            pr = json.loads(ren(props))
        except Exception:
            pr = {}
        navn = (pr.get("navn") or pr.get("name") or pr.get("titel")
                or pr.get("label") or etiket)
        node = {"id": "e" + nid, "label": navn, "group": etiket,
                "type": etiket.lower()}
        # Nyttige felter med, hvis de findes (bevis, rolle, domæne)
        for nøgle in ("bevis", "rolle", "domene", "note"):
            if pr.get(nøgle):
                node[nøgle] = pr[nøgle]
        noder.append(node)
        id_kort[nid] = node["id"]

    kanter = []
    for a, b, etiket in kanter_raa:
        a, b, etiket = ren(a), ren(b), ren(etiket)
        if a in id_kort and b in id_kort:
            kanter.append({"from": id_kort[a], "to": id_kort[b], "label": etiket})

    os.makedirs(os.path.dirname(UD), exist_ok=True)
    with open(UD, "w", encoding="utf-8") as fh:
        json.dump({"nodes": noder, "edges": kanter}, fh, ensure_ascii=False)

    etiketter = {}
    for n in noder:
        etiketter[n["group"]] = etiketter.get(n["group"], 0) + 1
    print(f"[efterforskning] {len(noder)} noder, {len(kanter)} kanter "
          f"i {len(etiketter)} typer -> {UD}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
