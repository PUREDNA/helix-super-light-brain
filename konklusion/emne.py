"""Emne- og kategorisystem i lillehjernen.

To niveauer:
  kategori — hvad slags viden (boernesag, jura, teknik, privat)
  emne     — den konkrete sag (dio, vodafone, teknik, danny-privat)

ALT ligger i lillehjernen. Ingen bro behoeves — Hermes' compression-plugin,
OpenWebUI eller hvad der ellers kobles paa kalder bare motoren, og emnet
foelger med automatisk.

Emnet saettes AF BRUGEREN, aldrig gaettet. Naavner brugeren et emne ved
navn, saettes det. Naavner han flere eller ingen, sker der intet — saa
spoerger Helix i stedet for at gaette.
"""
import os

import psycopg

DSN = os.environ.get(
    "KONKLUSION_DSN",
    "host=127.0.0.1 port=5432 dbname=hjerne user=hjerne password=skift-mig")

# Ord der peger paa et emne. Det er IKKE et gaet paa hvad samtalen handler
# om — kun et signal om at brugeren naevner emnet ved navn.
SIGNALER = {
    "dio": ("dio", "dios sag", "børnesagen", "boernesagen", "samvær med dio"),
    "vodafone": ("vodafone",),
    "teknik": ("docker", "port ", "gpu", "server", "container", "lillehjernen",
               "strata", "openwebui", "hermes", "konklusionsmotor"),
    "danny-privat": ("mit liv", "min mor", "min far", "privat"),
}


def hent_emne(session_id: str):
    """Hvad er sessionens emne og kategori? None hvis intet er sat."""
    with psycopg.connect(DSN, autocommit=True) as con, con.cursor() as cur:
        cur.execute("""SELECT e.navn, e.kategori FROM session_emne s
                       JOIN emne e ON e.navn = s.emne
                       WHERE s.session_id = %s""", (session_id,))
        return cur.fetchone()


def saet_emne(session_id: str, navn: str) -> bool:
    """Saet emnet — kun hvis det findes i listens kendte emner."""
    with psycopg.connect(DSN, autocommit=True) as con, con.cursor() as cur:
        cur.execute("SELECT 1 FROM emne WHERE navn = %s", (navn,))
        if not cur.fetchone():
            return False
        cur.execute("""INSERT INTO session_emne (session_id, emne)
                       VALUES (%s, %s)
                       ON CONFLICT (session_id)
                       DO UPDATE SET emne = EXCLUDED.emne, sat = now()""",
                    (session_id, navn))
        return True


def signal_emne(tekst: str):
    """Naavner brugeren præcis EET emne ved navn? Ellers None."""
    t = (tekst or "").lower()
    traef = [navn for navn, ord_ in SIGNALER.items()
             if any(o in t for o in ord_)]
    return traef[0] if len(traef) == 1 else None


def opdater_fra_tur(session_id: str, tekst: str) -> bool:
    """Kaldes ved hver tur. Saetter emnet hvis brugeren naevner det.

    Returnerer True hvis emnet blev sat eller skiftet.
    """
    navn = signal_emne(tekst)
    if not navn:
        return False
    nu = hent_emne(session_id)
    if nu and nu[0] == navn:
        return False
    return saet_emne(session_id, navn)


def emne_sql(session_id: str):
    """Filter til konklusionssoegning: kun samme emnes viden.

    Intet emne = ingen filtrering mulig = intet svar. Hellere tomt end
    forkert, saa en fremmed model ikke faar boernesagen midt i en
    samtale om maanelandingen.
    """
    e = hent_emne(session_id)
    if not e:
        return None
    return e[0]


def selvtest() -> None:
    assert signal_emne("lad os snakke om Dios sag") == "dio"
    assert signal_emne("nu ser vi på docker") == "teknik"
    assert signal_emne("godmorgen hvad skal vi lave") is None
    assert signal_emne("Vodafone og Dios sag") is None, "flere traef = spoerg"
    print("selvtest: 4 kontroller bestaaet")


if __name__ == "__main__":
    import sys
    if "--test" in sys.argv:
        selvtest()
