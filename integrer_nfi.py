#!/usr/bin/env python3
"""
Integrer NFI-ordninger i tilskuddskompasset
=============================================
Leser:
  tilskudd_data/ordninger.json      – eksisterende lottstift-ordninger
  tilskudd_data/nfi_ordninger.json  – nyinnhentede NFI-ordninger

Skriver nye versjoner av:
  tilskudd_data/ordninger.json
  tilskudd_data/ordninger.csv
  tilskudd_data/ordninger_data.js

NFI-ordninger får ID-er på formen NFI-001 … NFI-055.
Kjøringen er idempotent: eventuelle eksisterende NFI-poster fjernes
og erstattes ved nytt kjøring.
"""

import csv
import json
import re
from pathlib import Path

UTMAPPE = Path("tilskudd_data")

MND = {
    "januar": 1, "februar": 2, "mars": 3, "april": 4, "mai": 5, "juni": 6,
    "juli": 7, "august": 8, "september": 9, "oktober": 10,
    "november": 11, "desember": 12,
}

# Kategori → mottakerkategori
MOTTAKER = {
    "utvikling":                              "Næringsliv og enkeltpersoner",
    "produksjon":                             "Næringsliv og enkeltpersoner",
    "lansering-profilering-og-distribusjon":  "Næringsliv og enkeltpersoner",
    "kompetanseheving-2":                     "Næringsliv og enkeltpersoner",
    "formidling-2":                           "Ideelle og frivillige organisasjoner",
    "insentiv":                               "Næringsliv og enkeltpersoner",
}

# Ordninger med løpende behandling (ingen frist)
LOPENDE_HINT = {"rammetilskudd", "etterhandstilskudd", "sorfond",
                "insentivordningen-2023"}


def parse_frist_dato(tekst: str) -> tuple[int | None, int | None, int | None]:
    """'9. september 2026' → (9, 9, 2026)"""
    m = re.search(r"(\d{1,2})\.\s+(\w+)\s+(\d{4})", tekst.lower())
    if m and m.group(2) in MND:
        return int(m.group(1)), MND[m.group(2)], int(m.group(3))
    return None, None, None


def konverter_nfi(nfi: dict, nfi_id: str) -> dict:
    """Konverter ett NFI-ordning-objekt til kompasset-skjema."""
    slug = nfi["url"].rstrip("/").split("/")[-1]
    kat  = nfi.get("kategori", "")

    # Søknadsfrister
    frister = nfi.get("soknadsfrister", [])
    lopende = not frister or slug in LOPENDE_HINT
    frist_raa = "Løpende" if lopende else "; ".join(frister)
    if lopende:
        dag, mnd, aar = None, None, None
    else:
        dag, mnd, aar = parse_frist_dato(frister[0])

    # Ressurser
    ressurser = []
    portal = nfi.get("soknadsportal_url")
    lovdata = nfi.get("lovdata_url")
    if portal:
        ressurser.append({"tekst": "Søknadsportal (NFI)", "url": portal})
    if lovdata:
        ressurser.append({"tekst": "Regelverk (Lovdata)", "url": lovdata})

    # Prioritering + vilkår til andre_tildelingskriterier
    prioritering = (nfi.get("prioritering") or "").strip()
    vilkaar      = (nfi.get("vilkaar") or "").strip()
    and_krit = prioritering
    if vilkaar:
        and_krit = (and_krit + "\n\nVilkår:\n" + vilkaar).strip() if and_krit else vilkaar

    # type_tilskudd
    type_tilskudd = "Driftsmidler" if slug == "rammetilskudd" else "Prosjektmidler"

    return {
        "id":                                     nfi_id,
        "url":                                    nfi["url"],
        "navn":                                   nfi.get("navn") or "",
        "formaal":                                nfi.get("ingress") or "",
        "forvalter":                              "Norsk filminstitutt",
        "type_tilskudd":                          type_tilskudd,
        "mottakerkategori":                       MOTTAKER.get(kat, "Næringsliv og enkeltpersoner"),
        "finansiering":                           "Statsbudsjettet",
        "departement":                            "Kultur- og likestillingsdepartementet",
        "tilgjengelige_midler":                   None,
        "frist_raa":                              frist_raa,
        "frist_dag":                              dag,
        "frist_mnd":                              mnd,
        "frist_aar":                              aar,
        "mal_og_malgruppe_for_tilskuddsordningen": nfi.get("ingress") or "",
        "hvem_kan_motta_tilskudd":                nfi.get("hvem_kan_soke") or "",
        "hva_kan_tilskuddet_brukes_til":          nfi.get("hva_kan_sokes") or "",
        "andre_tildelingskriterier":              and_krit,
        "rapporteringskrav":                      None,
        "hvordan_soke":                           (
            "Søknader sendes inn via NFI sin søknadsportal: "
            f"{portal or 'https://tilskudd.nfi.no'}"
        ),
        "ressurser":                              ressurser,
        "stat_aar":                               None,
        "soekere":                                None,
        "tildelinger":                            None,
        "tildelt_kr":                             None,
        "omsoekt_kr":                             None,
        "innvilgelsesgrad":                       None,
        # NFI-spesifikke tilleggsfelt (brukes ikke av JS, men nyttig i CSV/JSON)
        "nfi_kategori":                           kat,
        "nfi_saksbehandlingstid":                 nfi.get("saksbehandlingstid") or "",
        "nfi_soknadsfrister":                     "; ".join(frister) if frister else "",
    }


def lag_js_rad(d: dict) -> dict:
    """Bygg ordninger_data.js-rad fra kompasset-ordning."""
    typer = []
    tt = d.get("type_tilskudd") or ""
    if "Drift" in tt:
        typer.append("Driftsmidler")
    if "Prosjekt" in tt:
        typer.append("Prosjektmidler")
    if not typer:
        typer = ["Prosjektmidler"]

    return {
        "id":               d["id"],
        "navn":             d["navn"],
        "forvalter":        d.get("forvalter") or "",
        "type":             typer,
        "sektor":           d.get("departement") or "Ukjent",
        "dag":              d.get("frist_dag"),
        "mnd":              d.get("frist_mnd"),
        "innvilgelsesgrad": d.get("innvilgelsesgrad"),
        "midler":           d.get("tildelt_kr"),
        "hvem":             d.get("hvem_kan_motta_tilskudd"),
        "hva":              d.get("hva_kan_tilskuddet_brukes_til"),
        "rapportering":     d.get("rapporteringskrav"),
    }


def main() -> None:
    # ── Last inn kildedata ────────────────────────────────────────────────────
    lottstift = json.loads((UTMAPPE / "ordninger.json").read_text(encoding="utf-8"))
    nfi_liste = json.loads((UTMAPPE / "nfi_ordninger.json").read_text(encoding="utf-8"))

    # Fjern eventuelle tidligere NFI-poster (idempotent)
    lottstift = [o for o in lottstift if not str(o.get("id", "")).startswith("NFI-")]

    print(f"Lottstift-ordninger: {len(lottstift)}")
    print(f"NFI-ordninger:       {len(nfi_liste)}")

    # ── Konverter NFI-ordninger ───────────────────────────────────────────────
    nfi_konvertert = []
    for i, nfi in enumerate(nfi_liste, 1):
        nfi_id = f"NFI-{i:03d}"
        nfi_konvertert.append(konverter_nfi(nfi, nfi_id))
        print(f"  {nfi_id}  {nfi['navn'][:60]}")

    # ── Slå sammen ───────────────────────────────────────────────────────────
    alle = lottstift + nfi_konvertert
    print(f"\nTotalt: {len(alle)} ordninger ({len(lottstift)} lottstift + {len(nfi_konvertert)} NFI)")

    # ── ordninger.json ────────────────────────────────────────────────────────
    json_fil = UTMAPPE / "ordninger.json"
    json_fil.write_text(
        json.dumps(alle, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print(f"\nSkrevet: {json_fil}  ({len(alle)} ordninger)")

    # ── ordninger.csv ─────────────────────────────────────────────────────────
    # Feltliste: union av alle felter, lottstift-felter først
    alle_felter: list[str] = []
    sett_felter: set[str] = set()
    for rad in alle:
        for k in rad:
            if k not in sett_felter:
                alle_felter.append(k)
                sett_felter.add(k)

    csv_fil = UTMAPPE / "ordninger.csv"
    with csv_fil.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=alle_felter, delimiter=";",
                           extrasaction="ignore")
        w.writeheader()
        for rad in alle:
            r = dict(rad)
            r["ressurser"] = json.dumps(r.get("ressurser") or [], ensure_ascii=False)
            w.writerow(r)
    print(f"Skrevet: {csv_fil}")

    # ── ordninger_data.js ─────────────────────────────────────────────────────
    js_rader = [lag_js_rad(d) for d in alle]
    js_fil = UTMAPPE / "ordninger_data.js"
    js_fil.write_text(
        "const ORDNINGER = " + json.dumps(js_rader, ensure_ascii=False, indent=1) + ";\n",
        encoding="utf-8"
    )
    print(f"Skrevet: {js_fil}")

    # ── Statistikk ────────────────────────────────────────────────────────────
    print("\n=== Fordeling forvalter ===")
    from collections import Counter
    for forvalter, antall in Counter(
        o.get("forvalter") or "Ukjent" for o in alle
    ).most_common(10):
        print(f"  {forvalter[:55]:<55} {antall:3d}")

    print("\n=== NFI-ordninger per kategori ===")
    for kat, antall in Counter(
        o.get("nfi_kategori") for o in nfi_konvertert
    ).most_common():
        print(f"  {kat:<55} {antall:3d}")

    frister_n = sum(1 for o in nfi_konvertert if o["frist_raa"] != "Løpende")
    print(f"\nNFI-ordninger med søknadsfrist:  {frister_n}")
    print(f"NFI-ordninger med løpende frist: {len(nfi_konvertert) - frister_n}")


if __name__ == "__main__":
    main()
