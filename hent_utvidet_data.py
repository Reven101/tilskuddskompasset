#!/usr/bin/env python3
"""
Utvidet datahøsting fra tilskudd.no – henter tildelingshistorikk og mottakere.
==============================================================================
Bygger på tilskuddsdata.py, men fokuserer på:
  1. Komplett tidsserie (budsjett, tildelt, mottakere per år)
  2. Enkelttildelinger med mottaker, orgnr, prosjekttittel, beløp
  3. Oppsummeringsstatistikk (allocationSummary)
  4. Strukturert innhold fra publishedVersion (mål, kriterier, rapportering)

Bruker __NEXT_DATA__-JSON som primærkilde (strukturert og stabil).

Merk om paginering:
  __NEXT_DATA__ inneholder kun topp 10 mottakere per ordning (sortert etter
  tildelingssum). Backend-API er ikke offentlig eksponert, så full mottakerliste
  krever browser-automatisering. Oppsummeringsstatistikk (totalRecipients,
  totalGrantedAmount etc.) dekker likevel alle mottakere.

Avhengigheter:  pip install requests beautifulsoup4
Kjøring:        python hent_utvidet_data.py
"""

import csv
import json
import re
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE = "https://tilskudd.lottstift.no"
HEADERS = {
    "User-Agent": "Tilskuddskompasset-datainnsamling (kontakt: kontakt@impromptu.no)"
}
PAUSE = 0.7
TIMEOUT = 20
ID_ROM = range(1, 1201)

session = requests.Session()
session.headers.update(HEADERS)


# ---------------------------------------------------------------- nettverk
def hent(url: str) -> requests.Response | None:
    for forsoek in range(3):
        try:
            r = session.get(url, timeout=TIMEOUT, allow_redirects=True)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r
        except requests.RequestException as e:
            vent = 2 ** forsoek
            print(f"  ! {e} – venter {vent}s", file=sys.stderr)
            time.sleep(vent)
    return None


def finn_urler_fra_sitemap() -> list[str]:
    for kandidat in ("/sitemap.xml", "/sitemap-0.xml", "/sitemap_index.xml"):
        r = hent(BASE + kandidat)
        if r is None:
            continue
        urler = re.findall(r"<loc>([^<]+/ordning/DT-\d{4}[^<]*)</loc>", r.text)
        if urler:
            print(f"Sitemap funnet: {len(urler)} ordning-URLer")
            return sorted(set(urler))
    print("Ingen sitemap – systematisk ID-gjennomgang")
    return []


# ---------------------------------------------------------------- JSON-parsing
def hent_next_data(html: str) -> dict | None:
    """Hent __NEXT_DATA__ JSON fra HTML."""
    soup = BeautifulSoup(html, "html.parser")
    tag = soup.find("script", id="__NEXT_DATA__")
    if not tag or not tag.string:
        return None
    try:
        return json.loads(tag.string)
    except json.JSONDecodeError:
        return None


def draft_js_tekst(raw: str | None) -> str | None:
    """Parse Draft.js JSON-streng til ren tekst."""
    if not raw:
        return None
    try:
        doc = json.loads(raw) if isinstance(raw, str) else raw
        blocks = doc.get("blocks", [])
        return "\n".join(b["text"] for b in blocks if b.get("text"))
    except (json.JSONDecodeError, TypeError, KeyError):
        return raw if isinstance(raw, str) else None


def hent_tidsserie(page_props: dict) -> dict:
    """Hent cardGrantYearSeriesDiagram – budsjett, tildelt, mottakere per år."""
    diagram = page_props.get("cardGrantYearSeriesDiagram", {})
    return {
        "budsjett_serie": diagram.get("grantSchemeAmount", []),
        "tildelt_serie": diagram.get("grantedAmount", []),
        "mottakere_serie": diagram.get("recipients", []),
    }


def hent_tildelingsaar(page_props: dict) -> list[dict]:
    """Hent allocationsYears – oversikt over år med tildelinger."""
    return page_props.get("allocationsYears", [])


def hent_mottakere_fra_queries(queries: list) -> tuple[list[dict], dict | None]:
    """Hent simpleRecipients og allocationSummary fra dehydratedState queries."""
    mottakere = []
    oppsummering = None

    for q in queries:
        qkey = q.get("queryKey", [])
        data = q.get("state", {}).get("data")
        if not data:
            continue

        # SimpleRecipients
        if len(qkey) > 0 and qkey[0] == "SimpleRecipients":
            edges = data.get("simpleRecipients", {}).get("edges", [])
            page_info = data.get("simpleRecipients", {}).get("pageInfo", {})
            for edge in edges:
                node = edge.get("node", {})
                for alloc in node.get("allocations", []):
                    mottakere.append({
                        "mottaker_navn": node.get("name"),
                        "mottaker_orgnr": node.get("orgId"),
                        "mottaker_sum_tildelt": node.get("sumAllocationsAmount"),
                        "mottaker_sum_soekt": node.get("sumApplicationAmount"),
                        "mottaker_antall_tildelinger": node.get("numberOfAllocations"),
                        "tildeling_tittel": alloc.get("title"),
                        "tildeling_aar": alloc.get("year"),
                        "tildeling_belop": alloc.get("amount"),
                        "tildeling_soekt_belop": alloc.get("applicationAmount"),
                    })
            # Merk: hasNextPage betyr at det finnes flere mottakere (paginert)
            if page_info.get("hasNextPage"):
                total = page_info.get("totalEdgeCount", "?")
                print(f"    Merk: Kun {page_info.get('endCursor', '?')}/{total} "
                      f"mottakere i __NEXT_DATA__ (paginert)")

        # AllocationSummary
        if len(qkey) > 0 and qkey[0] == "AllocationSummary":
            oppsummering = data.get("allocationSummary")

    return mottakere, oppsummering


def hent_publisert_versjon(next_data: dict) -> dict | None:
    """Hent grant.grantScheme.year.publishedVersion – strukturert ordningsinfo."""
    try:
        return (next_data["props"]["pageProps"]["grant"]
                ["grantScheme"]["year"]["publishedVersion"])
    except (KeyError, TypeError):
        return None


def parse_ordning_utvidet(html: str, ordning_id: str) -> dict | None:
    """Parse utvidet data fra en ordningsside."""
    next_data = hent_next_data(html)
    if not next_data:
        return None

    page_props = next_data.get("props", {}).get("pageProps", {})
    if not page_props or page_props.get("__N_SSG") and "grant" not in page_props:
        # Fallback/ISR-side uten data (isFallback: true)
        return None

    # Tidsserie
    tidsserie = hent_tidsserie(page_props)
    tildelingsaar = hent_tildelingsaar(page_props)

    # Mottakere og oppsummering
    queries = (page_props.get("dehydratedState", {}).get("queries", []))
    mottakere, oppsummering = hent_mottakere_fra_queries(queries)

    # Publisert versjon (strukturert innhold)
    publisert = hent_publisert_versjon(next_data)
    ordningsinfo = {}
    if publisert:
        ordningsinfo = {
            "id_intern": publisert.get("id"),
            "tittel": publisert.get("title"),
            "beskrivelse": publisert.get("description"),
            "forvalter_navn": publisert.get("administrator", {}).get("name"),
            "forvalter_kortnavn": publisert.get("administrator", {}).get("shortName"),
            "forvalter_orgnr": publisert.get("administrator", {}).get("orgId"),
            "forvalter_lenke": publisert.get("administrator", {}).get("link"),
            "eier_navn": publisert.get("owner", {}).get("name"),
            "eier_orgnr": publisert.get("owner", {}).get("orgId"),
            "soknadslenke": publisert.get("administratorGrantLink"),
            "soknadsskjema_lenke": publisert.get("applicationSchemaLink"),
            "regelverk_lenke": publisert.get("rulesLink"),
            "frist": publisert.get("currentDeadline"),
            "frister": publisert.get("deadlines"),
            "fristtype": publisert.get("deadlineType"),
            "belop": publisert.get("amount"),
            "beloptype": publisert.get("amountType"),
            "tilskuddstyper": [t.get("value") for t in publisert.get("grantTypes", [])],
            "mottakerkategorier": [a.get("value") for a in publisert.get("relevantApplicants", [])],
            "krever_frivilligregisteret": publisert.get("requiresNonProfit"),
            "maal_og_formaal": draft_js_tekst(publisert.get("objectives")),
            "hvem_kan_soeke": draft_js_tekst(publisert.get("relevantApplicant")),
            "hva_kan_brukes_til": draft_js_tekst(publisert.get("usableGrantArea")),
            "andre_kriterier": draft_js_tekst(publisert.get("other")),
            "rapporteringskrav": draft_js_tekst(publisert.get("reporting")),
            "maloppnaaelse": draft_js_tekst(publisert.get("achievement")),
            "hvordan_soeke": draft_js_tekst(publisert.get("howToApply")),
            "finansiering_kapitler": publisert.get("financing", {}).get("chapters", []),
            "aar": publisert.get("year"),
            "oppdatert": publisert.get("updated"),
        }

    return {
        "ordning_id": ordning_id,
        "ordningsinfo": ordningsinfo,
        "tidsserie": tidsserie,
        "tildelingsaar": tildelingsaar,
        "oppsummering": oppsummering,
        "mottakere": mottakere,
        "publiserte_aar": (next_data.get("props", {}).get("pageProps", {})
                          .get("grant", {}).get("grantScheme", {})
                          .get("publishedYears", [])),
    }


# ---------------------------------------------------------------- eksport
def skriv_ordninger_json(resultater: list[dict], utmappe: Path):
    """Skriv komplett ordningsdata til JSON."""
    ordninger = []
    for r in resultater:
        info = r["ordningsinfo"].copy()
        info["ordning_id"] = r["ordning_id"]
        info["tidsserie"] = r["tidsserie"]
        info["tildelingsaar"] = r["tildelingsaar"]
        info["oppsummering"] = r["oppsummering"]
        info["publiserte_aar"] = r["publiserte_aar"]
        info["antall_mottakere_hentet"] = len(r["mottakere"])
        ordninger.append(info)

    fil = utmappe / "ordninger_utvidet.json"
    fil.write_text(json.dumps(ordninger, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  -> {fil} ({len(ordninger)} ordninger)")


def skriv_tildelinger_csv(resultater: list[dict], utmappe: Path):
    """Skriv alle enkelttildelinger til CSV."""
    alle_tildelinger = []
    for r in resultater:
        oid = r["ordning_id"]
        tittel = r["ordningsinfo"].get("tittel", "")
        for m in r["mottakere"]:
            rad = {"ordning_id": oid, "ordning_tittel": tittel}
            rad.update(m)
            alle_tildelinger.append(rad)

    if not alle_tildelinger:
        print("  Ingen tildelinger å skrive")
        return

    fil = utmappe / "tildelinger.csv"
    felter = list(alle_tildelinger[0].keys())
    with fil.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=felter, delimiter=";")
        w.writeheader()
        w.writerows(alle_tildelinger)
    print(f"  -> {fil} ({len(alle_tildelinger)} tildelinger)")


def skriv_tidsserier_csv(resultater: list[dict], utmappe: Path):
    """Skriv tidsserier (budsjett, tildelt, mottakere) til CSV."""
    rader = []
    for r in resultater:
        oid = r["ordning_id"]
        tittel = r["ordningsinfo"].get("tittel", "")
        ts = r["tidsserie"]

        # Bygg oppslagsdict per år
        budsjett = {p["x"]: p["y"] for p in ts.get("budsjett_serie", [])}
        tildelt = {p["x"]: p["y"] for p in ts.get("tildelt_serie", [])}
        mottakere = {p["x"]: p["y"] for p in ts.get("mottakere_serie", [])}
        alle_aar = sorted(set(list(budsjett.keys()) + list(tildelt.keys()) + list(mottakere.keys())))

        for aar in alle_aar:
            rader.append({
                "ordning_id": oid,
                "ordning_tittel": tittel,
                "aar": aar,
                "budsjett": budsjett.get(aar),
                "tildelt": tildelt.get(aar),
                "antall_mottakere": mottakere.get(aar),
            })

    if not rader:
        print("  Ingen tidsserier å skrive")
        return

    fil = utmappe / "tidsserier.csv"
    felter = ["ordning_id", "ordning_tittel", "aar", "budsjett", "tildelt", "antall_mottakere"]
    with fil.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=felter, delimiter=";")
        w.writeheader()
        w.writerows(rader)
    print(f"  -> {fil} ({len(rader)} rader)")


def skriv_ordninger_csv(resultater: list[dict], utmappe: Path):
    """Skriv flat ordningsoversikt til CSV med nøkkelfelter."""
    rader = []
    for r in resultater:
        info = r["ordningsinfo"]
        opps = r.get("oppsummering") or {}
        rader.append({
            "ordning_id": r["ordning_id"],
            "tittel": info.get("tittel"),
            "forvalter": info.get("forvalter_navn"),
            "forvalter_orgnr": info.get("forvalter_orgnr"),
            "departement": info.get("eier_navn"),
            "departement_orgnr": info.get("eier_orgnr"),
            "tilskuddstyper": "; ".join(info.get("tilskuddstyper") or []),
            "mottakerkategorier": "; ".join(info.get("mottakerkategorier") or []),
            "belop_budsjett": info.get("belop"),
            "frist": info.get("frist"),
            "fristtype": info.get("fristtype"),
            "krever_frivilligregisteret": info.get("krever_frivilligregisteret"),
            "antall_soekere": opps.get("totalApplicants"),
            "antall_mottakere": opps.get("totalRecipients"),
            "antall_soknader": opps.get("totalApplications"),
            "antall_innvilget": opps.get("grantedApplications"),
            "total_soekt": opps.get("totalApplicationAmount"),
            "total_tildelt": opps.get("totalGrantedAmount"),
            "innvilgelsesgrad": (
                round(opps["grantedApplications"] / opps["totalApplications"], 3)
                if opps.get("totalApplications") and opps.get("grantedApplications")
                else None
            ),
            "soknadslenke": info.get("soknadslenke"),
            "regelverk_lenke": info.get("regelverk_lenke"),
            "beskrivelse": info.get("beskrivelse"),
        })

    if not rader:
        return

    fil = utmappe / "ordninger_oversikt.csv"
    felter = list(rader[0].keys())
    with fil.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=felter, delimiter=";")
        w.writeheader()
        w.writerows(rader)
    print(f"  -> {fil} ({len(rader)} ordninger)")


# ---------------------------------------------------------------- hoved
def main() -> None:
    utmappe = Path("tilskudd_data")
    utmappe.mkdir(parents=True, exist_ok=True)

    urler = finn_urler_fra_sitemap()
    if not urler:
        urler = [f"{BASE}/ordning/DT-{n:04d}" for n in ID_ROM]

    resultater: list[dict] = []
    feilet = 0

    for i, url in enumerate(urler, 1):
        m = re.search(r"(DT-\d{4})", url)
        oid = m.group(1) if m else f"UKJ-{i:04d}"

        r = hent(url)
        time.sleep(PAUSE)
        if r is None:
            feilet += 1
            continue

        data = parse_ordning_utvidet(r.text, oid)
        if data is None:
            # Fallback-side uten data (ISR), prøv med år i URL
            # Next.js kan kreve /ordning/DT-XXXX/2026/tittel
            feilet += 1
            continue

        resultater.append(data)
        tittel = (data["ordningsinfo"].get("tittel") or "")[:50]
        n_mott = len(data["mottakere"])
        n_aar = len(data["tidsserie"].get("budsjett_serie", []))
        print(f"[{i:>4}] {oid}  {tittel:<50}  mottakere: {n_mott:>3}  år: {n_aar}")

    print(f"\nFerdig: {len(resultater)} ordninger hentet, {feilet} feilet/tomme")
    print("\nSkriver ut filer...")

    skriv_ordninger_json(resultater, utmappe)
    skriv_ordninger_csv(resultater, utmappe)
    skriv_tildelinger_csv(resultater, utmappe)
    skriv_tidsserier_csv(resultater, utmappe)

    # Kompakt oppsummering
    tot_tildelinger = sum(len(r["mottakere"]) for r in resultater)
    tot_aar_datapunkter = sum(
        len(r["tidsserie"].get("budsjett_serie", [])) for r in resultater
    )
    print(f"\nOppsummering:")
    print(f"  Ordninger:       {len(resultater)}")
    print(f"  Tildelinger:     {tot_tildelinger}")
    print(f"  Tidsseriepunkter: {tot_aar_datapunkter}")


if __name__ == "__main__":
    main()
