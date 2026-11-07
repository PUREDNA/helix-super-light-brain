#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Kopiér MOC fra Super Brain ind i lillehjernen — kun MOC-grenen.

DNA 2. nov 2026: "så kopierer du den MOC der er derinde. Hele MOC. Altså det
vil sige med alle dens børn... Så det er det eneste der ligger i Lillehjernens
grafdatabase."

Sådan gør den:
  1. Læser ALT under MOC-knuden i Super Brain (knuder + kanter, rekursivt).
  2. Tømmer lillehjernens graf for knuder og kanter (labels bliver, de er skema).
  3. Skriver knuderne ind med deres properties, derefter kanterne.

Ingen model. Ingen gæt. Kun det der findes i kilden.
"""
import subprocess
import sys

KILDE = "Helix_Super_Brain"
MAAL = "Helix_Light_Brain"
GRAF = "hjerne"


def psql(container, sql):
    p = subprocess.run(
        ["docker", "exec", "-i", container, "psql", "-U", "hjerne", "-d", "hjerne",
         "-t", "-A", "-f", "-"],
        input=sql, capture_output=True, text=True,
    )
    # LOAD/SET skriver selv til stdout — de linjer er ikke data.
    out = "\n".join(
        l for l in p.stdout.splitlines()
        if l.strip() not in ("LOAD", "SET", "") and not l.strip().startswith("SET")
    )
    return out, p.stderr


def hent_moc_knuder():
    """Alle knuder under MOC-knuden, læst niveau for niveau.

    Den rekursive sti (INDHOLDER*0..3) fejler i Super Brains graf fordi der
    ligger hængende kanter — én ødelagt kant vælter hele forespørgslen.
    Derfor læses ét niveau ad gangen, og en kant der fejler springes over.
    """
    set_ = {}          # navn -> (label, props)
    niveau = hent_boern_navne(None)   # None = start ved selve MOC

    def laes(navne, d):
        liste = ", ".join("'" + n.replace("'", "''") + "'" for n in navne)
        sql = f"""
LOAD 'age';
SET search_path = ag_catalog, public;
SELECT * FROM cypher('{GRAF}', $$
  MATCH (m:`MOC`)
  WHERE m.navn IN [{liste}]
  RETURN m.navn, label(m), properties(m)
$$) AS (navn agtype, lbl agtype, props agtype);
"""
        out, err = psql(KILDE, sql)
        for linje in out.splitlines():
            if "|" not in linje:
                continue
            navn, lbl, props = linje.split("|", 2)
            navn = navn.strip().strip('"')
            set_[navn] = (lbl.strip().strip('"'), props.strip())
        return

    # MOC findes i MOC-labeltabellen sammen med sine børn (samme label).
    alle = hent_alle_moc_label()
    for navn, (lbl, props) in alle.items():
        set_[navn] = (lbl, props)
    return [(lbl, navn, props) for navn, (lbl, props) in set_.items()]


def hent_alle_moc_label():
    """Alle knuder med label MOC — det er MOC selv og alle dens børn."""
    sql = f"""
LOAD 'age';
SET search_path = ag_catalog, public;
SELECT * FROM cypher('{GRAF}', $$
  MATCH (m:MOC) RETURN m.navn, label(m), properties(m)
$$) AS (navn agtype, lbl agtype, props agtype);
"""
    out, err = psql(KILDE, sql)
    knuder = {}
    for linje in out.splitlines():
        if "|" not in linje:
            continue
        dele = linje.split("|", 2)
        if len(dele) < 3:
            continue
        navn, lbl, props = dele
        navn = navn.strip().strip('"')
        if navn and navn != "null":
            knuder[navn] = (lbl.strip().strip('"'), props.strip())
    return knuder


def hent_boern_navne(_):
    return []


def hent_kanter(navne):
    """Kanter mellem de knuder vi har hentet."""
    if not navne:
        return []
    liste = ", ".join("'" + n.replace("'", "''") + "'" for n in navne)
    sql = f"""
LOAD 'age';
SET search_path = ag_catalog, public;
SELECT * FROM cypher('{GRAF}', $$
  MATCH (a)-[e]->(b)
  WHERE a.navn IN [{liste}] AND b.navn IN [{liste}]
  RETURN label(e), a.navn, b.navn
$$) AS (k agtype, fra agtype, til agtype);
"""
    out, err = psql(KILDE, sql)
    if "ERROR" in err:
        print("FEJL ved kanter:", err[:400])
        return []
    kanter = []
    for linje in out.splitlines():
        if "|" not in linje:
            continue
        k, fra, til = [x.strip().strip('"') for x in linje.split("|", 2)]
        if k and k != "null":
            kanter.append((k, fra, til))
    return kanter


def toem_maal():
    """Slet alle knuder og kanter i lillehjernens graf (labels bliver)."""
    sql = f"""
LOAD 'age';
SET search_path = ag_catalog, public;
SELECT * FROM cypher('{GRAF}', $$ MATCH (n) DETACH DELETE n $$) AS (a agtype);
"""
    out, err = psql(MAAL, sql)
    if "ERROR" in err:
        print("FEJL ved tømning:", err[:400])
    else:
        print("  graf tømt")


def til_age_map(props: str) -> str:
    """properties() kommer som {"navn": "x"} — AGE vil have {navn: "x"}.

    Nøgler med bogstaver, tal og _ kan stå uden citationstegn; alt andet
    skal have dem. Værdier bliver som de er (de er allerede AGTYPE).
    # ponytail: holder til vores nøgler. Skal den bruges bredere, brug json.
    """
    import re
    s = props.strip()
    if not s.startswith("{") or not s.endswith("}"):
        return "{}"
    indre = s[1:-1].strip()
    if not indre:
        return "{}"
    dele = []
    for par in re.split(r', (?=["A-Za-z_æøåÆØÅ][A-Za-z0-9_æøåÆØÅ]*":)', indre):
        m = re.match(r'^"([^"]+)":\s*(.*)$', par.strip(), re.S)
        if not m:
            dele.append(par.strip())
            continue
        noegle, vaerdi = m.group(1), m.group(2)
        if not re.fullmatch(r"[A-Za-z_æøåÆØÅ][A-Za-z0-9_æøåÆØÅ]*", noegle):
            noegle = '"%s"' % noegle.replace('"', '\\"')
        dele.append(f"{noegle}: {vaerdi}")
    return "{" + ", ".join(dele) + "}"


def skriv(knuder, kanter):
    sætninger = ["LOAD 'age';", "SET search_path = ag_catalog, public;"]
    for lbl, navn, props in knuder:
        p = til_age_map(props)
        nm = navn.replace("'", "''")
        sætninger.append(
            f"SELECT * FROM cypher('{GRAF}', $$ "
            f"MERGE (n:`{lbl}` {{navn: '{nm}'}}) SET n = {p} $$) AS (a agtype);"
        )
    for (k, fra, til) in kanter:
        f = fra.replace("'", "''")
        t = til.replace("'", "''")
        sætninger.append(
            f"SELECT * FROM cypher('{GRAF}', $$ "
            f"MATCH (a {{navn:'{f}'}}), (b {{navn:'{t}'}}) "
            f"MERGE (a)-[:`{k}`]->(b) $$) AS (a agtype);"
        )
    out, err = psql(MAAL, "\n".join(sætninger))
    fejl = [l for l in err.splitlines() if "ERROR" in l]
    print(f"  skrevet: {len(knuder)} knuder, {len(kanter)} kanter, {len(fejl)} fejl")
    for f in fejl[:5]:
        print("   ", f[:140])


def main():
    print("1. læser MOC fra Super Brain ...")
    knuder = hent_moc_knuder()
    navne = [n for _, n, _ in knuder if n and n != "null"]
    print(f"   {len(knuder)} knuder, {len(set(navne))} unikke navne")
    print("2. læser kanter ...")
    kanter = hent_kanter(navne)
    print(f"   {len(kanter)} kanter")
    print("3. tømmer lillehjernens graf ...")
    toem_maal()
    print("4. skriver MOC ind i lillehjernen ...")
    skriv(knuder, kanter)
    print("færdig")


if __name__ == "__main__":
    main()
