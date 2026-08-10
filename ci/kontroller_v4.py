"""Kontrollerer ordninger_v4.js etter bygging — CI-vakt før publisering.

Kjøres av GitHub Actions rett etter lag_v4_data.py. Stopper publisering
hvis den genererte filen ser gal ut: bedre at nettsiden beholder gamle
data enn at den får ødelagte.

Kjøring:  python3 ci/kontroller_v4.py
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import date, datetime
from pathlib import Path

# ✓/✗ krasjer på cp1252-konsollet i Windows; CI kjører UTF-8 uansett.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

FIL = Path("ordninger_v4.js")
SAMLET = Path("tilskudd_data/tildelinger_samlet_2021_2026.csv")
MINST_ORDNINGER = 250  # per juli 2026 er det 307 — fall under her er alarm
PAAKREVDE_FELT = ("id", "tittel")

# Nettsidens default-visning bygger på frister. Faller dette tallet mot null,
# er ordningene fortsatt i filen, men usynlige for brukeren — akkurat den
# feilen som fantes før august 2026 og som ingen kontroll fanget.
MINST_MED_FREMTIDIG_FRIST = 40

# Berikelsen (mottakertabeller, fylker, beløpsfordeling) kommer fra
# tildelinger_samlet-CSV-en. Kollapser den, mister siden transparensdelen
# uten at antall ordninger endrer seg.
MINST_MED_MOTTAKERE = 250

# fristtype speiler tilskudd.no sin deadlineType. Dukker det opp en ny verdi
# der, slutter UI-ets frist-logikk å matche uten å feile — derfor rødt lys
# på ukjente verdier i stedet for stille feil.
KJENTE_FRISTTYPER = {None, "DEADLINE", "NO_DEADLINE", "UNKNOWN", "CONTINUOUS"}

# En hel datakilde kan falle ut uten at totalen kryper under MINST_ORDNINGER:
# mister vi alle NFI-ordningene, står vi igjen med ~250 og slipper gjennom.
# Derfor et gulv per kilde. Tallene er satt godt under dagens nivå (per august
# 2026: DT 162, NKF 48, NFI 61, KUL 16, FLB 15, KD 11) - de skal fange
# bortfall, ikke normal variasjon.
MINST_PER_KILDE = {"DT": 120, "NKF": 35, "NFI": 40, "FLB": 10}


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

    per_kilde: dict[str, int] = {}
    for o in ordninger:
        per_kilde[str(o["id"]).split("-")[0]] = per_kilde.get(str(o["id"]).split("-")[0], 0) + 1
    for kilde, minst in MINST_PER_KILDE.items():
        if per_kilde.get(kilde, 0) < minst:
            print(f"✗ bare {per_kilde.get(kilde, 0)} {kilde}-ordninger (venter minst {minst}) — "
                  "falt en hel datakilde ut av byggingen?")
            return 1

    ukjente = {o.get("fristtype") for o in ordninger} - KJENTE_FRISTTYPER
    if ukjente:
        print(f"✗ ukjente fristtype-verdier: {sorted(str(u) for u in ukjente)} — "
              "kilden har endret vokabular, og frist-logikken i index.html må oppdateres.")
        return 1

    i_dag = date.today()
    med_frist = 0
    for o in ordninger:
        for f in o.get("frister") or []:
            try:
                if date.fromisoformat(str(f)[:10]) >= i_dag:
                    med_frist += 1
                    break
            except ValueError:
                continue
    if med_frist < MINST_MED_FREMTIDIG_FRIST:
        print(f"✗ bare {med_frist} ordninger har en frist fram i tid "
              f"(venter minst {MINST_MED_FREMTIDIG_FRIST}) — ble fristene skrapet?")
        return 1

    med_mottakere = sum(1 for o in ordninger if o.get("topp_mottakere"))
    if med_mottakere < MINST_MED_MOTTAKERE:
        print(f"✗ bare {med_mottakere} ordninger har mottakerdata "
              f"(venter minst {MINST_MED_MOTTAKERE}) — kom tildelingsfilen med?")
        return 1

    # I CI skal sammenslåingssteget ha skrevet tildelingsfilen samme dag. Er den
    # eldre, bygget vi på releasens frosne kopi, og siden ville fått ferske
    # nøkkeltall med gamle mottakertabeller under dagens dato.
    if os.environ.get("CI"):
        if not SAMLET.exists():
            print(f"✗ {SAMLET} finnes ikke — kjørte slaa_sammen_hoveddatasett.py?")
            return 1
        skrevet = datetime.fromtimestamp(SAMLET.stat().st_mtime).date()
        if skrevet != i_dag:
            print(f"✗ {SAMLET} ble sist skrevet {skrevet}, ikke i dag — "
                  "sammenslåingssteget ble hoppet over, og tildelingsdataene er frosne.")
            return 1

    print(f"✓ ordninger_v4.js ser sunn ut: {len(ordninger)} ordninger, "
          f"{med_frist} med kommende frist, {med_mottakere} med mottakerdata, "
          f"generert {i_dag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
