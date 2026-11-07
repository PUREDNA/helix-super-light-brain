"""Helix Compression — et flyttelæs, ikke en kompressor.

DNA 2. nov 2026: Hermes' indbyggede kompressor kalder en fremmed model og
skriver et resumé. Det er der nuancerne forsvinder. Denne motor gør det
modsatte: når korttidshukommelsen er ved at være fuld, sendes de ældste
beskeder RÅT ind i Lillehjernen (/udled). Først når hjernen har kvitteret,
klippes de ud af historikken.

Reglerne (DNA):
  1. Flyt først, klip bagefter. Ingen kvittering = ingen sletning.
  2. Ingen opsummering. Ingen model skriver brugerens ord om.
  3. Ned til 65 % af vinduet, så der igen er luft til en lang samtale.
  4. Kan hjernen ikke følge med, klipper vi ud alligevel og skriver hvad der
     ikke blev ført ind — samtalen må aldrig gå i stå.

Aktiveres med `context.engine: helix-compression` i config.yaml.
"""
from __future__ import annotations

import json
import os
import threading
import urllib.request

from agent.context_engine import ContextEngine

HJERNE = os.environ.get("LILLEHJERNE", "http://127.0.0.1:6302")
NED_TIL = float(os.environ.get("HELIX_COMPRESS_NED_TIL", "0.65"))
TÆRSKEL = float(os.environ.get("HELIX_COMPRESS_TÆRSKEL", "0.90"))
LÅS = threading.Lock()   # to ture må ikke tømme samme historik samtidig


def _rens(tekst: str) -> str:
    """Fjern stemme-indpakningen, så hjernen får DNA's egne ord."""
    import re
    m = re.search(r"said:\s*[\"“](.*?)[\"”]", tekst or "", re.S)
    return (m.group(1) if m else (tekst or "")).strip()


def _taeller(tekst: str) -> int:
    # ponytail: ~3,5 tegn pr. token, ikke en rigtig tokenizer. Godt nok til en tærskel.
    return max(1, len(tekst or "") // 3)


class HelixCompression(ContextEngine):
    """Flytter historik til Langtidshukommelsen (Lillehjernen)."""

    def __init__(self, **kw):
        self.context_length = int(kw.get("context_length") or 0)
        self.threshold_tokens = int(self.context_length * TÆRSKEL) if self.context_length else 0
        self.threshold_percent = TÆRSKEL
        self.protect_first_n = 2
        self.protect_last_n = 4
        self.emit_automatic_compaction_status = True
        self.last_prompt_tokens = 0
        self.last_completion_tokens = 0
        self.last_total_tokens = 0
        self.compression_count = 0
        self.sidste_rapport = ""

    @property
    def name(self) -> str:
        return "helix-compression"

    def update_from_response(self, usage):
        if not isinstance(usage, dict):
            return
        self.last_prompt_tokens = int(usage.get("prompt_tokens") or 0)
        self.last_completion_tokens = int(usage.get("completion_tokens") or 0)
        self.last_total_tokens = int(usage.get("total_tokens") or 0)
        if not self.context_length:
            self.context_length = int(usage.get("context_length") or 0)
        if self.context_length:
            self.threshold_tokens = int(self.context_length * TÆRSKEL)

    def should_compress(self, prompt_tokens=None) -> bool:
        tal = prompt_tokens if prompt_tokens is not None else self.last_prompt_tokens
        if not self.context_length:
            return False
        # En tærskel der ikke er sat må aldrig blokere for tømning (DNA 2. nov 2026:
        # Hermes giver ikke altid context_length med, og så fylder historikken op).
        if tal >= self.threshold_tokens:
            return True
        return False

    def should_compress_preflight(self, messages) -> bool:
        """Grovt anslag før API-kaldet — fanger tilfældet hvor tokens ikke er kendt."""
        if not self.context_length:
            return False
        raat = sum(_taeller(str(m.get("content", ""))) for m in (messages or []))
        return raat >= self.threshold_tokens

    def has_content_to_compress(self, messages) -> bool:
        return len(messages or []) > self.protect_first_n + self.protect_last_n

    # --------------------------------------------------------------- flytning
    def _flyt(self, historik: list[dict]) -> tuple[int, str]:
        """Send de ældste beskeder råt til Lillehjernen. Returnerer (antal, svar)."""
        kilder = []
        for i, m in enumerate(historik):
            tekst = _rens(m.get("content") if isinstance(m.get("content"), str) else "")
            if len(tekst) < 40:
                continue
            rolle = m.get("role", "")
            if rolle not in ("user", "assistant"):
                continue
            kilder.append({"id": f"hist-{i}", "tekst": tekst,
                           "type": "samtale" if rolle == "user" else "samtale-assistent"})
        if not kilder:
            return 0, "intet at flytte"
        krop = json.dumps({"kilder": kilder}).encode()
        req = urllib.request.Request(HJERNE + "/udled", data=krop,
                                     headers={"Content-Type": "application/json"})
        svar = json.loads(urllib.request.urlopen(req, timeout=120).read())
        return len(kilder), json.dumps(svar, ensure_ascii=False)

    def compress(self, messages, current_tokens=None, focus_topic=None,
                 force=False, memory_context=""):
        msgs = list(messages or [])
        if not self.has_content_to_compress(msgs):
            return msgs
        with LÅS:
            # Budget måles fra den aktuelle brug, ellers tømmer vi intet når
            # samtalen er 90 % fuld, men vinduet er stort (målt 2. nov 2026).
            start = current_tokens or self.last_prompt_tokens
            budget = int((start or self.context_length) * NED_TIL)

            # Klip fra venstre (de ældste), men hold hoved og hale urørt.
            hoved = msgs[: self.protect_first_n]
            hale = msgs[-self.protect_last_n:]
            midte = msgs[self.protect_first_n: len(msgs) - self.protect_last_n]

            optaget = sum(_taeller(str(m.get("content", ""))) for m in hoved + hale)
            flyttes, beholdt = [], []
            rest = budget - optaget
            for msg in midte:            # ældste først: de ældste flyttes ud
                t = _taeller(str(msg.get("content", "")))
                if t <= rest and rest > 0:
                    beholdt.append(msg)
                    rest -= t
                else:
                    flyttes.append(msg)
            flyttes = list(flyttes)
            beholdt = list(beholdt)
            print(f"[helix-compression] budget {budget} optaget {optaget} midte {len(midte)} flyttes {len(flyttes)} beholdt {len(beholdt)}", flush=True)

            # RÅT ind i hjernen. Kun det der blev kvitteret, må slettes.
            n, svar = 0, "ikke kørt"
            if not flyttes:
                svar = "intet at flytte — historikken fylder mindre end budgettet"
            else:
                try:
                    n, svar = self._flyt(flyttes)
                except Exception as e:  # noqa: BLE001 — samtalen må ikke gå i stå
                    svar = f"FEJL: {e}"

            self.compression_count += 1
            self.sidste_rapport = f"flyttede {n} beskeder — {svar}"
            ny = hoved + beholdt + hale
            # Spor i historikken: hvad der blev flyttet, og at det skete uden resumé.
            ny.insert(len(hoved), {
                "role": "system",
                "content": (f"[HELIX FLYTTEDE {n} BESKEDER TIL LILLEHJERNEN] "
                            f"Ingen opsummering — de ligger råt i langtidshukommelsen "
                            f"og kan slås op der. {svar}"),
            })
            return ny

    def get_automatic_compaction_status_message(self, *, phase, default_message, **context):
        if self.sidste_rapport:
            return f"Helix Compression: {self.sidste_rapport}"
        return default_message


def register(ctx):
    ctx.register_context_engine(HelixCompression())
