"""Lav vektorer til konklusioner der mangler dem.

DNA 2026-11-15: INSERT'en skrev aldrig vektoren, saa 14.739 raekker blev
gemt uden — og kunne derfor ikke findes ved soegning. Dette script fylder
dem paa i portioner, saa det kan koere over flere ture.

    python3 fyld_vektorer.py --status
    python3 fyld_vektorer.py --antal 2000
"""
import argparse
import json
import os
import time
import urllib.request

import psycopg

DSN = os.environ.get("KONKLUSION_DSN",
                     "host=127.0.0.1 port=5432 dbname=hjerne user=hjerne password=skift-mig")
OLLAMA = os.environ.get("OLLAMA_HOST", "127.0.0.1")
PORT = int(os.environ.get("OLLAMA_PORT", "11434"))
MODEL = os.environ.get("EMBED_MODEL", "bge-m3")


def embed(tekst: str):
    try:
        body = json.dumps({"model": MODEL, "input": tekst[:8000]}).encode()
        r = urllib.request.Request(f"http://{OLLAMA}:{PORT}/api/embed", data=body,
                                   headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(r, timeout=60) as s:
            d = json.load(s)
        return d["embeddings"][0]
    except Exception:
        return None


def status() -> None:
    with psycopg.connect(DSN, autocommit=True) as con, con.cursor() as cur:
        cur.execute("""SELECT count(*) FILTER (WHERE vektor IS NOT NULL),
                              count(*) FILTER (WHERE vektor IS NULL)
                       FROM konklusion WHERE NOT ugyldig""")
        med, uden = cur.fetchone()
    print(f"med vektor: {med} | mangler: {uden}")


def fyld(antal: int) -> None:
    with psycopg.connect(DSN, autocommit=True) as con, con.cursor() as cur:
        cur.execute("""SELECT id, kilde_tekst FROM konklusion
                       WHERE NOT ugyldig AND vektor IS NULL
                         AND length(coalesce(kilde_tekst,'')) > 5
                       ORDER BY id LIMIT %s""", (antal,))
        raekker = cur.fetchall()

        n_ok = n_fejl = 0
        for kid, tekst in raekker:
            v = embed(tekst)
            if v is None:
                n_fejl += 1
                time.sleep(1)
                continue
            cur.execute("UPDATE konklusion SET vektor = %s WHERE id = %s", (v, kid))
            n_ok += 1
            if n_ok % 100 == 0:
                print(f"  {n_ok} klaret …")
        print(f"faerdig: {n_ok} fik vektor | {n_fejl} fejlede")


def main():
    p = argparse.ArgumentParser(description="Fyld manglende vektorer")
    p.add_argument("--status", action="store_true")
    p.add_argument("--antal", type=int, default=1500)
    a = p.parse_args()
    status()
    if a.status:
        return
    fyld(a.antal)
    status()


if __name__ == "__main__":
    main()
