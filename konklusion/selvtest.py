#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Selvtest — kører uden database. Fejler hvis mønstrene holder op med at virke.

    python3 motor.py --selvtest
"""
import sys
import motor


def selvtest():
    # Iagttagelse: noget man kan se
    u = motor.udtraek("Brian kom i skole med et blåt øje den 12.03.2026.")
    assert u["slags"] == "IAGTTAGELSE", u["slags"]
    assert u["datoer"] == [("12", "03", "2026")], u["datoer"]

    # Tolkning: en dom om det man ser
    u = motor.udtraek("Der er bekymring for Lottes omsorgssvigt.")
    assert u["slags"] in ("TOLKNING", "GENGIVELSE"), u["slags"]

    # Gengivelse: skabelonsprog der oversætter en kilde
    u = motor.udtraek("Det vurderes, at barnets bedste er at forblive anbragt.")
    assert u["slags"] == "GENGIVELSE", u["slags"]

    # Udtræk af numre og beløb
    u = motor.udtraek("Sagsnr. 1234-2025, CVR 12345678, bevilling 12.500,00 kr.")
    assert "1234-2025" in u["sagsnr"], u["sagsnr"]
    assert "12.500,00 kr." in u["beloeb"], u["beloeb"]

    # Hændelse kræver både dato og verbum
    u = motor.udtraek("Barnet blev fjernet den 03.05.2025.")
    assert u["haendelser"], u["haendelser"]
    assert u["datoer"], u["datoer"]

    # Bevisgrader
    assert motor.bevisgrad("x", "maalt") == "MAALT"
    assert motor.bevisgrad("x", "journal") == "DOKUMENTERET"
    assert motor.bevisgrad("x", "samtale") == "SAGT"
    # Bevis-skalaen (DNA 2. nov 2026): DNA's egne ord er stærkest om ham selv,
    # og maskinvolapyk er aldrig en konklusion.
    assert motor.bevisgrad("dna kan godt lide kaffe", "samtale", "dna") == "FOERSTEHAANDS"
    assert motor.bevisgrad("advokaten sad i bestyrelsen", "samtale", "hermes") == "ANDENHAANDS"
    assert motor.bevisgrad(
        "en enhed kører som enhed nummer 4 (subproceseret: 42, port: 21434, procesnr: 6820484123127969025)", "samtale") == "STOEJ"
    assert motor.bevisgrad(
        "forstået at hjernen er dømmestærk (REKKEVIDEN = 1635301573, SUBJEKT=117212763311)", "samtale") == "STOEJ"
    # Rigtig viden med tal må ikke ryge ud som støj.
    assert motor.bevisgrad(
        "Danny Nordstrom Andersen har en RTX 3060 med 12 GB hukommelse i sin maskine, købt i 2025", "samtale", "dna") == "FOERSTEHAANDS"

    # Formen der læser almindeligt sprog (DNA 2. nov 2026). Sætningerne er
    # taget ordret fra Super Brains egne dokumenterede konklusioner.
    def rammer(s):
        for m, e in motor.FORBINDELSER:
            mo = m.search(s)
            if mo:
                return e, mo.group("emne").strip().lower(), mo.group("vaerdi").strip()
        return None

    r = rammer("den gamle database ligger på port 6120")
    assert r and r[0] == "ligger_paa" and "6120" in r[2], r
    r = rammer("Port 9443 er dashboard-proxyen")
    assert r and r[0] == "er" and "dashboard" in r[2].lower(), r
    r = rammer("dna ønsker at rette alle agentfilerne til at henvise til hjernen")
    assert r and r[0] == "oensker", r
    r = rammer("SuperBrain bruger den aktuelle hjerne")
    assert r and r[0] == "oensker", r
    # Volapyk må ikke give en udledning.
    assert rammer("en enhed kører som enhed nummer 4 procesnr 6820484123127969025") is None

    print("selvtest: alle 6 kontroller bestået")


if __name__ == "__main__":
    if "--selvtest" in sys.argv:
        selvtest()
    else:
        motor.start()
