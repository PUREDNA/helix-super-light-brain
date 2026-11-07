#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Flytter DEN GAMLE GRAFS data ind i Super Brains EGEN graf.

DNA 2026-10-13: "du har ikke faaet al min data fra den gamle graf ind i den nye
graf, saa jeg kan se det."

Kilden er den kopi der allerede ligger i Super Brain (gammel_graf/juridiske_sager)
— den gamle base roeres ikke. Maalet er hjernens egen graf (hjerne/hjerne).

Alt kopieres LOGISK: label for label, knude for knude — saa id'er og katalog
tildeles af AGE selv. Egenskaberne (domene, kategori, rolle ...) foelger med,
plus et spoer 'fra_gammel_graf' og den gamle id, saa hver knude kan spores.
"""
import json
import subprocess
import sys

MAAL_DB, MAAL_GRAF = "hjerne", "hjerne"
KILDE_DB, KILDE_GRAF = "gammel_graf", "juridiske_sager"


def psql(db, sql, timeout=300):
    r = subprocess.run(["docker", "exec", "Helix_Super_Brain", "psql", "-U", "hjerne",
                        "-h", "127.0.0.1", "-d", db, "-tAc", sql],
                       capture_output=True, text=True, timeout=timeout)
    return "\n".join(l for l in r.stdout.split("\n") if l.strip() and
                     l.strip() not in ("LOAD", "SET", "CREATE EXTENSION")), r.stderr


def age(db, graf, q, kolonner=("x",), timeout=300):
    ali = ", ".join(f"c{i} agtype" for i in range(len(kolonner)))
    return psql(db, "LOAD 'age'; SET search_path = ag_catalog, public; "
                    "SET client_min_messages=warning; "
                    f"SELECT * FROM cypher('{graf}', $cy$ {q} $cy$) as ({ali});", timeout)


def kort(props_text):
    try:
        d = json.loads(props_text)
    except Exception:
        return None
    if not isinstance(d, dict):
        return None
    dele = []
    for k, v in d.items():
        if v is None or v == "":
            continue
        nk = k if k.replace("_", "").isalnum() else '"%s"' % k
        dele.append("%s: %s" % (nk, json.dumps(v, ensure_ascii=False)))
    return "{" + ", ".join(dele) + "}"


def main():
    # 1) hvilke labels findes i kilden?
    ud, fejl = psql(KILDE_DB, "select l.name || '|' || l.kind::text from ag_catalog.ag_label l "
                             "join ag_catalog.ag_graph g on l.graph = g.graphid "
                             f"where g.name = '{KILDE_GRAF}' order by l.id")
    labels = [(n, k) for n, k in (l.split("|") for l in ud.splitlines() if "|" in l)
              if not n.startswith("_ag_label_")]
    print(f"  labels i kilden: {len(labels)}", flush=True)

    # 2) opret dem der mangler i maalet
    nye = 0
    for navn, kind in labels:
        fn = "create_vlabel" if kind == "v" else "create_elabel"
        o, e = psql(MAAL_DB, f"LOAD 'age'; SET search_path = ag_catalog, public; "
                             f"SELECT ag_catalog.{fn}('{MAAL_GRAF}', '{navn}');")
        if "ERROR" not in (e or ""):
            nye += 1
    print(f"  labels sikret i maalet: {nye}", flush=True)

    # 3) knuderne over
    tot = 0
    for navn, kind in labels:
        if kind != "v":
            continue
        ud, fejl = age(KILDE_DB, KILDE_GRAF, f"MATCH (n:`{navn}`) RETURN id(n), properties(n)", ("i", "p"))
        if fejl and "ERROR" in fejl:
            print(f"   laes {navn}: {fejl[:90]}", flush=True)
            continue
        ko = []
        for linje in ud.splitlines():
            if "|" in linje:
                i, p = linje.split("|", 1)
                kk = kort(p.strip())
                if kk:
                    ko.append((i.strip(), kk))
        for i, kk in ko:
            q = (f'CREATE (n:`{navn}` {kk}) SET n.gammel_id = "{i}", '
                 f'n.fra_gammel_graf = "ja" RETURN 1')
            o, e = age(MAAL_DB, MAAL_GRAF, q)
            if e and "ERROR" in e:
                print(f"   skriv {navn}: {e[:110]}", flush=True)
            else:
                tot += 1
        print(f"   {navn}: {len(ko)}", flush=True)
    print(f"  KNUDER FLYTTET: {tot}", flush=True)

    # 4) kanterne over, koblet via gammel_id
    kt = 0
    for navn, kind in labels:
        if kind != "e":
            continue
        ud, fejl = age(KILDE_DB, KILDE_GRAF,
                       f"MATCH (a)-[r:`{navn}`]->(b) RETURN id(a), id(b), properties(r)", ("a", "b", "p"))
        if fejl or not ud.strip():
            continue
        ko = []
        for linje in ud.splitlines():
            d = linje.split("|")
            if len(d) == 3:
                kk = kort(d[2].strip()) or "{}"
                ko.append((d[0].strip(), d[1].strip(), kk))
        for a, b, kk in ko:
            q = (f'MATCH (x {{gammel_id: "{a}"}}), (y {{gammel_id: "{b}"}}) '
                 f'CREATE (x)-\u005br:`{navn}` {kk}\u005d->(y) RETURN 1')
            o, e = age(MAAL_DB, MAAL_GRAF, q)
            if e and "ERROR" in e:
                print(f"   skriv kant {navn}: {e[:110]}", flush=True)
            else:
                kt += 1
    print(f"  KANTER FLYTTET: {kt}", flush=True)

    # 5) EFTERPROEVNING
    for tekst, q in [("knuder i alt", "MATCH (n) RETURN count(n)"),
                     ("kanter i alt", "MATCH ()-[r]->() RETURN count(r)"),
                     ("fra den gamle graf", 'MATCH (n) WHERE n.fra_gammel_graf = "ja" RETURN count(n)'),
                     ("personer", "MATCH (n) WHERE label(n) = 'Person' RETURN count(n)")]:
        o, e = age(MAAL_DB, MAAL_GRAF, q)
        print(f"  {tekst}: {(o.strip().splitlines()[-1] if o.strip() else e[:90])}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
