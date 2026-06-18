#!/usr/bin/env python3
"""
Tilskuddskompasset – datahøster for tilskudd.no (v2)
=====================================================
Nytt i v2:
  * Henter sjekkliste-seksjonene per ordning:
      - Mål og målgruppe for tilskuddsordningen
      - Hvem kan motta tilskudd
      - Hva kan tilskuddet brukes til
      - Andre tildelingskriterier
      - Rapporteringskrav
      - Hvordan søke
  * Parser __NEXT_DATA__-JSON når den finnes (mest robust mot
    sammenleggbare/klient-rendrede seksjoner), med HTML-fallback
  * Henter Ressurser-lenker (forvalters søknadsside, regelverk)
  * Lagrer rå-JSON per ordning i tilskudd_data/raw/ for inspeksjon

Avhengigheter:  pip install requests beautifulsoup4
Kjøring:        python hent_tilskudd_v2.py
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
    # Vær transparent: sett inn egen kontaktinfo her
    "User-Agent": "Tilskuddskompasset-datainnsamling (kontakt: kontakt@impromptu.no)"
}
PAUSE = 0.7
TIMEOUT = 20
ID_ROM = range(1, 1201)

MND = {
    "januar": 1, "februar": 2, "mars": 3, "april": 4, "mai": 5, "juni": 6,
    "juli": 7, "august": 8, "september": 9, "oktober": 10,
    "november": 11, "desember": 12,
}

SJEKKLISTE_SEKSJONER = [
    "Mål og målgruppe for tilskuddsordningen",
    "Hvem kan motta tilskudd",
    "Hva kan tilskuddet brukes til",
    "Andre tildelingskriterier",
    "Rapporteringskrav",
    "Hvordan søke",
]

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
    print("Ingen sitemap med ordninger – systematisk ID-gjennomgang")
    return []


# ---------------------------------------------------------------- parsing
def tekstlinjer(soup: BeautifulSoup) -> list[str]:
    tekst = soup.get_text("\n", strip=True)
    return [l.strip() for l in tekst.split("\n") if l.strip()]


def verdi_etter_label(linjer: list[str], label: str) -> str | None:
    for i, l in enumerate(linjer[:-1]):
        if l == label:
            return linjer[i + 1]
    return None


def parse_belop(s: str | None) -> int | None:
    if not s:
        return None
    m = re.search(r"([\d\s\u00a0]+)\s*kr", s)
    return int(re.sub(r"[\s\u00a0]", "", m.group(1))) if m else None


def parse_frist(s: str | None) -> dict:
    ut = {"frist_raa": s, "frist_dag": None, "frist_mnd": None, "frist_aar": None}
    if not s:
        return ut
    m = re.search(r"(\d{1,2})\.\s*([a-zæøå]+)(?:\s+(\d{4}))?", s.lower())
    if m and m.group(2) in MND:
        ut["frist_dag"] = int(m.group(1))
        ut["frist_mnd"] = MND[m.group(2)]
        ut["frist_aar"] = int(m.group(3)) if m.group(3) else None
    elif "løpende" in (s or "").lower():
        ut["frist_raa"] = "Løpende"
    return ut


# ---------- __NEXT_DATA__ : mest robuste kilde for seksjonsinnhold ----------
def hent_next_data(soup: BeautifulSoup) -> dict | None:
    """Next.js-apper legger all sidedata som JSON i <script id='__NEXT_DATA__'>."""
    tag = soup.find("script", id="__NEXT_DATA__")
    if not tag or not tag.string:
        return None
    try:
        return json.loads(tag.string)
    except json.JSONDecodeError:
        return None


def sok_i_json(node, soekeord: str, treff: list, dybde: int = 0):
    """Rekursivt søk: finn dict-verdier der en nøkkel/nabotekst matcher seksjonsnavn.
    Generisk fordi JSON-strukturen må inspiseres ved første kjøring –
    se rå-dumpene i tilskudd_data/raw/."""
    if dybde > 12:
        return
    if isinstance(node, dict):
        for k, v in node.items():
            if isinstance(v, str) and soekeord.lower() in v.lower() and len(v) < 120:
                # Mulig overskriftsfelt – ta med søsken-tekstfelt som kandidatinnhold
                tekster = [
                    sv for sv in node.values()
                    if isinstance(sv, str) and len(sv) > 60
                ]
                if tekster:
                    treff.extend(tekster)
            sok_i_json(v, soekeord, treff, dybde + 1)
    elif isinstance(node, list):
        for el in node:
            sok_i_json(el, soekeord, treff, dybde + 1)


def seksjon_fra_html(soup: BeautifulSoup, overskrift: str) -> str | None:
    """Fallback: finn overskriftselement og samle tekst fra søsken til neste
    overskrift. Fanger også sammenlagt accordion-innhold som ligger i DOM."""
    for el in soup.find_all(["h2", "h3", "button", "summary"]):
        if el.get_text(strip=True) == overskrift:
            deler = []
            for sib in el.find_all_next():
                if sib.name in ("h2", "h3") or (
                    sib.name in ("button", "summary")
                    and sib.get_text(strip=True) in SJEKKLISTE_SEKSJONER
                ):
                    break
                if sib.name in ("p", "li"):
                    t = sib.get_text(" ", strip=True)
                    if t:
                        deler.append(t)
            if deler:
                return "\n".join(dict.fromkeys(deler))  # dedupliser, behold rekkefølge
    return None


def hent_seksjoner(soup: BeautifulSoup, next_data: dict | None) -> dict:
    ut = {}
    for seksjon in SJEKKLISTE_SEKSJONER:
        innhold = None
        if next_data:
            treff: list = []
            sok_i_json(next_data, seksjon, treff)
            if treff:
                innhold = max(treff, key=len)  # lengste kandidat = mest sannsynlig brødtekst
        if not innhold:
            innhold = seksjon_fra_html(soup, seksjon)
        noekkel = (
            seksjon.lower()
            .replace(" ", "_")
            .replace("å", "a").replace("ø", "o").replace("æ", "ae")
        )
        ut[noekkel] = innhold
    return ut


def hent_ressurser(soup: BeautifulSoup) -> list[dict]:
    """Lenker i Ressurser-seksjonen (søknadsside, regelverk hos forvalter)."""
    ress = []
    h = next(
        (el for el in soup.find_all(["h2", "h3"])
         if el.get_text(strip=True) == "Ressurser"), None
    )
    if not h:
        return ress
    for sib in h.find_all_next():
        if sib.name in ("h2", "h3"):
            break
        if sib.name == "a" and sib.get("href", "").startswith("http"):
            ress.append({"tekst": sib.get_text(strip=True), "url": sib["href"]})
    # dedupliser på url
    sett, ut = set(), []
    for r in ress:
        if r["url"] not in sett:
            sett.add(r["url"])
            ut.append(r)
    return ut


def parse_ordning(html: str, ordning_id: str, url: str, raw_dir: Path) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    linjer = tekstlinjer(soup)
    next_data = hent_next_data(soup)

    if next_data:  # rådump for inspeksjon av JSON-struktur ved første kjøring
        (raw_dir / f"{ordning_id}.json").write_text(
            json.dumps(next_data, ensure_ascii=False, indent=1), encoding="utf-8"
        )

    navn = None
    og = soup.find("meta", property="og:title")
    if og and og.get("content"):
        navn = og["content"].strip()
    if not navn and soup.h1:
        navn = soup.h1.get_text(strip=True)

    formaal = None
    md = soup.find("meta", attrs={"name": "description"})
    if md and md.get("content"):
        formaal = md["content"].strip()

    d = {
        "id": ordning_id,
        "url": url,
        "navn": navn,
        "formaal": formaal,
        "forvalter": verdi_etter_label(linjer, "Tilskuddsforvalter"),
        "type_tilskudd": verdi_etter_label(linjer, "Type tilskudd"),
        "mottakerkategori": verdi_etter_label(linjer, "Mottakerkategori"),
        "finansiering": verdi_etter_label(linjer, "Finansiering"),
        "departement": verdi_etter_label(linjer, "Ansvarlig departement"),
        "tilgjengelige_midler": verdi_etter_label(linjer, "Tilgjengelige midler"),
    }
    d.update(parse_frist(verdi_etter_label(linjer, "Søknadsfrist")))
    d.update(hent_seksjoner(soup, next_data))          # <- sjekkliste-feltene
    d["ressurser"] = hent_ressurser(soup)

    # --- Tildelingsstatistikk ---
    d.update({"stat_aar": None, "soekere": None, "tildelinger": None,
              "tildelt_kr": None, "omsoekt_kr": None, "innvilgelsesgrad": None})
    try:
        hist_i = linjer.index("Historikk")
        blokk = linjer[hist_i: hist_i + 40]
        for j, l in enumerate(blokk):
            if re.fullmatch(r"20\d{2}", l) and d["stat_aar"] is None:
                d["stat_aar"] = int(l)
            if l == "Søkere" and j + 1 < len(blokk) and blokk[j + 1].isdigit():
                d["soekere"] = int(blokk[j + 1])
            if l == "Tildelinger" and j + 1 < len(blokk) and blokk[j + 1].isdigit():
                d["tildelinger"] = int(blokk[j + 1])
            if l == "Tildelt" and j + 1 < len(blokk):
                d["tildelt_kr"] = parse_belop(blokk[j + 1])
            if l == "Omsøkt" and j + 1 < len(blokk):
                d["omsoekt_kr"] = parse_belop(blokk[j + 1])
        if d["soekere"] and d["tildelinger"]:
            d["innvilgelsesgrad"] = round(d["tildelinger"] / d["soekere"], 3)
    except ValueError:
        pass

    return d


# ---------------------------------------------------------------- hoved
def main() -> None:
    utmappe = Path("tilskudd_data")
    raw_dir = utmappe / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    urler = finn_urler_fra_sitemap()
    if not urler:
        urler = [f"{BASE}/ordning/DT-{n:04d}" for n in ID_ROM]

    resultater: list[dict] = []
    for i, url in enumerate(urler, 1):
        m = re.search(r"(DT-\d{4})", url)
        oid = m.group(1) if m else url
        r = hent(url)
        time.sleep(PAUSE)
        if r is None:
            continue
        data = parse_ordning(r.text, oid, r.url, raw_dir)
        if not data["navn"]:
            continue
        resultater.append(data)
        grad = f"{data['innvilgelsesgrad']:.0%}" if data["innvilgelsesgrad"] else "–"
        sjekk = sum(1 for s in SJEKKLISTE_SEKSJONER
                    if data.get(s.lower().replace(" ", "_")
                                .replace("å", "a").replace("ø", "o").replace("æ", "ae")))
        print(f"[{i:>4}] {oid}  {(data['navn'] or '')[:48]:<48} "
              f"innvilgelse: {grad:>4}  sjekkliste: {sjekk}/6 felt")

    print(f"\nFerdig: {len(resultater)} ordninger høstet")

    (utmappe / "ordninger.json").write_text(
        json.dumps(resultater, ensure_ascii=False, indent=2), encoding="utf-8")

    if resultater:
        felter = list(resultater[0].keys())
        with (utmappe / "ordninger.csv").open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=felter, delimiter=";")
            w.writeheader()
            for rad in resultater:
                rad = dict(rad)
                rad["ressurser"] = json.dumps(rad["ressurser"], ensure_ascii=False)
                w.writerow(rad)

    js_rader = []
    for d in resultater:
        typer = []
        if d["type_tilskudd"]:
            if "Drift" in d["type_tilskudd"]:
                typer.append("Driftsmidler")
            if "Prosjekt" in d["type_tilskudd"]:
                typer.append("Prosjektmidler")
        js_rader.append({
            "id": d["id"], "navn": d["navn"], "forvalter": d["forvalter"] or "",
            "type": typer or ["Driftsmidler"],
            "sektor": d["departement"] or "Ukjent",   # kurater manuelt i CSV
            "dag": d["frist_dag"], "mnd": d["frist_mnd"],
            "innvilgelsesgrad": d["innvilgelsesgrad"],
            "midler": d["tildelt_kr"],
            "hvem": d.get("hvem_kan_motta_tilskudd"),
            "hva": d.get("hva_kan_tilskuddet_brukes_til"),
            "rapportering": d.get("rapporteringskrav"),
        })
    (utmappe / "ordninger_data.js").write_text(
        "const ORDNINGER = " + json.dumps(js_rader, ensure_ascii=False, indent=1) + ";\n",
        encoding="utf-8")

    print("Skrevet: ordninger.json, ordninger.csv, ordninger_data.js + raw/")


if __name__ == "__main__":
    main()
