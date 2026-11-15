"""Juridisk tjekliste — kør Agent Paulus' 350 metodekort mod hjernens materiale.

Et metodekort er et SPØRGSMÅL, ikke et svar. Dette værktøj besvarer dem ikke;
det måler om der er materiale nok til at svare, og peger på hullet hvor der
ikke er.

    python3 juridisk.py --oversigt
    python3 juridisk.py --kort AD15 --ejer <bruger-id>
    python3 juridisk.py --daekning --ejer <bruger-id>
    python3 juridisk.py --selvtest

Kilderne er Agent Paulus 2.0 (Ole Bakkestrøm) — se
`Obsidian/Agenter/Helix/Rapporter/Agent Paulus — juridisk metode og sammenligning.md`.
Metodens egne ord om sig selv: den er IKKE gældende ret, og den er ikke
empirisk valideret. Den er et redskab til at tænke klart.
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

METODE_DIR = Path(os.environ.get(
    "PAULUS_METODER",
    "/home/dna/H.E.L.I.X WORKSPACE/Helix/paulus-analyse/Agent Paulus 2.0/agent/methods"))

FILER = {
    "AD": ("administrative.json", "Forvaltningsret"),
    "PV": ("psychological-violence.json", "Psykisk vold"),
    "IG": ("institutional-gaslighting.json", "Institutionel gaslighting"),
    "EMRK": ("emrk.json", "Menneskerettigheder (EMRK)"),
    "FT": ("ft.json", "Bevarede funktioner"),
}

# Hvilke ord i et metodekort peger på hvilke beviser i materialet?
# Dette er den bro der gør det muligt at sige "du mangler dokumentation for X".
SPOR = {
    "AD01": ["afgørelse", "meddelelse", "brev", "svar"],
    "AD05": ["hjemmel", "lov", "§"],
    "AD09": ["habilitet", "inhabilitet", "interesse"],
    "AD15": ["version", "gældende", "ophævet", "ændret"],
    "AD17": ["partshøring", "høring", "udtalelse"],
    "AD21": ["aktindsigt", "indsigt"],
    "AD24": ["notat", "notatpligt"],
    "AD25": ["journal", "journalisering", "sagsakt"],
    "AD26": ["begrundelse", "begrundet"],
    "AD27": ["klagevejledning", "klage"],
    "AD28": ["sagsbehandlingstid", "svar", "frist"],
    "AD36": ["genoptagelse", "genoptaget", "korrektion"],
    "AD41": ["gentaget", "igen", "mønster", "flere gange"],
}

DSN = os.environ.get("KONKLUSION_DSN",
                     "host=127.0.0.1 port=5432 dbname=hjerne user=hjerne password=skift-mig")


def indlaes() -> list[dict]:
    """Laes alle 350 metodekort."""
    kort = []
    for praefiks, (fil, navn) in FILER.items():
        p = METODE_DIR / fil
        if not p.exists():
            continue
        d = json.loads(p.read_text(encoding="utf-8"))
        for x in d.get("items", d if isinstance(d, list) else []):
            kid = x.get("id") or ""
            tekst = (x.get("question") or x.get("title") or x.get("name") or
                     x.get("rule") or "")
            kort.append({
                "id": kid,
                "spor": praefiks,
                "spor_navn": navn,
                "spoergsmaal": tekst.strip(),
                "kilder": x.get("source_links") or [],
            })
    return kort


def _ord(tekst: str) -> set[str]:
    return {w for w in re.findall(r"[a-zæøå]{4,}", (tekst or "").lower())}


def daekning(kort: dict, konklusioner: list[dict]) -> tuple[int, list[str]]:
    """Hvor meget materiale er der til dette kort? Returnerer (antal, eksempler).

    Vi maaler ikke om svaret er rigtigt — kun om der FINDES materiale at svare
    ud fra. Et hul i materialet er et hul, ikke en konklusion.

    DNA 2026-11-15: EMRK-kortene er korte og generiske ("Kortlaeg stat,
    kommune, region ..."). Foer talte de ALT materiale som traef, fordi
    naesten enhver saetning naevner en kommune. Nu kraever vi at mindst TO
    af kortets egne noegleord rammer samme raekke — ellers er det ikke et
    udsagn OM kortet, bare en tilfaeldig ordmatch.
    """
    k = kort["id"]
    soegeord = SPOR.get(k) or list(_ord(kort["spoergsmaal"]))[:6]
    if not soegeord:
        return 0, []
    kraev = 1 if k in SPOR else 2
    fund = []
    for r in konklusioner:
        tekst = " ".join(str(r.get(x) or "") for x in
                         ("emne", "egenskab", "vaerdi", "kilde_tekst")).lower()
        ramt = sum(1 for o in soegeord if o in tekst)
        if ramt >= kraev:
            fund.append(str(r.get("kilde_tekst") or r.get("vaerdi") or "")[:90])
    return len(fund), fund[:3]


def hent_konklusioner(ejer: str) -> list[dict]:
    import psycopg
    with psycopg.connect(DSN, autocommit=True) as con, con.cursor() as cur:
        cur.execute("""SELECT emne, egenskab, coalesce(vaerdi,''), coalesce(kilde_tekst,'')
                       FROM konklusion
                       WHERE NOT ugyldig AND (ejer = %s OR %s = '')
                       LIMIT 20000""", (ejer, ejer))
        return [{"emne": r[0], "egenskab": r[1], "vaerdi": r[2], "kilde_tekst": r[3]}
                for r in cur.fetchall()]


def oversigt(kort: list[dict]) -> None:
    fra_spor: dict[str, int] = {}
    for k in kort:
        fra_spor[k["spor_navn"]] = fra_spor.get(k["spor_navn"], 0) + 1
    print(f"{len(kort)} metodekort i alt\n")
    for navn, n in sorted(fra_spor.items(), key=lambda x: -x[1]):
        print(f"  {navn:32} {n:3}")


def vis_kort(kort: list[dict], kid: str) -> None:
    for k in kort:
        if k["id"].upper() == kid.upper():
            print(f"[{k['id']}] {k['spor_navn']}")
            print(f"\n{k['spoergsmaal']}\n")
            if k["kilder"]:
                print("Officielle kilder:")
                for s in k["kilder"][:3]:
                    print(" ", s)
            return
    print(f"Ukendt kort: {kid}")


def vis_daekning(kort: list[dict], konklusioner: list[dict]) -> None:
    huller, daekket = [], []
    for k in kort:
        n, eks = daekning(k, konklusioner)
        (daekket if n else huller).append((k, n, eks))

    print(f"Materiale gennemgaaet: {len(konklusioner)} konklusioner")
    print(f"Kort med materiale:    {len(daekket)}")
    print(f"Kort uden materiale:   {len(huller)}\n")

    print("=== DE STOERSTE HULLER (ingen materiale) ===")
    for k, _, _ in huller[:15]:
        print(f"  {k['id']:10} {k['spoergsmaal'][:88]}")

    print("\n=== BEDST DAEKKET ===")
    for k, n, eks in sorted(daekket, key=lambda x: -x[1])[:10]:
        print(f"  {k['id']:10} {n:4} traef  {eks[0][:70] if eks else ''}")


def selvtest() -> None:
    """Mindste kontrol: kan kortene laeses, og virker daeknings-maalingen?"""
    kort = indlaes()
    assert len(kort) >= 340, f"kun {len(kort)} kort fundet — stien er forkert?"
    assert all(k["id"] for k in kort), "et kort mangler id"
    assert any(k["spoergsmaal"] for k in kort), "ingen spoergsmaal laest"

    prove = [{"emne": "X", "egenskab": "y", "vaerdi": "afgørelse",
              "kilde_tekst": "kommunen traf afgørelse den 3. maj"}]
    ad01 = next(k for k in kort if k["id"] == "AD01")
    n, _ = daekning(ad01, prove)
    assert n == 1, f"AD01 burde finde 1 traef, fandt {n}"

    tom = daekning(ad01, [{"emne": "a", "egenskab": "b", "vaerdi": "c",
                           "kilde_tekst": "noget andet"}])
    assert tom[0] == 0, "tomt materiale gav traef"

    print(f"selvtest: 5 kontroller bestaaet ({len(kort)} kort indlaest)")


def main():
    p = argparse.ArgumentParser(description="Juridisk tjekliste fra Agent Paulus")
    p.add_argument("--oversigt", action="store_true")
    p.add_argument("--kort", metavar="ID")
    p.add_argument("--daekning", action="store_true")
    p.add_argument("--ejer", default="")
    p.add_argument("--selvtest", action="store_true")
    a = p.parse_args()

    if a.selvtest:
        return selvtest()

    kort = indlaes()
    if a.oversigt or not (a.kort or a.daekning):
        return oversigt(kort)
    if a.kort:
        return vis_kort(kort, a.kort)
    if a.daekning:
        return vis_daekning(kort, hent_konklusioner(a.ejer))


if __name__ == "__main__":
    main()
