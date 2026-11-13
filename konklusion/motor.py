#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Konklusionsmotoren — Helix Super Light Brain.

Erstatter den LLM der i Super Brain kalder sig deriver. Udleder konklusioner
af det der står i kilderne, med regler i stedet for gæt.

Principperne (se blueprintet, afsnit 5):
  1. En konklusion består af: emne, egenskab, værdi, kilde, tid + bevis + regel
  2. Fem former: findes, hændte, modsiger, mangler, gentages
  3. Tre bevisgrader: MAALT > DOKUMENTERET > SAGT
  4. Kan den ikke forstå teksten, gætter den ikke — den lægger den i
     læringsregisteret og siger det højt.

Endpoints:
    GET  /status          hvad den ved lige nu
    GET  /helbred         er den i live
    POST /udled           kør udledning over nye kilder
    GET  /register        læringsregisteret (det den ikke forstod)
    GET  /konklusioner    de udledte konklusioner
"""
import json
import os
import re
import sys
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

try:
    import psycopg
except ImportError:
    psycopg = None

PORT = int(os.environ.get("KONKLUSION_PORT", "6305"))

# Hvem ejer en konklusion uden en angivet ejer? DNA's egen konto i OpenWebUI
# (målt 2. nov 2026). Alt uden ejer er hans — en gæst må aldrig se det.
EJER_STANDARD = os.environ.get(
    "KONKLUSION_EJER_STANDARD",
    "99a107f4-b20e-468b-9b9e-a019c23c196e",
)
DSN = os.environ.get(
    "KONKLUSION_DSN",
    "host=127.0.0.1 port=5432 dbname=hjerne user=hjerne password=skift-mig",
)
OLLAMA = os.environ.get("EMBED_HOST", "127.0.0.1")
OLLAMA_PORT = int(os.environ.get("EMBED_PORT", "11434"))
EMBED_MODEL = os.environ.get("EMBED_MODEL", "bge-m3:latest")


# ---------------------------------------------------------------- udtræk
# Mønstrene er bevidst få og brede. Alt hvad de ikke fanger, ender i
# læringsregisteret — det er meningen, ikke en fejl.

CPR = re.compile(r"\b\d{6}[- ]?\d{4}\b")
SAGSNR = re.compile(r"\b(?:sags?[ -]?(?:nr\.?|nummer)\s*[:#]?\s*)([A-Z0-9][\w\-/]{4,})", re.I)
BELOEB = re.compile(r"\b(\d{1,3}(?:\.\d{3})*(?:,\d{2})?)\s*(kr\.?|DKK|EUR|€)", re.I)
DATO = re.compile(r"\b(\d{1,2})[./-](\d{1,2})[./-](\d{4})\b")
# Dato skrevet i ord: "den 9. november" / "20. august 2026" (DNA 2. nov 2026).
MAANEDER = ("januar|februar|marts|april|maj|juni|juli|august|september|"
            "oktober|november|december")
DATO_ORD = re.compile(r"\b(\d{1,2})\.?\s+(" + MAANEDER + r")(?:\s+(\d{4}))?\b", re.I)


def laes_dokument_dato(tekst: str):
    """Dokumentets EGET tidsstempel — labelen på dokumentet.

    DNA 5. nov 2026: et offentligt dokument er dateret, og datoen staar i
    brevhovedet ("21 juli 2020"), ikke i den enkelte saetning. Den dato er
    dokumentets label, og hver konklusion paa dokumentet arver den. Vi gaetter
    ikke: staar der ingen dato i hovedet, er datoen ukendt.
    """
    from datetime import datetime

    hoved = (tekst or "")[:600]
    for d, m_navn, y in DATO_ORD.findall(hoved):
        if not y:
            continue
        try:
            m = [x.lower() for x in MAANEDER.split("|")].index(m_navn.lower()) + 1
            return datetime(int(y), m, int(d))
        except ValueError:
            continue
    return None
TELEFON = re.compile(r"\b(?:\+45\s?)?(\d{8}|\d{2}\s\d{2}\s\d{2}\s\d{2})\b")
CVR = re.compile(r"\b(?:CVR[-\s]?(?:nr\.?)?\s*)?(\d{8})\b", re.I)

# Verber der markerer en hændelse
HAENDELSE = re.compile(
    r"\b(fjernet|anbragt|indstillet|ophævet|bevilget|afvist|indkaldt|"
    r"mødte|underskrev|afgav|traf|besluttede|vurderede|indberettede)\b",
    re.I,
)

# Dommer- og vurderingsord: når de optræder, er sætningen en TOLKNING,
# ikke en iagttagelse. Det skal stå i data.
TOLKNING = re.compile(
    r"\b(bekymret|bekymring|utilstrækkelig|mangelfuld|uhensigtsmæssig|"
    r"ikke\s+i\s+stand|hård|svigt|omsorgssvigt|uorden|ustabil)\b",
    re.I,
)

# Skabelonsprog der afslører en gengivelse, ikke en kilde
GENGIVELSE = re.compile(
    r"\b(der\s+er\s+bekymring|det\s+vurderes|det\s+skønnes|barnets\s+bedste|"
    r"i\s+forlængelse\s+af|på\s+baggrund\s+af)\b",
    re.I,
)


# Forbindelser i almindeligt sprog: "X er Y", "X ligger på Z", "X ønsker Y".
# Det er her hjernen kan læse samtaler og ikke kun sagsakter (DNA 2. nov 2026).
# Rækkefølgen betyder noget — den første der rammer vinder.
# Emnet må ikke indeholde et verbum: ellers bliver en hel sætning til et "emne"
# og resten til "værdi" (set 2. nov 2026: "Advokaten sad i bestyrelsen for det
# selskab Dio" = "anbragt hos samtidig med"). Emnet er 1-4 ord.
_EMNE = r"(?P<emne>[A-ZÆØÅ0-9][\wÆØÅæøå.\-]*(?:\s+[\wÆØÅæøå.\-]+){0,3})"
_PERSON_NAVN = r"(?P<emne>[A-ZÆØÅ][\wÆØÅæøå.\-]*(?:\s+[A-ZÆØÅ][\wÆØÅæøå.\-]*){0,2})"
FORBINDELSER = [
    (re.compile(r"^" + _EMNE + r"\s+ligger\s+(?:på|i|ved|under|hos)\s+"
                r"(?P<vaerdi>[^,]{2,120})", re.I), "ligger_paa"),
    (re.compile(r"^" + _EMNE + r"\s+hedder\s+(?P<vaerdi>[^,]{2,80})", re.I), "hedder"),
    (re.compile(r"^" + _EMNE + r"\s+består\s+af\s+(?P<vaerdi>[^,]{2,140})", re.I), "bestaar_af"),
    (re.compile(r"^" + _EMNE + r"\s+(?:\w+\s+)?(?:ønsker|vil\s+have|vil\s+gerne|"
                r"foretrækker|bruger|har\s+brug\s+for)\s+(?P<vaerdi>[^,]{3,200})", re.I), "oensker"),
    (re.compile(r"^" + _EMNE + r"\s+har\s+(?P<vaerdi>[^,]{3,180})", re.I), "har"),
    (re.compile(r"^" + _EMNE + r"\s+(?:er|blev|bliver)\s+"
                r"(?P<vaerdi>(?:en|et|den|det|ikke|nu|stadig)?[^,]{3,180})", re.I), "er"),
    (re.compile(r"^" + _EMNE + r"\s+(?:skal|møder|mødte)\s+i\s+ret\s+(?:i|ved|for)\s+"
                r"(?P<vaerdi>[^;]{3,120}?)(?:\s*[.;]\s*$|$)", re.I), "i_ret"),
    (re.compile(r"^" + _EMNE + r"\s+kan\s+"   # "Port 8100 kan vise grafen"
                r"(?P<vaerdi>[^.;]{5,200})", re.I), "kan"),
    (re.compile(r"^(?P<emne>[A-ZÆØÅ0-9][\wÆØÅæøå.\-]*)(?:\s+\w+){0,3}\s+jeg\s+"
                r"(?P<vaerdi>[^,]{5,200})", re.I), "siger"),
    (re.compile(r"^(?P<emne>[A-ZÆØÅ0-9][\wÆØÅæøå.\-]*)\s+(?:\w+\s+){0,2}?"
                r"(?:opdagede|fandt|konstaterede|målte|undersøgte|testede|"
                r"besluttede|fastslog)\s*,?\s*(?:at\s+)?(?P<vaerdi>[^,]{5,220})",
                re.I), "fandt"),
    (re.compile(r"^" + _EMNE + r"\s+(?:har|har\s+aftalt|aftalte)\s+med\s+"
                r"(?P<vaerdi>[^.;]{5,200})", re.I), "aftalte_med"),
    (re.compile(r"^(?P<emne>[A-ZÆØÅ0-9][\wÆØÅæøå.\-/ ]{1,60}?)\s+(?:blev|er\s+blevet)\s+"
                r"(?:henvist|sendt|flyttet)\s+(?P<vaerdi>[^.;]{5,200})", re.I), "blev"),
    (re.compile(r"^" + _EMNE + r"\s+(?:\w+\s+){0,3}?(?:skal|vil)\s+(?:ringe\s+til|"
                r"besøge|vise|sende|kontakte)\s+(?P<vaerdi>[^.;]{5,210}?)(?:\s+kl\.|$)", re.I), "skal_til"),
    # Klokkeslæt med tidszone: "kl. 16 dansk tid" / "kl. 15 i Portugal".
    (re.compile(r"^" + _EMNE + r"\s+(?:på|i)\s+\w+\s+kl\.?\s*(?P<vaerdi>\d{1,2}(?:[.:]\d{2})?"
                r"(?:\s+(?:dansk\s+tid|i\s+[A-ZÆØÅ][\wÆØÅæøå]+))?)", re.I), "klokken"),
]

# Sætningsgrænse. Et komma klipper KUN når næste ord starter en ny sætning;
# ellers er kommaet en del af værdien ("i ret i Svendborg den 9. november,
# fordi ..." skal blive én sætning til regel_er har læst den).
# Målt 2. nov 2026: datoer og bisætninger blev klippet af det gamle [.;]-split.
SÆTNING = re.compile(r"(?<=\w)[.;]\s+(?=[A-ZÆØÅ][a-zæøå])|(?<=\w),\s+(?=[A-ZÆØÅ][a-zæøå])|\n+")

# Person-roller i sagssprog: "Advokaten sad i bestyrelsen for Holmegårdshuset".
# Rollen skal have et sted, ellers er konklusionen halv (DNA 2. nov 2026).
_PERSON = r"(?P<person>[A-ZÆØÅ][\wÆØÅæøå.\- ]{1,45}?|\b(?:advokaten|moren|faren|barnet|sagsbehandleren|formanden|dommeren|psykologen|juraprofessoren)\b)"
ROLLE = re.compile(
    _PERSON + r"\s+(?:sad|sidder|var|er|blev|indgik)\s+i\s+"
    r"(?P<rolle>bestyrelsen|direktionen|ledelsen|ansættelse|praktik)\s+"
    r"(?:for|i|hos|ved)\s+(?P<sted>[A-ZÆØÅ][\wÆØÅæøå.\-]{1,50}(?:\s+[A-ZÆØÅ][\wÆØÅæøå.\-]{1,20}){0,2})",
    re.I)
OPDRAG = re.compile(
    _PERSON + r"\s+(?:blev\s+)?(?:anbragt|ansat|placeret)\s+(?:i|på|hos)\s+"
    r"(?P<sted>[A-ZÆØÅ][\wÆØÅæøå.\-]{1,50}(?:\s+[A-ZÆØÅ][\wÆØÅæøå.\-]{1,20}){0,2})",
    re.I)
# Embede: "Lisbeth Sten Jensen var sagkyndig dommer i kendelsen af 17. december."
EMBEDE = re.compile(
    r"(?P<person>[A-ZÆØÅ][\wÆØÅæøå.\-]*(?:\s+[A-ZÆØÅ][\wÆØÅæøå.\-]*){1,3})\s+"
    r"(?:var|er|blev|arbejdede\s+som|fungerede\s+som)\s+"
    r"(?P<embede>(?:sagkyndig\s+)?(?:dommer|advokat|psykolog|sagsbehandler|"
    r"formand|direktør|næstformand|læge|tilsynsførende))"
    r"(?:\s+(?:i|ved|for|på)\s+(?P<sted>[^.;,]{3,80}))?", re.I)
SAMTIDIG = re.compile(
    r"samtidig(?:t)?\s+med\s+(?:at\s+)?(?:hun|han|de|vedkommende)\s+(?P<handling>[^.;]{5,200})",
    re.I)
PERSON_FIX = re.compile(r"^(?:og|som|men)\s+|\s+(?:sad|sidder)$", re.I)

# Samtaleord der aldrig bliver et emne. "Men du", "Herfra", "Hvad" er ikke
# personer eller ting — de er stemmens bindeord (målt 2. nov 2026: de fyldte
# hele konklusionslisten med volapyk).
FYLD_EMNE = re.compile(
    r"^(men|og|så|fordi|derfor|hvad|hvordan|hvor|hvornår|herfra|derfra|"
    r"her|der|du|jeg|vi|man|det|den|de|han|hun|altså|ikke|ja|nej|"
    r"okay|ok|hmm|øh|nå|sådan|ligesom|bare|også|gerne|meget|lidt|"
    r"for|når|når\s+du|hvis|skal|kan|vil|er|har|var)\b",
    re.I)

# Danske småord. En sætning hvor de fylder over halvdelen, er ikke en
# sætning om noget — den er stemmens løse ord.
SMAAORD = re.compile(
    r"\b(der|som|at|og|jeg|du|vi|de|den|det|er|har|kan|skal|vil|på|i|"
    r"for|med|til|af|om|så|nu|her|jo|lidt|bare|meget|noget|ikke|hvad|"
    r"hvor|ser|ud|om|være|bliver|kommer|tager|giver)\b", re.I)

# Ord der bærer indhold: navne, steder, ting, tal.
NAVNEORD = re.compile(r"\b[A-ZÆØÅ][a-zæøå]{2,}|\b\d", )
# Uforståelige ord: Whisper skriver lyde som ord (fx "hinviser").
ULYD = re.compile(
    r"\b\w*(viser|stæb|skilds|tætter|vejledetning|rejn|konfidentjels)\w*\b", re.I)

# Ord der afslører at teksten er maskin- eller talteststøj, ikke viden.
TESTSTOEJ = re.compile(
    r"\b(test|prøve|testkør|kan du høre mig|høre mig|mikrofon|lydniveau|"
    r"check\s*check|en\s+to\s+tre)\b", re.I)

# Et ord der ikke findes: Whisper skriver lyde som ord. Ord uden vokal er
# mistænkelige.
ORD = re.compile(r"[a-zæøå]{3,}", re.I)


def er_stemmelarm(tekst: str) -> bool:
    """Er sætningen stemmens støj frem for DNA's mening?

    Målt 2. nov 2026: fodringen gav konklusioner som "Men du kan være lidt kig
    på, hvor der er hinviser" og "Stæbber siger et stæb vejledetning". Det er
    fejlhøringer, ikke viden. Vi gætter ikke på meningen — sætningen falder i
    registeret.
    # ponytail: to heuristikker, ikke en sprogmodel. Udvid når registeret viser huller.
    """
    t = (tekst or "").strip()
    if not t:
        return True
    # Systembeskeder og protokol (cron-påmindelser, værktøjsnoter) er ikke viden.
    if t.startswith("[") or "IMPORTANT: You are running" in t:
        return True
    if TESTSTOEJ.search(t):
        return True
    # Grin, gentagne bogstaver, ren interjektion: stemmen hørte noget forkert.
    if re.search(r"(h[åae]h)+|(\w)\2{4,}", t, re.I):
        return True
    ord_ = ORD.findall(t.lower())
    if len(ord_) >= 4:
        umulige = [o for o in ord_ if not re.search(r"[aeiouyæøå]", o)]
        if len(umulige) / len(ord_) > 0.2:
            return True
        # Næsten kun småord OG ingen navneord/tal: stemmens fyld.
        smaa = len(SMAAORD.findall(t))
        if smaa / len(ord_) > 0.55 and not NAVNEORD.search(t):
            return True
    # For kort til at bære en konklusion ("Åh.", "Tak.") — men en kort sætning
    # med tal eller navn kan godt bære noget ("Port 8300 er i brug").
    if len(ord_) <= 2 and not NAVNEORD.search(t):
        return True
    if ULYD.search(t):
        return True
    return False


# Et emne må ikke være en sætning: verbum i emnet = fejllæsning.
# Navn med stort begyndelsesbogstav: "Jeanette Gjørret". Bruges når en regel
# kun må gælde personer, ikke hele sætninger.
PERSON_NAVN = re.compile(r"^[A-ZÆØÅ][\wÆØÅæøå.\-]*(?:\s+[A-ZÆØÅ][\wÆØÅæøå.\-]*){0,2}$")
VERBUM = re.compile(
    r"\b(sad|sidder|stod|står|gik|går|kom|kommer|havde|har|var|er|blev|bliver|"
    r"kan|skal|vil|må|så|ser|sagde|siger|fik|får|gav|giver|tog|tager|"
    r"ligger|lå|kører|kørte|virker|virkede|bruger|brugte|skrev|skriver)\b",
    re.I,
)


# Emneord der ikke må blive et emne: pronominer og intetsigende fyld.
# Fra Honcho's deriverings-prompt (Plastic Labs): "leave no pronoun, 'it',
# 'there' or relative time unresolved" og "do not record conversational
# mechanics (greeting, thanking, acknowledging)". Det er den regel der gør
# en konklusion forståelig for en læser der kun kender navnet.
TOM_EMNE = re.compile(
    r"^(der|det|dette|disse|han|hun|vi|jeg|du|man|så|her|nu|"
    r"gælder|finder|kører|er|har|kan|skal|vil)\b|"
    r"^(den|de)\s+(?!gamle|nye|første|sidste|samme|øvrige|anden|ene)\b",
    re.I,
)
# Samtale-mekanik: hilsner, tak, bekræftelser. Aldrig en konklusion.
MEKANIK = re.compile(
    r"^(hej|hejsa|tak|tak for|ok|okay|ja|nej|godmorgen|godaften|"
    r"selvfølgelig|super|fint|godt|det lyder)\b", re.I,
)


def embed(tekst: str):
    """BGE-M3 via Ollama. Returnerer vektor eller None hvis den ikke svarer."""
    try:
        body = json.dumps({"model": EMBED_MODEL, "input": tekst[:8000]})
        c = http.client.HTTPConnection(OLLAMA, OLLAMA_PORT, timeout=30)
        c.request("POST", "/api/embed", body, {"Content-Type": "application/json"})
        r = c.getresponse()
        d = json.loads(r.read())
        c.close()
        return d["embeddings"][0]
    except Exception:
        return None


def find_iagttagelse_eller_tolkning(tekst: str) -> str:
    """Skeln iagttagelse fra tolkning fra konklusion — den vigtigste skelnen."""
    if GENGIVELSE.search(tekst):
        return "GENGIVELSE"
    if TOLKNING.search(tekst):
        return "TOLKNING"
    return "IAGTTAGELSE"


def udtraek(tekst: str) -> dict:
    """Træk det ud af en tekst som mønstre kan finde. Resten ignoreres."""
    return {
        "cpr": CPR.findall(tekst),
        "sagsnr": SAGSNR.findall(tekst),
        "beloeb": [f"{a} {b}" for a, b in BELOEB.findall(tekst)],
        "datoer": DATO.findall(tekst) + DATO_ORD.findall(tekst),
        "telefon": TELEFON.findall(tekst),
        "haendelser": HAENDELSE.findall(tekst),
        "slags": find_iagttagelse_eller_tolkning(tekst),
    }


def find_tid(tekst: str, kilde_tid=None):
    """Hvornår gjaldt det her i VERDEN?

    DNA 5. nov 2026: hver konklusion skal bære et tidspunkt — ellers kan man
    ikke se hvem der ændrede billedet, hvornår, og på hvilket grundlag.
    Rækkefølgen: en fuld dato i teksten selv (20. august 2026) vinder, fordi
    den står i kilden. Er der kun dag+måned (den 9. november), bruges året fra
    kildens tid. Findes ingen dato, er tidspunktet ukendt — vi gætter ikke.
    """
    from datetime import datetime

    for d, m, y in DATO.findall(tekst or ""):
        try:
            return datetime(int(y), int(m), int(d))
        except ValueError:
            continue
    for d, m_navn, y in DATO_ORD.findall(tekst or ""):
        m = [x.lower() for x in MAANEDER.split("|")].index(m_navn.lower()) + 1
        aar = int(y) if y else (kilde_tid.year if kilde_tid else None)
        if not aar:
            continue
        try:
            return datetime(aar, m, int(d))
        except ValueError:
            continue
    return None


def er_stoej(tekst: str) -> bool:
    """Maskinen der læser sin egen procesliste og tror det er viden.

    # ponytail: to mønstre, ikke en klassifikator. Udvid når støjen viser andre former.
    """
    t = tekst.lower()
    # DNA 5. nov 2026: stemmemærket "[taler: Danny (0.909, telefon · headset)]"
    # har mange tal og få ord — det lignede maskinvolapyk. Fjern mærket først,
    # ellers bliver beskeden kastet væk før den er læst.
    t = re.sub(r"^\s*\[\s*taler\s*:[^\]]*\]\s*", "", t, flags=re.I)
    if re.search(r"procesnr|subproces|portnavn|rekkeviden|doegntegelses", t):
        return True
    # Mange tekniske id'er, næsten ingen almindelige ord.
    ord_ = re.findall(r"[a-zæøå]{4,}", t)
    tal = re.findall(r"\d{4,}", t)
    return len(tal) >= 3 and len(ord_) < 6


def bevisgrad(tekst: str, kilde_type: str, observer: str = "") -> str:
    """MAALT > DOKUMENTERET > FOERSTEHAANDS > ANDENHAANDS > SAGT.

    FOERSTEHAANDS er DNA's egne ord om sig selv: kan ikke bevises af andre,
    men kan heller ikke afvises af et dokument. Det er den stærkeste kilde
    om en person — ikke den svageste (DNA 2. nov 2026).
    """
    if er_stoej(tekst):
        return "STOEJ"
    if kilde_type == "maalt":
        return "MAALT"
    if kilde_type in ("dokument", "journal", "afgoerelse"):
        return "DOKUMENTERET"
    if observer.lower() in ("dna", "danny"):
        return "FOERSTEHAANDS"
    if observer:
        return "ANDENHAANDS"
    return "SAGT"


# ------------------------------------------------------------- databasen

def sikr_skema(con):
    """Konklusionsmotorens egne tabeller. Kører hver gang — billigt."""
    with con.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS konklusion (
                id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
                emne         text NOT NULL,
                egenskab     text NOT NULL,
                vaerdi       text,
                form         text NOT NULL,     -- findes|haendte|modsiger|mangler|gentages
                bevis        text NOT NULL,     -- MAALT|DOKUMENTERET|SAGT
                regel        text NOT NULL,     -- hvilken regel udledte den
                kilde_id     text,
                kilde_tekst  text NOT NULL,
                slags        text,              -- IAGTTAGELSE|TOLKNING|GENGIVELSE
                sikkerhed    real,              -- embedding-lighed 0..1
                -- Bitemporalt (Zep/Graphiti-modellen, se blueprint 5.8):
                -- gyldig_fra/gyldig_til = hvornår kendsgerningen var sand i verden
                -- laert           = hvornår systemet fik den at vide
                -- ugyldig         = markeret af Drømmen, aldrig slettet
                gyldig_fra   timestamptz,
                gyldig_til   timestamptz,
                laert        timestamptz NOT NULL DEFAULT now(),
                ugyldig      boolean NOT NULL DEFAULT false,
                ugyldig_grund text,
                modsigelse_id uuid,             -- deles af de linjer der er uenige
                ejer         text,              -- OpenWebUI-brugerens id: hvem der ejer den
                oprettet     timestamptz NOT NULL DEFAULT now()
            )
        """)
        # Eksisterende baser: kolonnen kom til 2. nov 2026. Gæster skal have
        # deres eget rum, så en advokat aldrig kan læse DNA's børnesag.
        cur.execute("""
            ALTER TABLE konklusion ADD COLUMN IF NOT EXISTS ejer text
        """)
        cur.execute("""
            UPDATE konklusion SET ejer = %s WHERE ejer IS NULL
        """, (EJER_STANDARD,))
        cur.execute("""
            CREATE INDEX IF NOT EXISTS konklusion_ejer_idx
            ON konklusion (ejer, oprettet DESC)
        """)
        # Eksisterende baser: kolonnen kom til 2. nov 2026 sammen med
        # regel_modsiger der gemmer én linje pr. værdi i stedet for én klump.
        cur.execute("""
            ALTER TABLE konklusion ADD COLUMN IF NOT EXISTS modsigelse_id uuid
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS konklusion_modsigelse_idx
            ON konklusion (modsigelse_id) WHERE modsigelse_id IS NOT NULL
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS forstaaelse_register (
                id          bigserial PRIMARY KEY,
                kilde_id    text,
                tekst       text NOT NULL,
                grund       text NOT NULL,
                status      text NOT NULL DEFAULT 'NY',
                antal_set   int NOT NULL DEFAULT 1,
                kilde_type  text,
                oprettet    timestamptz NOT NULL DEFAULT now()
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS konklusion_emne_idx
            ON konklusion (emne, egenskab, oprettet DESC)
        """)
        # FUNDAMENT (DNA 4. nov 2026): den samme konklusion maa kun findes ÉN
        # gang pr. ejer. Reglen ligger i databasen, ikke i koden — saa kan
        # ingen kode, nu eller senere, lave dubletter. Maalt foer: 1351 raekker,
        # 508 dubletter (den værste 9 gange). Efter: 844 raekker, 844 unikke.
        # HENVISNING (DNA 4. nov 2026): hver konklusion skal kunne slaaes efter.
        # side_deres = dokumentets eget sidetal hvis det kan laeses.
        # side_vores = vores eget loebenummer, talt fra 1 — saa der ALTID findes
        # et nummer, ogsaa naar kommunen har gjort sidetallene ulaeselige.
        cur.execute("""
            ALTER TABLE konklusion ADD COLUMN IF NOT EXISTS dokument text
        """)
        cur.execute("""
            ALTER TABLE konklusion ADD COLUMN IF NOT EXISTS side_deres text
        """)
        cur.execute("""
            ALTER TABLE konklusion ADD COLUMN IF NOT EXISTS side_vores int
        """)
        # DNA 5. nov 2026: SIDENUMMERET HOERER MED I NOEGLEN. Den samme saetning
        # kan staa paa side 2 og side 87 i samme dokument — det er to fund med
        # hver sin henvisning, ikke en dublet. Uden sidenummer smed databasen
        # 1031 af 2041 konklusioner vaek i boernesagen (maalt).
        cur.execute("DROP INDEX IF EXISTS konklusion_unik")
        cur.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS konklusion_unik
            ON konklusion (emne, egenskab, coalesce(vaerdi,''),
                           coalesce(ejer,''), coalesce(dokument,''),
                           coalesce(side_vores, 0), coalesce(side_deres,''))
        """)
        # DNA 5. nov 2026: DOKUMENTET SOM EGEN KENDSGERNING. maindoc0.pdf er
        # 173 sider med mange breve indeni. Antallet af sider er en kendsgerning
        # om dokumentet og registreres ÉN gang — ikke gaettes ud fra de sider
        # vi tilfaeldigt fik tekst ud af.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS dokument (
                navn         text PRIMARY KEY,
                antal_sider  int NOT NULL,
                foerste_dato date,
                sidste_dato  date,
                laest        timestamptz NOT NULL DEFAULT now()
            )
        """)
        con.commit()


def gem_konklusion(con, k: dict):
    with con.cursor() as cur:
        cur.execute("""
            INSERT INTO konklusion
              (emne, egenskab, vaerdi, form, bevis, regel, kilde_id,
               kilde_tekst, slags, sikkerhed, modsigelse_id, ejer,
               dokument, side_deres, side_vores, gyldig_fra)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (emne, egenskab, coalesce(vaerdi,''), coalesce(ejer,''),
                         coalesce(dokument,''), coalesce(side_vores,0),
                         coalesce(side_deres,''))
            DO NOTHING
        """, (
            k["emne"], k["egenskab"], k.get("vaerdi"), k["form"], k["bevis"],
            k["regel"], k.get("kilde_id"), k["kilde_tekst"],
            k.get("slags"), k.get("sikkerhed"), k.get("modsigelse_id"),
            k.get("ejer") or EJER_STANDARD,
            k.get("dokument"), k.get("side_deres"), k.get("side_vores"),
            k.get("gyldig_fra"),
        ))
        # Hændelsesstyring (DNA 2. nov 2026): sig til i samme sekund en
        # konklusion lander, så broen kan vågne med det samme i stedet for at
        # spørge hvert minut. Sendes EFTER insert, så lytteren ser rækken.
        cur.execute("NOTIFY ny_konklusion")
        con.commit()


def gem_uforstaaet(con, kilde_id, tekst, grund, kilde_type):
    with con.cursor() as cur:
        # Tæl hvis den samme slags er set før
        cur.execute("""
            SELECT id, antal_set FROM forstaaelse_register
            WHERE tekst = %s AND status = 'NY' LIMIT 1
        """, (tekst[:2000],))
        r = cur.fetchone()
        if r:
            cur.execute(
                "UPDATE forstaaelse_register SET antal_set = antal_set + 1 WHERE id = %s",
                (r[0],),
            )
        else:
            cur.execute("""
                INSERT INTO forstaaelse_register (kilde_id, tekst, grund, kilde_type)
                VALUES (%s,%s,%s,%s)
            """, (kilde_id, tekst[:2000], grund, kilde_type))
        con.commit()


# ---------------------------------------------------------------- regler

def regel_laeser(con, tekst, kilde_id, kilde_type, taler=None,
                 dokument=None, side=None, ejer=None, kilde_tid=None,
                 dokument_dato=None):
    """Den danske læser — spaCy finder emne og genstand i sætningen.

    Rækkefølgen i motoren: de gamle mønstre prøver først, og kun hvis de ikke
    fandt noget, får læseren ordet. Så kan den ikke tage noget fra dem der
    allerede virker.

    Relationer bliver konklusioner af form 'findes' med egenskaben sat til
    verbet (fx 'snakke'), så broen kan slå op i registeret og sætte en kant
    som den plejer. Vi opfinder ikke en ny kanttype her — de findes allerede
    i grafen (KENDER, SAMARBEJDER_MED, KORRESPONDERER_MED ...).
    """
    try:
        from konklusion.laeser import laes
    except Exception:
        try:
            from laeser import laes          # når motor.py køres fra sin mappe
        except Exception as e:
            print(f"[motor] læseren kunne ikke indlæses: {e}", flush=True)
            return 0

    # DNA 4. nov 2026: SAETNINGEN ER KONKLUSIONEN. Laeseren giver den ordrette
    # tekst tilbage i f["tekst"]; den gemmes i kilde_tekst, som er det felt
    # brugeren ser. emne/egenskab/vaerdi er kun til soegning og graf.
    # Taleren foelger med, saa "jeg" bliver til den der taler.
    facts = laes(tekst, taler=taler, dokument=dokument, side=side, ejer=ejer)
    n = 0
    for f in facts:
        gem_konklusion(con, {
            "emne": f["emne"],
            "egenskab": f["egenskab"],
            "vaerdi": f["vaerdi"],
            "form": "haendte" if f["form"] == "haendte" else "findes",
            "bevis": bevisgrad(tekst, kilde_type),
            "regel": "laeser.ordret",
            "kilde_id": kilde_id,
            "kilde_tekst": f.get("tekst") or f["sats"],
            "slags": f.get("slags"),
            "dokument": f.get("dokument"),
            "side_deres": f.get("side_deres"),
            "side_vores": f.get("side_vores"),
            # TID (DNA 5. nov 2026): hvornaar gjaldt det her i verden. Datoen
            # kommer fra SAETNINGEN selv, ikke fra koerslen. "20. august 2026"
            # staar i teksten; findes ingen dato, er gyldig_fra NULL — vi
            # gaetter ikke, og "laert" er altid nu.
            # DNA 5. nov 2026: datoen hoerer til DOKUMENTET. Foerst proeves
            # saetningens egen dato, saa dokumentets tidsstempel, saa kildens tid.
            "gyldig_fra": (find_tid(f.get("tekst") or f["sats"], kilde_tid)
                           or (dokument_dato if f.get("dokument") else None)
                           or (kilde_tid if not f.get("dokument") else None)),
            # EJER (DNA 4. nov 2026): uden dette felt faldt alle konklusioner
            # tilbage paa standard-ejeren, og Asgers sager landede hos Danny.
            "ejer": ejer,
        })
        n += 1
    return n


def regel_findes(con, tekst, kilde_id, kilde_type, u, ejer=None):
    """Form 1 — noget optræder et sted, i en rolle, med en tilknytning."""
    n = 0
    for cpr in u["cpr"]:
        gem_konklusion(con, {
            "emne": f"person:{cpr}", "egenskab": "optræder_i", "vaerdi": kilde_id,
            "form": "findes", "bevis": bevisgrad(tekst, kilde_type),
            "regel": "findes.cpr", "kilde_id": kilde_id,
            "kilde_tekst": tekst[:2000], "slags": u["slags"], "ejer": ejer,
        })
        n += 1
    for s in u["sagsnr"]:
        gem_konklusion(con, {
            "emne": f"sag:{s}", "egenskab": "nævnt_i", "vaerdi": kilde_id,
            "form": "findes", "bevis": bevisgrad(tekst, kilde_type),
            "regel": "findes.sagsnr", "kilde_id": kilde_id,
            "kilde_tekst": tekst[:2000], "slags": u["slags"], "ejer": ejer,
        })
        n += 1
    return n


def regel_roller(con, tekst, kilde_id, kilde_type, u, ejer=None):
    """Form — en person i en rolle et sted, evt. samtidig med noget andet.

    DNA 2. nov 2026: sagssproget skriver "Advokaten sad i bestyrelsen for
    Holmegårdshuset, samtidig med at hun fører sager mod Børn- og
    Ungeudvalget". To konklusioner i én sætning, bundet af "samtidig med":
      personen -> rolle_i = bestyrelsen for Holmegårdshuset
      personen -> samtidig_med = fører sager mod Børn- og Ungeudvalget
    Rollen peger tilbage på et sted, ikke på en beskrivelse — uden stedet
    er konklusionen halv (DNA's egen indvending samme dag).
    # ponytail: fem mønstre, ikke en parser. Udvid når registeret viser huller.
    """
    n = 0
    sætninger = [s.strip() for s in re.split(r"[.;]\s+|\n+", tekst) if s.strip()]
    for s in sætninger:
        if len(s) < 15 or len(s) > 500:
            continue
        person, rolle_sted = None, None
        m = ROLLE.search(s)
        if m:
            person = (m.group("person") or "").strip()
            rolle_sted = f"{m.group('rolle').strip()} for {m.group('sted').strip()}"
        m3 = EMBEDE.search(s)
        if m3:
            person = person or (m3.group("person") or "").strip()
            if person == (m3.group("person") or "").strip():
                embede = m3.group("embede").strip()
                sted = (m3.group("sted") or "").strip()
                rolle_sted = f"{embede} i {sted}" if sted else embede
        m2 = OPDRAG.search(s)
        if m2:
            person = person or (m2.group("person") or "").strip()
            rolle_sted = f"opdraget/ansat i {m2.group('sted').strip()}"
        if not person or not rolle_sted:
            continue
        person = PERSON_FIX.sub("", person)   # "Advokaten" -> "Advokaten", men uden pronomen
        if len(person) < 2 or len(person) > 70:
            continue
        if TOM_EMNE.match(person) or VERBUM.search(person) or len(person.split()) > 4:
            continue
        gem_konklusion(con, {
            "emne": person[:120], "egenskab": "rolle_i", "vaerdi": rolle_sted[:220],
            "form": "findes", "bevis": bevisgrad(tekst, kilde_type),
            "regel": "rolle.sted", "kilde_id": kilde_id,
            "kilde_tekst": s[:2000], "slags": u["slags"], "ejer": ejer,
        })
        n += 1
        # "samtidig med at hun <handling>" — handlingen hører til samme person.
        m3 = SAMTIDIG.search(s)
        if m3:
            handling = m3.group("handling").strip(" ,")
            if 5 < len(handling) <= 200:
                gem_konklusion(con, {
                    "emne": person[:120], "egenskab": "samtidig_med",
                    "vaerdi": handling[:200], "form": "findes",
                    "bevis": bevisgrad(tekst, kilde_type),
                    "regel": "rolle.samtidig_med", "kilde_id": kilde_id,
                    "kilde_tekst": s[:2000], "slags": u["slags"], "ejer": ejer,
                })
                n += 1
    return n


def regel_er(con, tekst, kilde_id, kilde_type, u, ejer=None):
    """Form — X er Y / X ligger på Z / X har Y / X ønsker Y.

    Nogle sætninger bærer to ting: "Advokaten skal ringe til Danny på mandag
    kl. 16 dansk tid". Derfor én udledning pr. MØNSTER (dog højst ét pr.
    egenskab pr. sætning), ikke kun den første der rammer — ellers tabes
    klokken (DNA 2. nov 2026).

    Den form der gør motoren i stand til at læse almindeligt sprog, ikke kun
    CPR og sagsnumre. DNA 2. nov 2026: uden den kan hjernen intet lave af de
    konklusioner HC selv skrev.

    Vi udleder KUN når sætningen har et tydeligt subjekt og en tydelig
    forbindelse. Er vi i tvivl, falder den i registeret — gæt aldrig.
    # ponytail: fire mønstre, ikke en parser. Udvid når registeret viser huller.
    """
    n = 0
    brugte = set()   # egenskaber der allerede har givet en udledning i denne kilde
    for sætning in SÆTNING.split(tekst):
        s = sætning.strip()
        if len(s) < 12 or len(s) > 400:
            continue
        for moenster, egenskab in FORBINDELSER:
            if egenskab in brugte:
                continue
            m = moenster.search(s)
            if not m:
                continue
            emne = m.group("emne").strip(" ,\"'«»()")
            emne_lav = emne.lower()
            vaerdi = m.group("vaerdi").strip(" ,\"'«»().")
            if len(emne) < 2 or len(vaerdi) < 1:
                continue
            # Samtale-bindeord og fejlhøringer bliver aldrig til et emne.
            if FYLD_EMNE.match(emne) or er_stemmelarm(s):
                continue
            # Et emne der bærer et verbum er en sætning, ikke et subjekt.
            if VERBUM.search(emne) or len(emne.split()) > 4:
                continue
            # Klokken hører kun til et navn, ikke til en hel sætning.
            if egenskab == "klokken" and not PERSON_NAVN.match(emne):
                continue
            # Værdien må ikke indeholde et nyt subjekt-verbum-par; så er den
            # resten af en forkert opdelt sætning.
            if re.search(r"\b(og|men|fordi|så)\b", vaerdi, re.I) and len(vaerdi) > 120:
                continue
            # CPR/dato/sagsnummer har egne former — lad dem ligge.
            if CPR.search(emne_lav) or SAGSNR.search(emne_lav):
                continue
            gem_konklusion(con, {
                "emne": emne[:120], "egenskab": egenskab, "vaerdi": vaerdi[:400],
                "form": "findes", "bevis": bevisgrad(tekst, kilde_type),
                "regel": f"er.{egenskab}", "kilde_id": kilde_id,
                "kilde_tekst": s[:2000], "slags": u["slags"], "ejer": ejer,
            })
            n += 1
            brugte.add(egenskab)
            break   # én udledning pr. mønster, ikke pr. sætning
    return n


def regel_haendte(con, tekst, kilde_id, kilde_type, u, ejer=None):
    """Form 2 — en dato, en handling, en deltager."""
    if not u["datoer"] or not u["haendelser"]:
        return 0
    n = 0
    for d, m, y in u["datoer"]:
        m = m.zfill(2) if m.isdigit() else m
        y = y or "?"   # "den 9. november" har ikke altid årstal med
        for h in u["haendelser"]:
            gem_konklusion(con, {
                "emne": f"dato:{y}-{m.zfill(2)}-{d.zfill(2)}",
                "egenskab": "haendelse", "vaerdi": h.lower(),
                "form": "haendte", "bevis": bevisgrad(tekst, kilde_type),
                "regel": "haendte.dato+verbum", "kilde_id": kilde_id,
                "kilde_tekst": tekst[:2000], "slags": u["slags"], "ejer": ejer,
            })
            n += 1
    return n


def regel_modsiger(con):
    """Form 3 — samme emne+egenskab, to forskellige værdier.

    Vigtigt (DNA 2. nov 2026): modsigelsen gemmes som ÉN linje pr. værdi,
    hver med sin egen kilde — ikke som én streng med " | " imellem. Ellers
    ser en læser (og drømmen) kun én kilde der siger én ting, og så forsvinder
    selve uenigheden. Modsigelsen markeres i feltet `modsigelse_id`, som de
    berørte linjer deler.
    """
    # FUNDAMENT (DNA 3. nov 2026): grupperingen sker i Postgres, ikke i Python.
    # Før hentede vi HELE tabellen ud og grupperede i hukommelsen — målt kostede
    # det 1,5 s ved 200.000 rækker, og det vokser. Nu sender basen kun de
    # (emne, egenskab) der FAKTISK er uenige, med deres linjer. Antallet af
    # uenigheder er lille, uanset hvor stor tabellen bliver.
    with con.cursor() as cur:
        cur.execute("""
            WITH uenige AS (
                SELECT emne, egenskab
                FROM konklusion
                WHERE vaerdi IS NOT NULL AND form <> 'modsiger'
                GROUP BY emne, egenskab
                HAVING count(DISTINCT vaerdi) > 1
            )
            SELECT k.emne, k.egenskab, k.vaerdi, k.id, k.kilde_id, k.bevis, k.oprettet
            FROM konklusion k
            JOIN uenige u ON u.emne = k.emne AND u.egenskab = k.egenskab
            WHERE k.vaerdi IS NOT NULL AND k.form <> 'modsiger'
            ORDER BY k.emne, k.egenskab, k.oprettet
        """)
        raekker = cur.fetchall()

    grupper = {}
    for emne, egenskab, vaerdi, kid, kilde_id, bevis, oprettet in raekker:
        grupper.setdefault((emne, egenskab), []).append(
            {"vaerdi": vaerdi, "id": kid, "kilde_id": kilde_id,
             "bevis": bevis, "oprettet": oprettet})

    n = 0
    with con.cursor() as cur:
        for (emne, egenskab), linjer in grupper.items():
            vaerdier = {str(l["vaerdi"]) for l in linjer}
            if len(vaerdier) < 2:
                continue
            # Én modsigelses-id pr. (emne, egenskab) — stabil, ikke en ny pr. kørsel
            cur.execute("""
                SELECT modsigelse_id FROM konklusion
                WHERE emne = %s AND egenskab = %s AND modsigelse_id IS NOT NULL
                LIMIT 1
            """, (emne, egenskab))
            fundet = cur.fetchone()
            if fundet:
                modsigelse_id = fundet[0]
            else:
                cur.execute("SELECT gen_random_uuid()")
                modsigelse_id = cur.fetchone()[0]

            for l in linjer:
                cur.execute("""
                    UPDATE konklusion SET modsigelse_id = %s
                    WHERE id = %s AND (modsigelse_id IS NULL OR modsigelse_id <> %s)
                """, (modsigelse_id, l["id"], modsigelse_id))
                n += cur.rowcount

            # Selve modsigelsen som egen læsbar konklusion — den bærer
            # begge værdier, men som en sætning, ikke som en klumpet streng.
            sats = f"{emne}.{egenskab} har {len(vaerdier)} forskellige værdier: " + \
                   "; ".join(f"«{v}»" for v in sorted(vaerdier))
            gem_konklusion(con, {
                "emne": emne, "egenskab": f"modsiger:{egenskab}",
                "vaerdi": None,
                "form": "modsiger", "bevis": "DOKUMENTERET",
                "regel": "modsiger.samme_emne_forskellig_vaerdi",
                "kilde_tekst": sats, "modsigelse_id": modsigelse_id,
            })
            n += 1
    con.commit()
    return n


def regel_gentages(con, taerskel=3):
    """Form 5 — samme nøgle i mindst N kilder."""
    with con.cursor() as cur:
        cur.execute("""
            SELECT emne, egenskab, count(DISTINCT kilde_id) AS antal
            FROM konklusion
            WHERE kilde_id IS NOT NULL
            GROUP BY emne, egenskab
            HAVING count(DISTINCT kilde_id) >= %s
        """, (taerskel,))
        n = 0
        for emne, egenskab, antal in cur.fetchall():
            gem_konklusion(con, {
                "emne": emne, "egenskab": f"gentages:{egenskab}",
                "vaerdi": f"{antal} kilder", "form": "gentages",
                "bevis": "DOKUMENTERET",
                "regel": "gentages.mindst_N_kilder",
                "kilde_tekst": f"{emne}.{egenskab} optræder i {antal} kilder",
            })
            n += 1
    return n


def udled(con, kilder, tael_samlet=False):
    """Kør alle former over en liste kilder: [(id, tekst, type, ejer), ...]

    ejer = hvem i OpenWebUI der ejer samtalen (DNA 2. nov 2026). Gæster skal
    have deres eget rum: konklusioner uden ejer er DNA's egne, og en gæst må
    aldrig kunne læse dem.

    tael_samlet=False: de globale former (modsiger/gentages) kører KUN når
    nogen beder om det. Ellers tæller de gamle rækker med, hver gang en ny
    kilde kommer ind — og svaret siger 11 konklusioner om 12 kilder (målt
    2. nov 2026).
    """
    tal = {"laest": 0, "konklusioner": 0, "uforstaaet": 0}
    for rad in kilder:
        kilde_id, tekst, kilde_type = rad[0], rad[1], rad[2]
        ejer = rad[3] if len(rad) > 3 else ""
        _dok = rad[4] if len(rad) > 4 else None
        _side = rad[5] if len(rad) > 5 else None
        _kilde_tid = rad[6] if len(rad) > 6 else None
        tal["laest"] += 1
        if er_stoej(tekst):
            # Maskinvolapyk bliver aldrig en konklusion (DNA 2. nov 2026).
            gem_uforstaaet(con, kilde_id, tekst, "stoej", kilde_type)
            tal["uforstaaet"] += 1
            continue
        u = udtraek(tekst)
        # DNA 5. nov 2026: registeret gemmer den RENSEDE tekst — ikke den rå
        # med stemmemærket foran. Ellers staar der "[taler: Danny]" i en post
        # der skulle vise hvad Danny sagde.
        tekst = re.sub(r"^\s*\[\s*taler\s*:[^\]]*\]\s*", "", tekst, flags=re.I).strip() or tekst
        # DNA 5. nov 2026: LÆSEREN ER DEN ENESTE. De fire reserveveje
        # (findes/hændte/roller/er) blev bygget før læseren kunne gemme en
        # sætning ordret. De skar sætningen i emne/egenskab/værdi og gemte
        # stumperne — "Ingen af dine ting | er | væk". Ryddet væk, ikke
        # dæmpet: der er ingen trappe tilbage til det gamle mønster.
        # Taleren: læs den af beskedens eget mærke ("[taler: Danny]"), eller
        # af kildens ejer. Ukendt stemme bliver "Ukendt" — vi gætter ikke.
        try:
            from konklusion.laeser import find_taler
        except Exception:
            from laeser import find_taler      # naar motor.py koeres fra sin mappe
        # DNA 5. nov 2026: PROFILE. I et dokument er taleren UKENDT — find_taler
        # skal have dokumentet med, ellers gaar "jeg" til Danny. Maalt: tre
        # saetninger i boernesagen blev til "Danny kan ikke tage hjem til
        # Danny selv", hvor det var en foraelders ord.
        _taler = find_taler(tekst, _dok, ejer) or (f"bruger:{ejer}" if ejer and not _dok else "Ukendt")
        # DNA 2026-11-13: AI-ENS EGEN TALE ER IKKE VIDEN.
        # Helix' egne svar blev gemt som konklusioner — "Du sagde fjern alle
        # 164, men Danny stoppede for at rette drømmen først". Det er en
        # opsummering af samtalen, ikke en kendsgerning om verden. Naeste
        # model ville laese den som fakta. Kun menneskets ord og dokumenter
        # maa blive hukommelse.
        if not _dok and _taler in ("Helix", "Neo", "Ukendt", "ukendt"):
            continue
        _dok_dato = laes_dokument_dato(tekst) if _dok else None
        if _dok and len(rad) > 7 and rad[7]:
            # DNA 5. nov 2026: dokumentets ANTAL SIDER registreres som en
            # kendsgerning om dokumentet, ikke som en konklusion om verden.
            with con.cursor() as _c:
                _c.execute("""
                    INSERT INTO dokument (navn, antal_sider) VALUES (%s, %s)
                    ON CONFLICT (navn) DO UPDATE SET antal_sider = EXCLUDED.antal_sider
                """, (_dok, int(rad[7])))
                _c.execute("""
                    UPDATE dokument SET
                      foerste_dato = LEAST(coalesce(foerste_dato, %s::date), %s::date),
                      sidste_dato  = GREATEST(coalesce(sidste_dato, %s::date), %s::date)
                    WHERE navn = %s AND %s::date IS NOT NULL
                """, (_dok_dato, _dok_dato, _dok_dato, _dok_dato, _dok, _dok_dato))
            con.commit()
        fundet = regel_laeser(con, tekst, kilde_id, kilde_type, _taler,
                              _dok, _side, ejer, _kilde_tid, _dok_dato)

        if fundet == 0:
            # Intet mønster ramte. Gæt ikke — læg det i registeret.
            gem_uforstaaet(con, kilde_id, tekst, "ingen form ramte", kilde_type)
            tal["uforstaaet"] += 1
        else:
            tal["konklusioner"] += fundet

    if tael_samlet:
        tal["konklusioner"] += regel_modsiger(con)
        tal["konklusioner"] += regel_gentages(con)
    return tal


# --------------------------------------------------------------- serveren

class Handler(BaseHTTPRequestHandler):
    con = None

    def _json(self, obj, kode=200):
        b = json.dumps(obj, ensure_ascii=False, default=str).encode()
        self.send_response(kode)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def log_message(self, *a):
        pass

    def do_GET(self):
        p = urlparse(self.path)
        if p.path in ("/helbred", "/health"):
            return self._json({"status": "ok"})

        if p.path == "/status":
            with self.con.cursor() as cur:
                # DNA 2026-11-13: tallet skal vise hvad AI'en FAAR — ikke hvor
                # mange raekker der ligger i alt. De ugyldige taelles med i
                # "kasseret", saa man kan se oprydningen.
                cur.execute("""SELECT count(*) FILTER (WHERE NOT ugyldig),
                                      count(DISTINCT emne) FILTER (WHERE NOT ugyldig),
                                      count(*) FILTER (WHERE ugyldig)
                               FROM konklusion""")
                k, e, kasseret = cur.fetchone()
                cur.execute("SELECT count(*) FROM forstaaelse_register WHERE status='NY'")
                r = cur.fetchone()[0]
                cur.execute("""
                    SELECT bevis, count(*) FROM konklusion GROUP BY bevis
                """)
                b = dict(cur.fetchall())
            return self._json({
                "konklusioner": k, "emner": e,
                "kasseret": kasseret,
                "uforstaaet_i_register": r,
                "bevis": b,
                "kilder": "se /kilder",
            })

        if p.path == "/register":
            q = parse_qs(p.query)
            gr = int(q.get("antal", ["50"])[0])
            with self.con.cursor() as cur:
                cur.execute("""
                    SELECT id, tekst, grund, antal_set, kilde_type, oprettet
                    FROM forstaaelse_register WHERE status='NY'
                    ORDER BY antal_set DESC, oprettet DESC LIMIT %s
                """, (gr,))
                return self._json({"register": [
                    {"id": r[0], "tekst": r[1], "grund": r[2],
                     "antal": r[3], "type": r[4], "oprettet": r[5]}
                    for r in cur.fetchall()
                ]})

        if p.path == "/konklusioner":
            q = parse_qs(p.query)
            gr = int(q.get("antal", ["50"])[0])
            with self.con.cursor() as cur:
                cur.execute("""
                    SELECT emne, egenskab, vaerdi, form, bevis, regel, oprettet
                    FROM konklusion
                    WHERE NOT ugyldig
                    ORDER BY oprettet DESC LIMIT %s
                """, (gr,))
                return self._json({"konklusioner": [
                    {"emne": r[0], "egenskab": r[1], "vaerdi": r[2],
                     "form": r[3], "bevis": r[4], "regel": r[5], "oprettet": r[6]}
                    for r in cur.fetchall()
                ]})

        return self._json({"fejl": "ukendt sti"}, 404)

    def do_POST(self):
        p = urlparse(self.path)
        ln = int(self.headers.get("Content-Length", 0))
        data = json.loads(self.rfile.read(ln) or b"{}")

        if p.path == "/soeg":
            # Semantisk søgning (DNA 3. nov 2026): de konklusioner der LIGNER
            # spørgsmålet, ikke de nyeste. Se konklusion/soeg.py.
            try:
                from soeg import soeg as _soeg_fun
            except Exception:
                try:
                    from konklusion.soeg import soeg as _soeg_fun
                except Exception as e:
                    return self._json({"fejl": f"soegning utilgaengelig: {e}"}, 500)
            spoerg = (data.get("spoergsmaal") or "").strip()
            antal = int(data.get("antal") or 15)
            try:
                fund = _soeg_fun(self.con, spoerg, antal)
            except Exception as e:
                return self._json({"fejl": str(e), "fund": []}, 200)
            return self._json({"spoergsmaal": spoerg, "fund": fund})

        if p.path == "/udled":
            # dokument + side foelger med kilden (DNA 4. nov 2026), saa hver
            # konklusion kan henvises til praecis den side den stod paa.
            kilder = [
                (k.get("id", f"kilde-{i}"), k["tekst"], k.get("type", "ukendt"),
                 k.get("ejer", ""), k.get("dokument"), k.get("side"),
                 None, k.get("antal_sider"))
                for i, k in enumerate(data.get("kilder", []))
            ]
            if not kilder:
                return self._json({"fejl": "ingen kilder"}, 400)
            return self._json(udled(self.con, kilder,
                                    tael_samlet=bool(data.get("samlet"))))

        return self._json({"fejl": "ukendt sti"}, 404)


def start():
    if psycopg is None:
        print("psycopg mangler", file=sys.stderr)
        sys.exit(1)
    con = psycopg.connect(DSN, autocommit=True)
    # autocommit=True (DNA 4. nov 2026): foer delte én forbindelse uden autocommit
    # mellem alle traade, saa hver SELECT aabnede en transaktion der ALDRIG blev
    # afsluttet. Laasen blev hangende, ALTER TABLE ventede paa sig selv, og
    # hjernen kunne hverken laese eller skrive ("idle in transaction" i 7 min).
    # Maalt: 13 ventende forespoergsler. Hver saetning afslutter sig nu selv.
    sikr_skema(con)
    Handler.con = con
    print(f"Konklusionsmotoren lytter på {PORT}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    start()
