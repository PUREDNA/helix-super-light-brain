#!/usr/bin/env python3
"""Bygger OPS-datasættet til Helix Graph Viewer.

Læser KUN. Rører hverken Obsidian eller grafen.

Struktur (efter DNA's mønster — domæne = forælder, label = barn):
  - Hver .md-fil i vaulten  = en node
  - node.group              = TOPMAPPEN (fx 'Agenter', 'System')  <- domænet
  - node.age                = undermappen (labelen under domænet)
  - node.props              = frontmatter + metadata + første linjer
  - edges                   = [[wikilinks]] der kan bindes til en anden fil
                              + HAR_GREN fra domæne -> fil, og TILHØRER fil -> domæne
                              (så mappestrukturen bliver klikbar i træ/løs-visning)
  - node.type = 'mappe' for mappenoder

Skriver backend/data/ops.json — køres igen hver gang (idempotent).
"""
from __future__ import annotations

import json
import os
import re
from collections import Counter

VAULT = os.environ.get("OBSIDIAN_VAULT", "/vault")
UD = os.environ.get("OPS_JSON",
                    os.path.join(os.path.dirname(__file__), "data", "ops.json"))

SKIP_DIRS = {".obsidian", ".git", ".trash", "node_modules"}
BILLEDE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".mp3", ".mp4", ".pdf"}

# --- FACIT: agentnavne fra SOUL-filerne (DNA 2026-10-02) ---
# Mappenavnet er ikke altid agentens rigtige navn. SOUL-filen er facitlisten.
FACIT = {
    "bob-1": "Bob 1",
    "bob-2": "Bob 2",
    "bob-3": "Bob 3",
    "agent-one": "Agent One",
    "byggemand-bob": "Byggemand Bob",
    "gemini-ingest": "Gemini Ingest",
    "krypto": "Krypto",
    "mr-x": "Mr. X (Xerxes Aletheia)",
    "mr. x": "Mr. X (Xerxes Aletheia)",
    "pcb-per": "PCB Per",
    "poul-prompt": "Poul Prompt",
    "research": "Research",
    "revisor": "Revisoren",
    "sekretaer": "Sekretær Su",
    "sekretær su": "Sekretær Su",
    "trailer-team": "TIM",
    "trailer team": "TIM",
}

# Mapper der IKKE er agenter (stoette-mapper)
IKKE_AGENT = {"Realtime", "_Arkiv", "_Oversigt"}


def agentnavn(mappenavn: str) -> str:
    """Mappenavn -> agentens rigtige navn fra SOUL-filen."""
    return FACIT.get(mappenavn.lower(), mappenavn)


def frontmatter(raw: str) -> dict:
    """Læs YAML-frontmatter (simpelt — kun noegle: vaerdi)."""
    ud = {}
    if not raw.startswith("---"):
        return ud
    slut = raw.find("\n---", 3)
    if slut < 0:
        return ud
    for linje in raw[3:slut].split("\n"):
        if ":" in linje and not linje.strip().startswith("#"):
            k, _, v = linje.partition(":")
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k and v and not v.startswith("["):
                ud[k] = v
    return ud


def h1(raw: str) -> str:
    m = re.search(r"^#\s+(.+)$", raw, re.M)
    return m.group(1).strip() if m else ""


def main():
    noder, kanter = [], []
    tilfoejet_node = set()
    by_ref = {}
    filer = []

    # --- saml alle .md-filer ---
    for rod, dirs, fs in os.walk(VAULT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in fs:
            if f.lower().endswith(".md"):
                filer.append(os.path.join(rod, f))
    filer.sort()

    for p in filer:
        rel = os.path.relpath(p, VAULT).replace("\\", "/")
        try:
            raw = open(p, encoding="utf-8", errors="replace").read()
        except Exception:
            raw = ""
        dele = rel.split("/")
        top = dele[0] if len(dele) > 1 else "(rod)"
        under = "/".join(dele[1:-1]) if len(dele) > 2 else ""
        fm = frontmatter(raw)
        navn = fm.get("navn") or h1(raw) or os.path.basename(rel)[:-3]

        # --- DNA's regel (2026-10-02, rettet efter billede 1+2) ---
        # Facit er AG-grafen: MOC staar i midten, boernene rundt om — EET
        # barn pr. agent. Saadan skal OPS ogsaa se ud:
        #   DOMAENE = 'Agenter'   (foraelderen — boblen i midten)
        #   LABEL   = AGENTEN     (barnet — fx 'Agent One', 'Sekretær Su')
        #   DEL     = agentens ting (person_research, Rapporter …) = dens boern
        #
        # Trappestigen: domaene -> agent -> agentens ting. Hvert led kan
        # taendes/slukkes for sig. Som standard vises KUN domaenet og
        # agenterne — agentens boern ligger klar under den i sidebjaelken.
        #
        # dele[0] = vault-rod, dele[1] = agentmappe, dele[2:-1] = undermapper,
        # dele[-1] = filnavnet. DEL = den foerste ting under agenten.
        domene, label = top, (under or "noter")
        del_ = ""
        if top == "Agenter" and len(dele) > 1:
            domene = "Agenter"
            if dele[1] in IKKE_AGENT:
                label = dele[1] if len(dele) > 2 else os.path.basename(rel)[:-3]
                del_ = dele[2] if len(dele) > 3 else "noter"
            else:
                label = agentnavn(dele[1])
                # DEL = den umiddelbare ting under agenten (dens barn).
                del_ = dele[2] if len(dele) > 3 else "noter"
        elif top == "Agenter":
            domene = "Agenter"
            label = agentnavn(os.path.basename(rel)[:-3])
            del_ = "noter"
        # Alt indhold under Agenter/ er et BARN af agenten (skjult som
        # standard — kommer frem naar man taender agenten eller dens barn).
        arbejde = "1" if (top == "Agenter" and len(dele) > 1) else ""

        props = {
            "sti": rel,
            "filnavn": os.path.basename(rel),
            "mappe": os.path.dirname(rel) or "(rod)",
            "titel": navn,
            "bytes": os.path.getsize(p),
            "linjer": raw.count("\n") + 1,
            "wikilinks": len(re.findall(r"\[\[[^\]]+\]\]", raw)),
        }
        # frontmatter-felter med som kategori-praefiks (saa bundpanelet grupperer)
        for k, v in fm.items():
            if k in ("navn",):
                continue
            props[f"meta_{k}"] = v
        # foerste meningsfulde linjer som indhold
        brødtekst = re.sub(r"^---.*?\n---\n", "", raw, flags=re.S)
        props["indhold_uddrag"] = " ".join(brødtekst.split())[:600]

        noder.append({
            "id": rel,
            "label": navn,
            "group": domene,
            "age": label,
            "arbejde": arbejde,
            "del": del_,
            "role": fm.get("label") or label or "note",
            "props": props,
        })
        tilfoejet_node.add(rel)
        for nøgle in (os.path.basename(rel)[:-3], rel, rel[:-3], navn):
            by_ref.setdefault(nøgle.strip().lower(), rel)

    # --- mappenoder (saa domaenerne er klikbare og kan slukkes enkeltvis) ---
    mapper = Counter()
    for n in noder:
        dele = n["id"].split("/")
        for i in range(1, len(dele)):
            mapper["/".join(dele[:i])] += 1
    for mappe, antal in sorted(mapper.items()):
        mid = f"__mappe__/{mappe}"
        mdele = mappe.split("/")
        # samme regel: alt under Agenter/ hoerer til domaenet 'Agenter'
        if mdele[0] == "Agenter" and len(mdele) > 1:
            mgroup = "Agenter"
            # Labelen skal vaere AGENTENS navn (facit) — praecis som filerne,
            # saa mappen og dens noter hoerer til SAMME label i sidebjaelken.
            if len(mdele) == 2 and mdele[1] not in IKKE_AGENT:
                mage = agentnavn(mdele[1])
            else:
                mage = mdele[1]
        else:
            mgroup = mdele[0]
            mage = "mappe" if len(mdele) == 1 else "undermappe"
        # arbejde='1' for ALT under Agenter/ — bortset fra mappenoderne paa
        # dybde 2 (fx 'Agenter/Agent One'), som ER agenterne selv og vises.
        # Mappenoder paa dybde 1 ('Agenter') og 2 vises; resten er boern.
        if mdele[0] != "Agenter":
            marbejde = ""
        elif len(mdele) == 1:
            marbejde = ""            # 'Agenter' = midten, vises
        elif len(mdele) == 2 and mdele[1] not in IKKE_AGENT:
            marbejde = ""            # agenten selv, vises
        else:
            marbejde = "1"           # alt andet er barn, skjules
        noder.append({
            "id": mid,
            "label": agentnavn(mdele[-1]) if (mdele[0] == "Agenter"
                                              and len(mdele) == 2) else mdele[-1],
            "group": mgroup,
            "age": mage,
            "arbejde": marbejde,
            # mappenoder kan ogsaa vaere BOERN: en undermappes node hoerer
            # til agentens DEL-felt (samme navn som undermappen).
            "del": (mdele[2] if (mdele[0] == "Agenter" and len(mdele) > 2
                                 and marbejde == "1") else ""),
            "role": "mappe",
            "props": {"mappe": mappe, "titel": mdele[-1],
                      "antal_noter": str(antal), "sti": mappe},
        })
        # DNA 2026-10-02: INGEN selv-kant (from==to). Den gav en cirkel rundt
        # om noden selv i stedet for en forbindelse til midten. Mappenoder
        # forbindes KUN opad med TILHØRER (nedenfor).
        # undermappe -> foraeldermappe
        if "/" in mappe:
            forælder = f"__mappe__/{mappe.rsplit('/', 1)[0]}"
            kanter.append({"id": f"par-{mappe}", "from": mid, "to": forælder,
                           "label": "TILHØRER"})

    # --- kanter: hver fil -> sin mappe + wikilinks ---
    for n in noder:
        if n["id"].startswith("__mappe__/"):
            continue
        dele = n["id"].split("/")
        if len(dele) > 1:
            mappe_id = "__mappe__/" + "/".join(dele[:-1])
            kanter.append({"id": f"til-{n['id']}", "from": n["id"],
                           "to": mappe_id, "label": "TILHØRER"})

    for n in noder:
        if n["id"].startswith("__mappe__/"):
            continue
        p = os.path.join(VAULT, n["id"])
        try:
            raw = open(p, encoding="utf-8", errors="replace").read()
        except Exception:
            continue
        for m in re.finditer(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]", raw):
            tgt = by_ref.get(m.group(1).strip().lower())
            if tgt and tgt != n["id"]:
                kanter.append({"id": f"wl-{n['id']}-{tgt}", "from": n["id"],
                               "to": tgt, "label": "REFERERER_TIL"})

    # dedupe kanter
    set_k, unikke = set(), []
    for k in kanter:
        if k["id"] in set_k:
            continue
        set_k.add(k["id"])
        unikke.append(k)

    ud = {
        "graph": "OPS",
        "nodeCount": len(noder),
        "edgeCount": len(unikke),
        "nodes": noder,
        "edges": unikke,
    }
    os.makedirs(os.path.dirname(UD), exist_ok=True)
    with open(UD, "w", encoding="utf-8") as f:
        json.dump(ud, f, ensure_ascii=False)

    print(f"   skrevet: {UD}")
    print(f"   noter:   {sum(1 for n in noder if not n['id'].startswith('__mappe__/'))}")
    print(f"   mapper:  {sum(1 for n in noder if n['id'].startswith('__mappe__/'))}")
    print(f"   kanter:  {len(unikke)}")
    print(f"   domaener ({len(set(n['group'] for n in noder))}):")
    for d, a in Counter(n["group"] for n in noder).most_common():
        print(f"      {d:24} {a}")


if __name__ == "__main__":
    main()
