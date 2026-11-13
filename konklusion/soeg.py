#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Semantisk søgning i konklusionerne.

DNA 3. nov 2026: uden dette fik jeg de otte NYESTE konklusioner, uanset hvad
vi talte om. Nu finder vi de otte der LIGNER det der bliver spurgt om.

Sådan virker det:
  1. bge-m3 oversætter hver konklusion til 1024 tal (én gang, når den er ny)
  2. et spørgsmål oversættes til 1024 tal på samme måde
  3. de konklusioner hvis tal ligger nærmest, er de mest relevante

Skriver intet andet end vektoren på konklusionen.
"""
from __future__ import annotations

import json
import os
import urllib.request

DSN = os.environ.get(
    "KONKLUSION_DSN",
    "host=127.0.0.1 port=5432 dbname=hjerne user=hjerne password=skift-mig",
)
OLLAMA = os.environ.get("EMBEDDING_BASE_URL", "http://127.0.0.1:11434")
MODEL = os.environ.get("EMBEDDING_MODEL", "bge-m3")
DIM = 1024


def vektor(tekst: str, timeout: int = 20) -> list[float] | None:
    """Oversæt tekst til 1024 tal med bge-m3. None hvis den ikke svarer."""
    if not tekst or not tekst.strip():
        return None
    try:
        krop = json.dumps({"model": MODEL, "prompt": tekst[:2000]}).encode()
        req = urllib.request.Request(
            OLLAMA + "/api/embeddings", data=krop,
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read())
        v = d.get("embedding") or []
        return v if len(v) == DIM else None
    except Exception as e:  # noqa: BLE001
        print(f"[soeg] bge-m3 svarede ikke: {e}", flush=True)
        return None


def sikr_skema(con):
    """Kolonner og indekser til de tre søgespor. Kører hver gang — billigt.

    DNA 2026-11-08 (hybrid): ud over vektoren skal der være en dansk
    fuldtekst-kolonne (ordstammer) og en normaliseret tekst til trigram.
    Begge udfyldes af en trigger, så de aldrig kan komme ud af trit med
    rækken — der er ingen kode der skal huske at opdatere dem.
    """
    with con.cursor() as cur:
        cur.execute(f"ALTER TABLE konklusion ADD COLUMN IF NOT EXISTS vektor vector({DIM})")
        cur.execute("""
            CREATE INDEX IF NOT EXISTS konklusion_vektor_idx
            ON konklusion USING hnsw (vektor vector_cosine_ops)
        """)
        # Fuldtekst: dansk ordstamme over emne, egenskab og værdi.
        cur.execute("""
            ALTER TABLE konklusion ADD COLUMN IF NOT EXISTS soege_tsv tsvector
            GENERATED ALWAYS AS (
                to_tsvector('danish',
                    coalesce(emne,'') || ' ' || coalesce(egenskab,'') || ' '
                    || coalesce(vaerdi,''))
            ) STORED
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS konklusion_tsv_idx
            ON konklusion USING gin (soege_tsv)
        """)
        # Trigram: samme tekst, men til stavefejl og felthørte navne.
        cur.execute("""
            ALTER TABLE konklusion ADD COLUMN IF NOT EXISTS soege_tekst text
            GENERATED ALWAYS AS (
                coalesce(emne,'') || ' ' || coalesce(egenskab,'') || ' '
                || coalesce(vaerdi,'')
            ) STORED
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS konklusion_trgm_idx
            ON konklusion USING gin (soege_tekst gin_trgm_ops)
        """)
        con.commit()


def indekser(con, graense: int = 500, parti: int = 25) -> int:
    """Giv vektorer til konklusioner der mangler. Returnerer antallet.

    Ét kald pr. konklusion tog over et minut i alt fordi Ollama skal svare
    hver gang. Her sendes de i portioner, og der skrives efter hver portion,
    så et afbrudt gennemløb ikke starter forfra (DNA 3. nov 2026).
    """
    with con.cursor() as cur:
        cur.execute("""
            SELECT id, emne || ' ' || egenskab || ' ' || coalesce(vaerdi, '')
            FROM konklusion
            WHERE vektor IS NULL
            ORDER BY oprettet DESC
            LIMIT %s
        """, (graense,))
        raekker = cur.fetchall()

    n = 0
    for i in range(0, len(raekker), parti):
        portion = raekker[i:i + parti]
        opdateringer = []
        for kid, tekst in portion:
            v = vektor(tekst)
            if v:
                opdateringer.append(
                    ("[" + ",".join(f"{x:.6f}" for x in v) + "]", kid))
        if not opdateringer:
            continue
        with con.cursor() as cur:
            for vlit, kid in opdateringer:
                cur.execute("UPDATE konklusion SET vektor = %s::vector WHERE id = %s",
                            (vlit, kid))
        con.commit()
        n += len(opdateringer)
        print(f"[soeg] {n}/{len(raekker)} indekseret", flush=True)
    return n


def soeg(con, spoergsmaal: str, antal: int = 8, ejer: str | None = None) -> list[dict]:
    """Find de konklusioner der svarer på spørgsmålet — tre spor, ikke ét.

    DNA 2026-11-08 (hybrid): vektor alene taber på navne og tal, fordi
    bge-m3 lægger en hel sætning i 1024 tal og «Børnene» og «Børn» ender
    langt fra hinanden. Derfor tre spor i SAMME tabel (ingen nye systemer):

      1. vektor  — betydning (HNSW, cosinus)
      2. ord     — tsvector, dansk ordstamme: rammer navne og præcise ord
      3. trigram — pg_trgm: rammer stavefejl og felthørte navne

    Sporene lægges sammen med reciprocal rank fusion (RRF), som Zep og
    HippoRAG gør det: hver række får 1/(60+placering) pr. spor den er med i.
    Det er rang-baseret, så et spor med mange hits kan ikke overdøve de andre.
    Kilder: Zep (arXiv 2501.13956), HippoRAG (arXiv 2405.14831).
    """
    spoergsmaal = (spoergsmaal or "").strip()
    if not spoergsmaal:
        return []
    # DNA 2026-11-08 (SKRALD-FILTER): «Neo | bruge | værktøjer» er en rigtig
    # konklusion fra en rigtig sætning, men den svarer ikke på «Nikolaj Vinter».
    # En række hvis EMNE intet ord deler med spørgsmålet droppes — undtagen når
    # vektor-sporet alene finder den (så betydning kan stadig vinde over ord).
    _ord = [w for w in _normaliser(spoergsmaal).split() if len(w) > 1]
    ejer_sql = " AND (ejer = %s OR ejer IS NULL)" if ejer else ""
    ejer_par = [ejer] if ejer else []
    K = 60          # RRF-dæmpning (standard i litteraturen)
    PER_SPOR = max(antal * 6, 30)

    # ---- spor 1: vektor -------------------------------------------------
    v = vektor(spoergsmaal)
    if v:
        vlit = "[" + ",".join(f"{x:.6f}" for x in v) + "]"
        sql_v = f"""
            SELECT id, 1 - (vektor <=> %s::vector) AS lighed
            FROM konklusion
            WHERE vektor IS NOT NULL AND ugyldig = false{ejer_sql}
            ORDER BY vektor <=> %s::vector
            LIMIT %s
        """
        spor_v = [(r[0], r[1]) for r in _k(con, sql_v, [vlit] + ejer_par + [vlit, PER_SPOR])]
        # Ligheværdien gemmes: RRF kaster scoren væk og beholder kun rækkefølgen,
        # så uden den kan vi ikke se om «nærmeste af 70.000» er et rigtigt træf.
        _lighed = {kid: float(s) for kid, s in spor_v}
    else:
        spor_v = []
        _lighed = {}

    # ---- spor 2: dansk fuldtekst (ordstammer) ---------------------------
    # Hele spørgsmålet FØRST (AND), så «børn samvær» ikke giver rækker der kun
    # deler ét ord. Giver det intet, løsnes det til ENHVER (OR) — ellers ville
    # et spørgsmål om to ting ikke kunne finde en konklusion om den ene.
    sql_o_and = f"""
        SELECT id, ts_rank_cd(soege_tsv, q) AS rang
        FROM konklusion, plainto_tsquery('danish', %s) q
        WHERE soege_tsv @@ q AND ugyldig = false{ejer_sql}
        ORDER BY rang DESC
        LIMIT %s
    """
    sql_o_or = f"""
        SELECT id, ts_rank_cd(soege_tsv, q) AS rang
        FROM konklusion, to_tsquery('danish', %s) q
        WHERE soege_tsv @@ q AND ugyldig = false{ejer_sql}
        ORDER BY rang DESC
        LIMIT %s
    """
    spor_o = _k(con, sql_o_and, [spoergsmaal] + ejer_par + [PER_SPOR])
    if not spor_o:
        # plainto_tsquery binder ordene med AND; to_tsquery med | giver OR.
        _eller = " | ".join(_ord) if _ord else ""
        if _eller:
            spor_o = _k(con, sql_o_or, [_eller] + ejer_par + [PER_SPOR])

    # ---- spor 3: trigram (stavefejl, felthørte navne) -------------------
    # Sammenlign ORD for ORD, ikke hele sætningen mod hele sætningen:
    # «børn samvær» skal ramme «Børn | vurdere | samvær Dio», og det gør
    # similarity() på hele strengen ikke (den måler tegnrækkefølge).
    # Kun rækker hvis EMNE deler et ord med spørgsmålet kommer i betragtning,
    # og similarity() måler så ord mod ord. Det holder søgningen på emnets
    # 4.340 rækker i stedet for at trigramme hele tabellen igennem.
    sql_t = f"""
        WITH emner AS (
            SELECT DISTINCT emne FROM konklusion
            WHERE emne %% ANY(%s::text[]) AND ugyldig = false{ejer_sql}
            LIMIT 400
        )
        SELECT k.id, max(similarity(ord, k.emne)) AS lighed
        FROM konklusion k
        JOIN emner e ON e.emne = k.emne,
             unnest(%s::text[]) AS ord
        WHERE k.ugyldig = false
        GROUP BY k.id
        HAVING max(similarity(ord, k.emne)) > 0.4
        ORDER BY lighed DESC
        LIMIT %s
    """
    spor_t = _k(con, sql_t, [_ord] + ejer_par + [_ord, PER_SPOR])

    # ---- fusion (RRF) ---------------------------------------------------
    point: dict = {}
    for spor in (spor_v, spor_o, spor_t):
        for plads, (kid, _score) in enumerate(spor, start=1):
            point[kid] = point.get(kid, 0.0) + 1.0 / (K + plads)
    if not point:
        return []
    # ---- skrald-filter ---------------------------------------------------
    _v_ids = {k for k, _ in spor_v}
    _ord_maengde = set(_ord)
    bedste = sorted(point.items(), key=lambda x: -x[1])[:max(antal * 4, 40)]

    # ---- hent rækkerne én gang, med kilden ---------------------------------
    with con.cursor() as cur:
        cur.execute("""
            SELECT id, emne, egenskab, coalesce(vaerdi, ''), bevis,
                   coalesce(kilde_tekst, ''), coalesce(dokument, ''),
                   side_vores, coalesce(taler, '')
            FROM konklusion WHERE id = ANY(%s)
        """, ([k for k, _ in bedste],))
        raekker = {r[0]: r for r in cur.fetchall()}

    def _brugbart_emne(r) -> bool:
        return _normaliser(r[1]).strip() not in _TOMME_EMNER

    def _ordret(r) -> bool:
        """Står spørgsmålets ord ORDRET i den sætning rækken kom fra?

        Målt 2026-11-08: «born}}Agter» kom med på et trigram-hit, men kilden
        siger «... born}}Agter til sag ang. ...». Rækken ER korrekt udledt —
        det er PDF-tekstens skrald der står i emnet. Vi viser den derfor kun
        når dens KILDE faktisk indeholder ordene, så svaret kan efterprøves.
        """
        tekst = _normaliser(r[5])
        return all(o in tekst.split() for o in _ord_maengde)

    def _deler_ord(r) -> bool:
        # KUN emnet tælles. Målt 2026-11-08: «born}}Agter | siger» slap igennem,
        # fordi «samvær» stod i værdien — men emnet var volapyk, og rækken
        # svarer ikke på spørgsmålet. Emnet er det rækken handler om.
        return bool(_ord_maengde & set(_normaliser(r[1]).split()))

    # Rækkefølgen er fast: ordret i kilden → deler ord med emnet → vektoren.
    valgt = [(k, p) for k, p in bedste
             if k in raekker and _brugbart_emne(raekker[k])
             and _ordret(raekker[k])][:antal]
    if not valgt:
        valgt = [(k, p) for k, p in bedste
                 if k in raekker and _brugbart_emne(raekker[k])
                 and _deler_ord(raekker[k])][:antal]
    if not valgt:
        # Intet ord-match. Så er spørgsmålet enten om noget vi intet ved om
        # (så SIGER vi det — afholdenhed, ikke skrald), eller det rammes kun af
        # betydningen. Vi lukker først op for de brede rækker (Danny/Dio/Ukendt)
        # når der ikke findes ét brugbart emne blandt kandidaterne.
        #
        # DNA 2026-11-08 (LILLE MODEL): et tomt svar er dyrt — 9B-modellen har
        # ikke viden nok i sig selv til at dække hullet, så den fylder det ud
        # med gæt. Vektoren er et rigtigt træf når ligheden er over _VEKTOR_GULV;
        # under det er den bare den nærmeste af 70.000 og skal kastes væk.
        _naer = [(k, r[1]) for k, _p in bedste
                 if k in raekker and (r := raekker[k]) and _brugbart_emne(r)]
        _trufne = {kid for kid, _s in spor_v}
        _staerk = [(k, p) for k, p in bedste
                   if k in _trufne and k in raekker
                   and _brugbart_emne(raekker[k])
                   and _lighed[k] >= _VEKTOR_GULV]
        if _staerk:
            valgt = _staerk[:antal]
        elif _naer:
            return []
        else:
            valgt = [(k, p) for k, p in bedste if k in raekker][:antal]
    # ENS RÆKKE ÉN GANG (målt 2026-11-08): samme konklusion kan optræde flere
    # gange i basen (ulige store mellemrum i nøglen), og den blev vist 4 gange.
    set_ = set()
    unikke = []
    for k, p in valgt:
        r = raekker[k]
        noegle = (r[1], r[2], r[3])
        if noegle in set_:
            continue
        set_.add(noegle)
        unikke.append((k, p))
    bedste = unikke
    ids = [k for k, _ in bedste]

    # ---- hent rækkerne én gang, med kilden ---------------------------------
    with con.cursor() as cur:
        cur.execute("""
            SELECT id, emne, egenskab, coalesce(vaerdi, ''), bevis,
                   coalesce(kilde_tekst, ''), coalesce(dokument, ''),
                   side_vores, coalesce(taler, ''), coalesce(laert::text, '')
            FROM konklusion WHERE id = ANY(%s)
        """, (ids,))
        raekker = {r[0]: r for r in cur.fetchall()}
    ud = []
    for kid, p in bedste:
        r = raekker.get(kid)
        if not r:
            continue
        ud.append({"emne": r[1], "egenskab": r[2], "vaerdi": r[3],
                   "bevis": r[4], "kilde_tekst": r[5], "dokument": r[6],
                   "side": r[7], "taler": r[8], "laert": r[9],
                   "score": round(p, 4)})

    return _kun_gældende(con, ud)


# DNA 2026-11-13: VÆGTEN AFGØR FØRST — VED LIGE VÆGT VINDER DEN NYESTE.
# MÅLT (5) > FØRSTEHÅNDS (4) > DOKUMENTERET (3) > ANDENHÅNDS (2) > SAGT (1).
#
# FØRSTEHÅNDS ER OVER DOKUMENTERET. Det er DNA's egne ord om sig selv — de
# kan ikke bevises af andre, men kan heller ikke afvises af et dokument. Siger
# han at han er flyttet, gælder det, uanset hvad en gammel sagsakt siger.
# (Motorens bevisgradsfunktion har samme orden; se motor.py.)
_VÆGT = {"MAALT": 5, "FOERSTEHAANDS": 4, "DOKUMENTERET": 3,
         "ANDENHAANDS": 2, "SAGT": 1}


def _kun_gældende(con, ud: list[dict]) -> list[dict]:
    """Fjern rækker der er overhalet af en stærkere eller nyere konklusion."""
    if len(ud) < 2:
        return ud

    from importlib import util as _u
    _p = "/opt/lillehjerne/drom/drom.py"
    _s = _u.spec_from_file_location("drom_mod", _p)
    _m = _u.module_from_spec(_s)
    _s.loader.exec_module(_m)
    _noegle, _tal = _m._noegle, _m._tal

    # Samme nøgle + samme tal = samme udsagn. Er tallene forskellige, handler
    # det om samme emne med forskelligt svar — så skal kun ét med.
    grupper: dict[str, list[dict]] = {}
    for k in ud:
        n = _noegle(k.get("kilde_tekst") or "")
        if n:
            grupper.setdefault(n, []).append(k)

    overhalet: set = set()
    for n, raekker in grupper.items():
        if len(raekker) < 2:
            continue
        # Er der uenighed om et tal, er det en ægte konflikt.
        alle_tal = {t for r in raekker for t in _tal(r.get("kilde_tekst") or "")}
        if len(alle_tal) < 2:
            continue

        def rang(r):
            vaegt = _VÆGT.get((r.get("bevis") or "").upper(), 1)
            return (vaegt, str(r.get("laert") or ""))

        vinder = max(raekker, key=rang)
        for r in raekker:
            if r is not vinder:
                overhalet.add(r.get("kilde_tekst"))

    return [k for k in ud if k.get("kilde_tekst") not in overhalet]


# Emner der ikke kan bruges som opslag (målt 2026-11-08): «Ukendt | siger»
# fylder i hvert eneste resultat. De udelades KUN som emne-match; rækkerne
# bliver liggende og kan stadig rammes af vektoren eller af et rigtigt emne.
# DNA 2026-11-13: konstanten blev brugt men var aldrig defineret — hvert soeg
# kastede NameError og faldt tilbage til "de nyeste", saa hukommelsen gav
# tilfaeldige gamle raekker i stedet for relevante. 0.62 er samme gulv som
# vektorsoegningen bruger andre steder i lillehjernen.
_VEKTOR_GULV = 0.62

_TOMME_EMNER = {
    "ukendt", "det", "vi", "han", "hun", "du", "jeg", "dette", "den", "de",
    "man", "vi", "dem", "os", "sig", "der", "her", "så", "og", "men",
}


def _normaliser(tekst: str) -> str:
    """Små bogstaver og æ/ø/å skrevet om, så ord kan sammenlignes."""
    tekst = (tekst or "").lower()
    for a, b in (("æ", "ae"), ("ø", "o"), ("å", "aa"), ("é", "e")):
        tekst = tekst.replace(a, b)
    return "".join(c if (c.isalnum() or c.isspace()) else " " for c in tekst)


def _k(con, sql: str, par: list) -> list:
    """Kør ét spor. Et manglende indeks må ikke vælte hele søgningen."""
    try:
        with con.cursor() as cur:
            cur.execute(sql, par)
            return [(r[0], float(r[1] or 0)) for r in cur.fetchall()]
    except Exception as e:  # noqa: BLE001
        print(f"[soeg] spor fejlede ({e}) — de andre kører videre", flush=True)
        return []


# ---------------------------------------------------------------- selvtest
def _selvtest():
    import psycopg
    con = psycopg.connect(DSN, autocommit=True)
    sikr_skema(con)
    nye = indekser(con, 50)
    print(f"indekseret: {nye}")

    for spoergsmaal in ("børnesagen om Dio", "hvilken bil kører Danny", "hvilken port"):
        print(f"\nSPØRGSMÅL: {spoergsmaal}")
        for t in soeg(con, spoergsmaal, 3):
            print(f"  [{t['lighed']}] {t['emne']} · {t['egenskab']} = {t['vaerdi'][:40]}")
    con.close()


if __name__ == "__main__":
    _selvtest()
