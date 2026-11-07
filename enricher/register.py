#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Registeret — det der kan slås op.

Broen (bro.py) finder entiteter i en konklusion og spørger registeret:
*er det her sandt?* Registeret svarer med et opslag — ikke en mening.

Hvert opslag er en PIVOT: ind → opslag → ud. Hver pivot har et navn, så grafen
kan vise HVOR svaret kom fra. Det er hele pointen fra Flowsint: en kant skal
kunne pege på den kilde der afgjorde den.

Kilder, målt fra containeren 2026-10-12:

    DNS    dns.google (DoH)                 virker
    PORT   TCP-forbindelse til værten       virker
    GRAF   ag_catalog.ag_graph (egen base)  virker
    BASE   pg_database (egen base)          virker
    NOTE   /vault                           kun hvis vaulten er monteret
    CVR    proff.dk (CVR-spejl)             virker — gratis, ingen nøgle

Reglen er Flowsints: **hvad der ikke kan slås op, kommer ikke i grafen som
dokumenteret.** Kan vi ikke spørge, svarer vi KORTLAGT — aldrig DOKUMENTERET.
"""
from __future__ import annotations

import json
import os
import re
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None


# --------------------------------------------------------------- bevis-niveauerne
DOKUMENTERET = "DOKUMENTERET"
KORTLAGT = "KORTLAGT"
PAASTAND = "PÅSTAND"
IKKE_DOKUMENTERET = "IKKE DOKUMENTERET"

# Jo højere tal, jo stærkere. PÅSTAND er altid udgangspunktet — også for det
# der blev sagt ordret: at noget ER sagt er ikke det samme som at det er sandt.
RANGO = {IKKE_DOKUMENTERET: 0, PAASTAND: 1, KORTLAGT: 2, DOKUMENTERET: 3}

VAERT = os.environ.get("VAERT", "host.docker.internal")
VAULT = os.environ.get("OPS_VAULT", "/vault")

# Topdomæner vi tør kalde et domæne. Uden listen bliver "indekser.py" et
# domæne — og en fil er ikke et opslag.
TLD = {
    "dk", "com", "net", "org", "io", "dev", "ai", "shop", "nu", "co", "info",
    "biz", "eu", "se", "no", "de", "uk", "us", "fr", "es", "it", "nl", "pt",
    "fi", "pl", "ch", "at", "be", "app", "cloud", "systems", "tech", "online",
    "site", "store", "pro", "me", "tv", "gg", "xyz", "top", "live",
}

# Navne der ER værd at slå op, selv om de ikke har en prik.
KENDTE_GRAFER = ("hjerne", "juridiske_sager")
KENDTE_BASER = ("hjerne", "helix_graph", "honcho_main", "helix_main_db")
EGNE_PORTE = {5432: "PostgreSQL", 8100: "HC", 6080: "NPLL", 6122: "Ops", 6123: "Viewer"}


@dataclass
class Svar:
    """Registerets svar på ét opslag.

    `navn` er det kanoniske navn på det fundne (fx firmanavnet fra et
    CVR-opslag) — i modsætning til det rå input (fx selve CVR-nummeret).
    Er `navn` tomt, bruges input-navnet som før.
    `etiket` er hvilken node-etiket resultatet hører under (fx "Firma").
    Er den tomt, bruges den generiske "Entitet".
    """
    bevis: str
    kilde: str
    register: str
    navn: str = ""
    etiket: str = ""


@dataclass
class Pivot:
    """Ind → opslag → ud. `find` læser teksten, `opslag` spørger verden."""
    navn: str
    slags: str
    find: Callable[[str], list[str]]
    opslag: Callable[[str], Svar]
    beskrivelse: str = ""


# ------------------------------------------------------------------- finde-regler
# Reglerne er med vilje kedelige og deterministiske. De finder det, regler KAN
# finde. Alt andet er deriverens arbejde — ikke broens.
def find_domaener(tekst: str) -> list[str]:
    ud: list[str] = []
    for m in re.finditer(r"\b((?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,10})\b",
                         tekst.lower()):
        navn = m.group(1)
        if navn.rsplit(".", 1)[1] in TLD:
            ud.append(navn)
    return ud


def find_porte(tekst: str) -> list[str]:
    """To former, og ikke andre:
        "port 6120"                          — ordet står der
        "host.docker.internal:11434" / "127.0.0.1:5432"  — et værtsnavn eller en IP
    Den anden kræver et punktum i navnet foran, for ellers bliver klokkeslæt
    ("14:05") læst som port 5 — og så afkræfter registeret noget der er sandt.
    """
    ud: list[str] = []
    mønstre = (
        r"\bport(?:en|er)?\s*[:#]?\s*(\d{2,5})\b",
        r"(?<![\d:])(?:[a-z][a-z0-9-]*(?:\.[a-z0-9-]+)+|(?:\d{1,3}\.){3}\d{1,3}):(\d{2,5})\b",
    )
    for mønster in mønstre:
        for m in re.finditer(mønster, tekst.lower()):
            p = m.group(1)
            if 1 <= int(p) <= 65535:
                ud.append(p)
    return ud


def find_grafer(tekst: str) -> list[str]:
    return [g for g in KENDTE_GRAFER if re.search(rf"\b{g}\b", tekst, re.I)]


def find_baser(tekst: str) -> list[str]:
    return [b for b in KENDTE_BASER if re.search(rf"\b{b}\b", tekst, re.I)]


def find_noter(tekst: str) -> list[str]:
    return [m.group(1).strip() for m in re.finditer(r"\[\[([^\]|]{2,80})", tekst)]


def find_cvr(tekst: str) -> list[str]:
    """Finder CVR-numre. Konservativ regel: ordet \"cvr\" skal stå umiddelbart
    foran et 8-cifret tal (\"CVR 42665673\", \"cvr:42665673\", \"CVR-nr 42665673\").
    Et løst 8-cifret tal uden mærke kan være en dato eller et andet nummer —
    det tør vi ikke kalde et CVR-opslag.
    """
    ud: list[str] = []
    for m in re.finditer(r"\bcvr[^\d]{0,5}(\d{8})\b", tekst.lower()):
        ud.append(m.group(1))
    return ud


# ------------------------------------------------------------------ opslags-regler
def kan_forbindes(vaert: str, port: int, sek: float = 2.0) -> bool:
    try:
        with socket.create_connection((vaert, port), timeout=sek):
            return True
    except OSError:
        return False



# ------------------------------------------------------------ rolle-gaten
# Konklusionen kan påstå en ROLLE om et menneske registeret kender. Det er her
# den slags fejl opstår: "Danny ... som forsvarer" — registeret siger klager.
# Gaten spørger registeret FØR dommen falder, så påstanden ikke står uimodsagt.
ROLLE_ORD = (
    "klager", "sagsøger", "sagsoger", "indklagede", "modpart", "forsvarer",
    "advokat", "bistandsadvokat", "anklager", "vidne", "part", "dommer",
    "sagsbehandler", "plejemor", "plejefar", "anbragt", "barnet", "forælder",
    "direktør", "direktoer", "stifter", "bestyrelsesformand", "konsulent",
    "psykolog", "journalist", "undersøger", "medstyrer",
)
_PERSONER_CACHE: dict[str, str] | None = None


def personer_i_registeret(forbindelse) -> dict[str, str]:
    """navn -> rolle_i_sagen. Læses én gang fra registeret og huskes."""
    global _PERSONER_CACHE
    if _PERSONER_CACHE is not None:
        return _PERSONER_CACHE
    ud: dict[str, str] = {}
    try:
        with forbindelse.cursor() as cur:
            cur.execute(
                "SELECT navn, tekst FROM ag_catalog.referencer_embeddings "
                "WHERE tekst ILIKE %s", ("%rolle_i_sagen%",))
            for navn, tekst in cur.fetchall():
                m2 = re.search(r"rolle[a-zæøå_]*_i_sagen:\**\s*([^\n\[\*]{3,80})", tekst or "")
                if not m2:
                    continue
                navn = navn or ""
                if not str(navn).strip():
                    h = re.search(r"^#\s*(.+)$", tekst or "", re.M)   # fx '# Sandra Abild'
                    navn = h.group(1).strip() if h else ""
                if str(navn).strip():
                    ud[str(navn).strip()] = m2.group(1).strip()
    except Exception:
        return {}
    _PERSONER_CACHE = ud
    return ud

class Register:
    """Kataloget over hvad der kan slås op. Kræver en forbindelse til hjernens
    egen base for GRAF- og BASE-opslagene; de øvrige klarer sig uden."""

    def __init__(self, forbindelse=None):
        self.fb = forbindelse

    # ----- DNS -----
    def opslag_dns(self, domaene: str) -> Svar:
        if httpx is None:
            return Svar(KORTLAGT, "httpx mangler i miljøet — kunne ikke spørge", "DNS")
        try:
            r = httpx.get("https://dns.google/resolve",
                          params={"name": domaene, "type": "A"}, timeout=10)
            r.raise_for_status()
            d = r.json()
        except Exception as fejl:  # netværket kan fejle — det er ikke et svar
            return Svar(KORTLAGT, f"kunne ikke spørge DNS: {type(fejl).__name__}", "DNS")
        ip = [a.get("data") for a in (d.get("Answer") or []) if a.get("type") == 1]
        if ip:
            return Svar(DOKUMENTERET, f"DNS opgiver {domaene} → {', '.join(ip[:3])}", "DNS")
        if d.get("Status") == 3:
            return Svar(IKKE_DOKUMENTERET, f"DNS svarer NXDOMAIN: {domaene} findes ikke", "DNS")
        return Svar(KORTLAGT, f"DNS gav intet svar for {domaene}", "DNS")

    # ----- PORT -----
    def opslag_port(self, port: str) -> Svar:
        n = int(port)
        if n in EGNE_PORTE and kan_forbindes("127.0.0.1", n):
            return Svar(DOKUMENTERET, f"hjernen selv lytter på {n} ({EGNE_PORTE[n]})", "Maskinen")
        if kan_forbindes(VAERT, n):
            return Svar(DOKUMENTERET, f"noget lytter på {VAERT}:{n} (målt nu)", "Maskinen")
        return Svar(IKKE_DOKUMENTERET, f"intet lytter på port {n} (målt nu)", "Maskinen")

    # ----- GRAF -----
    def opslag_graf(self, graf: str) -> Svar:
        if self.fb is None:
            return Svar(KORTLAGT, "ingen forbindelse til basen — kunne ikke spørge", "Graf")
        try:
            with self.fb.cursor() as cur:
                cur.execute("SELECT count(*) FROM ag_catalog.ag_graph WHERE name = %s", (graf,))
                findes = cur.fetchone()[0]
        except Exception as fejl:
            return Svar(KORTLAGT, f"kunne ikke spørge kataloget: {type(fejl).__name__}", "Graf")
        if findes:
            return Svar(DOKUMENTERET, f"grafen '{graf}' findes i ag_catalog", "Graf")
        return Svar(IKKE_DOKUMENTERET, f"grafen '{graf}' findes ikke i denne base", "Graf")

    # ----- BASE -----
    def opslag_base(self, base: str) -> Svar:
        if self.fb is None:
            return Svar(KORTLAGT, "ingen forbindelse til basen — kunne ikke spørge", "Base")
        try:
            with self.fb.cursor() as cur:
                cur.execute("SELECT count(*) FROM pg_database WHERE datname = %s", (base,))
                findes = cur.fetchone()[0]
        except Exception as fejl:
            return Svar(KORTLAGT, f"kunne ikke spørge kataloget: {type(fejl).__name__}", "Base")
        if findes:
            return Svar(DOKUMENTERET, f"basen '{base}' findes på denne maskine", "Base")
        return Svar(KORTLAGT, f"basen '{base}' findes ikke her — den gamle base kræver "
                              f"adgangskode, så vi kan ikke afgøre det", "Base")

    # ----- NOTE -----
    def opslag_note(self, note: str) -> Svar:
        rod = Path(VAULT)
        if not rod.exists():
            return Svar(KORTLAGT, f"vaulten '{VAULT}' er ikke monteret — kunne ikke spørge", "Note")
        navn = note.strip()
        for sti in rod.rglob("*.md"):
            if sti.stem.lower() == navn.lower():
                return Svar(DOKUMENTERET, f"noten '{navn}' findes i vaulten", "Note")
        return Svar(IKKE_DOKUMENTERET, f"noten '{navn}' findes ikke i vaulten", "Note")

    # ----- CVR -----
    def opslag_cvr(self, cvr: str) -> Svar:
        if httpx is None:
            return Svar(KORTLAGT, "httpx mangler i miljøet — kunne ikke spørge", "CVR")
        # proff.dk spejler det danske CVR-register og svarer med struktureret
        # JSON i __NEXT_DATA__ — gratis, uden nøgle og uden browser. Det
        # officielle datacvr.virk.dk er Cloudflare-spærret og svarer 403.
        url = f"https://www.proff.dk/firma/-/-/-/{cvr}"
        try:
            r = httpx.get(
                url,
                timeout=25,
                follow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                                       "Chrome/120 Safari/537.36",
                         "Accept-Language": "da-DK,da;q=0.9"},
            )
            if r.status_code == 404:
                return Svar(IKKE_DOKUMENTERET, f"CVR {cvr} findes ikke i registeret", "CVR")
            r.raise_for_status()
        except Exception as fejl:
            return Svar(KORTLAGT, f"kunne ikke spørge CVR: {type(fejl).__name__}", "CVR")
        m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
                      r.text, re.S)
        if not m:
            return Svar(KORTLAGT, "proff.dk svarede uden __NEXT_DATA__ struktur", "CVR")
        try:
            data = json.loads(m.group(1))
        except json.JSONDecodeError:
            return Svar(KORTLAGT, "proff.dk returnerede ugyldig JSON", "CVR")
        c = data.get("props", {}).get("pageProps", {}).get("company") or {}
        navn = c.get("name") or c.get("legalName")
        if not navn:
            return Svar(IKKE_DOKUMENTERET, f"CVR {cvr} findes ikke i registeret", "CVR")
        status = (c.get("status") or {}).get("status")
        ansatte = c.get("employees") or c.get("numberOfEmployees")
        adr = c.get("visitorAddress") or {}
        adresse = " ".join([str(adr.get("addressLine") or ""),
                            str(adr.get("zipCode") or ""),
                            str(adr.get("postPlace") or "")]).strip()
        dele = [f"CVR {cvr} → {navn}"]
        if status:
            dele.append(str(status))
        if ansatte is not None:
            dele.append(f"{ansatte} ansatte")
        if adresse:
            dele.append(adresse)
        return Svar(DOKUMENTERET, "; ".join(dele), "CVR", navn=navn, etiket="Firma")

    # ----- kataloget -----
    def tjek_roller(self, tekst: str) -> list[tuple[str, Svar]]:
        """Spørger registeret om de roller konklusionen nævner for kendte personer."""
        personer = personer_i_registeret(self.fb)
        if not personer or not tekst:
            return []
        ud: list[tuple[str, Svar]] = []
        lav = tekst.lower()
        for navn, rolle in personer.items():
            fornavn = re.split(r"\s+", navn.strip())[0].lower()
            if len(fornavn) < 3 or fornavn not in lav:
                continue
            naevnt = {o for o in ROLLE_ORD if re.search(r"\b" + re.escape(o) + r"\b", lav)}
            if not naevnt:
                continue
            if rolle and any(o in rolle.lower() for o in naevnt):
                ud.append((navn, Svar(DOKUMENTERET, f"registeret: {navn} — {rolle}", "Register")))
            elif rolle:
                ud.append((navn, Svar(IKKE_DOKUMENTERET,
                           f"registeret siger '{navn} — {rolle}', konklusionen nævner "
                           f"{sorted(naevnt)}", "Register")))
        return ud

    def pivoter(self) -> list[Pivot]:
        return [
            Pivot("DNS", "Domæne", find_domaener, self.opslag_dns,
                  "Et domæne slås op hos dns.google — svarer det, er domænet der"),
            Pivot("Port", "Port", find_porte, self.opslag_port,
                  "Et portnummer prøves med en TCP-forbindelse — lytter nogen?"),
            Pivot("Graf", "Graf", find_grafer, self.opslag_graf,
                  "En graf slås op i ag_catalog.ag_graph"),
            Pivot("Base", "Database", find_baser, self.opslag_base,
                  "En database slås op i pg_database"),
            Pivot("Note", "Note", find_noter, self.opslag_note,
                  "En note slås op i vaulten"),
            Pivot("CVR", "Virksomhed", find_cvr, self.opslag_cvr,
                  "Et CVR-nummer slås op hos proff.dk — navn, status, ansatte, adresse"),
        ]

    def beskriv_catalog(self) -> str:
        linjer = []
        for p in self.pivoter():
            linjer.append(f"  {p.navn:<6} {p.slags:<10} {p.beskrivelse}")
        return "\n".join(linjer)
