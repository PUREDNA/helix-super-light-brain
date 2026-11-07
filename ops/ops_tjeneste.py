#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ops-tjenesten — Helix Super Brains mellemhukommelse (lag 2).

Obsidian er arbejdsbordet: en mappe med almindelige Markdown-filer, som
mennesket kan læse og rette i. Denne tjeneste gør mappen til en del af
hjernen ved at bygge et billede af den — noter som knuder, wikilinks og
mappetilhørsforhold som kanter — og vise det i browseren.

Kører på sin egen port. Bruger KUN Pythons standardbibliotek, så den
virker i en hvilken som helst container uden flere pakker.

    GET /                    → oversigtssiden
    GET /api/ops             → {"nodes": [...], "edges": [...]}
    GET /api/ops_note?sti=X  → notens rå indhold (JSON: {"tekst": "..."})

Vault-stien sættes med miljøvariablen OPS_VAULT (standard: /vault).
"""
import json
import os
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

VAULT = os.environ.get("OPS_VAULT", "/vault")
PORT = int(os.environ.get("OPS_PORT", "6122"))
HOST = os.environ.get("OPS_HOST", "0.0.0.0")

# Wikilinks: [[Navn]] og [[Navn|vist navn]]
WIKILINK = re.compile(r"\[\[([^\]\|]+)(?:\|[^\]]+)?\]\]")


def byg_ops():
    """Læs vaulten og byg knuder + kanter. Kun læsning — rører intet."""
    noder = []
    kanter = []
    note_stier = {}      # filsti (relativ, uden .md) -> sti til filen

    if not os.path.isdir(VAULT):
        return {"nodes": [], "edges": [], "fejl": f"vault findes ikke: {VAULT}"}

    mapper = set()

    for rod, undermapper, filer in os.walk(VAULT):
        # Spring skjulte mapper over (.obsidian, .git, .trash)
        undermapper[:] = [d for d in undermapper if not d.startswith(".")]
        rel_rod = os.path.relpath(rod, VAULT)
        if rel_rod == ".":
            rel_rod = ""

        # Mappenoder
        for d in undermapper:
            del_sti = os.path.join(rel_rod, d) if rel_rod else d
            mapper.add(del_sti)

        for f in filer:
            if not f.lower().endswith(".md"):
                continue
            rel = os.path.join(rel_rod, f) if rel_rod else f
            navn = rel[:-3]                       # uden .md
            top = rel.split(os.sep)[0] if os.sep in rel else "(roden)"
            note_stier[navn.lower()] = rel

            # Notens gruppe = topmappen (domænet), age = undermappen
            under = os.path.dirname(rel)
            noder.append({
                "id": navn,
                "label": os.path.basename(navn),
                "group": top,
                "age": under if under else "(roden)",
                "type": "note",
            })

    # Mappenoder (så træet kan tegnes)
    for m in sorted(mapper):
        noder.append({
            "id": "__mappe__/" + m,
            "label": os.path.basename(m),
            "group": m.split(os.sep)[0],
            "age": os.path.dirname(m) or "(roden)",
            "type": "mappe",
        })

    # Kant 1: note → mappe, og undermappe → forældermappe
    for n in noder:
        if n["type"] == "note":
            under = n["age"]
            if under and under != "(roden)":
                kanter.append({"from": n["id"], "to": "__mappe__/" + under,
                               "type": "TILHØRER"})
            else:
                kanter.append({"from": n["id"], "to": "__mappe__/(roden)",
                               "type": "TILHØRER"})
    for m in sorted(mapper):
        forælder = os.path.dirname(m)
        if forælder:
            kanter.append({"from": "__mappe__/" + m, "to": "__mappe__/" + forælder,
                           "type": "TILHØRER"})

    # Kant 2: wikilinks (note → note)
    for n in noder:
        if n["type"] != "note":
            continue
        fil = os.path.join(VAULT, note_stier[n["id"].lower()])
        try:
            with open(fil, encoding="utf-8", errors="replace") as fh:
                tekst = fh.read()
        except Exception:
            continue
        for maal in WIKILINK.findall(tekst):
            maal = maal.strip()
            if maal.lower() in note_stier:
                kanter.append({"from": n["id"],
                               "to": note_stier[maal.lower()][:-3],
                               "type": "REFERERER_TIL"})

    return {"nodes": noder, "edges": kanter}


OVERSIGT = """<!DOCTYPE html>
<html lang="da"><head><meta charset="utf-8">
<title>Ops — Helix Super Brain</title>
<style>
 body{font:15px/1.6 system-ui,sans-serif;margin:0;background:#14171c;color:#dfe4ea}
 header{padding:14px 20px;background:#1c2027;border-bottom:1px solid #2c323c}
 h1{margin:0;font-size:17px;font-weight:600}
 .tal{color:#8b98a8;font-size:13px;margin-top:3px}
 main{padding:20px;max-width:1100px;margin:0 auto}
 .gitter{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:14px}
 .kort{background:#1c2027;border:1px solid #2c323c;border-radius:9px;padding:13px 15px}
 .kort h3{margin:0 0 8px;font-size:14px;color:#7fd1ff;font-weight:600}
 .kort ul{margin:0;padding-left:17px;font-size:13px;color:#b6c0cc}
 .kort li{margin:2px 0}
 a{color:#7fd1ff;text-decoration:none} a:hover{text-decoration:underline}
 .tom{color:#8b98a8;font-style:italic}
</style></head><body>
<header><h1>Ops — arbejdsbordet</h1>
<div class="tal">__TAL__</div></header>
<main><div class="gitter">__KORT__</div></main>
</body></html>"""


class Handler(BaseHTTPRequestHandler):
    def _svar(self, kode, indhold, ctype="application/json; charset=utf-8"):
        raa = indhold.encode("utf-8") if isinstance(indhold, str) else indhold
        self.send_response(kode)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raa)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(raa)
        except BrokenPipeError:
            pass

    def log_message(self, fmt, *a):
        pass    # hold loggen ren — supervisoren logger selv

    def do_GET(self):
        u = urlparse(self.path)

        if u.path in ("/", "/index.html"):
            d = byg_ops()
            noder = d.get("nodes", [])
            noter = [n for n in noder if n["type"] == "note"]
            grupper = {}
            for n in noter:
                grupper.setdefault(n["group"], []).append(n["label"])
            kort = ""
            for g in sorted(grupper):
                liste = "".join(f"<li>{x}</li>" for x in sorted(grupper[g])[:14])
                mere = (f"<li class='tom'>… og {len(grupper[g])-14} mere</li>"
                        if len(grupper[g]) > 14 else "")
                kort += (f"<div class='kort'><h3>{g} "
                         f"<span style='color:#8b98a8;font-weight:400'>"
                         f"({len(grupper[g])})</span></h3><ul>{liste}{mere}</ul></div>")
            if not kort:
                kort = ("<div class='kort tom'>Ingen noter endnu. "
                        "Læg Markdown-filer i vaulten — de dukker op her.</div>")
            html = (OVERSIGT
                    .replace("__TAL__",
                             f"{len(noter)} noter · {len(noder)-len(noter)} mapper · "
                             f"{len(d.get('edges', []))} forbindelser")
                    .replace("__KORT__", kort))
            self._svar(200, html, "text/html; charset=utf-8")
            return

        if u.path == "/api/ops":
            self._svar(200, json.dumps(byg_ops(), ensure_ascii=False))
            return

        if u.path == "/api/ops_note":
            q = parse_qs(u.query)
            sti = (q.get("sti") or [""])[0]
            # Sikkerhed: hold os inden for vaulten
            fuld = os.path.normpath(os.path.join(VAULT, sti))
            if not fuld.startswith(os.path.realpath(VAULT)):
                self._svar(403, json.dumps({"fejl": "uden for vaulten"}))
                return
            if not os.path.isfile(fuld):
                self._svar(404, json.dumps({"fejl": "noten findes ikke"}))
                return
            try:
                with open(fuld, encoding="utf-8", errors="replace") as fh:
                    self._svar(200, json.dumps({"tekst": fh.read()},
                                               ensure_ascii=False))
            except Exception as e:
                self._svar(500, json.dumps({"fejl": str(e)}))
            return

        if u.path == "/status":
            d = byg_ops()
            noter = [n for n in d.get("nodes", []) if n["type"] == "note"]
            self._svar(200, json.dumps({
                "status": "klar",
                "vault": VAULT,
                "noter": len(noter),
                "knuder": len(d.get("nodes", [])),
                "kanter": len(d.get("edges", [])),
            }, ensure_ascii=False))
            return

        self._svar(404, json.dumps({"fejl": "findes ikke"}))


def main():
    if not os.path.isdir(VAULT):
        print(f"[ops] ADVARSEL: vaulten '{VAULT}' findes ikke — "
              f"mount den med -v <din mappe>:/vault:ro", flush=True)
    else:
        d = byg_ops()
        print(f"[ops] læser '{VAULT}': {len(d.get('nodes',[]))} knuder, "
              f"{len(d.get('edges',[]))} kanter", flush=True)
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"[ops] lytter på http://{HOST}:{PORT}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
