"""Kobler tilskuddsforvaltere mot Kudos-evalueringer — via API-ets eget
aktørsøk, ikke lokal navnematch.

VERSJON 2. Første versjon koblet på navnematch mot et lokalt snapshot og
ga falske nuller (Bufdir har 132 evalueringer i Kudos; navnematchingen
fant 0 fordi den bare så i owners-feltet). Nå spørres Kudos-API-et
direkte per forvalter med actor_name-filteret, som søker på tvers av
alle aktørroller og kortnavn — verifisert 2026-07-05: «Bufdir» og
fullt navn gir identisk svar.

For hver forvalter i tildelingsdataene hentes:
  - antall Kudos-evalueringer noensinne (type=Evaluering)
  - antall publisert 2021–2026
  - sum tildelt og antall tildelinger per budsjettår (fra tilskudd.no)

Kjøring:   python3 analyse/evalueringer_vs_tilskudd.py   (fra repo-roten)
Tid:       ~1 minutt (to API-kall per forvalter, høflig pause)
Krever:    tilskudd_data/tildelinger_alle.csv  (hent_bulk_tildelinger.py)
Resultat:  tilskudd_data/evalueringer_vs_tilskudd.csv + tabell i terminalen

METODENOTAT: utforskende statistikk, ikke kausalanalyse eller
kontrollrapport. Kudos' aktørsøk er tekstbasert — sjekk et par
forvaltere du kjenner i kudos.dfo.no før du publiserer tall. En
evaluering kan gjelde en annen del av virksomheten enn tilskudds-
forvaltningen, og tildelingsvinduet 2021–2026 er for kort for
årsak-virkning.
"""

from __future__ import annotations

import csv
import json
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

TILDELINGER_FIL = Path("tilskudd_data/tildelinger_alle.csv")
UTFIL = Path("tilskudd_data/evalueringer_vs_tilskudd.csv")

API = "https://kudos.dfo.no/api/v0/documents"
BRUKERAGENT = "Tilskuddskompasset-analyse (kontakt@impromptu.no)"
PAUSE = 0.25
TOPP_N = 25  # forvaltere i terminaltabellen (CSV-en får alle)


def vask_navn(navn: str) -> str:
    """Rydder artefakter fra tilskudd.no-navnene før API-søk.

    F.eks. «Kultur - og likestillingsdepartementet» (villfarent mellomrom
    før bindestreken) → «Kultur- og likestillingsdepartementet».
    """
    return " ".join(navn.replace(" - og ", "- og ").split())


def kudos_antall(navn: str, fra: int | None = None, til: int | None = None) -> int:
    """Antall Kudos-evalueringer der forvalteren er aktør (alle roller)."""
    params: dict = {"actor_name": navn, "type": "Evaluering", "per_page": 1}
    if fra:
        params["published_year_from"] = fra
    if til:
        params["published_year_to"] = til
    url = f"{API}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": BRUKERAGENT})
    with urllib.request.urlopen(req, timeout=30) as svar:
        return json.loads(svar.read().decode("utf-8")).get("meta", {}).get("total", 0)


def kudos_antall_taalmodig(navn: str, **kw) -> int | None:
    """Ett nytt forsøk ved nettverksfeil; None hvis begge ryker."""
    for forsok in (1, 2):
        try:
            return kudos_antall(navn, **kw)
        except Exception as e:
            if forsok == 2:
                print(f"  ! {navn}: {type(e).__name__}: {e}")
                return None
            time.sleep(2)


def les_tildelinger() -> list[dict]:
    if not TILDELINGER_FIL.exists():
        raise SystemExit(f"FEIL: {TILDELINGER_FIL} mangler — kjør først "
                         "python hent_bulk_tildelinger.py")
    with TILDELINGER_FIL.open("r", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f, delimiter=";"))


def main() -> int:
    print("Leser tildelingsdataene …")
    sum_per: dict[str, dict[int, float]] = defaultdict(lambda: defaultdict(float))
    antall_per: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    for rad in les_tildelinger():
        forvalter = vask_navn((rad.get("tilskuddsforvalter") or "").strip())
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

    print(f"  {len(sum_per)} forvaltere — spør Kudos om hver enkelt "
          f"(~{len(sum_per) * 2} kall) …")

    rader = []
    for i, (forvalter, per_aar) in enumerate(
            sorted(sum_per.items(), key=lambda p: -sum(p[1].values())), 1):
        totalt = kudos_antall_taalmodig(forvalter)
        nylig = kudos_antall_taalmodig(forvalter, fra=2021, til=2026)
        time.sleep(PAUSE)
        if i % 10 == 0 or i == len(sum_per):
            print(f"  {i}/{len(sum_per)} forvaltere sjekket")

        aar_med_tall = sorted(per_aar)
        forste, siste = aar_med_tall[0], aar_med_tall[-1]
        endring = ((per_aar[siste] - per_aar[forste]) / per_aar[forste] * 100
                   if per_aar[forste] and siste > forste else None)
        rader.append({
            "forvalter": forvalter,
            "evalueringer_totalt": totalt if totalt is not None else "",
            "evalueringer_2021_2026": nylig if nylig is not None else "",
            "sum_tildelt_2021_2026": round(sum(per_aar.values())),
            "antall_tildelinger": sum(antall_per[forvalter].values()),
            "forste_aar": forste,
            "siste_aar": siste,
            "endring_prosent": round(endring, 1) if endring is not None else "",
        })

    ubesvart = sum(1 for r in rader if r["evalueringer_totalt"] == "")
    if ubesvart > len(rader) * 0.2:
        raise SystemExit(f"FEIL: {ubesvart} av {len(rader)} forvaltere fikk ikke "
                         "svar fra Kudos — skriver ikke CSV. Prøv igjen.")

    with UTFIL.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rader[0].keys()), delimiter=";")
        w.writeheader()
        w.writerows(rader)
    print(f"✓ skrev {UTFIL} ({len(rader)} forvaltere, {ubesvart} uten svar)\n")

    print(f"{'Forvalter':<42} {'Eval.':>6} {'Eval 21-26':>10} "
          f"{'Sum tildelt':>14} {'Endring':>8}")
    print("-" * 84)
    for r in rader[:TOPP_N]:
        endring = f"{r['endring_prosent']}%" if r["endring_prosent"] != "" else "–"
        print(f"{r['forvalter'][:41]:<42} {r['evalueringer_totalt']!s:>6} "
              f"{r['evalueringer_2021_2026']!s:>10} "
              f"{r['sum_tildelt_2021_2026']:>14,.0f} {endring:>8}".replace(",", " "))

    print("\nMETODENOTAT: utforskende tall. Kudos' aktørsøk er tekstbasert — "
          "stikkprøv forvaltere\ndu kjenner på kudos.dfo.no før publisering.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
