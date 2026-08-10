#!/usr/bin/env python3
"""Bygger tilskudd_data.zip til GitHub-releasen «data-grunnlag».

Releasen er halvparten av den månedlige automatiseringen: workflowen skraper
tilskudd.no, kulturdirektoratet.no og bygger nettsidedataene selv, men de
manuelt nedlastede NKF/FLB- og NFI-filene kan den ikke lage. Dem henter den
herfra.

Zip-en inneholder kun de seks filene workflowen faktisk leser. Hele
tilskudd_data/ er 1,2 GB, mens disse er ~61 MB - resten regenereres av
skrapestegene eller brukes bare til egen analyse.

Mangler en fil, stopper vi heller enn å laste opp et ufullstendig grunnlag:
en zip uten f.eks. innvilgelsesgrad-tabellen ville gitt en workflow som kjører
grønt, men publiserer en nettside der kompassnålen mangler for hele
Kulturrådet.

Kjøring:  python lag_datagrunnlag_zip.py
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

KILDE = Path("tilskudd_data")
UT = Path("tilskudd_data.zip")

# Filnavn -> hvem som leser den. Kommentaren er ikke pynt: når en av disse
# forsvinner eller skifter navn, er det denne listen som forteller hva som
# knekker.
PAAKREVDE = {
    "nkf_flb_organisasjoner_2021_2026_alle_status.csv": "slaa_sammen_hoveddatasett.py",
    "nkf_flb_organisasjoner_2021_2026.csv": "lag_v4_data.py (mottakere/beløp)",
    "nkf_flb_innvilgelsesgrad_per_ordning.csv": "lag_v4_data.py (innvilgelsesgrad)",
    "brreg_lookup.csv": "slaa_sammen_hoveddatasett.py (sektorkode)",
    "nfi_ordninger.json": "lag_v4_data.py (NFI-frister)",
}

# NFI-tildelingsfila har nedlastingsdatoen i navnet og heter noe nytt hver
# halvårlige runde, så den kan ikke listes med fast navn. Samme mønster som
# lag_v4_data.py bruker: nyeste treff vinner.
NFI_MOENSTER = "nfi_tildelinger_*.xlsx"


def main() -> int:
    if not KILDE.is_dir():
        print(f"✗ finner ikke {KILDE}/ — kjør fra repo-roten.")
        return 1

    mangler = [(f, bruker) for f, bruker in PAAKREVDE.items() if not (KILDE / f).exists()]

    nfi = sorted(KILDE.glob(NFI_MOENSTER), key=lambda p: p.stat().st_mtime)
    if not nfi:
        mangler.append((NFI_MOENSTER, "lag_v4_data.py (NFI-tildelinger)"))

    if mangler:
        print(f"✗ {len(mangler)} påkrevde filer mangler i {KILDE}/:")
        for f, bruker in mangler:
            print(f"    {f}  (trengs av {bruker})")
        print("\nKjør den halvårlige NKF/FLB- eller NFI-rutinen i README før du bygger zip-en.")
        return 1

    filer = list(PAAKREVDE) + [nfi[-1].name]
    with zipfile.ZipFile(UT, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for f in filer:
            sti = KILDE / f
            print(f"  pakker {f} ({sti.stat().st_size / 1024 / 1024:.1f} MB) …")
            z.write(sti, arcname=f)  # flat zip - workflowen pakker ut i tilskudd_data/

    raa = sum((KILDE / f).stat().st_size for f in filer)
    pakket = UT.stat().st_size
    print(f"\n✓ {UT}: {pakket / 1024 / 1024:.1f} MB "
          f"({raa / 1024 / 1024:.0f} MB rå, {100 - pakket / raa * 100:.0f} % komprimert)")
    print("\nLast den opp som vedlegg på releasen «data-grunnlag» "
          "(Releases → data-grunnlag → Edit → slett gammelt vedlegg → dra inn det nye).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
