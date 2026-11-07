#!/usr/bin/env bash
# -*- coding: utf-8 -*-
# Startskript for Helix Super Brain 1.2.
#
# Forskellen fra 1.1: image'et indeholder ingen modeller. De hentes ved start
# (scripts/hent_modeller.sh) og lægges i volume, så det kun sker én gang.
#
# Rækkefølgen: henteren startes i baggrunden — den venter selv på Ollama —
# og supervisoren overtager derefter som containerens hovedproces.
set -u

echo "[1.2] let image: modellerne hentes ved start, hvis de mangler"
/opt/hjerne/scripts/hent_modeller.sh &

exec /opt/hjerne/scripts/supervisor.sh
