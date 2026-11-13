"""Fuld test af lillehjernen. Korer alle tjenester og alle regler igennem.

    python3 fuld_test.py

Fejler hojt hvis noget ikke virker. Kores efter enhver aendring.
"""
import json
import subprocess
import sys
import urllib.request

MOTOR = "http://127.0.0.1:6305"
VIEWER = "http://127.0.0.1:6301"
DROM = "http://127.0.0.1:6304"
VAULT = "http://127.0.0.1:6303"

DNA = "99a107f4-b20e-468b-9b9e-a019c23c196e"

fejl = []


def tjek(navn, ok, detalje=""):
    print(("  OK   " if ok else "  FEJL ") + navn + ((" — " + detalje) if detalje else ""))
    if not ok:
        fejl.append(navn)


def hent(url, timeout=20):
    with urllib.request.urlopen(url, timeout=timeout) as s:
        return json.load(s)


def hoved():
    print("1. TJENESTERNE SVARER")
    for navn, url in (("motor", MOTOR + "/status"), ("viewer", VIEWER + "/"),
                      ("drom", DROM + "/"), ("vault", VAULT + "/status")):
        try:
            with urllib.request.urlopen(url, timeout=10) as s:
                tjek(navn + " svarer", s.status == 200)
        except Exception as e:
            tjek(navn + " svarer", False, type(e).__name__)

    print("\n2. INGEN SKRALD TIL AI'EN")
    st = hent(MOTOR + "/status")
    tjek("kun gyldige taelles", st.get("konklusioner", 0) > 1000,
         f"{st.get('konklusioner')} i brug")
    tjek("kasserede er rapporteret", st.get("kasseret", 0) > 0,
         f"{st.get('kasseret')} kasseret")

    print("\n3. KONKLUSIONERNE ER VIDEN")
    d = hent(MOTOR + "/konklusioner?antal=20")
    kon = d.get("konklusioner", [])
    tjek("der er konklusioner", len(kon) > 0, f"{len(kon)}")
    ordrer = [k for k in kon
              if any(x in (k.get("vaerdi") or "").lower()
                     for x in ("du skal", "tilladelse", "godkendelse givet"))]
    tjek("ingen ordrer i udtraekket", not ordrer, f"{len(ordrer)} fundet")

    print("\n4. SOEGNINGEN VIRKER")
    for spoergsmaal in ("Dio samvaer", "boernesag kommune", "Hanne sagsbehandler"):
        try:
            r = urllib.request.Request(
                MOTOR + "/soeg",
                data=json.dumps({"spoergsmaal": spoergsmaal, "antal": 3}).encode(),
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(r, timeout=40) as s:
                svar = json.load(s)
            tjek(f"soeg '{spoergsmaal}'", not svar.get("fejl") and svar.get("fund"),
                 f"{len(svar.get('fund') or [])} fund")
        except Exception as e:
            tjek(f"soeg '{spoergsmaal}'", False, type(e).__name__)

    print("\n5. KONTORET ER GRAENSEN")
    try:
        a = hent(VIEWER + f"/api/graph?x=1&ejer={DNA}")
        tjek("DNA's graf har data", len(a.get("nodes", [])) > 0,
             f"{len(a.get('nodes', []))} noder")
        tom = hent(VIEWER + "/api/graph?x=1")
        tjek("uden ejer = ingen data", len(tom.get("nodes", [])) == 0)
    except Exception as e:
        tjek("kontor-graense", False, type(e).__name__)

    print("\n6. DROEMMEN")
    try:
        dr = hent(DROM + "/")
        tjek("droemmen koerer", "fund" in dr, f"{dr.get('fund')} fund")
    except Exception as e:
        tjek("droemmen koerer", False, type(e).__name__)

    print("\n7. ORDRE-FILTERET (kode-test)")
    r = subprocess.run(
        ["docker", "exec", "Helix_Light_Brain", "python3", "-c", """
import sys; sys.path.insert(0, '/opt/lillehjerne/konklusion')
from laeser import er_samtalestoej
ordrer = ['du skal bygge den', 'Slet skraldet nu', 'Ja tak, det maa du gerne']
fakta = ['Dio bor i plejefamilie i Broendby', 'Hanne Simonsen er sagsbehandler']
assert all(er_samtalestoej(t) for t in ordrer), 'ordre slap igennem'
assert not any(er_samtalestoej(t) for t in fakta), 'fakta blev kasseret'
print('ok')
"""], capture_output=True, text=True)
    tjek("ordrer afvises, fakta bevares", "ok" in r.stdout,
         (r.stdout or r.stderr)[:80])

    print()
    if fejl:
        print(f"{len(fejl)} FEJL: " + ", ".join(fejl))
        sys.exit(1)
    print("ALLE KONTROLLER BESTAAET")


if __name__ == "__main__":
    hoved()
