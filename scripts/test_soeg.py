#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Lille test af den semantiske søgning. Kør inde i containeren."""
import psycopg
import soeg

con = psycopg.connect(soeg.DSN, autocommit=True)
soeg.sikr_skema(con)

n = soeg.indekser(con, graense=30, parti=10)
print("indekseret:", n)

for q in ("børnesagen om Dio", "hvilken bil kører Danny",
          "hvilken port kører motoren på"):
    print()
    print("SPØRGSMÅL:", q)
    for t in soeg.soeg(con, q, 3):
        print(f"  [{t['lighed']}] {t['emne']} · {t['egenskab']} = {t['vaerdi'][:40]}")

con.close()
