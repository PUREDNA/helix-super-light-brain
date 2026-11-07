#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""NPLL paa AGE — Odins indlaerte doemmekraft, traenet paa vores egen graf.

Hvad Odins egen vej goer: den henter tripler fra ArangoDB, bygger en
vidensgraf, finder regler, traener NPLL-modellen og gemmer KUN regel-vaegtene
(~1 KB) i Arango-kollektionen OdinModels.

Hvad denne fil goer i stedet:
  1. henter tripler fra AGE-grafen gennem vores egen accessor (kun laesning)
  2. finder regler i DATAENE selv — Odins egen regelgenerator kender kun
     engelske sundheds-relationer (has_claim, works_at ...) og ville falde
     tilbage til én tom regel paa vores danske grafer
  3. traener samme NPLL-model (torch, CPU)
  4. gemmer vaegtene i Postgres (public.odin_model) og hver kants score i
     public.kant_score — altsaa i selve databasen, ikke i en anden motor

KUN laesning af grafen. Der skrives udelukkende i tabellerne odin_model og
kant_score, og kun naar --skriv er sat.

Brug:
    /opt/hjerne/venv/bin/python npll_paa_age.py --db helix_graph \
        --graf juridiske_sager --skriv
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from collections import Counter, defaultdict
from typing import Dict, List, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from odin_age_accessor import AgeGraf  # noqa: E402


# ------------------------------------------------------------------ 1. tripler
def tripler_fra_graf(g: AgeGraf) -> List[Tuple[str, str, str]]:
    def navn(i: str) -> str:
        return g.navn.get(str(i)) or f"knude:{i}"

    t = []
    for a, kanter in g.ud.items():
        for b, rel, _ in kanter:
            t.append((navn(a), rel, navn(b)))
    return t


# ------------------------------------------------------------- 2. regel-minedrift
def find_regler(tripler: List[Tuple[str, str, str]], min_stotte: int = 2,
                loft: int = 40) -> List[dict]:
    """Laerer regler af grafens egne vaner.

    To slags, begge lukkede (kroppen kan efterproeves i grafen):
      parallel:  (x,r1,y)                => (x,r2,y)
      kaede:     (x,r1,y) og (y,r2,z)    => (x,r3,z)
    Konfidens = hvor ofte konklusionen ogsaa findes / hvor ofte kroppen findes.
    """
    kanter = set((h, r, t) for h, r, t in tripler)
    ud = defaultdict(list)
    ind = defaultdict(list)
    for h, r, t in kanter:
        ud[h].append((r, t))
        ind[t].append((r, h))

    parallel_koerper: Counter = Counter()
    kaede_koerper: Counter = Counter()
    parallel_konkl: Counter = Counter()
    kaede_konkl: Counter = Counter()

    # parallel: samme hoved og hale med to relationer
    for h, t in {(h, t) for h, _, t in kanter}:
        rels = [r for (r, tt) in ud[h] if tt == t]
        for r1 in rels:
            for r2 in rels:
                if r1 == r2:
                    continue
                parallel_koerper[(r1, r2)] += 1
                if (h, r2, t) in kanter:
                    parallel_konkl[(r1, r2)] += 1

    # kaede: (x,r1,y),(y,r2,z) og se om (x,r3,z) findes
    for y, ind_kanter in ind.items():
        for r1, x in ind_kanter:
            for r2, z in ud.get(y, []):
                if x == z:
                    continue
                kaede_koerper[(r1, r2)] += 1
                for r3, z2 in ud.get(x, []):
                    if z2 == z:
                        kaede_konkl[(r1, r2, r3)] += 1

    regler = []
    for (r1, r2), stotte in parallel_koerper.items():
        if stotte >= min_stotte:
            konf = parallel_konkl[(r1, r2)] / stotte
            if konf > 0:
                regler.append({
                    "id": f"par:{r1}->{r2}",
                    "krop": [(r1, "?x", "?y")],
                    "hoved": (r2, "?x", "?y"),
                    "stotte": stotte,
                    "konfidens": round(konf, 3),
                })

    # kaede-regler: for hvert (r1,r2)-par find de r3 der oftest foelger med
    bedste: Dict[Tuple[str, str], Tuple[int, str]] = {}
    for (r1, r2, r3), antal in kaede_konkl.items():
        if kaede_koerper[(r1, r2)] < min_stotte:
            continue
        noegle = (r1, r2)
        if noegle not in bedste or antal > bedste[noegle][0]:
            bedste[noegle] = (antal, r3)

    for (r1, r2), (antal, r3) in bedste.items():
        stotte = kaede_koerper[(r1, r2)]
        konf = antal / stotte
        if konf > 0:
            regler.append({
                "id": f"kaede:{r1}+{r2}->{r3}",
                "krop": [(r1, "?x", "?y"), (r2, "?y", "?z")],
                "hoved": (r3, "?x", "?z"),
                "stotte": stotte,
                "konfidens": round(konf, 3),
            })

    regler.sort(key=lambda r: (-r["stotte"], -r["konfidens"]))
    return regler[:loft]


def til_logiske_regler(regler: List[dict], kg):
    from npll.core.logical_rules import Atom, LogicalRule, RuleType, Variable

    x, y, z = Variable("?x"), Variable("?y"), Variable("?z")
    navne = {r.name: r for r in kg.relations}
    ud = []
    for r in regler:
        try:
            krop = []
            for (rel, a1, a2) in r["krop"]:
                if rel not in navne:
                    break
                krop.append(Atom(navne[rel], (x if a1 == "?x" else y,
                                              y if a2 == "?y" else z)))
            hoved_rel = r["hoved"][0]
            if hoved_rel not in navne or len(krop) != len(r["krop"]):
                continue
            hoved = Atom(navne[hoved_rel], (x if r["hoved"][1] == "?x" else y,
                                            z if r["hoved"][2] == "?z" else y))
            ud.append(LogicalRule(
                rule_id=r["id"], body=krop, head=hoved,
                rule_type=RuleType.GENERAL, confidence=float(r["konfidens"]),
                support=int(r["stotte"]),
            ))
        except Exception as e:  # en enkelt daarlig regel maa ikke vaelte det hele
            print(f"   sprang regel over ({r['id']}): {e}")
    return ud


# --------------------------------------------------------------- 3. database
def gem_i_db(dsn: str, navn: str, data_hash: str, model, regler: List[dict],
             skema: dict, traening: dict, kanter: List[Tuple[str, str, str, float]]) -> None:
    import psycopg
    vaegte = model.mln.rule_weights.detach().cpu().tolist()
    with psycopg.connect(dsn) as f:
        with f.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS public.odin_model (
                    id         bigserial PRIMARY KEY,
                    navn       text UNIQUE NOT NULL,
                    data_hash  text,
                    vaegte     jsonb,
                    regler     jsonb,
                    skema      jsonb,
                    traening   jsonb,
                    oprettet   timestamptz DEFAULT now()
                )""")
            cur.execute("""
                INSERT INTO public.odin_model (navn, data_hash, vaegte, regler, skema, traening)
                VALUES (%s,%s,%s,%s,%s,%s)
                ON CONFLICT (navn) DO UPDATE SET
                    data_hash=EXCLUDED.data_hash, vaegte=EXCLUDED.vaegte,
                    regler=EXCLUDED.regler, skema=EXCLUDED.skema,
                    traening=EXCLUDED.traening, oprettet=now()""",
                (navn, data_hash, json.dumps(vaegte), json.dumps(regler),
                 json.dumps(skema), json.dumps(traening)))
            # kant-scores: samme tabel som doemmekraften bruger
            for h, r, t, s in kanter:
                cur.execute("""
                    INSERT INTO public.kant_score (kant_id, score, begrundelse)
                    VALUES (%s,%s,%s)""",
                    (f"{h}|{r}|{t}", float(s), "NPLL (Odin, laert paa AGE-grafen)"))
        f.commit()


def main() -> int:
    p = argparse.ArgumentParser(description="NPLL paa AGE — traen Odins doemmekraft paa vores graf")
    p.add_argument("--db", default="helix_graph")
    p.add_argument("--graf", default="juridiske_sager")
    p.add_argument("--db-skriv", default=os.environ.get("POSTGRES_DB", "hjerne"),
                   help="base hvor odin_model og kant_score ligger")
    p.add_argument("--epoker", type=int, default=10)
    p.add_argument("--em", type=int, default=5)
    p.add_argument("--min-stotte", type=int, default=2)
    p.add_argument("--loft", type=int, default=40)
    p.add_argument("--skriv", action="store_true", help="skriv vaegte og scores til basen")
    a = p.parse_args()

    def dsn(db):
        return (f"host=127.0.0.1 port=5432 dbname={db} "
                f"user={os.environ.get('POSTGRES_USER','hjerne')} "
                f"password={os.environ.get('POSTGRES_PASSWORD','')}")

    t0 = time.time()
    print("== 1. laeser grafen (kun laesning) ==")
    g = AgeGraf(dsn(a.db), a.graf)
    print("   " + g.rapport())
    tripler = tripler_fra_graf(g)
    print(f"   {len(tripler)} tripler hentet")
    if len(tripler) < 10:
        print("   for faa tripler til at traene")
        return 1

    print("\n== 2. finder regler i dataene ==")
    regler = find_regler(tripler, a.min_stotte, a.loft)
    for r in regler[:8]:
        krop = " og ".join(f"{rel}({a1},{a2})" for rel, a1, a2 in r["krop"])
        print(f"   {krop}  =>  {r['hoved'][0]}({r['hoved'][1]},{r['hoved'][2]})"
              f"   stotte={r['stotte']} konfidens={r['konfidens']}")
    print(f"   {len(regler)} regler i alt")
    if not regler:
        print("   ingen regler fundet — grafen har for faa gentagelser")
        return 1

    print("\n== 3. bygger vidensgraf og traener NPLL ==")
    from npll.core.knowledge_graph import load_knowledge_graph_from_triples
    from npll.npll_model import create_initialized_npll_model
    from npll.training.npll_trainer import TrainingConfig, create_trainer
    from npll.utils.config import NPLLConfig

    kg = load_knowledge_graph_from_triples(tripler, "AGE_KG")
    print(f"   {len(kg.entities)} entiteter, {len(kg.relations)} relationer, "
          f"{len(kg.known_facts)} kendte fakta")

    kendte = list(kg.known_facts)
    random.seed(42)
    antal_ukendt = max(1, len(kendte) // 10)
    for f in random.sample(kendte, antal_ukendt):
        kg.known_facts.discard(f)
        kg.add_unknown_fact(f.head.name, f.relation.name, f.tail.name)
    print(f"   {antal_ukendt} fakta holdt udenfor som ukendte (til at maale paa)")

    logiske = til_logiske_regler(regler, kg)
    print(f"   {len(logiske)} regler givet videre til modellen")

    cfg = NPLLConfig(device="cpu")  # vi lader grafikkortet vaere i fred for HC
    model = create_initialized_npll_model(kg, logiske, cfg)
    tr_cfg = TrainingConfig(num_epochs=a.epoker, max_em_iterations_per_epoch=a.em,
                            early_stopping_patience=3, save_checkpoints=False)
    trainer = create_trainer(model, tr_cfg)
    resultat = trainer.train()
    print(f"   traening faerdig: ELBO={resultat.final_elbo:.4f} "
          f"bedste={resultat.best_elbo:.4f} konvergeret={resultat.converged} "
          f"tid={resultat.total_training_time:.1f}s")

    print("\n== 4. scorer grafens kanter med den traenede model ==")
    from retrieval.confidence import NPLLConfidence
    conf = NPLLConfidence(model)
    kanter = [(h, r, t) for h, r, t in tripler]
    scores = conf.confidence_batch(kanter)
    fordeling = Counter(round(s, 1) for s in scores)
    print("   score-fordeling (0,1-trin): " +
          ", ".join(f"{k}: {v}" for k, v in sorted(fordeling.items())))
    print(f"   gennemsnit {sum(scores)/len(scores):.3f}, "
          f"mindste {min(scores):.3f}, stoerste {max(scores):.3f}")

    if a.skriv:
        print("\n== 5. gemmer i selve databasen ==")
        skema = {
            "graf": a.graf, "base": a.db,
            "knuder": len(list(g.nodes("global"))), "kanter": g.kanter,
            "entiteter": len(kg.entities), "relationer": len(kg.relations),
        }
        traening = {
            "elbo": float(resultat.final_elbo), "bedste_elbo": float(resultat.best_elbo),
            "konvergeret": bool(resultat.converged),
            "sekunder": float(resultat.total_training_time),
            "epoker": a.epoker, "fakta": len(tripler),
            "regler": len(logiske), "sekunder_ialt": round(time.time() - t0, 1),
        }
        import hashlib
        h = hashlib.sha256(json.dumps(sorted(tripler)).encode()).hexdigest()[:16]
        gem_i_db(dsn(a.db_skriv), f"AGE-{a.graf}", h,
                 model, regler, skema, traening,
                 list(zip([k[0] for k in kanter], [k[1] for k in kanter],
                          [k[2] for k in kanter], scores)))
        print(f"   odin_model og kant_score opdateret i basen '{a.db_skriv}'")
        print(f"   data-hash: {h}")
    else:
        print("\n(der blev IKKE skrevet til basen — koer igen med --skriv)")

    print(f"\nalt i alt {time.time()-t0:.1f} sekunder")
    return 0


if __name__ == "__main__":
    sys.exit(main())
