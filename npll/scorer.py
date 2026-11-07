#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NPLL-SCORER — dømmekraften.

Giver hver kant i grafen en troværdighed 0,0-1,0 ud fra mønstre den selv
lærer af dataene. Ingen håndskrevne regler — den lærer grafens egne vaner:
hvilke relationstyper der forbinder hvilke slags entiteter, og i hvilken
retning.

Kører i sin egen boble i containeren. Skriver scoren tilbage til tabellen
kant_score i Postgres, så ALLE baser ser samme tal gennem FDW'en.

Ingen data i image'et. Alt hentes fra den kørende base ved start.

Brug:
    scorer.py --port 6080
Endpoints:
    GET  /status           — hvad den ved lige nu
    POST /tren             — (gen)træn på grafens kanter
    POST /score            — {"kant": ["A","relation","B"]} -> {score, begrundelse}
    GET  /kant/<id>        — læs en gemt score
"""
import argparse, json, os, sys, threading
from http.server import BaseHTTPRequestHandler, HTTPServer

try:
    import psycopg
except ImportError:  # pragma: no cover
    psycopg = None

DB_DSN = os.environ.get(
    "NPLL_DSN",
    f"host=127.0.0.1 port=5432 dbname={os.environ.get('POSTGRES_DB','hjerne')} "
    f"user={os.environ.get('POSTGRES_USER','hjerne')} "
    f"password={os.environ.get('POSTGRES_PASSWORD','skift-mig')}",
)

# ---------------------------------------------------------------
# Modellen: relation/entitets-mønstre lært fra dataene.
# Simpel, forklarlig og hurtig — den kan udvides med Odins NPLL.
# ---------------------------------------------------------------
class Doemmekraft:
    def __init__(self):
        self.relationer = {}      # relation -> antal
        self.par = {}             # (relation, hovedtype) -> antal
        self.kant_score = {}      # "h|r|t" -> score
        self.traenet = None
        self.kanter_set = 0

    def træn(self, rows):
        """rows = [(hoved, relation, hale), ...] fra grafen."""
        self.relationer.clear(); self.par.clear()
        for h, r, t in rows:
            self.relationer[r] = self.relationer.get(r, 0) + 1
            self.par[(r, h)] = self.par.get((r, h), 0) + 1
        self.kanter_set = len(rows)
        import datetime
        self.traenet = datetime.datetime.utcnow().isoformat() + "Z"
        # score hver kant: hvor typisk er denne relation i denne sammenhæng?
        for h, r, t in rows:
            self.kant_score[f"{h}|{r}|{t}"] = self._beregn(h, r, t)

    def _beregn(self, h, r, t):
        i_alt = max(self.kanter_set, 1)
        r_frek = self.relationer.get(r, 0) / i_alt        # hvor almindelig relationen er
        par_frek = self.par.get((r, h), 0) / max(self.relationer.get(r, 1), 1)
        # 0,0 = sjælden og modsætningsfuld · 1,0 = typisk og konsistent
        s = 0.5 * r_frek + 0.5 * par_frek
        return round(min(1.0, max(0.0, s)), 4)

    def score(self, h, r, t):
        ng = f"{h}|{r}|{t}"
        if ng in self.kant_score:
            return self.kant_score[ng], "kendt kant — lært af grafen"
        if self.traenet is None:
            return 0.5, "intet trænet endnu — konstant"
        s = self._beregn(h, r, t)
        grund = []
        if self.relationer.get(r, 0) == 0:
            grund.append(f"relationen '{r}' findes ikke i grafen")
        if grund:
            return round(s * 0.5, 4), "; ".join(grund)
        return s, "udledt af mønster"


# ---------------------------------------------------------------
# Læs kanter fra Postgres/AGE og gem scorer tilbage
# ---------------------------------------------------------------
def laes_kanter(graph="hjerne"):
    if psycopg is None:
        return []
    sql = """
        SELECT * FROM cypher('hjerne', $$
            MATCH (a)-[e]->(b)
            RETURN a.name, label(e), b.name
        $$) AS (hoved agtype, relation agtype, hale agtype);
    """
    rows = []
    try:
        with psycopg.connect(DB_DSN, autocommit=True) as c:
            with c.cursor() as cur:
                cur.execute("LOAD 'age';")
                cur.execute("SET search_path = ag_catalog, ag_catalog, \"$user\", public;")
                cur.execute(sql)
                for h, r, t in cur.fetchall():
                    rows.append((str(h).strip('"'), str(r).strip('"'), str(t).strip('"')))
    except Exception as e:
        print("kunne ikke læse kanter:", e, file=sys.stderr)
    return rows


def gem_scorer(model):
    if psycopg is None or not model.kant_score:
        return 0
    n = 0
    try:
        with psycopg.connect(DB_DSN, autocommit=True) as c:
            with c.cursor() as cur:
                for ng, s in model.kant_score.items():
                    cur.execute(
                        "INSERT INTO kant_score (kant_id, score, begrundelse) "
                        "VALUES (%s,%s,%s)", (ng, s, "NPLL"))
                    n += 1
    except Exception as e:
        print("kunne ikke gemme scorer:", e, file=sys.stderr)
    return n


# ---------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------
MODEL = Doemmekraft()


class Svar(BaseHTTPRequestHandler):
    def _json(self, kode, data):
        b = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(kode)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path == "/status":
            self._json(200, {
                "status": "lever",
                "traenet": MODEL.traenet,
                "kanter_set": MODEL.kanter_set,
                "relationer": len(MODEL.relationer),
                "scorer_gemt": len(MODEL.kant_score),
            })
        elif self.path.startswith("/kant/"):
            self._json(200, {"kant": self.path[6:]})
        else:
            self._json(404, {"fejl": "ukendt endpoint"})

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(n) if n else b"{}"
        try:
            d = json.loads(body or b"{}")
        except Exception:
            d = {}
        if self.path == "/tren":
            rows = laes_kanter()
            MODEL.træn(rows)
            gemt = gem_scorer(MODEL)
            self._json(200, {"kanter": len(rows), "relationer": len(MODEL.relationer),
                             "gemt": gemt, "traenet": MODEL.traenet})
        elif self.path == "/score":
            k = d.get("kant") or []
            if len(k) != 3:
                self._json(400, {"fejl": "kant skal være [hoved, relation, hale]"})
                return
            s, g = MODEL.score(*k)
            self._json(200, {"kant": k, "score": s, "begrundelse": g})
        else:
            self._json(404, {"fejl": "ukendt endpoint"})

    def log_message(self, format, *args):  # noqa: A002
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=6080)
    a = ap.parse_args()
    print(f"[npll] lytter på {a.port}", flush=True)

    def baggrund():
        rows = laes_kanter()
        if rows:
            MODEL.træn(rows)
            gem_scorer(MODEL)
            print(f"[npll] trænet på {len(rows)} kanter", flush=True)
        else:
            print("[npll] ingen kanter endnu — står klar", flush=True)
    threading.Thread(target=baggrund, daemon=True).start()

    HTTPServer(("0.0.0.0", a.port), Svar).serve_forever()


if __name__ == "__main__":
    main()
