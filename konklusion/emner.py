"""Emneopdeling af konklusioner — saa en teknik-samtale ikke faar boernesag.

DNA 2026-11-16: "hvis jeg sidder og snakker med dig om data og teknik, saa skal
der ikke komme konklusioner omkring boernesagen."

Hver konklusion faar et emne fra en fast liste. Naar hjaernen spoerges, findes
spoergsmaalets emne foerst, og kun konklusioner i SAMME emne kommer med.
Er intet emne sikkert, kommer der intet — hellere tomt end forkert.

    python3 emner.py                    vis proever
    python3 emner.py --klassificer      saet emne paa alle
    python3 emner.py --test "hvad koster den"
"""
import argparse

import psycopg

DSN = "host=127.0.0.1 port=5432 dbname=hjerne user=hjerne password=skift-mig"

# Raekkefoelgen betyder noget: det foerste der rammer vinder — men kun naar
# begge er lige specifikke. Se vaelg_emne() nedenfor.
EMNER = [
    ("boernesag", (
        "dio", "samvær", "samvaer", "anbringelse", "plejefamilie", "brøndby",
        "broendby", "jammerbugt", "familieretshus", "ankestyrelsen",
        "børne- og unge", "boerne- og unge", "§ 71", "§71", "underretning",
        "forældreevne", "foeraeldreevne", "sagsbehandler", "psykolog",
        "samværskonsulent", "ditte", "danny nordstrøm", "danny nordstrom",
        "cpr", "børnesag", "boernesag", "tvangsfjernelse",
    )),
    ("teknik", (
        "docker", "container", "gpu", "grafikkort", "nvidia", "cuda",
        "ollama", "token", "kontekst", "postgres", "postgresql",
        "wsl", "linux", "windows", "driver", "strata", "openwebui", "hermes",
        "api", "endpoint", "logfil", "bug", "kode", "script", "python",
        "ram", "cpu", "vram", "lillehjerne", "lillehjernen",
        "graf", "viewer", "terminal", "kommando", "installation", "opdater",
        "backup", "netværk", "netvaerk", "ssh", "git", "github", "repo",
    )),
    ("oekonomi", (
        "pris", "koster", "kroner", "euro", "dollar", "budget", "regnskab",
        "faktura", "betale", "betalte", "løn", "loen", "udgift", "indtægt",
        "dropshipping", "leverandør", "leverandoer", "køb", "koeb", "salg",
    )),
    ("jura", (
        "paragraf", "§", "lov", "servicelov", "straffelov", "emrk", "domstol",
        "retten", "advokat", "anke", "klage", "afgørelse", "afgoerelse",
        "myndighed", "aktindsigt", "høring", "hoering",
    )),
    ("personligt", (
        "danny", "dna", "familie", "ven", "sandra", "jasmine", "jasmin",
        "helbred", "syg", "medicin", "følelse", "foelelse", "privat", "gud",
        "tro", "håb", "haab",
    )),
    # DNA 2026-11-16: "lave" alene er for bredt — det fangede "hvad skal vi
    # lave" og gav tilfaeldige saetninger. Nu kraever projekt-emnet et
    # konkret projektord.
    ("projekt", (
        "projekt", "opgave", "næste skridt", "naeste skridt", "todo",
        "kanban", "milepæl", "milepael", "deadline", "aftale om",
        "godmorgen", "skal vi", "hvad nu", "i dag skal",
    )),
]


def find_emner(tekst: str) -> set[str]:
    """Hvilke emner rammer teksten? Tom = ved det ikke."""
    t = (tekst or "").lower()
    ramt = set()
    for navn, ord_ in EMNER:
        if any(o in t for o in ord_):
            ramt.add(navn)
    return ramt


def vaelg_emne(spoergsmaal: str) -> str:
    """Det mest specifikke emne — eller tomt hvis intet rammer.

    DNA 2026-11-17: naar flere emner rammer, vinder det med det LAENGSTE
    ramte ord. Et specifikt ord som «advokat» slår et bredt som «port ».
    Ellers blev en advokatsaetning teknik, fordi den ogsaa naevnte en port.
    """
    t = (spoergsmaal or "").lower()
    bedst, bedste_laengde = "", 0
    for navn, ord_ in EMNER:
        # Kun de ord der FAKTISK staar i teksten tael med.
        ramte = [o for o in ord_ if o in t]
        if not ramte:
            continue
        laengde = max(len(o) for o in ramte)
        if laengde > bedste_laengde:
            bedst, bedste_laengde = navn, laengde
    return bedst


def klassificer() -> None:
    with psycopg.connect(DSN, autocommit=True) as con, con.cursor() as cur:
        cur.execute("""SELECT id, coalesce(kilde_tekst,'') FROM konklusion
                       WHERE NOT ugyldig
                         AND (emne_gruppe IS NULL OR emne_gruppe = '')""")
        raekker = cur.fetchall()
        print(f"klassificerer {len(raekker)} konklusioner")

        talt: dict[str, int] = {}
        for kid, tekst in raekker:
            valgt = vaelg_emne(tekst) or "ukendt"
            cur.execute("UPDATE konklusion SET emne_gruppe = %s WHERE id = %s",
                        (valgt, kid))
            talt[valgt] = talt.get(valgt, 0) + 1
        for k, n in sorted(talt.items(), key=lambda x: -x[1]):
            print(f"  {k:12} {n:6}")


def test(spoergsmaal: str) -> None:
    valgt = vaelg_emne(spoergsmaal)
    print(f"spoergsmaal: {spoergsmaal!r}")
    print(f"  emne: {valgt or 'INTET — hellere tomt end forkert'}")
    if not valgt:
        return
    with psycopg.connect(DSN, autocommit=True) as con, con.cursor() as cur:
        cur.execute("""SELECT count(*) FROM konklusion
                       WHERE NOT ugyldig AND emne_gruppe = %s""", (valgt,))
        print(f"  konklusioner i det emne: {cur.fetchone()[0]}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--klassificer", action="store_true")
    p.add_argument("--test")
    a = p.parse_args()
    if a.klassificer:
        return klassificer()
    if a.test:
        return test(a.test)
    for q in ("godmorgen hvad skal vi lave", "hjælp mig med docker",
              "børnesagen samvær", "hvad koster den maskine", "hvilken paragraf"):
        test(q)
        print()


if __name__ == "__main__":
    main()
