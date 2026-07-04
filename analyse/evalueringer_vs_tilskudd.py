"""Kobler Kudos-evalueringer mot tildelingsdata: hvem evalueres, og
hvordan ser tilskuddsstrømmene deres ut?

Steg 2 av 2. Leser snapshotet fra hent_kudos_evalueringer.py og
tildelinger_alle.csv (fra hent_bulk_tildelinger.py), kobler dem på
forvalternavn, og lager en oversikt per tilskuddsforvalter:

  - antall Kudos-evalueringer der forvalteren er aktør, per år
  - sum tildelt og antall tildelinger per budsjettår (2021–2026)
  - endring i tildelt sum fra første til siste hele budsjettår

VIKTIG METODENOTAT: Dette er UTFORSKENDE statistikk, ikke kausalanalyse.
Tildelingsdataene dekker bare 2021–2026 — altfor kort vindu til å si om
evalueringer *fører til* budsjettendringer. Bruk resultatet til å finne
mønstre verdt å undersøke skikkelig, ikke som konklusjoner.

Kjøring:   python3 analyse/evalueringer_vs_tilskudd.py    (fra repo-roten)
Krever:    tilskudd_data/kudos_evalueringer.json  (steg 1)
           tilskudd_data/tildelinger_alle.csv     (hent_bulk_tildelinger.py)
Resultat:  tilskudd_data/evalueringer_vs_tilskudd.csv + tabell i terminalen

Feltene i Kudos-dokumentene gjenkjennes defensivt (API-et er v0 og
udokumentert på dette punktet). Finner scriptet ikke aktører/årstall,
sier det fra og viser feltnavnene det faktisk ser — meld da fra, så
justeres gjenkjenningen.
"""

from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

EVAL_FIL = Path("tilskudd_data/kudos_evalueringer.json")
TILDELINGER_FIL = Path("tilskudd_data/tildelinger_alle.csv")
UTFIL = Path("tilskudd_data/evalueringer_vs_tilskudd.csv")

TOPP_N = 25  # forvaltere i terminaltabellen (CSV-en får alle)


# ---------------------------------------- feltgjenkjenning (Kudos v0) ----

def finn_aktornavn(dok: dict) -> list[str]:
    """Aktørnavn fra et Kudos-dokument, uansett hvilken form v0 bruker."""
    navn: list[str] = []
    for nokkel in ("actors", "aktorer", "organizations", "publishers", "owners"):
        for aktor in dok.get(nokkel) or []:
            if isinstance(aktor, dict):
                for felt in ("name", "navn", "actor_name", "organization_name"):
                    if aktor.get(felt):
                        navn.append(str(aktor[felt]))
                        break
            elif isinstance(aktor, str):
                navn.append(aktor)
    for nokkel in ("owner", "utgiver", "publisher"):
        verdi = dok.get(nokkel)
        if isinstance(verdi, dict) and verdi.get("name"):
            navn.append(str(verdi["name"]))
        elif isinstance(verdi, str) and verdi:
            navn.append(verdi)
    return navn


def finn_aar(dok: dict) -> int | None:
    """Publiseringsår fra et Kudos-dokument."""
    for nokkel in ("published_year", "publication_year", "year"):
        verdi = dok.get(nokkel)
        if verdi and str(verdi)[:4].isdigit():
            return int(str(verdi)[:4])
    for nokkel in ("published_at", "published_date", "publication_date",
                   "published", "created_at"):
        verdi = dok.get(nokkel)
        if verdi and str(verdi)[:4].isdigit():
            return int(str(verdi)[:4])
    for nokkel in ("concerned_year", "concerned_year_to", "concerned_year_from"):
        verdi = dok.get(nokkel)
        if verdi and str(verdi)[:4].isdigit():
            return int(str(verdi)[:4])
    return None


def norm(navn: str) -> str:
    return " ".join(str(navn).lower().replace("-", " ").split())


# ------------------------------------------------------- innlesing ----

def les_evalueringer() -> list[dict]:
    if not EVAL_FIL.exists():
        raise SystemExit(f"FEIL: {EVAL_FIL} mangler — kjør først "
                         "python3 analyse/hent_kudos_evalueringer.py")
    dokumenter = json.loads(EVAL_FIL.read_text(encoding="utf-8"))["dokumenter"]

    uten_aktor = sum(1 for d in dokumenter if not finn_aktornavn(d))
    if uten_aktor > len(dokumenter) * 0.9:
        eksempel = dokumenter[0] if dokumenter else {}
        raise SystemExit(
            "FEIL: fant ikke aktørfeltet i Kudos-dokumentene.\n"
            f"Feltene i første dokument er: {sorted(eksempel)}\n"
            "Meld fra hvilke felt som ligner aktører, så justeres "
            "finn_aktornavn() i dette scriptet."
        )
    print(f"  {len(dokumenter)} evalueringer, {uten_aktor} uten gjenkjent aktør")
    return dokumenter


def les_tildelinger() -> list[dict]:
    if not TILDELINGER_FIL.exists():
        raise SystemExit(f"FEIL: {TILDELINGER_FIL} mangler — kjør først "
                         "python hent_bulk_tildelinger.py")
    with TILDELINGER_FIL.open("r", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f, delimiter=";"))


# --------------------------------------------------------- analyse ----

def main() -> int:
    print("Leser Kudos-evalueringene …")
    evalueringer = les_evalueringer()
    print("Leser tildelingsdataene …")
    tildelinger = les_tildelinger()

    # evalueringer per normalisert aktørnavn, med årstall
    eval_per_aktor: dict[str, list[int | None]] = defaultdict(list)
    for dok in evalueringer:
        aar = finn_aar(dok)
        for navn in set(map(norm, finn_aktornavn(dok))):
            eval_per_aktor[navn].append(aar)

    # tildelinger per forvalter: sum og antall per budsjettår
    sum_per: dict[str, dict[int, float]] = defaultdict(lambda: defaultdict(float))
    antall_per: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    for rad in tildelinger:
        forvalter = (rad.get("tilskuddsforvalter") or "").strip()
        if not forvalter:
            continue
        try:
            aar = int(float(rad.get("budsjettar") or 0))
            belop = float(rad.get("tildelt_belop") or 0)
        except (ValueError, TypeError):
            continue
        if belop > 0 and 2021 <= aar <= 2026:
            sum_per[forvalter][aar] += belop
            antall_per[forvalter][aar] += 1

    print(f"  {len(sum_per)} forvaltere i tildelingsdataene, "
          f"{len(eval_per_aktor)} aktører i evalueringene")

    # koble: eksakt normalisert match, ellers innholdsmatch begge veier
    rader = []
    for forvalter, per_aar in sum_per.items():
        n = norm(forvalter)
        eval_aar = eval_per_aktor.get(n)
        if eval_aar is None:
            treff = [a for a in eval_per_aktor if len(n) > 6 and (n in a or a in n)]
            eval_aar = [aar for a in treff for aar in eval_per_aktor[a]] if treff else []

        aar_med_tall = sorted(per_aar)
        forste, siste = aar_med_tall[0], aar_med_tall[-1]
        endring = ((per_aar[siste] - per_aar[forste]) / per_aar[forste] * 100
                   if per_aar[forste] and siste > forste else None)
        rader.append({
            "forvalter": forvalter,
            "evalueringer_totalt": len(eval_aar),
            "evalueringer_2021_2026": sum(1 for a in eval_aar if a and 2021 <= a <= 2026),
            "sum_tildelt_2021_2026": round(sum(per_aar.values())),
            "antall_tildelinger": sum(antall_per[forvalter].values()),
            "forste_aar": forste,
            "siste_aar": siste,
            "endring_prosent": round(endring, 1) if endring is not None else "",
        })

    rader.sort(key=lambda r: -r["sum_tildelt_2021_2026"])

    with UTFIL.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rader[0].keys()), delimiter=";")
        w.writeheader()
        w.writerows(rader)
    print(f"✓ skrev {UTFIL} ({len(rader)} forvaltere)\n")

    print(f"{'Forvalter':<42} {'Eval.':>6} {'Eval 21-26':>10} "
          f"{'Sum tildelt':>14} {'Endring':>8}")
    print("-" * 84)
    for r in rader[:TOPP_N]:
        endring = f"{r['endring_prosent']}%" if r["endring_prosent"] != "" else "–"
        print(f"{r['forvalter'][:41]:<42} {r['evalueringer_totalt']:>6} "
              f"{r['evalueringer_2021_2026']:>10} "
              f"{r['sum_tildelt_2021_2026']:>14,.0f} {endring:>8}".replace(",", " "))

    print("\nMETODENOTAT: utforskende tall — navnematch mellom to registre og "
          "et kort tidsvindu.\nSjekk enkeltforvaltere du kjenner før du "
          "trekker slutninger, og se CSV-en for alle.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
