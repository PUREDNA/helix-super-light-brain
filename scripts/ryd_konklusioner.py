#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gennemgang af hjernens konklusioner i Super Brain-containeren.

Formaal: finde ud af hvad der skal ryddes ud af de GAMLE konklusioner (alle lavet
af den svage 4B-model) foer den nye model begynder at lave nye.

Ingen model bruges — sorteringen er deterministisk (den tæller ord og moenstre),
praecis som kategoriseringen i den anden hjerne. Alt kan rulles tilbage: der
SKRIVES ikke, der SÆTTES et tidsstempel i deleted_at (den bloede sletning).

  python3 ryd_konklusioner.py            # kun forslag (roerer intet)
  python3 ryd_konklusioner.py --anvend   # saetter deleted_at paa det der skal vaek
"""
import json
import re
import subprocess
import sys
from collections import Counter

PG = ["psql", "-U", "hjerne", "-h", "127.0.0.1", "-d", "hjerne", "-tAc"]

# --- Moenstre: kun det der er MAALBART forkert ryger ud. Emne og personlighed
#     er VELKOMNE (DNA vil gerne have, at hjernen kender hans kaffe og hund).
VRØVL = [
    r"forskeli", r"sprøvet", r"sprøve", r"vedrettet", r"opfylde kravet",
    r"kunne ikke", r"gjorde noget forkert", r"har gjort noget forkert",
    r"proevede", r"prøvede at", r"glemte at", r"du skal", r"assistenten",
    r"jeg har", r"helix skal", r"det lykkedes ikke",
]
# Forkert subjekt: brugeren er Danny — ikke Helix, ikke en rolle.
FORKERT_SUBJEKT = [
    r"^dna hedder helix", r"dna er helix", r"dna's navn er helix",
    r"^helix hedder dna", r"brugeren hedder helix",
]
# Tomt eller uforpligtende: siger intet man kan efterproeve.
UBESTEMT = [
    r"har tidligere arbejdet", r"har arbejdet med", r"er i gang med",
    r"har noget med", r"synes faktisk at", r"har flere", r"paa flere platforme",
    r"generelt", r"i det hele taget",
]
# REFERAT-FORM: tredjeperson der beskriver hvad han sagde, uden en kendsgerning.
# Det er praecis den form DNA kalder et referat — og den vil han ikke have.
REFERAT = [
    r"^spørger om", r"^spoerger om", r"^siger at", r"^siger ", r"^tænker ",
    r"^ved ikke", r"^vil have", r"^vil gerne", r"^kan se", r"^måske ",
    r"^maaske ", r"^tror ", r"^synes at", r"^fortæller ", r"^naevner ",
    r"^kommer ind på", r"^er i tvivl", r"^overvejer",
]


def hent() -> list[dict]:
    sql = ("select json_agg(row_to_json(t)) from (select id, level, content, "
           "created_at::text from hc.documents where deleted_at is null) t")
    r = subprocess.run(PG + [sql], capture_output=True, text=True, timeout=120)
    return json.loads(r.stdout.strip() or "[]")


def klasser(k: dict, sete: Counter) -> list[str]:
    t = k["content"].strip()
    lav = t.lower()
    ud = []
    noegle = re.sub(r"[^a-zæøå0-9 ]", "", lav)[:90]
    if sete[noegle]:
        ud.append("dublet")
    sete[noegle] += 1
    if len(t) < 30 and not re.search(r"\b[A-ZÆØÅ][a-zæøå]{2,}", t[1:]):
        ud.append("for kort")
    for m in REFERAT:
        if re.search(m, lav):
            ud.append("referat-form")
            break
    for m in VRØVL:
        if re.search(m, lav):
            ud.append("vrøvl/om sig selv")
            break
    for m in FORKERT_SUBJEKT:
        if re.search(m, lav):
            ud.append("forkert navn")
            break
    for m in UBESTEMT:
        if re.search(m, lav):
            ud.append("intet at efterproeve")
            break
    return ud


def main():
    anvend = "--anvend" in sys.argv
    k = hent()
    print(f"  konklusioner i alt: {len(k)}")
    sete = Counter()
    behold, ryd = [], []
    for x in k:
        grunde = klasser(x, sete)
        (ryd if grunde else behold).append((x, grunde))

    taeller = Counter(g for _, gr in ryd for g in gr)
    print(f"\n  BEHOLD: {len(behold)}   |   RYD: {len(ryd)}")
    print("  hvorfor de ryger:")
    for navn, antal in taeller.most_common():
        print(f"     {navn:22} {antal}")

    # Gem altid en kopi foer der roeres noget.
    fil = f"/tmp/konklusioner-backup-{'efter' if anvend else 'foer'}.json"
    with open(fil, "w", encoding="utf-8") as f:
        json.dump(k, f, ensure_ascii=False, indent=1)
    print(f"\n  kopi af ALLE {len(k)} gemt: {fil}")

    print("\n  --- 10 eksempler paa det der ryger:")
    for x, gr in ryd[:10]:
        print(f"     [{'/'.join(gr)}] {x['content'][:95]}")
    print("\n  --- 8 eksempler paa det der bliver:")
    for x, _ in behold[:8]:
        print(f"     {x['content'][:95]}")

    if not anvend:
        print("\n  (kun forslag — koer med --anvend for at rydde)")
        return 0

    ids = [str(x["id"]).replace("'", "") for x, _ in ryd]
    liste = ",".join("'" + i + "'" for i in ids)
    sql = ("update hc.documents set deleted_at = now() where id in "
           f"({liste})")
    r = subprocess.run(PG + [sql], capture_output=True, text=True, timeout=180)
    print(f"\n  ryddet: {r.stdout.strip() or r.stderr.strip()}")
    tjek = subprocess.run(PG + ["select count(*) from hc.documents where deleted_at is null"],
                          capture_output=True, text=True, timeout=60)
    print(f"  tilbage i basen: {tjek.stdout.strip()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
