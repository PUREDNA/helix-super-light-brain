#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Laeseren — spaCy paa dansk, inde i selve Konklusionsmotoren.

HVORFOR HER OG IKKE I BROEN (DNA 2. nov 2026): det er motoren der laeser
saetningen og laver fejlen. Broen faar en daarlig vare at binde. Derfor
rettes det her, hvor fejlen opstaar.

REGEL: denne fil maa ALDRIG kunne vaelte motoren. Er spaCy ikke installeret,
eller fejler den paa en saetning, siger vi det hoest og falder tilbage til
de gamle moenstre. En hjerne der ikke kan laese er vaerre end en hjerne der
laeser mindre.

Det den kan, maalt paa 300 register-tekster 2. nov 2026: 73 % af de
ikke-stoej tekster gav mindst ét brugbart faktum (141 af 192).

Det den IKKE kan alene, og som derfor er filtreret her:
  * Spoergsmaal og samtale-mekanik er ikke fakta.
  * Grundleddet skal vaere en person, en organisation eller en ting — ikke
    en dato, et pronomen eller en biseatning. Uden det filter gav spaCy
    "2026-10-11 undersoegte DNA" med datoen som grundled.
"""

from __future__ import annotations

import re

_nlp = None
_forsoegt = False

# Ord der aldrig kan vaere et grundled: pronominer og fyld.
TOM = {
    "som", "der", "det", "den", "de", "han", "hun", "vi", "jeg", "du", "man",
    "så", "her", "nu", "hvad", "hvem", "hvor", "hvordan", "hvornår", "dette",
    "disse", "noget", "nogen", "alt", "alle", "ingen", "intet",
}

SPOERGSMAAL = re.compile(r"\?\s*$")
# Systemsnak er ikke altid skrald (DNA 3. nov 2026). Et dagsbrev, en opgaveliste
# eller en fejlbesked er MASKINE der taler — ikke Danny. Men en sætning om at
# "motoren kører på port 6305" ER en kendsgerning. Derfor skelnes der:
#   MASKINE_START = teksten BEGYNDER som en maskinbesked -> skrald
#   MASKINE_ORD   = spredte systemord -> ikke nok alene, læseren afgør resten
MASKINE_START = re.compile(
    # DNA 5. nov 2026: "[taler: X]" er IKKE en maskinbesked — det er
    # stemmemærket der siger HVEM der taler. Det fangede 56 af 120 beskeder
    # og kastede dem væk som skrald. Det fjernes fra teksten i laes(),
    # ikke bruges som afvisning. Samme med "[ taler: X ]".
    r"^\s*(\[[a-zæøå ]+\]|dagsbrev|åbne opgaver|opgaver klar|"
    r"(cron|failure|traceback)[: _]|\[cron|error[: ]|warning[: ]|\$ |"
    r"python3 |docker |system:)",
    re.I,
)
# Mærker der ALDRIG er indhold: de fjernes fra teksten foer den laeses.
MASKINE_MÆRKE = re.compile(r"^\s*\[\s*(taler|note|helix|system)\s*:[^\]]*\]\s*", re.I)
# Hele beskeden er en opgaveliste/fejlrapport — så er der intet faktum i den.
MASKINE_HEL = re.compile(
    r"(åbne opgaver|ingen aftaler i morgen|opgaver klar|"
    r"\d+ ready, \d+ i gang|kalenderen er tom|crash-loop)",
    re.I,
)
# META er MINE egne forklaringer, ikke viden om DNA (målt 3. nov 2026).
# Halvdelen af konklusionerne blev "Sletningen vente på godkendelse" og
# "Inden for mit kontekstvindue kan jeg se mine egne fejl" — altså mig der
# forklarer mig, læst som om det var kendsgerninger om ham.
# META = MINE egne forklaringer, ikke viden om den der taler.
# DNA 4. nov 2026: den gamle regel ramte ALT med "jeg ... kan/skal/ved" og
# kastede hans egne praeferencer vaek ("Jeg kan godt lide kaffe"). Vi ved hvem
# der taler — saa det afgoeres af taleren, ikke af ordene. Her fanges kun
# systemsnak der ikke er en konklusion uanset hvem der siger det.
# DNA 5. nov 2026: det der goer en saetning til min egen systemsnak — ikke
# bare et ord som "konklusioner" som DNA selv bruger om sin egen sag.
SYSTEMSNAK = re.compile(
    r"\b(provider|parameter|kontekstvindue|kommando|terminal|traceback|"
    r"docker|systemd|api-noegle|api-nøgle|token|kodeord|logfil)\b",
    re.I,
)
META = re.compile(
    r"(godkendelse|kontekstvindue|konklusion(er)?\b|provider|"
    r"parameter|indekser|kommando|terminal|filen|koden)\b",
    re.I,
)
# Ord der aldrig er et rigtigt emne alene.
TOM_EMNE = {
    "i stedet", "nej", "ja", "brug", "mange udvidelser", "] udvidelser",
    "en som boks", "backup", "sletningen", "hud'en", "udvidelser",
}
# DNA 5. nov 2026: rammerne omkring en besked er ikke indhold. De skal
# afvises uanset hvor i teksten de staar, ikke kun i begyndelsen.
TEKNISK_MÆRKE_FJERN = re.compile(
    # DNA 5. nov 2026: Faster-Whisper og HUD'en skriver maerket baade med og
    # uden firkantede parenteser. Det skal fjernes uanset formen.
    r"\[\s*/?taler\s*:[^\]]*\]|\[\s*/?OUT-OF-BAND[^\]]*\]|"
    r"\bOUT-OF-BAND USER MESSAGE\b[^.]*?(?=\.|$)|"
    r"\[\s*/?(INST|MEMORY|System note)\s*\]|"
    r"\bOUT-OF-BAND USER MESSAGE\b|direct message from the user,? delivered once at this position; not tool output and not a new delivery when replayed from conversation history",
    re.I,
)
TEKNISK_MÆRKE = re.compile(
    r"OUT-OF-BAND|\[/?taler\s*:|\[System note\]|\[OUT-OF-BAND|"
    r"\[/?INST\]|\[/?MEMORY|direct message from the user",
    re.I,
)
FILTER_STOEJ = re.compile(
    r"nikolaj\s+wint|nicolai\s+wint|wint(er|her)\b|"
    r"undertekst|tekstet af|dansk tekst|"
    r"abonner p|kanal(er)?\b",
    re.I,
)
# Islandsk volapyk er altid fejlhoert stoej i en dansk samtale.
ISLANDSK = re.compile(
    r"\b(þ|ð|ætla|hvað|það|ekki|við|eru|þér|þú|hann|hún|af\s+þv|"
    r"þessu|þeir|þær|ekkert|sagði|kemur|komið)\b",
    re.I,
)
# DNA 2026-11-13: ORDRER OG TILLADELSER ER IKKE VIDEN.
# En lille model der laeser hukommelsen maa ALDRIG finde en konklusion der
# siger "du skal bygge X" eller "tilladelse givet" — den ville tro det var
# en sandhed om verden, eller en ordre den skulle foelge. Ordrer hoerer til
# samtalen, ikke til hukommelsen. Kun fakta gemmes.
ORDRE = re.compile(
    r"\b(du|vi)\s+(skal|maa|kan|boer)\s+"
    r"(lave|bygge|rette|slette|koere|saette|give|sende|finde|tjekke|se|tage|"
    r"starte|genstarte|aendre|skrive|vise|hente|bruge)\b"
    r"|\b(tilladelse|godkendelse)\b.{0,25}\b(givet|ok|ja|modtaget|har)\b"
    r"|^(slet|ret|byg|koer|start|genstart|aendr|skriv|vis|hent|giv|send|find|tjek|tag)\b"
    # "Ja tak, det maa du gerne" / "det maa du gerne" = tilladelse, ikke viden.
    r"|^(ja|nej|ok|okay|fint|godt)\b[^.!?]*\b(gerne|godt|bare|nu|endnu|først|straks|omgående)\b"
    r"|^(ja|nej|ok|okay)\b[,:\s]+(vis|slet|ret|byg|kør|start|giv|send|find|tjek|tag|hent|skriv|ændr)\b"
    r"|\bdu\s+(maa|kan)\s+gerne\b",
    re.I,
)


# DNA 2026-11-13: ARBEJDSNOTER ER IKKE VIDEN.
# "Danny tjekker om den har de nye rettelser" beskriver hvad vi gjorde i
# samtalen — ikke hvordan verden er. En model der laeser det senere tror det
# er en kendsgerning. Kun saetninger der beskriver en tilstand maa gemmes.
ARBEJDSNOTE = re.compile(
    r"^(danny|helix|jeg|vi|han|hun|de)\s+"
    r"(tjekker|finder|proever|ser|kigger|koerer|retter|bygger|"
    r"laver|saetter|venter|skal|vil|kan|goer|siger|faar|tager)\b"
    r"|^(nu|saa|sådan|derfor|ellers|imens|bagefter)\s",
    re.I,
)


def _har_substans(t: str) -> bool:
    """Har saetningen noget der kan slas op senere?

    Et navn, et tal, et sted eller en dato. "Der er grafen." har intet af det;
    "Dio bor i Brondby" har baade navn og sted.
    """
    if re.search(r"\d", t):                      # tal, dato, portnummer
        return True
    # Egennavn — men ikke et almindeligt ord blot fordi det staar foerst.
    if re.search(r"\b(?!(?:Der|Det|Den|Jeg|Du|Vi|Han|Hun|De|Nu|Saa|Så|Men|Og|"
                 r"Fordi|Hvis|Naar|Når|Sådan|Her|Derfor|Ellers|Imens)\b)"
                 r"[A-ZÆØÅ][a-zæøå]{2,}", t):
        return True
    if len(t.split()) >= 8:                      # lang nok til at baere indhold
        return True
    return False


# DNA 2026-11-13: SIDSTE SIGTE — kun fulde, beskrivende saetninger slipper ud.
# En konklusion skal kunne laeses som et svar paa "hvad ved vi?" uden kontekst.
_METASPROG = re.compile(
    r"(dokumentliste|hvem\s*/\s*hvornår|oprettet \d\d-\d\d|anmoder|anbefale|"
    r"check at|status:|^\s*\d+\.\s|--\s|##|\*\*|tør?t kørt|tørt kørt|"
    r"efterlyser|tabellen har|rapporten|kopien|omfanget)",
    re.I,
)


def er_metasprog(tekst: str) -> bool:
    """Er saetningen arbejdssprog fra vores egen samtale?

    DNA 13. nov 2026: lillehjernen skal svare paa "hvad ved vi om sagen?" —
    ikke "hvad lavede vi i tirsdags?". Formatering, todo-lister, statuslinjer
    og interne noter hoerer i samtalen, ikke i hukommelsen.
    """
    return bool(_METASPROG.search(tekst or ""))


MEKANIK = re.compile(
    # DNA 5. nov 2026: "Ja"/"Nej" er kun fyld naar de staar ALENE.
    # "Ja, du skal lave det omgående" er en ordre, ikke en hilsen.
    r"^(hej|hejsa|tak|ok|okay|ja|nej|godmorgen|godaften|nå|jamen|altså)\b[\s.,!]*$"
    r"|^(kan du|vil du|skal vi|hvad|hvordan|hvor|hvornår|hvem|er det|har du)\b",
    re.I,
)
# DNA 5. nov 2026: EN HILSEN ELLER ET INDLEDENDE ORD KOSTER ALDRIG RESTEN.
# "Jamen det er ikke så vigtigt. Nu skal vi se om vi kan..." blev kastet HELT
# fordi "Jamen" stod foerst. Reglen her fjerner kun det led der er mekanik,
# og lader resten af saetningen staa som kilden skrev den.
HILSEN_FORAN = re.compile(
    r"^\s*(jamen|altså|nåh|nå|okay|ok|ja|nej|hej|hejsa|tak)\s*[,!.:]?\s+",
    re.I,
)
# Et grundled der er en dato, et tal eller et tidspunkt er ikke et emne.
ER_DATO = re.compile(
    r"^\d{1,4}[./-]\d{1,2}([./-]\d{1,4})?$|^\d{4}$|^kl\.?\s*\d|^\d{1,2}[.:]\d{2}$"
)

# Verber der baerer en relation mellem to parter (DNA's eksempel:
# "Soeren har snakket med Peter" -> en kant, ikke en saetning).
RELATIONSVERB = {
    "snakke", "tale", "møde", "mødes", "ringe", "skrive", "sende", "give",
    "tage", "købe", "sælge", "betale", "ansætte", "fyre", "besøge", "hjælpe",
    "fortælle", "spørge", "svare", "aftale", "bestille", "levere", "modtage",
    "kende", "samarbejde", "korrespondere", "arbejde", "bo", "flytte", "rejse",
    "beslutte", "godkende", "afvise", "anmelde", "klage", "vidne", "undersøge",
    "vurdere", "instruere", "bistå", "repræsentere",
}


def _model():
    """Indlaes den danske model én gang. Fejler den, siger vi det og gaar videre."""
    global _nlp, _forsoegt
    if _forsoegt:
        return _nlp
    _forsoegt = True
    try:
        import spacy  # noqa: F401

        for navn in ("da_core_news_lg", "da_core_news_md", "da_core_news_sm"):
            try:
                _nlp = spacy.load(navn)
                break
            except Exception:
                continue
    except Exception as e:  # spaCy mangler helt
        print(f"[laeser] spaCy utilgaengelig: {e} — bruger de gamle moenstre",
              flush=True)
        _nlp = None
    return _nlp


def er_samtalestoej(tekst: str) -> bool:
    """Spoergsmaal, hoeflighed og stemmens eget filt-nonsens baerer ikke et faktum.

    DNA 3. nov 2026: Whisper samler stoej op som ord — stemmens eget navn
    ("Nikolaj Winter"), filtertekster og islandsk volapyk. Det er IKKE viden om
    ham, og det maa aldrig blive en konklusion.
    """
    t = (tekst or "").strip()
    # DNA 5. nov 2026: stemmemærket og de tekniske rammer fjernes FØRST.
    # "Ja, du skal lave det omgående" blev kastet væk som en hilsen, fordi
    # MEKANIK kun så ordet "Ja" i begyndelsen. Uden mærket er det en ordre.
    t = MASKINE_MÆRKE.sub("", t).strip()
    t = TEKNISK_MÆRKE_FJERN.sub(" ", t).strip()
    if not t:
        return True
    if SPOERGSMAAL.search(t) or MEKANIK.match(t):
        return True
    # DNA 2026-11-13: ordrer og tilladelser gemmes ALDRIG som konklusioner.
    if ORDRE.search(t):
        return True
    # Arbejdsnoter om hvad vi gjorde i samtalen er heller ikke viden.
    if ARBEJDSNOTE.search(t):
        return True
    # DNA 2026-11-13: en saetning uden navn, tal eller sted er ikke viden.
    # "Der er grafen." / "Sa broen peger paa tom luft." beskriver ingenting
    # der kan slas op senere.
    if not _har_substans(t):
        return True
    # Formatering, todo-lister og statuslinjer er arbejdssprog, ikke viden.
    if er_metasprog(t):
        return True
    if FILTER_STOEJ.search(t):
        return True
    # Maskinbeskeder: dagsbreve, opgavelister, fejlrapporter, cron.
    if MASKINE_START.search(t) or MASKINE_HEL.search(t):
        return True
    # Meta: mine egne forklaringer, ikke viden om DNA.
    # DNA 5. nov 2026: META maa KUN afvise en saetning der er SYSTEMSNAK — ikke
    # en hel besked. "Jeg vil godt have at du sletter alle de konklusioner"
    # blev kastet fordi ordet "konklusioner" staar i listen. Det er hans ord
    # om hans egen sag, ikke min forklaring. Bremsen virker nu kun naar
    # saetningen ogsaa taler om min drift (provider, parameter, kommando).
    if META.search(t) and SYSTEMSNAK.search(t):
        return True
    # DNA 5. nov 2026: TEKNISKE MÆRKER. "OUT-OF-BAND USER MESSAGE", "[taler: X]",
    # "[System note]" er rammer omkring beskeden, ikke noget nogen sagde.
    # De slap igennem naar de stod midt i en sammensmeltet tekst.
    if TEKNISK_MÆRKE.search(t):
        return True
    # Islandsk i en dansk samtale er altid fejlhoert stoej (DNA's egen regel).
    if ISLANDSK.search(t):
        return True
    return False


def _navn(tok) -> str:
    """Hele navnefrasen, ikke bare ordet.

    DNA 3. nov 2026: sammensatte navne blev klippet ("Advokaten Jeanette
    Gjørret" -> "Advokaten Jeanette"). Reglen er: et egennavn følger med
    sine nabo-egennavne, og en foranstillet titel ("Advokaten") hører med.
    """
    sent = tok.sent
    if tok.ent_type_:
        for e in sent.ents:
            if tok.i >= e.start and tok.i < e.end:
                return e.text.strip()

    dele = [tok.text]
    # Egennavne til højre for ordet hører til samme navn — også tal, så
    # "Opel Astra 1,4" ikke mister modelbetegnelsen.
    if tok.pos_ == "PROPN" or tok.ent_type_:
        for b in tok.rights:
            if b.pos_ in ("PROPN", "NUM") or b.ent_type_ or b.dep_ == "flat":
                dele.append(b.text)
            elif b.dep_ in ("flat", "appos") and b.pos_ in ("NOUN", "PROPN"):
                dele.append(b.text)
    else:
        for b in tok.rights:
            if b.dep_ in ("nmod", "flat", "appos") and b.pos_ in ("NOUN", "PROPN"):
                dele.append(b.text)
                break

    # Titler og kendeord til venstre.
    for b in tok.lefts:
        if b.dep_ in ("det", "amod", "poss", "case"):
            dele.insert(0, b.text)
        elif b.pos_ == "NOUN" and tok.pos_ == "PROPN":
            dele.insert(0, b.text)

    return " ".join(dele).strip()


def _loes_pronomen(tok, doc):
    """Bind et pronomen til det det peger paa (DNA 3. nov 2026).

    Maalt: 39 % af konklusionerne havde et pronomen som emne ("Nu", "Dem",
    "Efter du"). Pronomen-binding er det der goer dem til noget der kan laeses.

    Reglen er spaCys egen: et pronomen peger paa det naermeste navneord FØR
    det i samme saetning eller i den foregaaende — helst et egennavn. Kan vi
    ikke finde et, giver vi op (returnerer None); vi gaetter ikke.
    """
    if tok.pos_ != "PRON" and (tok.text or "").lower() not in TOM:
        return None

    def er_navn(t):
        return t.pos_ == "PROPN" or t.ent_type_ in ("PER", "ORG", "LOC")

    # 1) Samme saetning, foer pronomenet: helst et egennavn, ellers et navneord.
    for t in reversed([x for x in tok.sent if x.i < tok.i]):
        if er_navn(t):
            return _navn(t)
    for t in reversed([x for x in tok.sent if x.i < tok.i]):
        if t.pos_ == "NOUN" and t.text.lower() not in TOM:
            return _navn(t)

    # 2) Foregaaende saetninger, nyeste foerst. Tag GRUNDLEDDET — ikke det
    #    sidste navn. Maalt: "Soeren snakkede med Peter. Han sagde..." bandt
    #    "Han" til Peter fordi han stod sidst. Det er forkert; pronomenet peger
    #    paa den der HANDLEDE i den foregaaende saetning.
    saetninger = list(doc.sents)
    try:
        idx = saetninger.index(tok.sent)
    except ValueError:
        return None
    for sent in reversed(saetninger[:idx]):
        for t in sent:
            if t.dep_ in ("nsubj", "nsubj:pass") and er_navn(t):
                return _navn(t)
    for sent in reversed(saetninger[:idx]):
        for t in sent:
            if t.dep_ in ("nsubj", "nsubj:pass") and t.pos_ == "NOUN":
                return _navn(t)
    return None


def _brugbart(navn: str, tok=None) -> bool:
    """Kan dette vaere et emne eller en genstand? Dato, tal og pronomen: nej."""
    n = (navn or "").strip()
    if not n or len(n) < 2:
        return False
    if n.lower() in TOM:
        return False
    if ER_DATO.match(n):
        return False
    if tok is not None and tok.pos_ in ("NUM", "DET", "PRON", "ADP", "CCONJ"):
        return False
    # Et enkelt lille ord er ikke et emne.
    if len(n) <= 2:
        return False
    return True


# DNA's eget OpenWebUI-bruger-id. Kun denne ejer maa faa "Danny" som taler
# naar beskeden ikke baerer et stemmemaerke (DNA 11. nov 2026).
DANNY_EJER = "99a107f4-b20e-468b-9b9e-a019c23c196e"


def find_taler(tekst: str, dokument: str | None = None,
               ejer: str | None = None) -> str | None:
    """Hvem siger dette? Læs stemmegenkendelsens mærke, gæt ikke.

    DNA 3. nov 2026: beskeden kommer med et mærke i begyndelsen —
    '[taler: Danny (0.87, telefon)]' eller '[taler: ukendt]'. Det er den
    VEJVISER der afgør hvad "jeg" peger på. Uden mærket (skrevet besked)
    er det DNA selv, fordi det er hans samtale.

    DNA 5. nov 2026: DEN REGEL GAELDER KUN I SAMTALEN. I et dokument maa
    "jeg" ALDRIG blive til Danny — dokumentet er skrevet af hvem som helst
    (mor, sagsbehandler, en advokat), og der staar aldrig et talermærke i
    en PDF. Uden denne graense blev "jeg kan ikke tage hjem til min dreng"
    til "Danny kan ikke tage hjem til Danny selv" (maalt 3 steder i sagen).
    """
    m = re.search(r"\[taler:\s*([^\]\(,]+)", tekst or "", re.I)
    if m:
        navn = m.group(1).strip()
        if not navn or navn.lower() in ("ukendt", "unknown", "arvet"):
            return None     # vi ved ikke hvem — gæt ikke
        return navn
    # INTET MAERKE: kun i samtalen er det DNA — og kun naar ejeren ER DNA.
    # DNA 11. nov 2026: Asger skriver i OpenWebUI uden stemmemaerke. Reglen
    # gjorde hans 264 saetninger til "Danny siger", saa hans research forurenede
    # DNA's egne konklusioner. En fremmed ejer faar sit eget navn som taler.
    if dokument:
        return None
    if ejer and ejer != DANNY_EJER:
        return f"bruger:{ejer}"
    return "Danny"          # ingen stemme i beskeden = skrevet af DNA


# PAPIRE-FILTERET (DNA 4. nov 2026)
# En konklusion skal sige noget om VERDEN — noget der kan vaere sandt eller
# falsk om en sag. Papir siger kun noget om dokumentet selv: sidetal,
# sidehoveder, afsenderfelter, tomme felter. Det bliver ALDRIG en konklusion.
#
# Maalt: "E-mail: hebch@brondby.dk Side 116 af 170 Side 201 af 1220 Side 2 af 3
# Boerne- og familieafdelingen" blev en konklusion ud af maindoc0.pdf.
PAPIR = re.compile(
    r"(^|\s)(side|s\.)\s*\d+\s*(af|/)\s*\d+"          # Side 116 af 170
    r"|\bj\.?nr\.?\s*\d"                                # J.nr. 20-35975
    r"|\bcpr\.?\s*nr\.?"                                 # Cpr.nr.
    r"|^\s*\d{6}-?\d{4}\b"                                # CPR som foerste ord
    r"|\b\d{6}-\d{4}\b.*\bcpr\b"                          # CPR ... cpr.
    r"|\bcpr\b.*\b\d{6}-\d{4}\b"                          # cpr. ... CPR
    r"|\btlf\.?\s*[:+]?\s*[\d\s+]*\d{4}"                # Tlf. +4543...
    r"|^\s*e-?mail\s*:"                                  # E-mail: ...
    r"|\bwww\.|https?://"                               # webadresser
    r"|\b\d{1,2}\.\s*(januar|februar|marts|april|maj|juni|juli|august|"
    r"september|oktober|november|december)\s+\d{4}\s*$",   # dato alene
    re.I,
)

# PAPIRE-ORD: en saetning der KUN bestaar af disse baerer intet om verden.
PAPIR_ORD = {
    "side", "sider", "sidehoved", "sidefod", "bilag", "indhold", "fortegnelse",
    "kopi", "genpart", "dokument", "dokumentet", "journal", "sagsnummer",
    "afsnit", "kapitel", "udskrift", "vedlagt", "vedlaegges", "underskrift",
    "underskrevet", "initialer", "stempel", "blanket", "skema",
}


# BLANKET-SPROG (DNA 5. nov 2026). En blanket taler TIL læseren: "du skal
# vaere opmaerksom paa", "her kan du vedhæfte", "du er ikke part i sagen".
# Det er kommunens formular, ikke en konklusion om Dio eller Danny. Maalt i
# boernesagen: ca. 90 af 1625 raekker var ren blanket.
BLANKET = re.compile(
    r"\b(du skal være opmærksom på|her kan du|du kan vedhæfte|"
    r"du er ikke part i sagen|du vil ikke blive orienteret|"
    r"har du spørgsmål|kontakt os|udfyld|tryk på|klik på|"
    r"felter med|obligatoriske felter|sendes til|"
    r"underretning om udsatte børn|anonym underretning|"
    r"den, der får kendskab til|forældrene har ret til aktindsigt|"
    r"forældremyndighedsindehaveren (har|er)|"
    r"barnet oplysninger om barnet|oplysninger om barnet|"
    r"danny bekræfter, at de indtastede|"
    r"denne side opstår|teknisk årsag|"
    # DNA 5. nov 2026: udfyldningsvejledning og XML-affald. Kommunen har
    # vedhæftet selve formularfilen i stedet for at printe den (side 64), og
    # vejledningen gentager sig paa side 85, 88, 94: "Beskriv årsagen til din
    # henvendelse". Ingen af dem siger noget om Dio.
    r"beskriv årsagen|årsagen til din henvendelse|beskriv kort|"
    r"<[A-Za-zæøå]+[^>]*>|</\s*[A-Za-zæøå]+>|/>|>\s*<)\b",
    re.I,
)


def er_papir(saetning: str) -> bool:
    """Siger saetningen noget om dokumentet i stedet for om verden?"""
    t = (saetning or "").strip()
    if not t:
        return True
    # DNA 5. nov 2026: blanket-sprog er papir, uanset hvor i saetningen det staar.
    if BLANKET.search(t):
        return True
    if PAPIR.search(t):
        return True
    # Felt-agtig: "Noget: noget" uden et verbum, fx "E-mail: hebch@..."
    if ":" in t and len(t.split()) <= 6:
        return True
    # Kun papir-ord tilbage naar man fjerner tal og tegn?
    ord_i = [w.strip(".,;:()[]").lower() for w in t.split()]
    ord_i = [w for w in ord_i if w and not w.isdigit() and len(w) > 2]
    if len(ord_i) <= 2 and all(w in PAPIR_ORD for w in ord_i):
        return True
    return False


# TOM SNAK (DNA 4. nov 2026). "Nu siger jeg noget", "Forstaar du hvad jeg
# mener?" — der er ingen paastand i saetningen, saa der er intet at gemme.
TOMSNAK = re.compile(
    # DNA 5. nov 2026: den gamle regel fangede ALT der begyndte med "nu", "ja",
    # "jamen" eller "altså" — ogsaa en rigtig konklusion. "Jamen det er ikke
    # saa vigtigt med klagebogen nu" blev kastet. Fyld er en saetning der
    # KUN er fyld: et indledende ord og saa ikke noget indhold.
    r"^\s*(nu|ja|nej|okay|ok|så|altså|saa|altsaa|jamen|hmm|nemlig)\s*[.,!]?\s*$"
    r"|^(jeg )?(siger|sagde|taler|snakker|fortæller|fortalte|fortaeller)\b[^.?!]{0,40}$"
    r"|^(forstår|forstod|hører|ser) du\b[^.?!]*(mener|hvad)\?\s*$"
    r"|^(er du|kan du|vil du|skal vi|har du)\b[^.?!]*\?\s*$"
    r"|^(hvad|hvordan|hvornår|hvornaar|hvor|hvem|hvilken)\b[^.?!]*\?\s*$"
    r"|^\s*(tak|hej|hejsa|godmorgen|godaften|farvel)\b[^.?!]*$",
    re.I,
)


# EN SAETNING DER SLUTTER MIDT I (DNA 4. nov 2026). PDF'en bryder linjer, og
# spaCy tror hver linje er en saetning: "Boerne- og familieafdelingen anmoder
# om" blev gemt uden at sige hvad de anmoder om. Ordene er de samme — der
# mangler bare resten. Saadanne halve saetninger bliver ikke konklusioner.
HALV_SLUT = re.compile(
    # DNA 5. nov 2026: STORE/SMÅ BOGSTAVER AFGØR INTET. Faster-Whisper skriver
    # hvad den hører, og kan skrive "OM" midt i en sætning. Bindeordet afgøres
    # af dets PLADS: det staar efter et komma, eller efter et ord der ikke er
    # et tal eller en forkortelse. "nummerplade 2110 OM" er en nummerplade —
    # tallet foran gør det. "anmoder om" er et bindeord.
    r"(?:,\s*|\b(?!\d)[a-zæøå]{3,}\s+)"
    r"(om|at|som|der|og|eller|men|for|til|med|p[aa]|i|af|fra|ved|over|"
    r"under|efter|f[oa]r|uden|mellem|gennem|hos|samt|b[aa]de)\s*[.,;:]?\s*$",
    re.I,
)
# Kun naar bindeordet staar UDEN et rigtigt grundled bagefter: "og han har
# styr paa det" er en fortsaettelse. "Der blev afholdt 27 moeder" er en hel
# saetning — "der" er grundled. Derfor afgoeres det paa saetningens bygning.
HALV_START = re.compile(
    # DNA 5. nov 2026: starter saetningen med "og/eller/men/som/at", er det
    # KUN en fortsaettelse hvis der ikke findes et grundled i den.
    # "Og saa vil jeg gerne vide hvad du mener" har "jeg" — HEL saetning.
    # "og fra politiet der har reageret" har intet grundled — halv.
    r"^\s*(og|eller|men|som|at|samt)\s+(?![^.?!]*\b(jeg|du|han|hun|vi|de|den|"
    r"det|man)\b)[^.?!]*[.?!]\s*$",
    re.I,
)


def er_halv(saetning: str) -> bool:
    """Starter eller slutter saetningen midt i en anden saetning?"""
    t = (saetning or "").strip()
    if not t:
        return True
    # DNA 5. nov 2026: der er INGEN laengdegraense. "Jeg er glad" er en
    # konklusion. Den gamle regel kastede alt under tre ord vaek og sendte
    # saetningen ned i de gamle moenstre, som skar den i stykker.
    if HALV_SLUT.search(t):
        return True
    if HALV_START.search(t):
        return True

    # STARTER MIDT I (DNA 4. nov 2026). PDF bryder linjer, saa en saetning kan
    # begynde med et lille bogstav eller et komma: "nogen der har hoert
    # barnegraad", ", og fra politiet der har reageret...". En rigtig saetning
    # begynder med stort eller et tal.
    foerste = t[0]
    if foerste in ",;:":
        return True
    if foerste.isalpha() and foerste.islower():
        return True
    # Sidetal der er smuttet ind foran: "2 ikke er grund til bekymring for Dio".
    # Et enkelt eller to cifre efterfulgt af et lille ord er resten af en
    # saetning, ikke begyndelsen paa en ny.
    # Sidetal der er smuttet ind foran ("7 vurderer ikke, at..."). Det er ikke
    # en fortsaettelse — saetningen ER rigtig, tallet skal bare ikke med.
    # Derfor afvises den ikke her; tallet fjernes i _en_konklusion.

    # SLUTTER MED KOMMA: "Den foerste familieinstitution Danny og Dio kom paa,"
    # — saetningen er ikke faerdig.
    if t.rstrip().endswith(","):
        return True
    return False


# DNA 5. nov 2026: FORMLAR-RESTER OG SIDEOVERSKRIFTER. Maalt paa maindoc 1-3:
# 305 korte raekker, hvoraf de fleste er blanket-felter, KLE-koder, sidetal
# som "Opdateret 2019 2", og tabelhoveder som "Doer Postnummer By". De siger
# intet om verden — de er trykte felter og overskrifter.
RESTER = re.compile(
    r"^\s*(/|><|>|KLE\s|Udskrift af|Opdateret \d{4}|Se vejledning|"
    r"Bekræft oplysninger|Navn\s*$|Signerede|Besøg\s*$|Ankestyrelsen \d|"
    r"Dør Postnummer|Postnummer By|☒|☐|Fornavn\s|Efternavn\s|Adresse\s*$|"
    r"CPR\s*$|Cpr\s*$|Dato\s*$|Journalnummer|Sagsnummer\s*$|Side \d)",
    re.I,
)
BRUDT_TEGN = re.compile(r"[\ufffd\u0000-\u0008\u000e-\u001f]")
# DNA 5. nov 2026: MAILHOVEDER. Konvolutten (From/Sent/To) er tom — men SUBJECT
# er indhold: det siger hvad mailen handler om. Børnesager er fulde af mailkorrespondance,
# og emnet skal med som konklusion, ikke kastes væk.
MAILHOVED = re.compile(
    r"^\s*(from|to|sent|cc|bcc|dato|til|fra|sendt|vedhæftet)\s*:",
    re.I,
)
# Emnet læses som en konklusion: "Emne: Bekymring for Dio" -> "Bekymring for Dio".
EMNELINJE = re.compile(r"^\s*(?:subject|emne)\s*:\s*(.+)$", re.I | re.M)
MAIL_TYPE = re.compile(
    r"^\s*(?:from\s*:\s*.+|sent\s*:\s*.+)|(?:subject|emne)\s*:",
    re.I | re.M,
)


def er_mail(tekst: str) -> bool:
    """Er dette en e-mail? Dokumentprofilen kategoriserer den som sin egen slags."""
    return bool(MAIL_TYPE.search(tekst or ""))


# Hele konvolut-linjen fjernes fra teksten — baade "From: X" og "Sent: Thu, ...".
MAILHOVED_KONVOLUT = re.compile(
    r"^\s*(?:from|to|sent|cc|bcc|dato|til|fra|sendt|vedhæftet)\s*:[^\n]*$",
    re.I | re.M,
)
# DNA 5. nov 2026: FELTRÆKKE. "Personnummer Adresse Tværvej 8 4573 Højby
# Telefonnummer 50205203" er en udfyldt blanket, ikke en sætning.
FELTNAVN = re.compile(
    r"\b(personnummer|cpr[- ]?nr|adresse|telefonnummer|postnummer|"
    r"efternavn|fornavn|fødselsdato|nationalitet|statsborgerskab|"
    r"civilstand|beskæftigelse|indkomst|formue)\b",
    re.I,
)


def er_rest(saetning: str) -> bool:
    """Er saetningen en trykt rest — felt, kode, tabelhoved eller oedelagt tegn?"""
    t = (saetning or "").strip()
    if not t:
        return True
    if RESTER.search(t):
        return True
    if BRUDT_TEGN.search(t):
        return True
    # DNA 5. nov 2026: mailhoved og feltraekke er konvolut og blanket.
    if MAILHOVED.search(t):
        return True
    if FELTNAVN.search(t):
        _ord = re.findall(r"[A-Za-zÆØÅæøå]{4,}", t)
        _felter = len(FELTNAVN.findall(t))
        # Mange feltnavne OG ingen saetningsbygning: det er en udfyldt blanket.
        if _felter >= 1 and not re.search(
                r"\b(er|har|kan|skal|vil|blev|bliver|var|siger|sagde|gav|får|"
                r"fik|kom|gik|tog|vurderer|skriver|mener|bor)\b", t, re.I):
            return True
        if _felter >= 2:
            return True
    # Kort OG uden et verbum: "Danny Andersen cpr.", "BRØNDBY", "Navn".
    # En kort saetning MED udsagn er en rigtig konklusion ("Ut svarede ja").
    if len(t.split()) <= 4:
        ord_ = re.findall(r"[A-Za-zÆØÅæøå]{3,}", t)
        if len(ord_) <= 3 and not re.search(
                r"\b(er|har|kan|skal|vil|blev|bliver|var|siger|sagde|gav|får|"
                r"fik|kom|gik|tog|ser|så|vurderer|skriver|mener|bor)\b", t, re.I):
            return True
    return False


def er_tomsnak(saetning: str) -> bool:
    """Baerer saetningen en paastand — eller er den bare fyld?"""
    t = (saetning or "").strip()
    # DNA 5. nov 2026: ingen laengdegraense. Fyld afgoeres af moensteret,
    # ikke af hvor mange ord der er. "Danny er glad" er tre ord og en
    # konklusion; "Nu siger jeg noget" er fire ord og fyld.
    return bool(TOMSNAK.search(t))


# HENVISNING (DNA 4. nov 2026). Hver konklusion skal kunne slaaes efter:
# hvilket DOKUMENT den staar i, og hvilken SIDE. Er sidetallet gjort ulaeseligt
# (kommunen har lagt dem oveni hinanden), taeller vi selv siderne og bruger
# vores eget nummer. Saa findes der altid noget at henvise til.
SIDE_DERES = re.compile(r"\bside\s*(\d+)\s*(?:af|/)\s*(\d+)", re.I)


def _side_deres(tekst: str) -> str | None:
    """Læs dokumentets eget sidetal, hvis det kan ses i teksten."""
    m = SIDE_DERES.search(tekst or "")
    return f"{m.group(1)} af {m.group(2)}" if m else None


# ===================================================== DE TO PROFILER
# DNA 5. nov 2026: to slags tekst, to sæt regler. De maa ikke dele skæbne —
# en regel der er rigtig i en samtale kan være forkert i et dokument.
#
#   SAMTALE   : der er et talermærke, "jeg" er den der taler, hilsener er fyld,
#               og en kort sætning som "jeg er glad" ER en konklusion.
#   DOKUMENT  : der er intet talermærke, "jeg" bliver STÅENDE, blanket og
#               sidehoveder er papir, og hver sætning skal kunne slås efter
#               på dokument og side.
#
# Profilen vælges på om kilden er et dokument — ikke på hvad teksten ligner.
SAMTALE = "samtale"
DOKUMENT = "dokument"


def profil_for(dokument: str | None) -> str:
    """Hvilken profil skal denne tekst læses med?"""
    return DOKUMENT if dokument else SAMTALE


def laes(tekst: str, taler: str | None = None,
         dokument: str | None = None, side: int | None = None,
         ejer: str | None = None) -> list[dict]:
    """Laes en tekst og returnér de saetninger der ER konklusioner.

    DNA 4. nov 2026 — denne regel erstatter den gamle der splittede saetningen
    op i grundled/verbum/genstand og byggede en NY saetning ("Dio | bor |
    plejefamilie"). DNA's ord:

        "Havde vi nu faaet den til at tage selve konklusionen fra min saetning,
        ordret, saa den bare klipper det ud og siger: okay, det er en
        konklusion. Den begynder ikke at lave om paa det."

    Derfor: SAETNINGEN ER KONKLUSIONEN. Vi beholder den ordret. Det eneste vi
    aendrer er "jeg", der peger paa den der taler.

    Hvert fund er {tekst, emne, egenskab, vaerdi, sats}. `tekst` er den ordrette
    konklusion — det er DEN der gemmes i hjerne.konklusion. De tre felter
    emne/egenskab/vaerdi er kun til soegning og graf; de maa ikke erstatte
    teksten.
    """
    # DNA 5. nov 2026: DENNE LINJE VAR FEJLEN. Den kastede HELE beskeden naar
    # den foerste saetning var mekanik — "Hvad er det, du har lavet? Den muter
    # bare, og naar jeg trykker..." blev smidt vaek med en rigtig konklusion
    # i anden saetning. Afgoerelsen sker nu i _ordrette, saetning for saetning.
    nlp = _model()
    if nlp is None:
        # Uden spaCy kan vi ikke dele i saetninger. Tag hele teksten ordret.
        return _ordrette(tekst, None, taler, dokument, side)

    if taler is None:
        # DNA 5. nov 2026: taleren afgoeres i den rigtige profil. I et dokument
        # er der intet maerke, og saa er taleren UKENDT — "jeg" bliver staaende.
        taler = find_taler(tekst, dokument, ejer)
    # DNA 5. nov 2026: "ukendt" er en ADVARSEL, ikke et navn. Staar der
    # "[taler: ukendt]" i beskeden, ved vi ikke hvem der taler — men vi ved
    # at det ikke er Danny der skrev den. Saa kan "jeg" ikke blive til ham.
    if taler is None and re.search(r"\[taler:\s*ukendt", tekst or "", re.I):
        taler = "Ukendt"

    # PDF bryder linjer midt i saetninger. Saml dem FOER spaCy deler, ellers
    # tror spaCy at hver linje er sin egen saetning (DNA 4. nov 2026).
    # DNA 5. nov 2026: MAILHOVEDET SKAL LÆSES FØR LINJERNE SAMLES. Emnelinjen
    # staar paa sin egen linje — samler vi først, forsvinder den.
    _raa = (tekst or "")[:8000]
    _emne_fund = []
    if dokument and er_mail(_raa):
        for _e in (m.strip() for m in EMNELINJE.findall(_raa)):
            if _e:
                _k = _en_konklusion(_e, taler, None, dokument, side,
                                    slags="EMAIL_EMNE")
                if _k:
                    _emne_fund.append(_k)
        _raa = MAILHOVED_KONVOLUT.sub(" ", _raa)
        _raa = EMNELINJE.sub(" ", _raa)

    renset = re.sub(r"\s+", " ", _raa)
    # DNA 5. nov 2026: de tekniske rammer fjernes fra teksten FOER den læses.
    # "[ taler: ukendt ] Ej, du skal..." er en saetning nogen sagde — ikke
    # skrald — men mærket foran hører ikke til nogen saetning.
    renset = TEKNISK_MÆRKE_FJERN.sub(" ", renset).strip()
    if not renset:
        return []

    # DNA 5. nov 2026: EN MAIL ER EN MAIL. I dokumentprofilen bliver emnet
    # (Subject/Emne) til en konklusion — "Bekymring for Dio" siger noget om
    # sagen. Konvolutten (From/Sent/To) er data paa dokumentet, ikke indhold.
    # Det her hoerer KUN til dokumentprofilen, aldrig samtalen.
    if not renset.strip():
        return _emne_fund
    try:
        doc = nlp(renset)
    except Exception as e:
        print(f"[laeser] spaCy fejlede: {e}", flush=True)
        return _emne_fund + _ordrette(tekst, None, taler, dokument, side)

    return _emne_fund + _ordrette(tekst, doc, taler, dokument, side)


def _ordrette(tekst: str, doc, taler: str | None,
              dokument: str | None = None, side: int | None = None) -> list[dict]:
    """Del i saetninger og behold hver saetning ORDRET.

    Kun "jeg/mig/min/mit/mine" aendres til talerens navn — og kun naar vi ved
    hvem der taler. Er taleren ukendt, bliver "jeg" til "Ukendt".
    """
    if doc is not None:
        saetninger = [s for s in doc.sents]
    else:
        saetninger = []

    fund = []
    if not saetninger:
        # Ingen spaCy: del paa punktum, men behold teksten.
        # DNA 5. nov 2026: samme mail-regel som hovedvejen — emnet bliver en
        # konklusion, konvolutten fjernes.
        _t0 = tekst or ""
        if dokument and er_mail(_t0):
            for _e in EMNELINJE.findall(_t0):
                if _e.strip():
                    fund.append(_en_konklusion(_e.strip(), taler, None,
                                               dokument, side, slags="EMAIL_EMNE"))
            _t0 = MAILHOVED_KONVOLUT.sub(" ", _t0)
            _t0 = EMNELINJE.sub(" ", _t0)
        for raw in re.split(r"(?<=[.!?])\s+", _t0.strip()):
            raw = raw.strip()
            if len(raw) < 3:
                continue
            if (er_samtalestoej(raw) or er_papir(raw)
                    or er_tomsnak(raw) or er_halv(raw)):
                continue
            fund.append(_en_konklusion(raw, taler, None, dokument, side))
        return [f for f in fund if f]

    # DNA 5. nov 2026: EN HILSEN I STARTEN MAER ALDRIG KOSTE RESTEN AF BESKEDEN.
    # "Nå Helix, så er vi en ny session. Og jeg tænker..." har "Nå" foerst og
    # blev kastet HELT — selv om der stod rigtige konklusioner bagefter.
    # Er hele beskeden mekanik, falder den ud. Er den det ikke, afgoeres HVER
    # saetning for sig.
    _hele = er_samtalestoej(tekst)
    # DNA 5. nov 2026: HVERT LED AFGOERES FOR SIG. "Hvad er det, du har lavet
    # med den der dobbeltfunktion? Den muter bare, og naar jeg trykker..."
    # blev kastet HELT fordi FOERSTE saetning er et spoergsmaal. Men svarer
    # han paa sit eget spoergsmaal i naeste saetning, ER det en konklusion.
    # Derfor: findes der MINDST ÉN saetning uden fyld, maa hele beskeden
    # ikke forkastes — hver saetning afgoeres saa for sig.
    _har_indhold = any(
        not er_samtalestoej(re.sub(r"\s+", " ", s.text).strip())
        for s in saetninger if len(s.text.strip()) >= 3
    )
    if _hele and not _har_indhold:
        return []
    for sent in saetninger:
        raw = re.sub(r"\s+", " ", sent.text).strip()
        if len(raw) < 3:
            continue
        if er_samtalestoej(raw):
            # DNA 5. nov 2026: EN HILSEN KOSTER ALDRIG RESTEN. "Jamen det er
            # ikke saa vigtigt med klagebogen nu." blev kastet fordi "Jamen"
            # stod foerst — men saetningen baerer en konklusion. Hilsenen
            # fjernes, og resten afgoeres som enhver anden saetning.
            _u = HILSEN_FORAN.sub("", raw).strip()
            if (_u and _u != raw and not er_samtalestoej(_u)
                    and not er_papir(_u) and not er_tomsnak(_u) and not er_halv(_u)):
                fund.append(_en_konklusion(_u, taler, None, dokument, side))
                continue
            if not _hele and len(saetninger) > 1:
                continue
            for _d in re.split(r"(?<=[.!?])\s+", raw):
                _d = _d.strip()
                if len(_d) >= 3 and not er_samtalestoej(_d) and not er_papir(_d):
                    fund.append(_en_konklusion(_d, taler, None, dokument, side))
            continue
        # PAPIR og TOM SNAK (DNA 4. nov 2026): sidetal og fyld er ikke viden.
        # DNA 5. nov 2026: RESTER — trykte felter, KLE-koder, tabelhoveder,
        # oedelagte tegn. De er ikke saetninger nogen har skrevet.
        if er_papir(raw) or er_tomsnak(raw) or er_halv(raw) or er_rest(raw):
            continue
        # DNA 5. nov 2026: der kraeves IKKE et verbum. "Handling har
        # konsekvens" faldt ud her og blev derefter skaaret i stykker af
        # det gamle moenster. Saetningen er konklusionen — punktum.
        fund.append(_en_konklusion(raw, taler, sent, dokument, side))
    return [f for f in fund if f]


def _en_konklusion(raw: str, taler: str | None, sent,
                   dokument: str | None = None, side: int | None = None,
                   slags: str | None = None) -> dict | None:
    """Byg ét fund ud af ÉN saetning — teksten bevares ordret."""
    navn = taler or "Ukendt"
    tekst = raw

    # Kun foersteperson erstattes. "Jeg bor i Portugal" -> "Danny bor i Portugal".
    # PDF bryder linjer midt i saetninger (DNA 4. nov 2026). Saml dem, saa
    # konklusionen kan laeses som den blev skrevet — ordene er de samme.
    tekst = re.sub(r"\s+", " ", raw).strip()
    # Sidetal foran saetningen er papir, ikke indhold (DNA 4. nov 2026).
    # DNA 5. nov 2026: reglen fandtes to steder og omskrev KILDEKODEN —
    # "dagbogen, saa den" blev til "dagbogen. saa den". Nu fjernes tallet
    # KUN naar det staar foran et lille bogstav (en sidetal-rest), og
    # kommaet bevares.
    if re.match(r"^\s*\d{1,3}\s+[a-zæøå]", tekst):
        tekst = re.sub(r"^\s*\d{1,3}\s+", "", tekst)

    if sent is not None:
        ordene = []
        for t in sent:
            # DNA 5. nov 2026: kun i SAMTALEN erstattes foersteperson.
            # I et dokument er taleren ukendt — "jeg" bliver staaende, saa
            # man kan se at det ikke er Danny der taler.
            # DNA 5. nov 2026: UKENDT MAAL IKKE IND I EN SAETNING. "Ukendt er
            # bange for at blande Ukendt" blev meningsloest. Naar vi ikke ved
            # hvem der taler, bliver "jeg" STAAENDE som det blev sagt.
            if (taler is not None and navn != "Ukendt"
                    and t.pos_ == "PRON"
                    and (t.text or "").lower() in ("jeg", "mig", "min", "mit", "mine")):
                ordene.append(navn)
            else:
                ordene.append(t.text)
        tekst = " ".join(ordene)
        # spaCy splitter tegn; saet det sammen som dansk skrives.
        # DNA 5. nov 2026: ogsaa apostrof — "Dio's" blev til "Dio ' s".
        tekst = re.sub(r"\s+([’'])\s*", r"\1", tekst)
        tekst = re.sub(r"\s+([.,;:!?])", r"\1", tekst).strip()
        # Sidetal foran saetningen er papir — fjernes EFTER samlingen, men
        # DNA 5. nov 2026: kun tallet, ALDRIG kilden. Den gamle linje efter
        # denne satte "dagbogen, saa" til "dagbogen. saa" — ordene skal staa
        # som de blev sagt.
        if re.match(r"^\d{1,3}\s+[a-zæøå]", tekst):
            tekst = re.sub(r"^\d{1,3}\s+", "", tekst)
    else:
        tekst = re.sub(r"\b(jeg|mig|min|mit|mine)\b", navn, raw, flags=re.I)

    # DNA 5. nov 2026: DEN DER TALER OG DEN DER LYTTES TIL.
    # Naar det er MIG der siger saetningen, er "du" Danny — ikke mig selv.
    # MEN: naar det er DNA der taler, betyder "du" Helix, og den skal staa.
    # Kun naar taleren er en anden end Danny maa "du" blive til Danny.
    if (navn.lower() not in ("danny", "dna", "ukendt")
            and sent is not None):
        tekst = re.sub(r"\b(du|dig|din|dit|dine)\b", "Danny", tekst, flags=re.I)
        # ...og kun i den saetning hvor DNA faktisk bliver talt TIL.
        # "Jeg vil gerne have" har ingen "du" — den skal staa urørt.

    # DNA 5. nov 2026: et komma bliver ALDRIG et punktum. Min gamle
    # "så"-regel omskrev kilden — "dagbogen, så den er registreret" blev
    # "dagbogen. så den er". spaCy deler sætningerne selv; den skal ikke
    # have hjælp der ændrer ordene.


    # Emne/egenskab/vaerdi: kun til soegning. Teksten er facit.
    emne = egenskab = vaerdi = None
    if sent is not None:
        for t in sent:
            if t.dep_ in ("nsubj", "nsubj:pass"):
                emne = navn if (t.text or "").lower() in ("jeg", "mig") else _navn(t)
                break
        for t in sent:
            if t.pos_ == "VERB" and t.dep_ in ("ROOT", "conj"):
                egenskab = (t.lemma_ or t.text).lower()
                break
        for t in sent:
            if t.dep_ in ("dobj", "obj", "iobj", "obl") and t.pos_ in ("NOUN", "PROPN"):
                vaerdi = _navn(t)
                break

    return {
        "tekst": tekst,
        # DNA 5. nov 2026: et mail-emne er sit eget maerke, saa man kan se
        # forskel paa "emnet paa mailen" og "en saetning i mailen".
        "slags": slags,
        "emne": emne or navn,
        "egenskab": egenskab or "siger",
        "vaerdi": vaerdi,
        "form": "findes",
        "relationel": False,
        "sats": tekst,
        "bevis": "SAGT",
        "dokument": dokument,
        "side_deres": _side_deres(raw),
        "side_vores": side,
    }


def _selvtest():
    """Den mindste proeve der fejler hvis laeseren holder op med at virke."""
    if _model() is None:
        print("laeser: spaCy ikke installeret — selvtest springes over")
        return

    f = laes("Søren har snakket med Peter om mødet på mandag klokken 14.")
    assert f, "fandt intet faktum i DNA's eget eksempel"
    par = [(x["emne"], x["vaerdi"]) for x in f]
    assert any("Søren" in a and b and "Peter" in b for a, b in par), \
        f"Soeren-Peter-relationen mangler: {f}"
    assert any(x["relationel"] for x in f), "snakke skulle give en relation"

    # En dato maa aldrig blive grundled.
    g = laes("2026-10-11 undersøgte DNA Tiiny AI Pocket Lab.")
    assert not any(x["emne"].startswith("2026") for x in g), \
        f"dato blev grundled: {g}"

    # Spoergsmaal er ikke fakta.
    assert laes("Kan du ikke lige prøve at finde ud af det?") == [], \
        "spoergsmaal blev laest som faktum"

    print("laeser: selvtest OK")


if __name__ == "__main__":
    _selvtest()
