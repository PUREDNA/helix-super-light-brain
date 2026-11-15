"""Kontor-kontrol: beviser at hver bruger kun ser sit eget kontor.

Kør efter enhver ændring i viewer/motor/bro. Fejler højlydt hvis en
bruger kan se en andens data.

    python3 kontor_kontrol.py
"""
import json
import os
import sys
import urllib.request

VIEWER = "http://127.0.0.1:6301"
DNA = os.environ.get("TEST_DNA_ID", "")   # saet TEST_DNA_ID for at teste kontor
ASGER = os.environ.get("TEST_ANDEN_BRUGER_ID", "")

fejl = []


def hent(sti):
    with urllib.request.urlopen(VIEWER + sti, timeout=15) as s:
        return json.load(s)


def tjek(navn, ok, detalje=""):
    print(("OK   " if ok else "FEJL ") + navn + ((" — " + detalje) if detalje else ""))
    if not ok:
        fejl.append(navn)


def main():
    if not (DNA and ASGER):
        print("SPRINGET OVER: saet TEST_DNA_ID og TEST_ANDEN_BRUGER_ID for at "
              "teste kontor-opdelingen paa din egen installation.")
        return

    # 1. Grafen: Asger maa ikke se DNA's knuder — men han maa gerne se SINE EGNE.
    a_graf = hent(f"/api/graph?x=1&ejer={ASGER}")
    d_graf = hent(f"/api/graph?x=1&ejer={DNA}")
    andres = [n for n in a_graf["nodes"]
              if (n.get("props") or {}).get("ejer") not in ("", ASGER)]
    tjek("Asger ser ikke DNA's knuder i sin graf", not andres,
         f"{len(andres)} fremmede af {len(a_graf['nodes'])}")
    tjek("DNA's graf har knuder", len(d_graf["nodes"]) > 0,
         f"{len(d_graf['nodes'])} noder")

    # 2. Kontoret: Asger ser sit eget
    a_kontor = hent(f"/api/kontor?ejer={ASGER}")
    tjek("Asgers kontor har hans egne konklusioner",
         a_kontor["ejer"] == ASGER and len(a_kontor["nodes"]) > 1,
         f"{len(a_kontor['nodes'])} noder")
    d_kontor = hent(f"/api/kontor?ejer={DNA}")
    tjek("DNA's kontor er et andet rum",
         d_kontor["ejer"] == DNA)

    # 3. Soegning: Asger finder ikke DNA's sager
    for ord_ in ("Hanne", "Dio", "Simonsen", "Brøndby"):
        a_s = hent(f"/api/search?q={urllib.parse.quote(ord_)}&ejer={ASGER}")
        tjek(f"Asger kan ikke soege '{ord_}' i DNA's data",
             len(a_s.get("nodes", [])) == 0,
             f"{len(a_s.get('nodes', []))} fund")

    # 4. Ingen ugyldige rækker i kontoret
    ugyldige = [n for n in a_kontor["nodes"]
                if n["props"].get("bevis") == "" and not n.get("label")]
    tjek("Ingen tomme konklusioner i Asgers kontor", not ugyldige)

    print()
    if fejl:
        print(f"{len(fejl)} FEJL")
        sys.exit(1)
    print("ALLE KONTROLLER BESTAAET")


if __name__ == "__main__":
    import urllib.parse  # noqa: F401
    main()
