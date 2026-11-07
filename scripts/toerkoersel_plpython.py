#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TØRKØRSEL: hvornår koster det at hente data UD af basen?

Måler kun. Skriver intet rigtigt. Bruger en TEMP-tabel der forsvinder selv.

Spørgsmålet (DNA 3. nov 2026): skal beregningen flyttes IND i Postgres via
plpython, eller er det billigere at hente rækkerne ud som vi gør nu? Det
afhænger kun af hvor mange rækker der er — og det kan måles.

Kør: docker cp ... && docker exec Helix_Light_Brain python3 /tmp/toerkoersel_plpython.py
"""
import time

import psycopg

DSN = "host=127.0.0.1 port=5432 dbname=hjerne user=hjerne password=skift-mig"
STOERRELSER = [1_000, 10_000, 50_000, 200_000]


def main():
    with psycopg.connect(DSN, autocommit=True) as con:
        with con.cursor() as cur:
            # TEMP-tabel: forsvinder når forbindelsen lukkes. Rører intet rigtigt.
            cur.execute("""
                CREATE TEMP TABLE prove (
                    id      bigserial PRIMARY KEY,
                    emne    text,
                    egenskab text,
                    vaerdi  text,
                    bevis   text
                ) ON COMMIT PRESERVE ROWS
            """)

            print(f"{'raekker':>8} {'hent ud':>10} {'regn i PG':>11} {'forskel':>10}")
            print("-" * 44)

            sidste = 0
            for n in STOERRELSER:
                cur.execute("""
                    INSERT INTO prove (emne, egenskab, vaerdi, bevis)
                    SELECT 'emne' || (g %% 500), 'eg' || (g %% 40),
                           'vaerdi' || g, 'SAGT'
                    FROM generate_series(%s::bigint, %s::bigint) g
                """, (sidste + 1, n))
                sidste = n

                # A: hent alt ud og regn i Python (som vi goer i dag)
                t = time.perf_counter()
                cur.execute("SELECT emne, egenskab, vaerdi, bevis FROM prove")
                raekker = cur.fetchall()
                len({r[0] for r in raekker})
                ud = time.perf_counter() - t

                # B: lad Postgres regne (ren SQL, samme svar)
                t = time.perf_counter()
                cur.execute("SELECT count(DISTINCT emne) FROM prove")
                cur.fetchone()
                inde = time.perf_counter() - t

                print(f"{n:>8} {ud*1000:>9.1f}ms {inde*1000:>10.1f}ms "
                      f"{(ud-inde)*1000:>9.1f}ms")

            cur.execute("DROP TABLE prove")


if __name__ == "__main__":
    main()
