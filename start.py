#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
start.py — Helix Super Light Brain.

Starter alt inde i containeren i rigtig rækkefølge:
  1. Ollama med BGE-M3 (den eneste model — til søgning, ikke konklusioner)
  2. Konklusionsmotoren på 6305
  3. Drømmen på 6304
  4. En simpel viewer på 6301 der viser hvad hjernen ved
  5. En lille API-gateway på 6302 (Hukommelsen) som Super Brain-klienterne kender

Holder sig selv i live og genstarter en død del.
"""
import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import http.client

from openapi import OPENAPI, hent, post

KONKLUSION = "http://127.0.0.1:6305"
DROM = "http://127.0.0.1:6304"
VIEWER_PORT = int(os.environ.get("VIEWER_PORT", "6301"))
HUK_PORT = int(os.environ.get("HUKOMMELSE_PORT", "6302"))


def hent(base, sti, timeout=5):
    try:
        u = urlparse(base)
        c = http.client.HTTPConnection(u.hostname, u.port, timeout=timeout)
        c.request("GET", sti)
        r = c.getresponse()
        d = json.loads(r.read() or b"{}")
        c.close()
        return d
    except Exception as e:
        return {"fejl": str(e)}


HTML = """<!doctype html><html lang="da"><head><meta charset="utf-8">
<title>Lille Hjernen</title>
<style>
 body{margin:0;font:15px/1.5 system-ui,sans-serif;background:#0d1117;color:#c9d1d9}
 header{padding:14px 20px;background:#161b22;border-bottom:1px solid #30363d}
 h1{margin:0;font-size:17px;font-weight:600}
 .nav a{color:#58a6ff;margin-right:16px;text-decoration:none;font-size:14px}
 main{padding:20px;max-width:900px}
 table{width:100%;border-collapse:collapse;margin:10px 0}
 th,td{text-align:left;padding:6px 8px;border-bottom:1px solid #21262d;font-size:14px}
 th{color:#8b949e;font-weight:500}
 .tal{font-size:26px;font-weight:600;color:#7ee787}
 .kort{display:inline-block;background:#161b22;border:1px solid #30363d;
       border-radius:8px;padding:14px 18px;margin:0 12px 12px 0}
 .lille{color:#8b949e;font-size:12px}
</style></head><body>
<header><h1>Lille Hjernen — Helix Super Light Brain</h1>
<div class="nav"><a href="/">Status</a><a href="/register">Læringsregister</a>
<a href="/konklusioner">Konklusioner</a><a href="/drom">Drømmen</a></div></header>
<main id="m">indlæser…</main>
<script>
async function j(u){const r=await fetch(u);return r.json()}
async function tegn(){
 const p=location.pathname, m=document.getElementById('m');
 if(p==='/register'){
   const d=await j('/api/register?antal=100');
   m.innerHTML='<h3>Det hjernen ikke forstod ('+d.register.length+')</h3>'+
     '<p class="lille">Hver post afgøres senere: bliv en regel, eller kasseres som støj.</p>'+
     '<table><tr><th>Set</th><th>Type</th><th>Grund</th><th>Tekst</th></tr>'+
     d.register.map(r=>`<tr><td>${r.antal}</td><td>${r.type||''}</td>
       <td class="lille">${r.grund}</td><td>${(r.tekst||'').slice(0,140)}</td></tr>`).join('')+'</table>';
 } else if(p==='/konklusioner'){
   const d=await j('/api/konklusioner?antal=100');
   m.innerHTML='<h3>Konklusioner ('+d.konklusioner.length+')</h3>'+
     '<table><tr><th>Form</th><th>Bevis</th><th>Emne</th><th>Egenskab</th><th>Værdi</th></tr>'+
     d.konklusioner.map(k=>`<tr><td>${k.form}</td><td>${k.bevis}</td>
       <td>${k.emne}</td><td>${k.egenskab}</td><td>${(k.vaerdi||'').slice(0,60)}</td></tr>`).join('')+'</table>';
 } else if(p==='/drom'){
   const d=await j('/api/drom');
   m.innerHTML='<h3>Drømmens fund ('+(d.fund||[]).length+')</h3>'+
     '<table><tr><th>Slags</th><th>Alvor</th><th>Emne</th><th>Detalje</th></tr>'+
     (d.fund||[]).map(f=>`<tr><td>${f.slags}</td><td>${f.alvor}</td>
       <td>${f.emne}</td><td class="lille">${f.detalje}</td></tr>`).join('')+'</table>';
 } else {
   const s=await j('/api/status');
   m.innerHTML=`<div class="kort"><div class="tal">${s.konklusioner||0}</div>
     <div class="lille">konklusioner</div></div>
     <div class="kort"><div class="tal">${s.emner||0}</div>
     <div class="lille">emner</div></div>
     <div class="kort"><div class="tal">${s.uforstaaet_i_register||0}</div>
     <div class="lille">ikke forstået endnu</div></div>
     <h3>Bevisgrader</h3><table><tr><th>Grad</th><th>Antal</th></tr>`+
     Object.entries(s.bevis||{}).map(([k,v])=>`<tr><td>${k}</td><td>${v}</td></tr>`).join('')+
     `</table><p class="lille">Ingen LLM. Python udleder, BGE-M3 finder, Postgres husker.</p>`;
 }
}
tegn();
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def _send(self, body, ctype="application/json; charset=utf-8", kode=200):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False, default=str)
        b = body.encode() if isinstance(body, str) else body
        self.send_response(kode)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def log_message(self, format, *args):
        pass

    def do_GET(self):
        p = urlparse(self.path)
        if p.path in ("/", "/register", "/konklusioner", "/drom"):
            return self._send(HTML, "text/html; charset=utf-8")
        if p.path == "/api/status":
            return self._send(hent(KONKLUSION, "/status"))
        if p.path == "/api/register":
            return self._send(hent(KONKLUSION, "/register?antal=100"))
        if p.path == "/api/konklusioner":
            return self._send(hent(KONKLUSION, "/konklusioner?antal=100"))
        if p.path == "/api/drom":
            return self._send(hent(DROM, "/fund"))
        if p.path in ("/helbred", "/health"):
            k = hent(KONKLUSION, "/helbred")
            d = hent(DROM, "/helbred")
            return self._send({
                "status": "ok" if k.get("status") == "ok" else "delvist",
                "konklusionsmotor": k.get("status", "nede"),
                "drom": d.get("status", "nede"),
            })
        return self._send({"fejl": "ukendt sti"}, kode=404)


class Hukommelse(BaseHTTPRequestHandler):
    """Det klienterne kender som hukommelsen (6302).
    OpenWebUI læser /openapi.json her og kalder de øvrige stier."""

    def _send(self, obj, kode=200, ctype="application/json; charset=utf-8"):
        if isinstance(obj, (dict, list)):
            body = json.dumps(obj, ensure_ascii=False, default=str)
        else:
            body = obj
        b = body.encode()
        self.send_response(kode)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def log_message(self, format, *args):
        print(f"[hukommelse] {self.command} {self.path}", flush=True)

    def _krop(self):
        ln = int(self.headers.get("Content-Length", 0) or 0)
        try:
            return json.loads(self.rfile.read(ln) or b"{}")
        except Exception:
            return {}

    def do_GET(self):
        p = urlparse(self.path)
        q = parse_qs(p.query)
        antal = q.get("antal", ["25"])[0]

        if p.path in ("/helbred", "/health"):
            return self._send({"status": "ok"})
        if p.path == "/openapi.json":
            return self._send(OPENAPI)
        if p.path == "/status":
            return self._send(hent(KONKLUSION, "/status"))
        if p.path == "/konklusioner":
            return self._send(hent(KONKLUSION, f"/konklusioner?antal={antal}"))
        if p.path == "/register":
            return self._send(hent(KONKLUSION, f"/register?antal={antal}"))
        if p.path == "/drom":
            return self._send(hent(DROM, "/fund"))
        return self._send({"fejl": "ukendt sti"}, 404)

    def do_POST(self):
        p = urlparse(self.path)
        if p.path == "/udled":
            return self._send(post(KONKLUSION, "/udled", self._krop()))
        if p.path == "/drom/koer":
            return self._send(post(DROM, "/koer", {}))
        return self._send({"fejl": "ukendt sti"}, 404)


def pas_paa(navn, kommando, miljoe=None):
    """Start en del og genstart den hvis den dør. Alt logges."""
    def loeb():
        genstart = 0
        while True:
            try:
                p = subprocess.Popen(kommando, env=miljoe)
                print(f"[{navn}] startet (pid {p.pid})", flush=True)
                kode = p.wait()
                genstart += 1
                print(f"[{navn}] STOPPEDE med kode {kode} — genstart #{genstart} om 5 s",
                      flush=True)
            except Exception as e:
                print(f"[{navn}] KUNNE IKKE STARTE: {e}", flush=True)
            time.sleep(5)
    threading.Thread(target=loeb, daemon=True).start()


def vent_paa(navn, url, sekunder=60):
    """Vent til en del svarer, og skriv hvad der skete."""
    for i in range(sekunder):
        r = hent(url, "/helbred", timeout=2)
        if r.get("status") == "ok":
            print(f"[{navn}] svarer efter {i} s", flush=True)
            return True
        time.sleep(1)
    print(f"[{navn}] SVARER IKKE efter {sekunder} s", flush=True)
    return False


def start():
    miljoe = os.environ.copy()

    print("=" * 60, flush=True)
    print("[start] Helix Super Light Brain", flush=True)
    print("[start] ingen sprogmodel — kun BGE-M3 til søgning", flush=True)
    print("=" * 60, flush=True)

    # 1. Ollama — startes IKKE her. Supervisor ejer den (afsnit 0a i
    # supervisor.sh), og to startere på samme port betød 68 tabte genstarter
    # i træk med "address already in use" (målt 2. nov 2026). Én ejer, én server.

    # 2. Konklusionsmotoren
    pas_paa("konklusion", [sys.executable,
                           "/opt/lillehjerne/konklusion/motor.py"], miljoe)

    # 3. Drømmen
    pas_paa("drom", [sys.executable,
                     "/opt/lillehjerne/drom/drom.py"], miljoe)

    # 4. Triggeren — fanger nye samtaler uden at modellen skal kalde noget
    pas_paa("trigger", [sys.executable,
                        "/opt/lillehjerne/trigger.py"], miljoe)

    time.sleep(8)
    vent_paa("konklusion", KONKLUSION)
    vent_paa("drom", DROM)

    # 4. Hukommelsen (6302).
    # Viewer (6123) startes IKKE her — supervisor ejer den, og to startere på
    # samme port gav "Address already in use" i loggen (målt 2. nov 2026).
    def huk():
        print(f"[hukommelse] lytter på {HUK_PORT}", flush=True)
        ThreadingHTTPServer(("0.0.0.0", HUK_PORT), Hukommelse).serve_forever()

    print("[start] alle dele startet — se /helbred for samlet status", flush=True)
    huk()


if __name__ == "__main__":
    start()
