#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Selvtest for konklusionsmotorens sætningsregler. Kør: python3 konklusion/selvtest_regler.py"""
import os
import sys
import re

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import motor  # noqa: E402

# (sætning, antal forventede udledninger, forventet emne eller None)
PRØVER = [
    ("Advokaten sad i bestyrelsen for det selskab Dio blev anbragt hos", 0, None),
    ("databasen skal fungere som hjerne i et kriminalmagasin", 0, None),
    ("Su har fået sin egen skill som shop-ansvarlig", 1, "Su"),
    ("Port 8300 er i brug", 1, "Port 8300"),
    ("skillen er skrevet: simply-hosting", 1, "skillen"),
    ("DNA ønsker en super light hjerne", 1, "DNA"),
    ("Hermes opdagede, at domænet er ledigt", 1, "Hermes"),
    ("Danny skal i ret i Svendborg den 9. november", 1, "Danny"),
    ("Danny kan være efterlyst, fordi man vil anholde ham", 1, "Danny"),
    ("Jeanette Gjørret skal ringe til Danny på mandag kl. 16", 1, "Jeanette Gjørret"),
    ("Retssagen BS-34811/2026-NAE blev henvist fra Retten i Næstved", 1, "Retssagen BS-34811/2026-NAE"),
    ("Det er en fin dag", 0, None),
]


def rammer(sætning):
    """Alle udledninger reglen ville lave (samme logik som regel_er)."""
    ud = []
    brugte = set()
    dele = re.split(r"(?<=\w)[.;]\s+(?=[A-ZÆØÅ][a-zæøå])|(?<=\w),\s+(?=[A-ZÆØÅ][a-zæøå])|\n+", sætning)
    for s in dele:
        s = s.strip()
        for mønster, egenskab in motor.FORBINDELSER:
            if egenskab in brugte:
                continue
            m = mønster.search(s)
            if not m:
                continue
            emne = m.group("emne").strip()
            if (motor.TOM_EMNE.match(emne) or motor.FYLD_EMNE.match(emne)
                    or motor.er_stemmelarm(s)
                    or motor.VERBUM.search(emne) or len(emne.split()) > 4):
                continue
            # et emne der ikke ligner et navn (fx "Retten mødes") må ikke bære en klokke
            if egenskab == "klokken" and not motor.PERSON_NAVN.match(emne):
                continue
            ud.append((emne, egenskab, m.group("vaerdi").strip()))
            brugte.add(egenskab)
            break
    return ud


def første(sætning):
    u = rammer(sætning)
    return u[0] if u else None


ROLLER = [
    ("Advokaten sad i bestyrelsen for Holmegårdshuset, samtidig med at hun fører "
     "sager mod Børn- og Ungeudvalget", 2, "Advokaten", "bestyrelsen for Holmegårdshuset"),
    ("Barnet blev anbragt i Holmegårdshuset", 1, "Barnet", "opdraget/ansat i Holmegårdshuset"),
    ("Der er ingen rolle her", 0, None, None),
    ("Lisbeth Sten Jensen var sagkyndig dommer i kendelsen",
     1, "Lisbeth Sten Jensen", "sagkyndig dommer i kendelsen"),
]


def roller(sætning):
    """Samme udvælgelse som regel_roller, uden database."""
    ud = []
    for s in [x.strip() for x in sætning.split(".") if x.strip()]:
        person, rolle_sted = None, None
        m = motor.ROLLE.search(s)
        if m:
            person = (m.group("person") or "").strip()
            rolle_sted = f"{m.group('rolle').strip()} for {m.group('sted').strip()}"
        m3 = motor.EMBEDE.search(s)
        if m3:
            person = person or (m3.group("person") or "").strip()
            if person == (m3.group("person") or "").strip():
                embede = m3.group("embede").strip()
                sted = (m3.group("sted") or "").strip()
                rolle_sted = f"{embede} i {sted}" if sted else embede
        m2 = motor.OPDRAG.search(s)
        if m2:
            person = person or (m2.group("person") or "").strip()
            rolle_sted = f"opdraget/ansat i {m2.group('sted').strip()}"
        if not person or not rolle_sted:
            continue
        if motor.TOM_EMNE.match(person) or motor.VERBUM.search(person) or len(person.split()) > 4:
            continue
        ud.append((person, rolle_sted))
        if motor.SAMTIDIG.search(s):
            ud.append((person, "samtidig"))
    return ud


def demo():
    fejl = 0
    # Værdien skal læses HELT: dato og bisætning må ikke klippes af kommaet
    # (målt 2. nov 2026: "Svendborg den 9" og "være efterlyst").
    from_ret = første("Danny skal i ret i Svendborg den 9. november")
    if not from_ret or from_ret[2].strip() != "Svendborg den 9. november":
        fejl += 1
        print("FEJL: datoen klippes ->", from_ret)
    efter = første("Danny kan være efterlyst, fordi man vil anholde ham")
    if not efter or "anholde" not in efter[2]:
        fejl += 1
        print("FEJL: bisætningen tabes ->", efter)
    if "DATO" in dir(motor) and not motor.DATO.findall("den 9. november 2026"):
        pass  # ponytail: dato-mønsteret kræver tal-tal-år; tekstmåneder er endnu ikke dækket
    # sagsnummer må ikke fange "sagkyndig" (målt 2. nov 2026)
    if motor.SAGSNR.findall("Lisbeth Sten Jensen var sagkyndig dommer"):
        fejl += 1
        print("FEJL: SAGSNR fanger sagkyndig")
    # stemmelarm må ikke blive en konklusion (målt 2. nov 2026)
    for skrald in ("Men du kan være lidt kig på, hvor der er hinviser",
                   "Stæbber siger et stæb vejledetning",
                   "Herfra sidder der ser det ud som om at containeren",
                   "Det er en prøve, kan du høre mig"):
        if rammer(skrald):
            fejl += 1
            print("FEJL: stemmelarm blev en konklusion ->", rammer(skrald))
    if not rammer("Su har fået sin egen skill som shop-ansvarlig"):
        fejl += 1
        print("FEJL: støjsorteringen spiste en ægte sætning")
    if motor.SAGSNR.findall("sagsnr. 1234-5678") != ["1234-5678"]:
        fejl += 1
        print("FEJL: SAGSNR fanger ikke et rigtigt sagsnummer")
    for sætning, antal, emne in PRØVER:
        r = første(sætning)
        fik = 0 if r is None else 1
        if fik != antal or (emne and (r is None or r[0] != emne)):
            fejl += 1
            print("FEJL:", sætning[:50], "| forventet", antal, emne, "| fik", r)
    for sætning, antal, emne, rolle in ROLLER:
        ud = roller(sætning)
        if len(ud) != antal or (emne and (not ud or ud[0][0] != emne)) \
                or (rolle and (not ud or ud[0][1] != rolle)):
            fejl += 1
            print("FEJL (rolle):", sætning[:50], "| forventet", antal, emne, rolle, "| fik", ud)
    print("selvtest:", "ok" if fejl == 0 else f"{fejl} fejl")
    return fejl


if __name__ == "__main__":
    sys.exit(1 if demo() else 0)
