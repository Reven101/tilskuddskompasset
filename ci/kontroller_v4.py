"""Kontrollerer ordninger_v4.js etter bygging — CI-vakt før publisering.

Kjøres av GitHub Actions rett etter lag_v4_data.py. Stopper publisering
hvis den genererte filen ser gal ut: bedre at nettsiden beholder gamle
data enn at den får ødelagte.

Kjøring:  python3 ci/kontroller_v4.py
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path

FIL = Path("ordninger_v4.js")
MINST_ORDNINGER = 250  # per juli 2026 er det 307 — fall under her er alarm
PAAKREVDE_FELT = ("id", "tittel")


def main() -> int:
    if not FIL.exists():
        print(f"✗ {FIL} finnes ikke — lag_v4_data.py feilet?")
        return 1
    tekst = FIL.read_text(encoding="utf-8")

    m = re.search(r'const GENERERT = "(\d{4}-\d{2}-\d{2})"', tekst)
    if not m:
        print("✗ fant ikke GENERERT-datoen — er filformatet endret?")
        return 1
    if m.group(1) != date.today().isoformat():
        print(f"✗ GENERERT er {m.group(1)}, ikke dagens dato — ble filen bygget på nytt?")
        return 1

    m = re.search(r"const ORDNINGER = (\[.*\]);?\s*$", tekst, re.S)
    if not m:
        print("✗ fant ikke ORDNINGER-listen i filen")
        return 1
    try:
        ordninger = json.loads(m.group(1).rstrip(";"))
    except json.JSONDecodeError as e:
        print(f"✗ ORDNINGER er ikke gyldig JSON: {e}")
        return 1

    if len(ordninger) < MINST_ORDNINGER:
        print(f"✗ bare {len(ordninger)} ordninger (venter minst {MINST_ORDNINGER}) — "
              "datakilde delvis nede? Publiserer ikke.")
        return 1
    for felt in PAAKREVDE_FELT:
        mangler = sum(1 for o in ordninger if not o.get(felt))
        if mangler:
            print(f"✗ {mangler} ordninger mangler feltet «{felt}»")
            return 1

    print(f"✓ ordninger_v4.js ser sunn ut: {len(ordninger)} ordninger, generert {date.today()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
