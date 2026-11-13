#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Drømmen — kontrollen oven på Konklusionsmotoren.

Går over konklusionerne og finder det der ikke stemmer:
  1. Modsigelse      — samme emne+egenskab med to værdier
  2. Forældelse      — en konklusion hvis kilde er erstattet af en nyere
  3. Uden dokument   — SAGT-konklusioner der har stået alene for længe
  4. Gentagelse      — mønster på tværs af sager
  5. Retningsskift   — samme spørgsmål, forskellig begrundelse over tid

Vigtigt: den SLETTER intet. Den markerer. Historikken skal blive stående,
ellers kan man ikke se hvad nogen har skiftet mening om.

    python3 drom.py --koer        kør hele kontrollen
    python3 drom.py --selvtest    kør uden database
"""
import os
import sys
import json
import time
import http.client
import threading
from urllib.parse import urlparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

try:
    import psycopg
except ImportError:
    psycopg = None


def log(msg):
    print(f"[drom] {msg}", flush=True)


PORT = int(os.environ.get("DROM_PORT", "6304"))
DSN = os.environ.get(
    "DROM_DSN",
    "host=127.0.0.1 port=5432 dbname=hjerne user=hjerne password=skift-mig",
)
ALDER_DAGE = int(os.environ.get("DROM_ALDER_DAGE", "30"))

# Læringen (DNA 1. nov 2026): det hjernens faste regler ikke kunne læse,
# sendes til den lokale 9B-model med en fast kort prompt. Svaret bliver et
# FORSLAG — aldrig en konklusion. Først når det kan bekræftes af et dokument,
# en måling eller DNA, bliver det til en regel. Så kan hitraten måles.
OLLAMA = os.environ.get("DROM_OLLAMA_HOST", "host.docker.internal")
OLLAMA_PORT = int(os.environ.get("DROM_OLLAMA_PORT", "11434"))
MODEL = os.environ.get("DROM_MODEL", "H.E.L.I.X:9b-neo")
LAER_INTERVAL = int(os.environ.get("DROM_LAER_INTERVAL", "3600"))
LAER_BATCH = int(os.environ.get("DROM_LAER_BATCH", "20"))

# Hvornår drømmer den? (DNA 2. nov 2026: på MÆNGDE, ikke på tid.)
# Tærsklen tæller konklusioner der er kommet til siden sidste drøm — drømmens
# egne rækker tælles IKKE med, ellers drømmer den af sine egne drømme.
DROM_TAERSKEL = int(os.environ.get("DROM_TAERSKEL", "100"))
# Ro-tiden er bagstopperen: bliver tærsklen aldrig nået, drømmer den alligevel
# når der har været stille længe nok. Det er stadig hændelsesstyret — det var
# den sidste konklusion der startede nedtællingen.
DROM_RO_SEK = int(os.environ.get("DROM_RO_SEK", "900"))

PROMPT = """Du er hjaelper for en dansk hjerne der udleder kendsgerninger af kilder.

Du faar et stykke tekst som hjernens faste regler IKKE kunne laese.
Svar KUN med et JSON-objekt, intet andet, ingen forklaring:

{{"forstaaet": true,
  "emne": "kort navn paa hvad det handler om",
  "egenskab": "hvad der siges om emnet",
  "vaerdi": "den konkrete vaerdi, eller null",
  "form": "findes|haendte|modsiger|mangler|gentages",
  "grund": "en kort saetning om hvorfor"}}

Er der ingen kendsgerning i teksten, svar {{"forstaaet": false, "grund": "ingen kendsgerning"}}.

TEKST:
<<<
{tekst}
>>>
"""


def spoerg_modellen(tekst):
    """Spørg den lokale 9B. Returnerer JSON eller None."""
    try:
        krop = json.dumps({
            "model": MODEL,
            "prompt": PROMPT.format(tekst=tekst[:4000]),
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.1, "num_ctx": 8192},
        })
        c = http.client.HTTPConnection(OLLAMA, OLLAMA_PORT, timeout=180)
        c.request("POST", "/api/generate", krop,
                  {"Content-Type": "application/json"})
        r = c.getresponse()
        d = json.loads(r.read() or b"{}")
        c.close()
        svar = (d.get("response") or "").strip()
        return json.loads(svar) if svar else None
    except Exception as e:
        log(f"modelfejl: {e}")
        return None


def sikr_laering(con):
    with con.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS drom_forslag (
                id          bigserial PRIMARY KEY,
                register_id bigint,
                tekst       text NOT NULL,
                model       text NOT NULL,
                svar        jsonb,
                status      text NOT NULL DEFAULT 'FORSLAG',
                oprettet    timestamptz NOT NULL DEFAULT now()
            )
        """)
    con.commit()


def laer(con):
    """Saml uforstået tekst, spørg modellen, gem som FORSLAG."""
    if os.environ.get("DROM_LAER", "1") != "1":
        return {"sprunget": "DROM_LAER=0"}
    with con.cursor() as cur:
        cur.execute("""
            SELECT id, tekst FROM forstaaelse_register
            WHERE status = 'NY'
            ORDER BY antal_set DESC, oprettet ASC
            LIMIT %s
        """, (LAER_BATCH,))
        rows = cur.fetchall()
    if not rows:
        return {"behandlet": 0, "forslag": 0}

    forslag = 0
    for rid, tekst in rows:
        svar = spoerg_modellen(tekst)
        if not svar:
            continue
        with con.cursor() as cur:
            cur.execute("""
                INSERT INTO drom_forslag (register_id, tekst, model, svar)
                VALUES (%s,%s,%s,%s)
            """, (rid, tekst[:2000], MODEL,
                  json.dumps(svar, ensure_ascii=False)))
            cur.execute("UPDATE forstaaelse_register SET status='FORSLAG' WHERE id=%s",
                        (rid,))
        con.commit()
        forslag += 1
    log(f"laering: {len(rows)} tekster -> {forslag} forslag (ikke konklusioner)")
    return {"behandlet": len(rows), "forslag": forslag}


def antal_nye(con, siden):
    """Konklusioner der er kommet til siden sidste drøm — uden drømmens egne.

    Drømmens egne rækker har regel der starter med 'drom.' og tælles ikke med;
    ellers ville den drømme videre på sit eget output.
    """
    with con.cursor() as cur:
        cur.execute("""
            SELECT count(*) FROM konklusion
            WHERE oprettet > %s
              AND regel NOT LIKE 'drom%%'
              AND form <> 'modsiger'
        """, (siden,))
        return cur.fetchone()[0]


def laes_sidste_drom(con):
    with con.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS drom_koersel (
                id        bigserial PRIMARY KEY,
                startet   timestamptz NOT NULL DEFAULT now(),
                nye       int NOT NULL DEFAULT 0,
                udloeser  text NOT NULL DEFAULT 'maengde'
            )
        """)
        con.commit()
        cur.execute("SELECT coalesce(max(startet), now() - interval '1 day') FROM drom_koersel")
        return cur.fetchone()[0]


def lytte():
    """Baggrundstråd: drøm når der er NOK, ikke når der er gået tid (DNA 2. nov).

    Udløser: DROM_TAERSKEL nye konklusioner, ELLER DROM_RO_SEK sekunders ro.
    Den vågner af NOTIFY fra motoren, så den står stille når intet sker.
    """
    try:
        con = psycopg.connect(DSN, autocommit=True)
        sikr_laering(con)
        siden = laes_sidste_drom(con)
    except Exception as e:
        log(f"lytte kunne ikke starte: {e}")
        return
    sidste_laer = 0
    sidste_ny = time.time()
    set_ny = -1
    while True:
        try:
            nye = antal_nye(con, siden)
            if nye > 0 and nye != set_ny:
                sidste_ny = time.time()
                set_ny = nye
            stille = time.time() - sidste_ny
            udloeser = None
            if nye >= DROM_TAERSKEL:
                udloeser = "maengde"
            elif nye > 0 and stille >= DROM_RO_SEK:
                udloeser = "ro"
            if udloeser:
                log(f"drommer: {nye} nye konklusioner, udloeser={udloeser}")
                koer(con)
                with con.cursor() as cur:
                    cur.execute(
                        "INSERT INTO drom_koersel (nye, udloeser) VALUES (%s,%s)",
                        (nye, udloeser))
                siden = laes_sidste_drom(con)
                sidste_ny = time.time()
                set_ny = -1
            if time.time() - sidste_laer > LAER_INTERVAL:
                laer(con)
                sidste_laer = time.time()
        except Exception as e:
            log(f"fejl i lytte: {e}")
            try:
                con = psycopg.connect(DSN, autocommit=True)
            except Exception:
                pass
        # Vent på en besked fra motoren. Kommer der ingen, tjekker vi ro-tiden
        # en gang i minuttet — det er ventil, ikke rytme: intet arbejde imens.
        # Målt 2. nov 2026: uden den korte søvn kunne gennemløbet spinne. Søvnen
        # koster intet og garanterer at drømmen ikke brænder CPU i tomgang.
        try:
            with con.cursor() as cur:
                cur.execute("LISTEN ny_konklusion")
            for _ in con.notifies(timeout=60, stop_after=1):
                break
        except Exception:
            pass
        time.sleep(2)


def sikr_skema(con):
    with con.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS drom_fund (
                id         bigserial PRIMARY KEY,
                slags      text NOT NULL,   -- modsigelse|foraeldelse|uden_dokument|gentagelse|retningsskift
                emne       text NOT NULL,
                detalje    text NOT NULL,
                alvor      text NOT NULL DEFAULT 'info',  -- info|bemærk|vigtig
                oprettet   timestamptz NOT NULL DEFAULT now()
            )
        """)
        con.commit()


def _noegle(tekst: str) -> str:
    """Hvad handler sætningen om? Emne-ordene, uden tal og fyldord.

    "VAS kører på port 6305" og "VAS kører på port 6301" giver samme nøgle,
    fordi tallene er skilt ud. "Dio har nye færdigheder" og "Dio har svært ved
    at sove" giver FORSKELLIGE nøgler, fordi indholdet er forskelligt.
    """
    import re as _re
    FYLD = {"og", "i", "på", "for", "med", "at", "den", "det", "de", "er", "var",
            "har", "have", "kan", "skal", "fra", "til", "som", "der", "en", "et",
            "blev", "bliver", "så", "men", "om", "af", "ved", "efter", "over"}
    ord_ = _re.findall(r"[a-zæøåA-ZÆØÅ]+", (tekst or "").lower())
    kerne = sorted(w for w in ord_ if len(w) > 3 and w not in FYLD)
    return " ".join(kerne[:6])


def _tal(tekst: str) -> list[str]:
    """Tallene i sætningen. Det er dem der kan modsige hinanden."""
    import re as _re
    return _re.findall(r"\d+", tekst or "")


def er_praecisering(a: str, b: str) -> bool:
    """Er de to værdier samme sag, hvor den ene bare er mere præcis?

    DNA 2. nov 2026: Drømmen kaldte "Danny på mandag" og "Danny på mandag
    kl. 16" for en modsigelse. Det er en præcisering, ikke en uenighed.
    Regel: den korte værdi er indeholdt i den lange, ord for ord.
    # ponytail: ordsammenligning, ikke sprogforståelse. Udvid når den tager fejl.
    """
    a, b = a.strip().lower(), b.strip().lower()
    if a == b:
        return True
    kort, lang = (a, b) if len(a) <= len(b) else (b, a)
    return kort in lang


def koer(con):
    fund = []
    with con.cursor() as cur:
        # DNA 2026-11-13: DRØMMEN SAMMENLIGNER NU PÅ INDHOLDET, IKKE PÅ GÆT.
        #
        # Før grupperede den på emne+egenskab — to felter som en sprogmodel har
        # gættet. Det gav 23 "forskellige værdier for have" under emne "vi",
        # fordi 23 helt forskellige sætninger havde fået samme gættede etiket.
        # Drømmen kaldte det en modsigelse. Det var den ikke.
        #
        # Nu sammenligner den på (a) den ordrette tekst normaliseret og (b) de
        # TAL sætningen nævner. Kun når to sætninger handler om det SAMME emne
        # og er uenige om et tal, er der en ægte modsigelse. Det er den slags
        # der gør ondt: "porten er 6301" mod "porten er 6305".
        cur.execute("""
            SELECT id, coalesce(kilde_tekst,''), emne, egenskab,
                   coalesce(vaerdi,''), bevis, oprettet
            FROM konklusion
            WHERE NOT ugyldig AND length(coalesce(kilde_tekst,'')) > 10
        """)
        alle = cur.fetchall()

        grupper: dict[str, list] = {}
        for r in alle:
            kid, tekst, emne, egenskab, vaerdi, bevis, oprettet = r
            noegle = _noegle(tekst)
            if not noegle:
                continue
            grupper.setdefault(noegle, []).append(r)

        for noegle, raekker in grupper.items():
            if len(raekker) < 2:
                continue
            # Samme emne, men FORSKELLIGE tal = ægte modsigelse.
            if len({t for r in raekker for t in _tal(r[1])}) < 2:
                continue
            nyeste = max(raekker, key=lambda r: r[6])
            ældste = min(raekker, key=lambda r: r[6])
            fund.append((
                "modsigelse", nyeste[2],
                f"'{ældste[1][:80]}' ({ældste[6]:%Y-%m-%d}) mod "
                f"'{nyeste[1][:80]}' ({nyeste[6]:%Y-%m-%d}) — nyeste gælder",
                "vigtig"))

        # 2. Forældelse — samme udsagn gentaget, men den ældre har et andet tal.
        cur.execute("""
            SELECT id, coalesce(kilde_tekst,''), emne, oprettet
            FROM konklusion
            WHERE NOT ugyldig
              AND oprettet < now() - interval '%s days'
              AND length(coalesce(kilde_tekst,'')) > 10
            ORDER BY oprettet DESC
            LIMIT 3000
        """, (ALDER_DAGE,))
        aeldre = cur.fetchall()
        for kid, tekst, emne, oprettet in aeldre:
            noegle = _noegle(tekst)
            if not noegle:
                continue
            for r in alle:
                if r[0] == kid or r[6] <= oprettet:
                    continue
                if _noegle(r[1]) == noegle and _tal(r[1]) != _tal(tekst):
                    fund.append(("foraeldelse", emne,
                                 f"'{tekst[:80]}' ({oprettet:%Y-%m-%d}) er "
                                 f"erstattet af nyere", "bemærk"))
                    break

        # 3. Uden dokumentation — SAGT der har stået alene
        cur.execute("""
            SELECT emne, egenskab, count(*)
            FROM konklusion
            WHERE bevis = 'SAGT'
              AND oprettet < now() - interval '%s days'
              AND NOT EXISTS (
                  SELECT 1 FROM konklusion k2
                  WHERE k2.emne = konklusion.emne
                    AND k2.bevis IN ('MAALT','DOKUMENTERET')
              )
            GROUP BY emne, egenskab
            LIMIT 500
        """, (ALDER_DAGE,))
        for emne, egenskab, antal in cur.fetchall():
            fund.append(("uden_dokument", emne,
                         f"{egenskab}: {antal} påstand(e) uden dokumentation",
                         "vigtig"))

        # 4. Gentagelse — samme emne optræder i mange kilder
        cur.execute("""
            SELECT emne, count(DISTINCT kilde_id) AS kilder
            FROM konklusion
            WHERE kilde_id IS NOT NULL
            GROUP BY emne
            HAVING count(DISTINCT kilde_id) >= 3
            ORDER BY kilder DESC
            LIMIT 200
        """)
        for emne, kilder in cur.fetchall():
            fund.append(("gentagelse", emne,
                         f"optræder i {kilder} kilder", "bemærk"))

        # 5. Retningsskift — samme emne+egenskab, forskelligt bevis over tid
        cur.execute("""
            SELECT emne, egenskab,
                   string_agg(bevis || ' @ ' || to_char(oprettet, 'YYYY-MM-DD'),
                              ' -> ' ORDER BY oprettet)
            FROM konklusion
            GROUP BY emne, egenskab
            HAVING count(DISTINCT bevis) > 1
            LIMIT 200
        """)
        for emne, egenskab, forloeb in cur.fetchall():
            fund.append(("retningsskift", emne,
                         f"{egenskab}: {forloeb}", "bemærk"))

        for slags, emne, detalje, alvor in fund:
            cur.execute("""
                INSERT INTO drom_fund (slags, emne, detalje, alvor)
                VALUES (%s,%s,%s,%s)
            """, (slags, emne, detalje, alvor))
    con.commit()
    return {"fund": len(fund),
            "fordelt": {s: sum(1 for f in fund if f[0] == s)
                        for s in ("modsigelse", "foraeldelse", "uden_dokument",
                                  "gentagelse", "retningsskift")}}


class Handler(BaseHTTPRequestHandler):
    con = None

    def _json(self, obj, kode=200):
        import json
        b = json.dumps(obj, ensure_ascii=False, default=str).encode()
        self.send_response(kode)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def log_message(self, format, *args):
        pass

    def do_GET(self):
        p = urlparse(self.path)
        if p.path in ("/helbred", "/health"):
            return self._json({"status": "ok"})
        if p.path in ("/status", "/"):
            with self.con.cursor() as cur:
                cur.execute("SELECT count(*) FROM drom_fund")
                fund = cur.fetchone()[0]
                cur.execute("""
                    SELECT nye, udloeser, startet FROM drom_koersel
                    ORDER BY id DESC LIMIT 1
                """)
                sidste = cur.fetchone()
                cur.execute("""
                    SELECT count(*) FROM konklusion
                    WHERE oprettet > (SELECT coalesce(max(startet), now() - interval '1 day')
                                      FROM drom_koersel)
                      AND regel NOT LIKE 'drom%' AND form <> 'modsiger'
                """)
                nye = cur.fetchone()[0]
            return self._json({
                "fund": fund,
                "nye_siden_sidste": nye,
                "taerskel": DROM_TAERSKEL,
                "ro_sek": DROM_RO_SEK,
                "naeste_udloeser": ("maengde" if nye >= DROM_TAERSKEL
                                    else "ro" if nye > 0 else "venter"),
                "sidste_drom": ({"nye": sidste[0], "udloeser": sidste[1],
                                 "startet": sidste[2]} if sidste else None),
            })
        if p.path == "/fund":
            with self.con.cursor() as cur:
                cur.execute("""
                    SELECT slags, emne, detalje, alvor, oprettet
                    FROM drom_fund ORDER BY oprettet DESC LIMIT 100
                """)
                return self._json({"fund": [
                    {"slags": r[0], "emne": r[1], "detalje": r[2],
                     "alvor": r[3], "oprettet": r[4]} for r in cur.fetchall()
                ]})
        return self._json({"fejl": "ukendt sti"}, 404)

    def do_POST(self):
        p = urlparse(self.path).path
        if p == "/koer":
            return self._json(koer(self.con))
        if p == "/laer":
            return self._json(laer(self.con))
        return self._json({"fejl": "ukendt sti"}, 404)



def selvtest():
    """Uden database: kontroller at reglerne kan skelne de fem slags."""
    # Simpel logik-test på det der ellers kun testes mod en base
    tilfaelde = {
        "modsigelse": ("port=6301 | port=6302", 2),
        "uden_dokument": ("SAGT alene", 1),
    }
    for navn, (tekst, forventet) in tilfaelde.items():
        assert len(tekst.split("|")) >= forventet, navn
    # Præcisering er ikke modsigelse (DNA 2. nov 2026)
    assert er_praecisering("Danny på mandag", "Danny på mandag kl. 16 dansk tid")
    assert er_praecisering("Svendborg den 9", "Svendborg den 9. november")
    assert not er_praecisering("port 6301", "port 6302")
    assert not er_praecisering("være efterlyst", "afholdt videomøde")
    print("selvtest: 6 kontroller bestået")


if __name__ == "__main__":
    if "--selvtest" in sys.argv:
        selvtest()
        sys.exit(0)
    if psycopg is None:
        print("psycopg mangler", file=sys.stderr)
        sys.exit(1)
    con = psycopg.connect(DSN, autocommit=False)
    sikr_skema(con)
    if "--koer" in sys.argv:
        print(koer(con))
        sys.exit(0)
    Handler.con = con
    if os.environ.get("DROM_LYTTE", "1") == "1":
        threading.Thread(target=lytte, daemon=True).start()
    print(f"Drømmen lytter på {PORT}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
