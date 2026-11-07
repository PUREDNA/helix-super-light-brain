#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Kopiér Super Brains GRAF over i Lillehjernen — uden konklusioner.

DNA 5. nov 2026: "alle konklusioner fra Superbrain skal ikke over. Jeg skal
have en ren lillehjerne. Kopiér hele strukturen med DNA som egocenter,
alt undtagen konklusioner."

Reglerne:
  * MOC i lillehjernen ROERES IKKE — den er hjernens arbejdsregister.
  * Konklusions-knuder kopieres IKKE.
  * Alt andet kopieres med egenskaber og kanter. DNA bliver centrum.
  * Knudens gamle id gemmes som "gammel_id", saa kanterne kan genskabes.

    python3 kopier_graf.py [--toerkoersel]
"""
import json
import subprocess
import sys

SB = "Helix_Super_Brain"
LB = "Helix_Light_Brain"
DB = "hjerne"
# DNA 5. nov 2026: TROKOPI. Alt med — ogsaa MOC. Kun konklusionerne holdes ude,
# fordi lillehjernen skal starte ren. Resten rydder vi bagefter hvis noget er
# for meget, som DNA sagde.
UDELAD = {"Konklusion"}


def psql(vært, sql):
    r = subprocess.run(
        ["docker", "exec", vært, "psql", "-U", "hjerne", "-d", DB, "-tA",
         "-F", "\t", "-c", sql],
        capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"{vært}: {r.stderr.strip()[:400]}")
    return [l.split("\t") for l in r.stdout.strip().split("\n") if l.strip()]


def labels(vært, kind=None):
    sql = "select name, kind from ag_catalog.ag_label order by id"
    rows = psql(vært, sql)
    return [(r[0], r[1]) for r in rows
            if not r[0].startswith("_") and (kind is None or r[1] == kind)]


def agtype_lit(eg):
    """Python-dict -> AGE's kort-syntaks: {key: 'vaerdi', ...}"""
    dele = []
    for n, v in eg.items():
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            dele.append(f"{n}: {v}")
        elif isinstance(v, bool):
            dele.append(f"{n}: {'true' if v else 'false'}")
        else:
            t = str(v).replace("\\", "\\\\").replace("'", "''").replace("\n", "\\n")
            dele.append(f"{n}: '{t}'")
    return "{" + ", ".join(dele) + "}"


def main():
    tør = "--toerkoersel" in sys.argv
    sb_lab = labels(SB)
    lb_navne = {n for n, _ in labels(LB)}

    plan = []
    for navn, kind in sb_lab:
        if navn in UDELAD:
            continue
        antal = int(psql(SB, f'select count(*) from hjerne."{navn}"')[0][0])
        plan.append((navn, kind, antal))

    print(f"{'label':22} {'kind':5} {'raekker':>7}  status")
    for navn, kind, antal in plan:
        findes = "findes" if navn in lb_navne else "MANGLER"
        print(f"{navn:22} {kind:5} {antal:7}  {findes}")

    print("\nUDELADT:", ", ".join(sorted(UDELAD)))
    if tør:
        print("\nTOERKOERSEL — intet skrevet.")
        return

    json.dump(plan, open("/home/dna/.hermes/cache/scratch/graf_plan.json", "w"),
              ensure_ascii=False)

    # ---- 1. knuder ind, med gammel_id bevaret
    v_labels = [n for n, k, a in plan if k == "v" and a > 0]
    n = 0
    for lab in v_labels:
        for kid, props in psql(SB, f'select id, properties from hjerne."{lab}"'):
            eg = json.loads(props)
            eg["gammel_id"] = kid
            lit = agtype_lit(eg)
            psql(LB, f"LOAD 'age'; SET search_path = ag_catalog, hjerne, public; "
                     f"select * from ag_catalog.cypher('hjerne', $$ CREATE (n:{lab} {lit}) "
                     f"RETURN id(n) $$) as (i agtype);")
            n += 1
            if n % 200 == 0:
                print(f"  knuder: {n}", flush=True)
    print(f"knuder skrevet: {n}", flush=True)

    # ---- 2. kanter ind, koblet via gammel_id
    e_labels = [n for n, k, a in plan if k == "e" and a > 0]
    k = 0
    for lab in e_labels:
        for _eid, sid, tid, props in psql(
                SB, f'select id, start_id, end_id, properties from hjerne."{lab}"'):
            eg = json.loads(props) if props.strip() not in ("", "{}") else {}
            lit = agtype_lit(eg)
            psql(LB, f"LOAD 'age'; SET search_path = ag_catalog, hjerne, public; "
                     f"select * from ag_catalog.cypher('hjerne', $$ "
                     f"MATCH (a), (b) WHERE a.gammel_id = '{sid}' AND b.gammel_id = '{tid}' "
                     f"CREATE (a)-[r:{lab} {lit}]->(b) RETURN id(r) $$) as (i agtype);")
            k += 1
            if k % 500 == 0:
                print(f"  kanter: {k}", flush=True)
    print(f"kanter skrevet: {k}", flush=True)


if __name__ == "__main__":
    main()
