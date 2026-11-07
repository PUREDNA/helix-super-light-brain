#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Efterfylder de kanter der faldt ud, da containeren blev genstartet midt i
flytningen (8 af 456). Tæller kilde og mål op mod hinanden og kopierer KUN
forskellen — knuderne røres ikke (de er alle 404 over).

Trygt at køre flere gange: den kopierer kun det der mangler.
"""
import subprocess

MAAL_DB, MAAL_GRAF = "hjerne", "hjerne"
KILDE_DB, KILDE_GRAF = "gammel_graf", "juridiske_sager"


def psql(db, sql, timeout=300):
    r = subprocess.run(["docker", "exec", "Helix_Super_Brain", "psql", "-U", "hjerne",
                        "-h", "127.0.0.1", "-d", db, "-tAc", sql],
                       capture_output=True, text=True, timeout=timeout)
    return "\n".join(l for l in r.stdout.split("\n") if l.strip() and
                     l.strip() not in ("LOAD", "SET")), r.stderr


SIDSTE_FEJL = [""]      # så vi kan skelne "ingen rækker" fra "kaldet fejlede"


def age(db, graf, q, kolonner=("x",), timeout=300):
    ali = ", ".join(f"c{i} agtype" for i in range(len(kolonner)))
    ud, fejl = psql(db, "LOAD 'age'; SET search_path = ag_catalog, public; "
                        "SET client_min_messages=warning; "
                        f"SELECT * FROM cypher('{graf}', $cy$ {q} $cy$) as ({ali});", timeout)
    SIDSTE_FEJL[0] = (fejl or "").strip()
    return ud, fejl


def antal(ud):
    for l in reversed(ud.strip().split("\n")):
        if l.strip():
            return int(l.strip())
    return -1


def main():
    # kanttyper i kilden
    ud, fejl = psql(KILDE_DB, "select l.name from ag_catalog.ag_label l join ag_catalog.ag_graph g "
                             f"on l.graph=g.graphid where g.name='{KILDE_GRAF}' and l.kind='e'")
    typer = [t.strip() for t in ud.splitlines() if t.strip()]
    print(f"  kanttyper i kilden: {len(typer)}", flush=True)
    if not typer:
        # VIGTIGT: tomt svar er IKKE det samme som "intet mangler" — det kan være
        # at containeren var ved at genstarte. Sig det direkte i stedet for at gætte.
        print(f"  STOP: kunne ikke læse kanttyperne i {KILDE_DB}/{KILDE_GRAF}.", flush=True)
        print(f"        svar fra basen: {(fejl or '').strip()[:200] or '(tomt — ingen fejlbesked)'}", flush=True)
        return 2

    mangler = []
    for t in typer:
        u1, _ = age(KILDE_DB, KILDE_GRAF, f"MATCH ()-[r:`{t}`]->() RETURN count(r)")
        u2, _ = age(MAAL_DB, MAAL_GRAF, f"MATCH ()-[r:`{t}`]->() RETURN count(r)")
        k, m = antal(u1), antal(u2)
        if k < 0 or m < 0:
            print(f"   {t}: kunne ikke tælles (kilden={u1.strip()[:40]!r}, målet={u2.strip()[:40]!r})", flush=True)
            continue
        if k > 0:
            diff = k - m
            print(f"   {t}: kilde {k} → mål {m}" + (f"   MANGLER {diff}" if diff > 0 else "   ok"), flush=True)
            if diff > 0:
                mangler.append((t, diff))

    if not mangler:
        print("  INTET MANGLER — alt er med.", flush=True)
        return 0

    print(f"\n  efterfylder {len(mangler)} kanttype(r):", flush=True)
    for t, diff in mangler:
        ud, _ = age(KILDE_DB, KILDE_GRAF,
                    f"MATCH (a)-[r:`{t}`]->(b) RETURN id(a), id(b), properties(r)", ("a", "b", "p"))
        # de der allerede er overført, kendes på at begge ender har gammel_id OG kanten findes
        ud2, _ = age(MAAL_DB, MAAL_GRAF,
                     f'MATCH (x)-[r:`{t}`]->(y) WHERE x.gammel_id IS NOT NULL AND y.gammel_id IS NOT NULL '
                     f'RETURN x.gammel_id, y.gammel_id', ("a", "b"))
        findes = {tuple(l.split("|")[:2]) for l in ud2.splitlines() if "|" in l}
        n = 0
        for linje in ud.splitlines():
            d = linje.split("|")
            if len(d) != 3:
                continue
            a, b, p = d[0].strip(), d[1].strip(), d[2].strip()
            if (a, b) in findes:
                continue
            try:
                import json
                dd = json.loads(p)
                dele = ", ".join(f"{k}: {json.dumps(v, ensure_ascii=False)}"
                                 for k, v in (dd or {}).items() if v not in (None, ""))
                kk = "{" + dele + "}"
            except Exception:
                kk = "{}"
            q = (f'MATCH (x {{gammel_id: "{a}"}}), (y {{gammel_id: "{b}"}}) '
                 f'CREATE (x)-\u005br:`{t}` {kk}\u005d->(y) RETURN 1')
            o, e = age(MAAL_DB, MAAL_GRAF, q)
            if e and "ERROR" in e:
                print(f"     {t}: {e[:100]}", flush=True)
            else:
                n += 1
        print(f"   {t}: {n} efterfyldt", flush=True)

    # SLUTTAELLING
    print("\n  === SLUTTAELLING ===", flush=True)
    for tekst, db, graf in [("kilde: knuder", KILDE_DB, KILDE_GRAF), ("kilde: kanter", KILDE_DB, KILDE_GRAF),
                            ("mål: knuder", MAAL_DB, MAAL_GRAF), ("mål: kanter", MAAL_DB, MAAL_GRAF)]:
        q = "MATCH (n) RETURN count(n)" if "knuder" in tekst else "MATCH ()-[r]->() RETURN count(r)"
        o, e = age(db, graf, q)
        print(f"   {tekst}: {antal(o)}", flush=True)
    o, _ = age(MAAL_DB, MAAL_GRAF, 'MATCH (n) WHERE n.fra_gammel_graf = "ja" RETURN count(n)')
    print(f"   mål: knuder fra den gamle graf: {antal(o)}", flush=True)
    o, _ = age(MAAL_DB, MAAL_GRAF, "MATCH (n) WHERE label(n) = 'Person' RETURN count(n)")
    print(f"   mål: personer: {antal(o)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
