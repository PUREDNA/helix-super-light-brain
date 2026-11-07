#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
trigger.py — det der fanger alt ind uden at nogen behøver kalde værktøjet.

Læser OW's chat_message-tabel, finder nye beskeder siden sidst, og sender
dem til Konklusionsmotoren som kilder.

Vigtigt (DNA 1. nov 2026):
  * ALT tages ind — både DNA's beskeder og modellens svar.
  * Men de mærkes forskelligt, så de aldrig blandes:
        DNA's beskeder   -> type "samtale"      -> bevis SAGT
        modellens svar   -> type "modelsvar"    -> bevis GÆT
    Modellens svar er ikke en kilde. Det er en påstand nogen har fremsat.
    Drømmen kan senere se om et modelsvar holder.

Kører som en tråd inde i start.py. Ingen egen port.
"""
import json
import os
import time
from urllib.parse import urlparse

import http.client

try:
    import psycopg
except ImportError:
    psycopg = None

KONKLUSION = "http://127.0.0.1:6305"
OW_DSN = os.environ.get(
    "OW_DSN",
    "host=127.0.0.1 port=5432 dbname=helix_main_db user=hjerne password=skift-mig",
)
INTERVAL = int(os.environ.get("TRIGGER_INTERVAL", "60"))   # sekunder
BATCH = int(os.environ.get("TRIGGER_BATCH", "50"))


def log(msg):
    print(f"[trigger] {msg}", flush=True)


def post(base, sti, krop, timeout=60):
    try:
        u = urlparse(base)
        c = http.client.HTTPConnection(u.hostname, u.port, timeout=timeout)
        c.request("POST", sti, json.dumps(krop),
                  {"Content-Type": "application/json"})
        r = c.getresponse()
        d = json.loads(r.read() or b"{}")
        c.close()
        return d
    except Exception as e:
        return {"fejl": str(e)}


def sikr_skema(con):
    """Triggerens eget bogmærke: hvilke beskeder er læst."""
    with con.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS trigger_laest (
                besked_id   text PRIMARY KEY,
                laest_tid   bigint NOT NULL DEFAULT 0,
                laest       timestamptz NOT NULL DEFAULT now(),
                konklusioner int NOT NULL DEFAULT 0
            )
        """)
        cur.execute("""
            ALTER TABLE trigger_laest ADD COLUMN IF NOT EXISTS laest_tid bigint NOT NULL DEFAULT 0
        """)
        con.commit()


def nye_beskeder(con, graense):
    """Hent nye beskeder fra OW's chat_message.

    OW gemmer id som text og content som json-array. Vi sorterer på
    created_at (unix-sekunder) og husker tidsstemplet.
    """
    with con.cursor() as cur:
        cur.execute("""
            SELECT id, role, content, created_at, chat_id, user_id
            FROM chat_message
            WHERE created_at > %s
              AND content IS NOT NULL
              AND role IN ('user','assistant')
            ORDER BY created_at
            LIMIT %s
        """, (graense, BATCH))
        return cur.fetchall()


def tekst_af(content):
    """OW's content er en json-liste af blokke: [{"type":"text","text":"..."}]."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    dele = []
    if isinstance(content, list):
        for b in content:
            if isinstance(b, dict):
                if b.get("text"):
                    dele.append(str(b["text"]))
            elif isinstance(b, str):
                dele.append(b)
    elif isinstance(content, dict) and content.get("text"):
        dele.append(str(content["text"]))
    return "\n".join(dele)


def behandl(con):
    """Én runde: find nye beskeder, send dem ind, husk hvad der er læst."""
    with con.cursor() as cur:
        cur.execute("SELECT coalesce(max(laest_tid), 0::bigint) FROM trigger_laest")
        graense = cur.fetchone()[0]

    rows = nye_beskeder(con, graense)
    if not rows:
        return 0

    kilder = []
    for mid, role, content, created, chat_id, user_id in rows:
        t = tekst_af(content).strip()
        # LAENGDEGRAENSEN (DNA 4. nov 2026): foer blev alt under 20 tegn kastet
        # vaek, saa Asgers foerste besked ("Hello" + fire uploadede filer) gik
        # tabt uden spor. Nu afgoeres det paa INDHOLDET: en hilsen baerer intet,
        # men en kort sagssaetning goer. Laeseren i motoren filtrerer selv
        # hilsener og fyld fra — her skal vi kun undgaa det helt tomme.
        if len(t) < 3:
            continue
        kilder.append({
            "id": f"ow:{mid}",
            # DNA's egne ord er en kilde. Modellens svar er en påstand.
            "type": "samtale" if role == "user" else "modelsvar",
            "tekst": t[:8000],
            # HVEM der sagde det (DNA 2. nov 2026). Gæster i OpenWebUI får
            # deres eget rum: uden dette felt kan hjernen ikke skelne Lottes
            # sager fra DNA's, og så kan de blive blandet sammen.
            "ejer": user_id or "",
        })

    svar = post(KONKLUSION, "/udled", {"kilder": kilder}) if kilder else {}
    antal = svar.get("konklusioner", 0)

    # MAERKET (DNA 4. nov 2026): foer satte vi maerket til den NYESTE besked i
    # hele batchen — ogsaa dem der blev kasseret. Asgers foerste hilsen ("Hello")
    # skubbede dermed maerket forbi alle hans rigtige beskeder, og de blev aldrig
    # laest. Nu huskes hver besked for sig, og maerket er den nyeste vi FAKTISK
    # har vaeret igennem.
    with con.cursor() as cur:
        for mid, _role, _content, created, *_rest in rows:
            cur.execute("""
                INSERT INTO trigger_laest (besked_id, laest_tid, konklusioner)
                VALUES (%s, %s, 0) ON CONFLICT (besked_id) DO NOTHING
            """, (mid, int(created or 0)))
        con.commit()

    log(f"{len(kilder)} kilder -> {antal} konklusioner "
        f"({svar.get('uforstaaet', 0)} uforstået)")
    return len(kilder)


def loeb():
    """Kører til den bliver stoppet. Aldrig stop-funktion (DNA 1. nov)."""
    if psycopg is None:
        log("psycopg mangler — trigger kan ikke køre")
        return
    con = None
    while True:
        try:
            if con is None or con.closed:
                # autocommit=True (DNA 4. nov 2026): samme fejl som motoren havde.
                # Uden autocommit aabnede hvert laes en transaktion der aldrig blev
                # afsluttet. Laasen blev hangende, og til sidst stod FEM
                # forespoergsler i ko paa OW's database. Triggeren kunne hverken
                # laese eller skrive, og den skrev ingen fejl.
                con = psycopg.connect(OW_DSN, autocommit=True)
                sikr_skema(con)
                log("forbundet til OW's database")
            behandl(con)
        except Exception as e:
            log(f"fejl: {e} — prøver igen om {INTERVAL} s")
            try:
                if con:
                    con.close()
            except Exception:
                pass
            con = None
        time.sleep(INTERVAL)


if __name__ == "__main__":
    loeb()
