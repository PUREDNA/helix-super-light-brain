#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Viewer-tjenesten — brugerfladen ind i hjernen.

Den rigtige graph-viewer, tilpasset Super Brain. Læser grafen (AGE) og
noterne, og tegner dem som et interaktivt net. Alt er læsning.

Kører på sin egen port. Bruger Flask.

    GET /                    → brugerfladen
    GET /api/graph           → grafen som knuder og kanter
    GET /api/ops             → noterne som knuder og kanter
    GET /api/ops_note?sti=X  → én note
    GET /api/moc_vektorer    → vektorerne (søgning på betydning)
    GET /api/search?q=X      → søg i grafen
    GET /api/neighbors?id=X  → naboerne til en knude
"""
import os
import sys

# Flask-appen ligger i app.py ved siden af denne fil.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app   # noqa: E402

if __name__ == "__main__":
    port = int(os.environ.get("VIEWER_PORT", "6123"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
