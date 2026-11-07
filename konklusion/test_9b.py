#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_9b.py — hvor skarp er H.E.L.I.X:9b-neo til at udlede konklusioner?

Kører samme skabelon som motoren vil bruge: systembesked, én sætning, JSON ud.
    python3 test_9b.py
"""
import json
import sys
import time
import urllib.request

MODEL = "H.E.L.I.X:9b-neo"
OLLAMA = "http://127.0.0.1:11434/api/chat"

SYSTEM = ("Du er en dansk konklusionsmotor. Udled KUN det der står i sætningen. "
          "Gæt aldrig. Svar som JSON.")


def spørg(sætning: str) -> tuple[str, float]:
    krop = json.dumps({
        "model": MODEL,
        "messages": [{"role": "system", "content": SYSTEM},
                     {"role": "user", "content":
                      f"Sætning: {sætning}\nSvar KUN dette JSON: "
                      '{"emne":"<person eller ting>","egenskab":"<forhold>",'
                      '"vaerdi":"<det der siges>"} eller {"uforstaaet": true}'}],
        "stream": False, "think": False, "format": "json",
        "options": {"num_ctx": 8192, "temperature": 0.0, "num_predict": 90},
    }).encode()
    t0 = time.time()
    req = urllib.request.Request(OLLAMA, data=krop,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        svar = json.loads(r.read())
    return svar.get("message", {}).get("content", ""), round(time.time() - t0, 1)


# (sætning, forventet emne-ord, skal kunne læses?, kommentar)
PRØVER = [
    ("Advokaten sad i bestyrelsen for Holmegårdshuset.", "advokat", True, "rolle med sted"),
    ("Lisbeth Sten Jensen var sagkyndig dommer i kendelsen.", "lisbeth", True, "navn + embede"),
    ("Danny skal i ret i Svendborg den 9. november.", "danny", True, "dato i ord"),
    ("Jeanette Gjørret skal ringe til Danny på mandag kl. 16 dansk tid.", "gjørret", True, "aftale med tid"),
    ("Retssagen BS-34811/2026-NAE blev henvist fra Næstved til Svendborg.", "bs-34811", True, "sagsnummer"),
    ("Børn- og Ungeudvalget stemte 4-1 imod anbringelse den 17. august 2020.", "ungeudvalg", True, "afstemning"),
    ("Deirdre King sendte en underretning om mistanke den 6. april 2020.", "deirdre", True, "handling"),
    ("Stæbber siger et stæb vejledetning.", "", False, "stemmelarm"),
    ("Men du kan være lidt kig på, hvor der er hinviser.", "", False, "stemmelarm"),
    ("Det er en prøve, kan du høre mig.", "", False, "mikrofontest"),
    ("Hej med dig.", "", False, "hilsen"),
]


def demo() -> int:
    fejl = 0
    for sætning, forventet, skal_læses, note in PRØVER:
        try:
            svar, tid = spørg(sætning)
            d = json.loads(svar) if svar.strip().startswith("{") else {}
        except Exception as e:  # noqa: BLE001
            print(f"FEJL(kald) {sætning[:40]} → {e}")
            fejl += 1
            continue
        læst = not d.get("uforstaaet")
        emne = str(d.get("emne", "")).lower()
        ok = (læst == skal_læses) and (not forventet or forventet in emne)
        fejl += 0 if ok else 1
        print(f"{'OK ' if ok else 'FEJL'} [{tid}s] {note:15s} | "
              f"emne={d.get('emne', '-' )[:24]:24s} "
              f"eg={str(d.get('egenskab', '-'))[:14]:14s} "
              f"vaerdi={str(d.get('vaerdi', '-'))[:40]}")
    print(f"\ntest_9b: {len(PRØVER) - fejl} af {len(PRØVER)} rigtige")
    return fejl


if __name__ == "__main__":
    sys.exit(1 if demo() else 0)
