"""helix-memory — Lillehjernen som Memory Provider i Hermes.

DNA 2026-11-03: Lillehjernen er MIN hjerne. Super Brain fik ALLE samtaler,
fordi krogen sad i Hermes selv (Honcho-plugin'ets saveMessages), ikke i
OpenWebUI. Derfor gør denne provider det samme: sync_turn sender hver
afsluttet tur — DNA's besked OG mit svar — til Konklusionsmotoren. Så bliver
det vi taler om her til konklusioner på samme måde som før.

To veje ind, med vilje:
  * sync_turn  — Hermes' egen krog: HUD, Telegram, CLI, alt.
  * OpenWebUI  — triggeren i containeren læser OW's chat-tabel.
Begge skriver til det samme hjerne.konklusion, hver med sin ejer.
"""
from __future__ import annotations

import json
import os
import urllib.request

from agent.memory_provider import MemoryProvider

# 6302 = hukommelseslaget (læsning). 6305 = Konklusionsmotoren (skrivning).
HJERNE = os.environ.get("LILLEHJERNE", "http://127.0.0.1:6302")
MOTOR = os.environ.get("LILLEHJERNE_MOTOR", "http://127.0.0.1:6305")


def _navn_for(ejer: str) -> str:
    """Slå brugerens navn op i OpenWebUI's brugertabel.

    DNA 2026-11-15: der maa ikke staa et fast navn i containeren. Deler man
    den med 250 mennesker, skal hver af dem se deres eget navn — ikke DNA's.
    Bruger-id'et er noeglen; navnet er svaret. Findes brugeren ikke, staar
    der "ukendt", ikke et tilfaeldigt navn.
    """
    if not ejer or ejer.startswith("bruger:"):
        return "ukendt"
    try:
        import psycopg
        dsn = os.environ.get(
            "LILLEHJERNE_OW_DSN",
            "host=127.0.0.1 port=5432 dbname=helix_main_db user=hjerne password=skift-mig")
        with psycopg.connect(dsn) as con, con.cursor() as cur:
            cur.execute('SELECT name FROM public."user" WHERE id = %s LIMIT 1',
                        (ejer,))
            r = cur.fetchone()
        return ((r[0] or "").strip() or "ukendt") if r else "ukendt"
    except Exception:
        return "ukendt"


def _hent(sti: str, timeout: int = 5) -> dict:
    try:
        with urllib.request.urlopen(HJERNE + sti, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except Exception as e:  # noqa: BLE001
        return {"fejl": str(e)}


def _soeg(spoergsmaal: str, antal: int = 15, timeout: int = 20) -> dict:
    """Spørg motoren hvad den ved der ligner spørgsmålet."""
    if not spoergsmaal.strip():
        return {}
    try:
        data = json.dumps({"spoergsmaal": spoergsmaal, "antal": antal},
                          ensure_ascii=False).encode()
        req = urllib.request.Request(
            MOTOR + "/soeg", data=data,
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except Exception as e:  # noqa: BLE001
        print(f"[lillehjerne] soegning fejlede: {e}", flush=True)
        return {}


def _send(kilder: list, timeout: int = 30) -> dict:
    """Send kilder til motoren, så de bliver til konklusioner."""
    if not kilder:
        return {}
    try:
        data = json.dumps({"kilder": kilder}, ensure_ascii=False).encode()
        req = urllib.request.Request(
            MOTOR + "/udled", data=data,
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except Exception as e:  # noqa: BLE001
        # Hjernen må aldrig vælte en tur. Fejlen logges og glemmes.
        print(f"[lillehjerne] kunne ikke sende tur: {e}", flush=True)
        return {}


class HelixSuperLightBrain(MemoryProvider):
    """Lillehjernen: konklusioner med kilde og bevisgrad. Ingen opsummering."""

    def __init__(self, **kw):
        self._kw = kw
        self._session = ""

    @property
    def name(self) -> str:
        return "helix-super-light-brain"

    @property
    def display_name(self) -> str:
        return "Helix Super Light Brain"

    def is_available(self) -> bool:
        # Kun konfiguration — ingen netværkskald her (Hermes' kontrakt).
        return True

    def initialize(self, session_id: str, **kwargs) -> None:
        self._session = session_id

    def unavailable_reason(self) -> str:
        return "Lillehjernen svarer ikke på " + HJERNE

    def system_prompt_block(self) -> str:
        return ("Langtidshukommelsen er Helix Super Light Brain: konklusioner "
                "udledt af regler, hver med kilde og bevisgrad. Slå op i den "
                "frem for at gætte.")

    def sync_turn(
        self, user_content: str, assistant_content: str, *,
        session_id: str = "", messages=None, turn_author=None,
    ) -> None:
        """Kun DNA's ord går i hjernen — ikke mine egne svar.

        DNA 3. nov 2026: jeg sendte ogsaa mit eget svar ind som kilde, og saa
        blev mine forklaringer til "konklusioner": "Sletningen vente paa
        godkendelse", "resten filen lave = memory". Det er mig der forklarer
        mig, ikke viden om ham. Kun det HAN siger er en kilde.
        """
        if not (user_content and user_content.strip()):
            return
        sid = session_id or self._session or "ukendt"
        ejer = (turn_author or {}).get("id", "") or ""
        kilder = [{
            "id": f"hermes:{sid}:u",
            "type": "samtale",
            "tekst": user_content.strip()[:8000],
            "ejer": ejer,
            # DNA 2026-11-15: TALEREN KOMMER FRA BRUGEREN — ikke fra et fast
            # navn. Foer stod "Danny" hardkodet, saa hans navn dukkede op i
            # enhver anden brugers hjerne. Nu slaas navnet op paa bruger-id'et.
            "taler": _navn_for(ejer),
        }]
        # Assistentens svar er IKKE en konklusion om DNA, men det er en
        # konklusion om MIG (DNA 5. nov 2026: "i Helix har du både en privat
        # og en data"). Det gaar i Helix-kategorien, adskilt fra hans.
        if assistant_content and assistant_content.strip():
            kilder.append({
                "id": f"hermes:{sid}:a",
                "type": "samtale",
                "tekst": assistant_content.strip()[:8000],
                "ejer": ejer,
                "taler": "Helix",
            })
        _send(kilder)

    def get_tool_schemas(self) -> list:
        """Ingen egne værktøjer endnu — opslag går gennem prefetch."""
        return []

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        """De konklusioner der LIGNER spørgsmålet — aldrig de nyeste.

        DNA 2026-11-13: TOMT SPØRGSMÅL GIVER INTET.
        Før faldt den tilbage til de 15 nyeste naar soegningen ikke gav noget.
        Det betoed at en ny model i en ny session startede med tilfaeldige
        konklusioner af helt andet emne — og de kunne vaelte hele projektet.
        Hellere tom hukommelse end forkert hukommelse.
        """
        if not (query or "").strip():
            return ""

        linjer = []
        d = _soeg(query)
        for k in (d.get("fund") or [])[:15]:
            linje = _linje(k)
            if linje:
                linjer.append(linje)
        if not linjer:
            return ""
        # DNA 2026-11-13: AI'en skal kunne SE forskel paa hvad der er hukommelse
        # og hvad der er samtalen lige nu. Derfor en tydelig ramme og et
        # tidspunkt paa hver linje.
        return ("[HUKOMMELSE — konklusioner fra lillehjernen, ikke det vi taler om nu]\n"
                + "\n".join(linjer)
                + "\n[SLUT PAA HUKOMMELSE]")


def _linje(k: dict) -> str:
    """Én konklusion som tekst med tid.

    DNA 2026-11-13: DEN ORDRETTE TEKST VISES — ikke de tre gættede felter.
    Foer stod der "Danny · haste = strata", fordi emne/egenskab/vaerdi er
    gæt fra en sprogmodel og blander ordene. Teksten er facit.
    """
    tekst = (k.get("tekst") or k.get("kilde_tekst") or "").strip()
    if not tekst:
        # Ældre rækker uden tekst: sæt de tre felter sammen som før.
        tekst = " · ".join(x for x in (k.get("emne"), k.get("egenskab"),
                                       k.get("vaerdi")) if x)
    if not tekst:
        return ""

    # Tidsstempel: hvornår blev det lært. Kun dato og time — ikke sekunder.
    tid = (k.get("laert") or k.get("oprettet") or "")
    tid = str(tid)[:16].replace("T", " ")
    bevis = (k.get("bevis") or "").upper()
    mærke = {"SAGT": "sagt", "FOERSTEHAANDS": "førstehånd",
             "ANDENHAANDS": "andenhånd"}.get(bevis, "")
    hale = " · ".join(x for x in (mærke, tid) if x)
    return f"- {tekst}" + (f"  ({hale})" if hale else "")


def register(ctx):
    ctx.register_memory_provider(HelixSuperLightBrain())
