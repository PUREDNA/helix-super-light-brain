#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test af Helix Compression uden for Hermes. Kør: python3 test_engine.py"""
import os
import sys

sys.path.insert(0, "/home/dna/.hermes/plugins")

# Hermes' ContextEngine findes kun inde i installationen
W = ("/home/dna/.hermes/installs/7a82428ae527ef89/environments/"
     "a729bea5a5dc4f98a5adfbedd48934c3/workspace")
sys.path.insert(0, W)

import importlib.util  # noqa: E402

spec = importlib.util.spec_from_file_location(
    "helix_compression", "/home/dna/.hermes/plugins/helix-compression/__init__.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def lav_historik(n=40, tegn=3000):
    return [{"role": "user" if i % 2 == 0 else "assistant",
             "content": (("Danny siger noget vigtigt nummer %d om Holmegårdshuset "
                          "og retssagen i Svendborg den 9. november. " % i) + "x" * tegn)}
            for i in range(n)]


class FakeMotor(mod.HelixCompression):
    """Uden netværk: kvitterer for alt."""
    kaldt = []
    sidst = []

    def _flyt(self, historik):
        FakeMotor.kaldt.append(len(historik))
        FakeMotor.sidst = list(historik)
        return len(historik), '{"laest": %d, "konklusioner": 3}' % len(historik)


def demo():
    fejl = 0
    e = FakeMotor(context_length=10000)

    # 1. Tærskel: 90 % af vinduet
    assert e.threshold_tokens == 9000, e.threshold_tokens
    if e.should_compress(8000):
        fejl += 1
        print("FEJL: fyrer for tidligt")
    if not e.should_compress(9500):
        fejl += 1
        print("FEJL: fyrer ikke ved 95 %")

    # 2. Tømning: ned mod 65 %, hoved og hale urørt
    hist = lav_historik(40, tegn=4000)   # ~45.000 tegn = 15.000 tokens
    e.context_length = 15000
    ny = e.compress(hist, current_tokens=14500)
    if ny[0] != hist[0] or ny[-1] != hist[-1]:
        fejl += 1
        print("FEJL: hoved eller hale blev rørt")
    if not (1 < len(ny) < len(hist)):
        fejl += 1
        print("FEJL: historikken blev ikke kortere (ind", len(hist), "ud", len(ny), ")")
    flyttede = len(hist) - (len(ny) - 1)   # minus markøren
    if flyttede <= 0:
        fejl += 1
        print("FEJL: ingen beskeder flyttet")
    # De flyttede skal være de ÆLDSTE, og rækkefølgen skal bevares
    ældste = hist[2]                                   # efter hovedet, før det der beholdes
    if ældste not in FakeMotor.sidst:
        fejl += 1
        print("FEJL: de ældste blev ikke flyttet først")
    if ældste in ny:
        fejl += 1
        print("FEJL: en flyttet besked står stadig i historikken")
    if not any("HELIX FLYTTEDE" in str(m.get("content", "")) for m in ny):
        fejl += 1
        print("FEJL: ingen flytte-markør i historikken")
    if not FakeMotor.kaldt:
        fejl += 1
        print("FEJL: intet blev sendt til hjernen")

    # 3. Råt: intet resumé-ord, og DNA's ord er med i det der sendes
    sendt = []
    e._flyt = lambda h: (sendt.extend(h), (len(h), "ok"))[1]
    e.compress(lav_historik(100), current_tokens=10000)
    tekst = " ".join(str(m.get("content", "")) for m in sendt)
    if "Holmegårdshuset" not in tekst:
        fejl += 1
        print("FEJL: de rå ord blev ikke sendt")

    # 4. Hjernen nede: samtalen må ikke gå i stå
    def braender(h):
        raise RuntimeError("hjerne nede")
    e._flyt = braender
    ny = e.compress(lav_historik(100), current_tokens=10000)
    if not any("FEJL" in str(m.get("content", "")) for m in ny):
        fejl += 1
        print("FEJL: nedbrud blev ikke noteret")

    print("test:", "ok" if fejl == 0 else f"{fejl} fejl")
    return fejl


if __name__ == "__main__":
    sys.exit(1 if demo() else 0)
