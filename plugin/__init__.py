"""Helix Super Light Brain — Hermes-plugin.

To dele i én pakke:

  * memory.py       Memory Provider: hver tur går ind i hjernen, og
                     konklusionerne hentes tilbage som langtidshukommelse.
  * compression.py  Context Engine: når vinduet fylder, flyttes historikken
                     RÅT ind i hjernen i stedet for at blive opsummeret.

Installation (som plugin i en Hermes-profil):

    mkdir -p ~/.hermes/plugins/helix-super-light-brain
    cp plugin/*.py plugin/plugin.yaml ~/.hermes/plugins/helix-super-light-brain/

Sæt derefter i config.yaml:

    memory.provider: helix-super-light-brain
    context.engine: helix-compression

Kører hjernen ikke på 127.0.0.1, sæt LILLEHJERNE og LILLEHJERNE_MOTOR.
"""
from __future__ import annotations


def register(ctx):
    from . import compression, memory

    ctx.register_memory_provider(memory.HelixSuperLightBrain())
    ctx.register_context_engine(compression.HelixCompression())
