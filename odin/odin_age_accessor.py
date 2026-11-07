#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Odin paa AGE — en accessor der lader Odins hentelag laese Apache AGE i Postgres.

Baggrund: Odin (odin-engine 0.3.0) kan kun ArangoDB ud af boksen, men dens
hentelag arbejder mod en lille kontrakt — GraphAccessor — med fire metoder:
iter_out, nodes, degree og community_seed_norm. Denne fil er en udgave af den
kontrakt der laeser AGE-grafen i stedet.

KUN LAESNING. Der skrives intet til databasen, og intet i containeren aendres.
Grafen indlaeses én gang i hukommelsen (vores grafer er smaa: 404 knuder / 456
kanter), saa iter_out bliver et opslag og ikke et databasekald pr. skridt.

Brug (inde i containeren, med dens eget venv):

    /opt/hjerne/venv/bin/python odin_age_accessor.py \
        --db helix_graph --graf juridiske_sager --fra "Hanne Simonsen"

Forbindelsen bygges af POSTGRES_USER / POSTGRES_PASSWORD / POSTGRES_DB fra
miljoeet — der staar ingen adgangskode i denne fil.
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict
from typing import Dict, Iterable, List, Optional, Tuple

try:
    import psycopg
except ImportError:  # pragma: no cover
    psycopg = None


# ---------------------------------------------------------------- agtype-hjaelp
def ag2py(v):
    """AGE svarer i agtype (en tekst-form). Oversaet det vi skal bruge."""
    if v is None:
        return None
    if not isinstance(v, str):
        return v
    s = v.strip()
    if s.startswith('"') and s.endswith('"'):
        return s[1:-1]
    if s in ("true", "false"):
        return s == "true"
    if s in ("null",):
        return None
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        return s


class AgeGraf:
    """Laeser hele grafen ind i hukommelsen én gang. Intet skrives tilbage."""

    def __init__(self, dsn: str, graf: str, skema: str = "public"):
        if psycopg is None:
            raise RuntimeError("psycopg mangler i dette miljoe")
        self.graf = graf
        self.skema = skema
        self.ud: Dict[str, List[Tuple[str, str, float]]] = defaultdict(list)
        self.ind: Dict[str, List[Tuple[str, str, float]]] = defaultdict(list)
        self.navn: Dict[str, str] = {}
        self.etiketter: Dict[str, List[str]] = {}
        self.kanter = 0

        with psycopg.connect(dsn) as forbindelse:
            with forbindelse.cursor() as cur:
                cur.execute("SET search_path=ag_catalog,public")
                cur.execute("LOAD 'age'")
                # Grafen skal vaere en REGISTRERET graf — ellers stopper vi her.
                cur.execute("SELECT name FROM ag_catalog.ag_graph WHERE name=%s", (graf,))
                if not cur.fetchone():
                    raise RuntimeError(f"grafen '{graf}' findes ikke i denne base")
                self._laes_kanter(cur)
                self._laes_knuder(cur)

    def _cypher(self, cur, forespoergsel: str) -> List[tuple]:
        cur.execute(
            f"SELECT * FROM cypher('{self.graf}', $cy$ {forespoergsel} $cy$) AS t(v agtype)"
        )
        return cur.fetchall()

    def _laes_kanter(self, cur) -> None:
        cur.execute(
            f"SELECT * FROM cypher('{self.graf}', $cy$ "
            "MATCH (a)-[r]->(b) "
            "RETURN id(a), type(r), id(b), a.name, b.name "
            "$cy$) AS t(ida agtype, rel agtype, idb agtype, na agtype, nb agtype)"
        )
        for ida, rel, idb, na, nb in cur.fetchall():
            a, b = str(ag2py(ida)), str(ag2py(idb))
            r = ag2py(rel) or "relateret_til"
            self.ud[a].append((b, r, 1.0))
            self.ind[b].append((a, r, 1.0))
            self.kanter += 1
            if ag2py(na):
                self.navn.setdefault(a, str(ag2py(na)))
            if ag2py(nb):
                self.navn.setdefault(b, str(ag2py(nb)))

    def _laes_knuder(self, cur) -> None:
        cur.execute(
            f"SELECT * FROM cypher('{self.graf}', $cy$ "
            "MATCH (n) RETURN id(n), labels(n), n.name $cy$) "
            "AS t(idn agtype, lab agtype, navn agtype)"
        )
        for idn, lab, navn in cur.fetchall():
            i = str(ag2py(idn))
            self.etiketter[i] = []
            if ag2py(navn):
                self.navn.setdefault(i, str(ag2py(navn)))

    # --------------------------------------------------------- GraphAccessor
    def iter_out(self, node: str) -> Iterable[Tuple[str, str, float]]:
        yield from self.ud.get(str(node), [])

    def iter_in(self, node: str) -> Iterable[Tuple[str, str, float]]:
        yield from self.ind.get(str(node), [])

    def nodes(self, community_id: str = "global") -> Iterable[str]:
        alle = set(self.ud) | set(self.ind) | set(self.etiketter)
        return sorted(alle)

    def degree(self, node: str) -> int:
        return len(self.ud.get(str(node), []))

    def community_seed_norm(self, community_id: str, seeds: List[str]) -> List[str]:
        return seeds

    def find_ved_navn(self, navn: str, antal: int = 5) -> List[Tuple[str, str]]:
        navn_l = navn.strip().lower()
        fundet = [(i, n) for i, n in self.navn.items() if n.lower() == navn_l]
        if not fundet:
            fundet = [(i, n) for i, n in self.navn.items() if navn_l in n.lower()]
        return fundet[:antal]

    def rapport(self) -> str:
        knuder = len(self.nodes("global"))
        return (
            f"grafen '{self.graf}': {knuder} knuder, {self.kanter} kanter, "
            f"{len(self.navn)} med navn"
        )


def main() -> int:
    p = argparse.ArgumentParser(description="Odin paa AGE — laesekun adgang")
    p.add_argument("--db", default=os.environ.get("POSTGRES_DB", "hjerne"))
    p.add_argument("--graf", default="hjerne")
    p.add_argument("--vaert", default="127.0.0.1")
    p.add_argument("--port", default="5432")
    p.add_argument("--fra", default="", help="start-knude: navn eller id")
    p.add_argument("--max-stier", type=int, default=20)
    p.add_argument("--hop", type=int, default=3)
    p.add_argument("--beam", type=int, default=64)
    p.add_argument("--vis", type=int, default=5)
    a = p.parse_args()

    dsn = (
        f"host={a.vaert} port={a.port} dbname={a.db} "
        f"user={os.environ.get('POSTGRES_USER','hjerne')} "
        f"password={os.environ.get('POSTGRES_PASSWORD','')}"
    )

    print("== 1. laeser grafen (kun laesning) ==")
    g = AgeGraf(dsn, a.graf)
    print("   " + g.rapport())

    if not a.fra:
        print("\nIngen start-knude givet (--fra). Eksempler fra grafen:")
        for i, n in list(g.navn.items())[:10]:
            print(f"   {i}  {n}")
        return 0

    seeds = [a.fra] if a.fra.isdigit() else []
    if not seeds:
        fundet = g.find_ved_navn(a.fra)
        if not fundet:
            print(f"   ingen knude fundet paa '{a.fra}'")
            return 1
        seeds = [i for i, _ in fundet[:1]]
        print(f"   start-knude: {fundet[0][1]} (id {seeds[0]})")
    print(f"   ud-gaaende kanter fra start: {g.degree(seeds[0])}")

    print("\n== 2. rejser Odins hentelag paa grafen ==")
    from retrieval.orchestrator import OrchestratorParams, RetrievalOrchestrator
    from retrieval.confidence import ConstantConfidence

    orch = RetrievalOrchestrator(
        accessor=g,
        edge_confidence=ConstantConfidence(0.8),  # NPLL er Arango-specifik; se planen
    )
    params = OrchestratorParams(
        community_id="global",
        max_paths=a.max_stier,
        hop_limit=a.hop,
        beam_width=a.beam,
    )
    res = orch.retrieve(seeds=seeds, params=params)

    print("\n== 3. hvad kom der ud ==")
    stier = res.get("paths") or []
    print(f"   stier ud: {len(stier)}")
    tri = res.get("triage") or {}
    print(f"   triage: {tri.get('score')}")
    print(f"   insight_score: {res.get('insight_score')}")
    agg = res.get("aggregates") or {}
    moenstre = agg.get("motifs") or []
    print(f"   moenstre: {len(moenstre)}")
    for m in moenstre[:3]:
        print(f"     {m.get('pattern')}  kanter={m.get('edge_count')}  stier={m.get('path_count')}")

    print(f"\n   de {a.vis} bedste stier:")
    for s in stier[: a.vis]:
        kanter = s.get("edges") or []
        if not kanter:
            continue
        knuder = [kanter[0].get("u"), *(k.get("v") for k in kanter)]
        navne = [g.navn.get(str(k), str(k)) for k in knuder]
        print(f"     [{float(s.get('score', 0)):.2f}] " + " -> ".join(navne))
    return 0


if __name__ == "__main__":
    sys.exit(main())
