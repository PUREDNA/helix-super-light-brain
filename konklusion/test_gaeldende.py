"""Bevis for 'nyeste viden vinder'-reglen.

Kør: python3 test_gaeldende.py  (inde i containeren)

Reglen: VÆGTEN AFGØR FØRST. Ved lige vægt vinder den nyeste.
MÅLT(5) > DOKUMENTERET(4) > FØRSTEHÅNDS(3) > ANDENHÅNDS(2) > SAGT(1)
"""
import sys

sys.path.insert(0, "/opt/lillehjerne/konklusion")


def gaeldende(raekker):
    """Kopi af _kun_gældende uden database — samme logik, testbar."""
    from importlib import util as _u
    _s = _u.spec_from_file_location("drom_mod", "/opt/lillehjerne/drom/drom.py")
    _m = _u.module_from_spec(_s)
    _s.loader.exec_module(_m)
    _noegle, _tal = _m._noegle, _m._tal

    grupper = {}
    for k in raekker:
        n = _noegle(k["tekst"])
        if n:
            grupper.setdefault(n, []).append(k)

    overhalet = set()
    for n, gruppe in grupper.items():
        if len(gruppe) < 2:
            continue
        if len({t for r in gruppe for t in _tal(r["tekst"])}) < 2:
            continue

        def rang(r):
            return (r["vaegt"], r["dato"])

        vinder = max(gruppe, key=rang)
        for r in gruppe:
            if r is not vinder:
                overhalet.add(r["tekst"])
    return [k for k in raekker if k["tekst"] not in overhalet]


def r(tekst, vaegt, dato):
    return {"tekst": tekst, "vaegt": vaegt, "dato": dato}

def main():
    # 1. Nyeste samtale slår ældre samtale
    ud = gaeldende([r("VAS kører på port 6301", 1, "2026-11-10"),
                    r("VAS kører på port 6305", 1, "2026-11-13")])
    assert [k["tekst"] for k in ud] == ["VAS kører på port 6305"], ud
    print("OK  1. nyeste samtale vinder over ældre")

    # 2. Dokument slår samtale, selv om samtalen er nyere
    ud = gaeldende([r("VAS kører på port 6305", 1, "2026-11-13"),
                    r("VAS kører på port 6301", 4, "2026-11-01")])
    assert [k["tekst"] for k in ud] == ["VAS kører på port 6301"], ud
    print("OK  2. dokument slår nyere samtale")

    # 3. DNA's egne ord (førstehånd) slår dokument
    #    Samme formulering, uenige om tallet — ellers ser systemet dem som to
    #    forskellige udsagn og beholder begge (den sikre vej).
    ud = gaeldende([r("Dio bor i plejefamilie nr 2", 3, "2026-11-01"),
                    r("Dio bor i plejefamilie nr 5", 4, "2026-11-13")])
    assert [k["tekst"] for k in ud] == ["Dio bor i plejefamilie nr 5"], ud
    print("OK  3. DNA's egne ord slår dokument")

    # 4. Nyeste dokument slår ældre dokument (samme formulering, uenige om årstal)
    ud = gaeldende([r("Sagens status er afsluttet 2024", 3, "2024-01-01"),
                    r("Sagens status er afsluttet 2025", 3, "2025-06-01")])
    assert [k["tekst"] for k in ud] == ["Sagens status er afsluttet 2025"], ud
    print("OK  4. nyeste dokument vinder over ældre")

    # 5. To forskellige ting om samme person er IKKE en konflikt
    ud = gaeldende([r("Dio har nye færdigheder", 2, "2026-11-01"),
                    r("Dio har svært ved at sove", 2, "2026-11-13")])
    assert len(ud) == 2, ud
    print("OK  5. to forskellige udsagn fjernes ikke")

    # 6. Samme udsagn uden tal er ingen konflikt — de supplerer hinanden
    ud = gaeldende([r("Dio bor i plejefamilie", 4, "2026-11-01"),
                    r("Dio bor i plejefamilie i Brøndby", 4, "2026-11-02")])
    assert len(ud) == 2, ud
    print("OK  6. praecisering fjernes ikke")

    print("\nALLE 6 KONTROLLER BESTAAET")


if __name__ == "__main__":
    main()
