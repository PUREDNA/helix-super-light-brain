"""Saet ejer paa grafens knuder ud fra konklusionens ejer.

Kører én gang efter brugeropdelingen (DNA 11. nov 2026).

Metoden: læs konklusionens id -> ejer fra Postgres, og sæt n.ejer paa den
tilsvarende knude i grafen. Noder uden en kendt konklusion (de gamle,
importerede) bliver staaende med tom ejer = hovedbygningen.

    python3 -m scripts.saet_ejer_paa_graf
"""
import os

import psycopg

DSN = os.environ.get("DSN", "host=127.0.0.1 port=5432 dbname=hjerne user=hjerne password=skift-mig")
GRAF = "hjerne"


def main():
    with psycopg.connect(DSN, autocommit=True) as con, con.cursor() as cur:
        cur.execute("SELECT id::text, coalesce(ejer,'') FROM hjerne.konklusion")
        ejere = dict(cur.fetchall())
        print(f"{len(ejere)} konklusioner med ejer")

        cur.execute("LOAD 'age'")
        cur.execute('SET search_path = ag_catalog, hjerne, public')

        sat = 0
        for kid, ejer in ejere.items():
            if not ejer:
                continue
            # AGE tager ikke parametre ind i cypher-blokken — strengen bygges.
            # Id'er er uuid'er og ejere er kendte bruger-id'er fra databasen.
            cur.execute(
                f"""SELECT * FROM cypher('hjerne', $$
                      MATCH (n:Konklusion {{navn: '{kid}'}}) SET n.ejer = '{ejer.replace("'", "")}' RETURN n
                    $$) AS (n agtype)"""
            )
            sat += len(cur.fetchall())
        print(f"ejer sat paa {sat} knuder")


if __name__ == "__main__":
    main()
