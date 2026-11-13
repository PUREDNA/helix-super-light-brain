#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Broen — den der rejser kanterne.

    konklusion i hc.documents
          ↓  pivoter finder entiteter
    registeret slår op (register.py)
          ↓
    knude + kant i grafen 'hjerne'   —  og et bevis-niveau der kan forsvares

Den er deterministisk: der er ingen model i denne fil. Den kan køre i
baggrunden, og den kan køre igen — det den allerede har afgjort, springes over
(bro.koersel).

Brug (inde i containeren):

    /opt/hjerne/hcvenv/bin/python /opt/hjerne/enricher/bro.py --engangs --vis
    /opt/hjerne/hcvenv/bin/python /opt/hjerne/enricher/bro.py            # loekke

Intet i denne fil skriver til hc-skemaet. Den læser konklusionerne og skriver
kun i grafen og i sit eget skema.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
from pathlib import Path

try:
    import psycopg
except ImportError:  # pragma: no cover
    psycopg = None

sys.path.insert(0, str(Path(__file__).resolve().parent))
from register import (  # noqa: E402
    DOKUMENTERET, IKKE_DOKUMENTERET, KORTLAGT, PAASTAND, RANGO, Register, Svar,
)

GRAF = os.environ.get("GRAF", "hjerne")


# ------------------------------------------------------------------ AGE-hjaelpere
def esc(s) -> str:
    """Lav en tekst om til noget der kan staa i en Cypher-literal."""
    return str(s).replace("\\", "\\\\").replace("'", "\\'")


def _norm(s) -> str:
    """Normaliser et navn, saa registerets stavemaade matcher grafens.

    proff.dk skriver \"Abild/v.Sandra Abild\" (uden mellemrum), mens grafen
    har \"Abild/v. Sandra Abild\". Foer vi matcher, fjernes mellemrum omkring
    \"/\" og efter \".\", og alt lowercases — saa de to former bliver ens.
    """
    s = str(s or "").strip().lower()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"\s*/\s*", "/", s)
    s = re.sub(r"\.\s*", ".", s)
    return s


def _ag_val(r) -> str:
    """Hent en agtype-vaerdi ud (returneres som JSON-streng med quotes)."""
    import json as _json
    s = str(r)
    try:
        return str(_json.loads(s))
    except Exception:
        return s


def find_eksisterende(cur, etiket: str, navn: str,
                      ejer: str | None = None) -> str | None:
    """Returner det eksisterende navn der matcher normaliseret, ellers None.

    DNA 11. nov 2026: kun inden for SAMME ejer. Ellers landede Asgers personer
    paa DNA's knuder.
    """
    raekker = cypher(cur, f"MATCH (n:{etiket}) WHERE n.ejer = '{esc(ejer or '')}' RETURN n.navn")
    maal = _norm(navn)
    for (r,) in raekker:
        if _norm(_ag_val(r)) == maal:
            return _ag_val(r)
    return None


def cypher(cur, saetning: str, kolonner: str = "(v agtype)"):
    cur.execute(f"SELECT * FROM cypher('{GRAF}', $cy$ {saetning} $cy$) AS t{kolonner}")
    return cur.fetchall()


def sikr_knude(cur, etiket: str, navn: str, ejer: str | None = None, **egenskaber):
    """Findes knuden FOR DENNE EJER, bruges den. Ellers laves den.

    DNA 11. nov 2026: BRUGEROPDELING. Foer slog opslaget kun paa navn, saa
    Asgers personer landede paa DNA's knuder — hans sagsakter blev læst som
    DNA's egen viden. Nu er ejeren en del af noeglen: to brugere kan have
    hver sin "Hanne Simonsen" uden at de smelter sammen.
    """
    findes = cypher(cur, f"MATCH (n:{etiket} {{navn:'{esc(navn)}'}}) WHERE n.ejer = '{esc(ejer or '')}' RETURN n.navn")
    if findes:
        return
    par = "".join(f", {k}: '{esc(v)}'" for k, v in egenskaber.items() if v is not None)
    cypher(cur, f"CREATE (n:{etiket} {{navn:'{esc(navn)}', ejer:'{esc(ejer or '')}'{par}}}) RETURN n.navn")


def opdater_knude(cur, etiket: str, navn: str, **egenskaber):
    """Findes knuden FOR SAMME EJER, opdateres de givne egenskaber. Ellers laves den.

    Forskellen fra sikr_knude: registerdata (fx CVR-nummer på en Firma-node)
    skal LANDE på den eksisterende node — ikke lave en dobbelt der flyder løst.
    DNA 11. nov 2026: ejeren er en del af noeglen.
    """
    ejer = egenskaber.get("ejer") or ""
    findes = cypher(cur, f"MATCH (n:{etiket} {{navn:'{esc(navn)}'}}) WHERE n.ejer = '{esc(ejer)}' RETURN n.navn")
    if findes:
        sette = ", ".join(f"n.{k} = '{esc(v)}'" for k, v in egenskaber.items() if v is not None)
        if sette:
            cypher(cur, f"MATCH (n:{etiket} {{navn:'{esc(navn)}'}}) SET {sette}")
        return
    par = "".join(f", {k}: '{esc(v)}'" for k, v in egenskaber.items() if v is not None)
    cypher(cur, f"CREATE (n:{etiket} {{navn:'{esc(navn)}'{par}}}) RETURN n.navn")


def sikr_kant(cur, fra_etiket: str, fra_navn: str, kant: str,
              til_etiket: str, til_navn: str, ejer: str | None = None,
              **egenskaber):
    """Findes kanten, bruges den. Ellers laves den.

    DNA 11. nov 2026: kanten baerer ejeren, saa en brugers kanter ikke blandes
    med en andens. Oprydningen af gamle kanter sker i SQL (se oprydningsscript).

    Tjekket er ikke pynt. Uden det skrev broen en NY kant hver gang to
    konklusioner naevnte den samme entitet — grafen voksede med dubletter
    hver runde (maalt 2026-10-14: 201 dubletkanter, bl.a. tolv ens kanter fra
    'port:6120' til 'Maskinen'). Broen SKAL kunne koere igen uden at grafen
    gror; derfor tjekkes der foer der skrives.
    """
    findes = cypher(
        cur,
        f"MATCH (a:{fra_etiket} {{navn:'{esc(fra_navn)}', ejer:'{esc(ejer or '')}'}})-[r:{kant}]->"
        f"(b:{til_etiket} {{navn:'{esc(til_navn)}', ejer:'{esc(ejer or '')}'}}) "
        f"RETURN r LIMIT 1",
    )
    if findes:
        return
    par = "".join(f", {k}: '{esc(v)}'" for k, v in egenskaber.items() if v is not None)
    cypher(
        cur,
        f"MATCH (a:{fra_etiket} {{navn:'{esc(fra_navn)}', ejer:'{esc(ejer or '')}'}}), "
        f"(b:{til_etiket} {{navn:'{esc(til_navn)}', ejer:'{esc(ejer or '')}'}}) "
        f"CREATE (a)-[:{kant} {{{kant.lower()}: true, ejer:'{esc(ejer or '')}'{par}}}]->(b) RETURN 1",
    )


# ------------------------------------------------------------------------- loekken
def skema(cur):
    """Broens eget skema — laes fra filen ved siden af, saa der kun er een kilde."""
    sql = (Path(__file__).resolve().parent / "skema.sql").read_text(encoding="utf-8")
    cur.execute(sql)


try:
    from kategori import vaelg_kategori
except Exception:  # noqa: BLE001
    vaelg_kategori = None  # type: ignore


def hent_konklusioner(cur, graense: int) -> list[tuple]:
    # Lillehjernen har ingen HC (Honcho). HC er erstattet af konklusionsmotoren,
    # så broen læser konklusion-motorens egen tabel. Kolonnerne mappes til den
    # samme form som før, så resten af filen er uændret (DNA 2. nov 2026).
    cur.execute(
        """
        SELECT k.id::text, k.kilde_tekst, k.bevis, 'dna', 'dna',
               k.oprettet, '{}', k.ejer
          FROM konklusion k
         WHERE k.kilde_tekst IS NOT NULL
           AND length(k.kilde_tekst) > 3
           AND NOT EXISTS (SELECT 1 FROM bro.koersel b WHERE b.konklusion_id = k.id::text)
         ORDER BY k.oprettet
         LIMIT %s
        """,
        (graense,),
    )
    return cur.fetchall()


def afgoer(bevis_liste: list[str]) -> str:
    """Konklusionens bevis = det staerkeste af dens opslag. Modsigelse vinder:
    kan registeret pege paa at noget er forkert, skal det ikke skjules."""
    if not bevis_liste:
        return PAASTAND
    if IKKE_DOKUMENTERET in bevis_liste:
        return IKKE_DOKUMENTERET
    return max(bevis_liste, key=lambda b: RANGO.get(b, 0))


def koer_igennem(forbindelse, graense: int, vis: bool) -> dict:
    reg = Register(forbindelse)
    pivoter = reg.pivoter()
    tal = {"konklusioner": 0, "kanter": 0, "dokumenteret": 0,
           "kortlagt": 0, "afkraeftet": 0, "paastand": 0}

    with forbindelse.cursor() as cur:
        skema(cur)
    forbindelse.commit()

    while True:
        with forbindelse.cursor() as cur:
            raekker = hent_konklusioner(cur, graense)
        if not raekker:
            break

        for kid, tekst, niveau, observer, observed, skabt, meta, ejer in raekker:
            # DNA 2026-10-18: SAMTALER SKAL IKKE IND I GRAFEN.
            # Alt andet gaar igennem som foer; kun kategori "Samtalen" springes over.
            try:
                if tekst and vaelg_kategori(tekst)[0] == "Samtalen":
                    with forbindelse.cursor() as cur:
                        try:
                            cur.execute("INSERT INTO bro.koersel (konklusion_id) VALUES (%s) ON CONFLICT DO NOTHING", (kid,))
                            forbindelse.commit()
                        except Exception:
                            forbindelse.rollback()
                    continue
            except Exception:
                pass
            entiteter: list[tuple[str, str, object]] = []
            for p in pivoter:
                for navn in dict.fromkeys(p.find(tekst)):     # unik, raekkefoelge bevaret
                    svar = p.opslag(navn)
                    entiteter.append((navn, p.slags, svar))

            for navn, svar in reg.tjek_roller(tekst):
                entiteter.append((navn, "Person", svar))
            bevis = afgoer([s.bevis for _, _, s in entiteter])

            with forbindelse.cursor() as cur:
                cur.execute("LOAD 'age'")
                cur.execute("SET search_path = ag_catalog, \"$user\", public")
                # DNA 3. nov 2026: konklusioner skal IKKE være egne knuder i grafen.
                # 426 konklusioner fyldte halvdelen af skaermen og gjorde grafen
                # ubrugelig. Nu samles de paa ÉT punkt, "Konklusioner", som man kan
                # slukke for i vieweren. Viden er ikke vaek — den ligger stadig i
                # hjerne.konklusion og kan findes med den semantiske soegning.
                sikr_knude(cur, "Konklusioner", "samlet", ejer=ejer, tekst="Konklusioner",
                           niveau=niveau, bevis=bevis, observer=observer)
                sikr_kant(cur, "Konklusioner", "samlet", "INDEHOLDER",
                          "Konklusion", kid, tekst=tekst[:200])
                for navn, slags, svar in entiteter:
                    sikr_knude(cur, "Register", svar.register, ejer=ejer, slags="opslag")
                    # Et opslag der kender sit kanoniske navn og sin etiket
                    # (fx CVR → "Firma" med firmanavnet) skal lande på den
                    # EKSISTERENDE node, ikke lave en dobbelt. Ellers bruges
                    # den generiske Entitet-node som før.
                    if svar.etiket and svar.navn:
                        knude_etiket = svar.etiket
                        # Matcher den eksisterende node på normaliseret navn,
                        # så "Abild/v.Sandra Abild" lander på grafens
                        # "Abild/v. Sandra Abild" i stedet for at lave en dobbelt.
                        fundet = find_eksisterende(cur, knude_etiket, svar.navn, ejer)
                        knude_navn = fundet if fundet else svar.navn
                        egenskaber = {"bevis": svar.bevis, "slags": slags,
                                      "cvr": navn}
                    else:
                        knude_etiket = "Entitet"
                        knude_navn = f"{slags.lower()}:{navn}"
                        egenskaber = {"entitet": navn, "slags": slags,
                                      "bevis": svar.bevis}
                    egenskaber["ejer"] = ejer or ""
                    opdater_knude(cur, knude_etiket, knude_navn, **egenskaber)
                    # DNA 11. nov 2026: Konklusion-knuden skal BAERE ejeren.
                    # Foer blev den lavet implicit af kanten, og saa manglede
                    # ejer-feltet — opslaget paa ejer ramte ingenting.
                    sikr_knude(cur, "Konklusion", kid, ejer=ejer, tekst=tekst[:200])
                    sikr_kant(cur, "Konklusion", kid, "NÆVNER", knude_etiket,
                              knude_navn, ejer=ejer)
                    sikr_kant(cur, "Konklusion", kid,
                              {DOKUMENTERET: "BEKRÆFTET_I",
                               IKKE_DOKUMENTERET: "AFKRÆFTET_I"}.get(svar.bevis, "STILLE_I"),
                              knude_etiket, knude_navn, ejer=ejer)
                    sikr_kant(cur, knude_etiket, knude_navn,
                              "OPSLÅET_I", "Register", svar.register,
                              ejer=ejer, kilde=svar.kilde[:300])
                    cur.execute(
                        """INSERT INTO bro.entitet (navn, slags, register, bevis, kilde)
                           VALUES (%s,%s,%s,%s,%s)
                           ON CONFLICT (navn, slags) DO UPDATE
                             SET bevis = EXCLUDED.bevis, kilde = EXCLUDED.kilde,
                                 sidste = now()""",
                        (navn, slags, svar.register, svar.bevis, svar.kilde[:300]),
                    )
                cur.execute(
                    """INSERT INTO bro.koersel (konklusion_id, niveau, bevis,
                                               entiteter, kanter, resultat)
                       VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (konklusion_id) DO NOTHING""",
                    (kid, niveau, bevis, len(entiteter), len(entiteter) * 3,
                     f"{len(entiteter)} entiteter"),
                )
            forbindelse.commit()

            tal["konklusioner"] += 1
            tal["kanter"] += len(entiteter) * 3
            if bevis == DOKUMENTERET:
                tal["dokumenteret"] += 1
            elif bevis == IKKE_DOKUMENTERET:
                tal["afkraeftet"] += 1
            elif bevis == KORTLAGT:
                tal["kortlagt"] += 1
            else:
                tal["paastand"] += 1

            if vis:
                mærke = {DOKUMENTERET: "DOKUMENTERET", KORTLAGT: "KORTLAGT",
                         IKKE_DOKUMENTERET: "AFKRÆFTET", PAASTAND: "PÅSTAND"}.get(
                             bevis, bevis)
                print(f"  [{mærke:<12}] {tekst[:64]!r}  ({len(entiteter)} entiteter)")

        if vis:
            print(f"  ... {tal['konklusioner']} konklusioner, {tal['kanter']} kanter")

    return tal


def main() -> int:
    ap = argparse.ArgumentParser(description="Broen — konklusion → register → kant")
    ap.add_argument("--engangs", action="store_true", help="koer én gang og stop")
    ap.add_argument("--vis", action="store_true", help="skriv hvad der sker")
    ap.add_argument("--parti", type=int, default=100, help="hvor mange ad gangen")
    ap.add_argument("--soevn", type=int, default=60, help="sekunder mellem runder")
    ap.add_argument("--katalog", action="store_true", help="vis registeret og stop")
    a = ap.parse_args()

    if a.katalog:
        print("Registeret kan slaa op:")
        print(Register().beskriv_catalog())
        return 0

    if psycopg is None:
        print("psycopg mangler i dette miljoe", file=sys.stderr)
        return 2

    dsn = (f"host=127.0.0.1 port=5432 dbname={os.environ.get('POSTGRES_DB', 'hjerne')} "
           f"user={os.environ.get('POSTGRES_USER', 'hjerne')} "
           f"password={os.environ.get('POSTGRES_PASSWORD', '')}")

    print(f"[bro] grafen '{GRAF}' — registeret: "
          + ", ".join(p.navn for p in Register().pivoter()))

    # Hændelsesstyret (DNA 2. nov 2026): broen skal IKKE vågne hvert minut.
    # Den lytter på 'ny_konklusion', som motoren sender via NOTIFY i samme
    # sekund en konklusion lander. Er der intet nyt, står den stille på en
    # ventende forbindelse og bruger nul CPU. 'select(60)' er kun en
    # sikkerhedsventil, ikke en rytme: kommer der ingen besked, tjekker den
    # alligevel en gang i minuttet i tilfælde af tabt forbindelse.
    while True:
        try:
            with psycopg.connect(dsn, autocommit=True) as lyt:
                lyt.execute("LISTEN ny_konklusion")
                while True:
                    # DNA 2026-11-13: autocommit paa forbindelsen.
                    # Foer aabnede en SELECT en transaktion der blev haengende i
                    # "idle in transaction" hvis noget gik galt midt i. En
                    # saadan laas blokerede hele tabellen i 28 minutter, saa
                    # hverken motoren eller en ALTER TABLE kom igennem.
                    # Broen laeser og skriver i enkelte saetninger — den har
                    # ikke brug for en samlet transaktion.
                    with psycopg.connect(dsn, autocommit=True) as fb:
                        tal = koer_igennem(fb, a.parti, a.vis)
                    if a.engangs:
                        print(f"[bro] faerdig: {tal}")
                        return 0
                    if tal["konklusioner"]:
                        print(f"[bro] runde: {tal}", flush=True)
                    # Vent på NOTIFY. Timeout er kun en ventil, ikke en rytme.
                    lyt.execute("SELECT 1")
                    lyt.notifies(timeout=a.soevn, stop_after=1)
        except Exception as fejl:
            print(f"[bro] fejl: {type(fejl).__name__}: {fejl}", file=sys.stderr)
            if a.engangs:
                return 1
            time.sleep(5)
            continue


if __name__ == "__main__":
    raise SystemExit(main())