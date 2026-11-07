#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
openapi.py — værktøjsfladen OpenWebUI kalder.

OpenWebUI læser et OpenAPI-dokument for at vide hvad hjernen kan. Dette er
den fil. Den beskriver tre værktøjer og sender dem videre til
Konklusionsmotoren og Drømmen.

Kører som en del af start.py på port 6302 (Hukommelsen).
"""
import json
from urllib.parse import urlparse, parse_qs

import http.client

KONKLUSION = "http://127.0.0.1:6305"
DROM = "http://127.0.0.1:6304"


def hent(base, sti, timeout=10):
    try:
        u = urlparse(base)
        c = http.client.HTTPConnection(u.hostname, u.port, timeout=timeout)
        c.request("GET", sti)
        r = c.getresponse()
        d = json.loads(r.read() or b"{}")
        c.close()
        return d
    except Exception as e:
        return {"fejl": str(e)}


def post(base, sti, krop, timeout=30):
    try:
        u = urlparse(base)
        c = http.client.HTTPConnection(u.hostname, u.port, timeout=timeout)
        c.request("POST", sti, json.dumps(krop),
                  {"Content-Type": "application/json"})
        r = c.getresponse()
        d = json.loads(r.read() or b"{}")
        c.close()
        return d
    except Exception as e:
        return {"fejl": str(e)}


OPENAPI = {
    "openapi": "3.1.0",
    "info": {
        "title": "Lille Hjernen",
        "version": "1.0.0",
        "description": (
            "Helix Super Light Brain. Udleder konklusioner af kilder med regler "
            "i stedet for gæt. Enhver konklusion bærer kilde, tid og bevisgrad "
            "(MAALT, DOKUMENTERET eller SAGT)."
        ),
    },
    "servers": [{"url": "http://host.docker.internal:6302"}],
    "paths": {
        "/status": {
            "get": {
                "operationId": "hjerne_status",
                "summary": "Hvad hjernen ved lige nu",
                "description": (
                    "Antal konklusioner, emner, hvor meget der ikke blev forstået, "
                    "og fordelingen af bevisgrader. Brug den når brugeren spørger "
                    "'hvad ved du' eller 'hvad har vi'."
                ),
                "responses": {"200": {"description": "Status"}},
            }
        },
        "/udled": {
            "post": {
                "operationId": "hjerne_udled",
                "summary": "Læs kilder og udled konklusioner",
                "description": (
                    "Send tekst ind som kilder. Hjernen udtrækker sagsnumre, CPR, "
                    "beløb, datoer og hændelser, og udleder konklusioner efter "
                    "faste former. Tekst den ikke forstår havner i lærings-"
                    "registeret — den gætter aldrig."
                ),
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "kilder": {
                                        "type": "array",
                                        "items": {
                                            "type": "object",
                                            "properties": {
                                                "id": {"type": "string"},
                                                "tekst": {"type": "string"},
                                                "type": {
                                                    "type": "string",
                                                    "description": "journal, dokument, maalt eller samtale",
                                                },
                                            },
                                            "required": ["tekst"],
                                        },
                                    }
                                },
                                "required": ["kilder"],
                            }
                        }
                    },
                },
                "responses": {"200": {"description": "Hvad der blev udledt"}},
            }
        },
        "/konklusioner": {
            "get": {
                "operationId": "hjerne_konklusioner",
                "summary": "Hent de nyeste konklusioner",
                "parameters": [
                    {
                        "name": "antal",
                        "in": "query",
                        "schema": {"type": "integer", "default": 25},
                    }
                ],
                "responses": {"200": {"description": "Liste af konklusioner"}},
            }
        },
        "/register": {
            "get": {
                "operationId": "hjerne_register",
                "summary": "Det hjernen ikke forstod",
                "description": (
                    "Læringsregisteret. Hver post er tekst ingen regel kunne "
                    "læse. Dem afgør DNA eller jeg senere: bliv en regel, eller "
                    "kasseres som støj."
                ),
                "parameters": [
                    {
                        "name": "antal",
                        "in": "query",
                        "schema": {"type": "integer", "default": 25},
                    }
                ],
                "responses": {"200": {"description": "Registeret"}},
            }
        },
        "/drom": {
            "get": {
                "operationId": "hjerne_drom",
                "summary": "Drømmens fund",
                "description": (
                    "Modsigelser, forældede konklusioner, påstande uden "
                    "dokumentation, gentagelser og retningsskift."
                ),
                "responses": {"200": {"description": "Fund"}},
            }
        },
    },
}
