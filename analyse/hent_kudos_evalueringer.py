"""Høster alle evalueringer fra Kudos (DFØ) til et lokalt snapshot.

Steg 1 av 2 i evaluering-mot-tilskudd-analysen. Henter alle dokumenter
med type=Evaluering fra Kudos-API-et (~7 000 stk, ~140 sider) og lagrer
rådataene som JSON. Steg 2 (evalueringer_vs_tilskudd.py) gjør koblingen
mot tildelingsdataene.

Kjøring:   python3 analyse/hent_kudos_evalueringer.py     (fra repo-roten)
Tid:       2–4 minutter (høflig pause mellom kallene)
Resultat:  tilskudd_data/kudos_evalueringer.json

API-et er verifisert 2026-07-04 — se api-atlas/eksempler/hent_kudos.py
i Impromptu-Analytics-repoet for full dokumentasjon av parametrene.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

API = "https://kudos.dfo.no/api/v0/documents"
BRUKERAGENT = "Tilskuddskompasset-analyse (kontakt@impromptu.no)"
UTFIL = Path("tilskudd_data/kudos_evalueringer.json")
PAUSE = 0.3


def hent_side(side: int) -> dict:
    params = urllib.parse.urlencode({"type": "Evaluering", "page": side})
    req = urllib.request.Request(f"{API}?{params}",
                                 headers={"User-Agent": BRUKERAGENT})
    with urllib.request.urlopen(req, timeout=60) as svar:
        return json.loads(svar.read().decode("utf-8"))


def main() -> int:
    print("Henter alle evalueringer fra Kudos …")
    forste = hent_side(1)
    meta = forste.get("meta", {})
    sider, total = meta.get("last_page", 1), meta.get("total", 0)
    if total < 1_000:
        print(f"FEIL: bare {total} evalueringer — har API-et endret seg?")
        return 1
    print(f"  {total} evalueringer fordelt på {sider} sider")

    dokumenter = list(forste.get("data", []))
    for side in range(2, sider + 1):
        dokumenter.extend(hent_side(side).get("data", []))
        if side % 10 == 0 or side == sider:
            print(f"  side {side}/{sider} ({len(dokumenter)} dokumenter)")
        time.sleep(PAUSE)

    if len(dokumenter) < total * 0.95:
        print(f"FEIL: fikk {len(dokumenter)} av {total} — avbryter uten å skrive.")
        return 1

    UTFIL.parent.mkdir(parents=True, exist_ok=True)
    UTFIL.write_text(json.dumps(
        {"meta": {"kilde": "Kudos (DFØ)", "type": "Evaluering",
                  "dato_hentet": date.today().isoformat(), "antall": len(dokumenter)},
         "dokumenter": dokumenter},
        ensure_ascii=False), encoding="utf-8")
    print(f"✓ skrev {UTFIL} ({len(dokumenter)} evalueringer)")
    print("Neste steg: python3 analyse/evalueringer_vs_tilskudd.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
