# Helix Super Light Brain — lillehjernen

Hjernen i Helix-systemet. Den erstatter Super Brains sprogmodel med regler:
Python udleder, Postgres husker, spaCy læser dansk.

Dette repository er hjernen ALENE. Ingen andre Helix-tjenester. Ét image,
én container.

## Hvad den er

Én container (`Helix_Light_Brain`) med alt hvad hjernen behøver:

| Tjeneste | Port | Hvad den gør |
|---|---|---|
| PostgreSQL 18 + AGE | 5432 | databasen og grafen |
| Ollama | 11434 | bge-m3, den ENESTE sprogmodel i containeren |
| Konklusionsmotoren | 6305 | udleder konklusioner af kilder |
| Drømmen | 6304 | kontrol: modsigelse, forældelse, retningsskift |
| Triggeren | — | læser nye samtaler og sender dem ind |
| Broen | — | konklusion → register → kant i grafen |
| Kategoriseringen | — | kategori og emne på hver konklusion |
| NPLL-scorer | 6080 | troværdighed 0–1 på kanter, ren Python |
| Ops | 6122 | noterne som graf |
| Viewer | 6123 | brugerfladen |

Ud af huset: 6301 (viewer), 6302 (hukommelsen), 6303 (ops),
6304 (drømmen), 6305 (motoren).

## Princippet

Super Brain dømte med en sprogmodel. En sprogmodel gætter. Super Light
udleder — og hver udledning kan spores tilbage til den række der bar den.

**Rollerne i én linje:** spaCy læser, Python dømmer, Postgres husker.

## Læseren

`konklusion/laeser.py` bruger spaCy + `da_core_news_lg` (dansk grammatikmodel,
602 MB, bagi image'et). Den finder grundled, udsagnsord og genstand i stedet
for at matche ord.

Regler der blev målt frem (3. nov 2026):

- **Førsteperson peger på taleren.** "Jeg" → den der ejer samtalen, læst af
  stemmemærket `[taler: X]`. Ukendt stemme giver ingen konklusion.
- **Pronominer bindes** til nærmeste egennavn — helst grundleddet i den
  foregående sætning, ikke det sidste navn.
- **Tal er facitpunkter** og skal med: "187.000", "27", "tre".
- **`obl` kan være genstand** i dansk ("til møde"), så den afvises kun når
  ordet er ren mængde eller tid.
- **AUX kan være ROOT** ("Danny skal til møde" har intet VERB).
- **Grundled-fallback** når spaCy tager et ukendt egennavn for et adverbium
  ("Holmegårdshuset" blev ADV).

Målt: 25 af 25 på to portioner børnesagssætninger.

## Drømmen

Drømmer på MÆNGDE, ikke på tid: 100 nye konklusioner eller 900 sekunders ro,
efter at broen har meldt færdig. Drømmens egne rækker tælles ikke med.

Ved uenighed peger den på den værdi der gælder — MÅLT/DOKUMENTERET slår SAGT,
og nyest slår ældst. Den tabende slettes ikke, den bliver i historikken.

Hændelsesstyret: motoren sender `NOTIFY ny_konklusion`, og broen og drømmen
lytter i stedet for at spørge hvert minut.

## Ejer-adskillelse

Hver konklusion bærer `ejer` = OpenWebUI-brugerens id. Alt uden ejer er
DNA's konto. En gæst kan ikke se DNA's børnesag.

OpenWebUI deler i forvejen alt per bruger (43 tabeller med `user_id` +
`access_grant`); hjernen følger det samme id.

## To veje ind

- **Hermes-krogen** (`sync_turn` i memory-provideren) — HUD, Telegram, CLI.
- **OpenWebUI-triggeren** — OW's chat-tabel.

Begge skriver til `hjerne.konklusion`, hver med sin ejer.

## Byg og kør

```bash
docker compose build
docker compose up -d
```

Image'et er selvkørende: spaCy og den danske model ligger i det, så
containeren kan læse dansk uden at hente noget udefra. Første start henter
bge-m3 ind i containeren.

Tjek at den lever:

```bash
curl http://127.0.0.1:6305/status
```

## Koble OpenWebUI på

Er OpenWebUI i samme docker-netværk:

```
http://helix-light-brain:6305
```

Ellers brug værtens IP og port 6305.

## Data

Alt data ligger i volumes og følger ikke med image'et:

- `brain_pg` — Postgres
- `brain_modeller` — Ollama-modeller
- `brain_obsidian` — viewerenes noter

Start forfra: `docker compose down -v`.

## Filerne

```
konklusion/motor.py     konklusionsmotoren (udledning, former, bevisgrader)
konklusion/laeser.py    den danske læser (spaCy)
drom/drom.py            drømmen (kontrol og konsolidering)
trigger.py              læser nye samtaler
enricher/bro.py         konklusion → register → kant
enricher/kategori.py    kategori og emne
npll/scorer.py          troværdighed på kanter
start.py                starter motor, drøm og trigger
scripts/supervisor.sh   starter alt i containeren
Dockerfile.hjerne       image'et (bruges)
```

## Kendte skævheder

- Adverbialer som "1,4 fire" kan havne i parentesen på en værdi.
- Gamle konklusioner fra før læseren blev rettet ligger stadig som støj.
