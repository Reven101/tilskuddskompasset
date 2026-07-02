#!/usr/bin/env python3
"""
Henter beskrivende innhold for Kulturråd/Fond for lyd og bilde-ordninger fra
kulturdirektoratet.no/tilskuddsordninger/<slug> - samme type innhold som
hent_utvidet_data.py henter fra tilskudd.no (mål/formål, hvem kan søke, hva
kan brukes til, vurderingskriterier, rapporteringskrav, regelverk).

Siden er vanlig server-rendret HTML (ingen JSON-datablokk som på tilskudd.no),
så innholdet hentes ved å lese tekst under faste, gjenkjennbare overskrifter.

Matcher sidene mot våre ordningskoder (NKF-xxx/FLB-xxx/KUL-xxx) via
sidetittelen, som er identisk med tilskuddsordning-navnet vi allerede har i
nkf_flb_innvilgelsesgrad_per_ordning.csv.

Kjøring: python hent_kulturdirektoratet_innhold.py
"""
import json
import re
import time
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup

BASE = "https://www.kulturdirektoratet.no"
LISTING = f"{BASE}/tilskuddsordninger"
GRAD_FIL = "tilskudd_data/nkf_flb_innvilgelsesgrad_per_ordning.csv"
OUT = "tilskudd_data/kulturdirektoratet_innhold.json"
PAUSE = 0.5
HEADERS = {"User-Agent": "Tilskuddskompasset-databerikelse (kontakt: kontakt@impromptu.no)"}

session = requests.Session()
session.headers.update(HEADERS)


def hent_slugs() -> list[str]:
    r = session.get(LISTING, timeout=20)
    r.raise_for_status()
    slugs = sorted(set(re.findall(r'/tilskuddsordninger/([a-z0-9-]+)"', r.text)))
    return slugs


def tekst_mellom(start_tag, stop_navn=("h2", "h3")) -> str:
    """Samler all <p>/<li>-tekst fra rett etter start_tag til neste overskrift
    på samme eller høyere nivå."""
    deler = []
    for sib in start_tag.find_next_siblings():
        if sib.name in stop_navn:
            break
        if sib.name in ("p", "ul", "ol"):
            txt = sib.get_text(" ", strip=True)
            if txt:
                deler.append(txt)
    return "\n".join(deler)


def finn_seksjon(soup, *overskrift_fragmenter) -> str:
    for tag in soup.find_all(["h2", "h3", "h4"]):
        tekst = tag.get_text(strip=True).lower()
        if not any(frag.lower() in tekst for frag in overskrift_fragmenter):
            continue
        # Toppnivå-seksjonene er bygget som <details><summary><h3>..</h3></summary><div>innhold</div></details> -
        # innholdet er IKKE en sibling av h-taggen, men av <summary> (h-taggens forelder).
        if tag.parent and tag.parent.name == "summary":
            panel = tag.parent.find_next_sibling()
            if panel:
                deler = [p.get_text(" ", strip=True) for p in panel.find_all(["p", "li"])]
                return "\n".join(d for d in deler if d)
        return tekst_mellom(tag, stop_navn=("h2", "h3", "h4"))
    return ""


def hent_ordning(slug: str) -> dict:
    r = session.get(f"{BASE}/tilskuddsordninger/{slug}", timeout=20)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    h1 = soup.find("h1")
    tittel = h1.get_text(strip=True) if h1 else ""

    formaal = finn_seksjon(soup, "bidra til (formål)", "bidra til")
    hvem = finn_seksjon(soup, "hvem kan søke")
    hva = finn_seksjon(soup, "hva kan få tilskudd")
    kriterier = finn_seksjon(soup, "vurderingskriterier", "blir søknadene vurdert")
    rapportering = finn_seksjon(soup, "rapport og regnskap")
    hvordan = finn_seksjon(soup, "må søknaden inneholde")

    regelverk = ""
    for tag in soup.find_all(["h3"]):
        if "rettslig grunnlag" in tag.get_text(strip=True).lower():
            for sib in tag.find_next_siblings():
                if sib.name in ("h2", "h3"):
                    break
                a = sib.find("a", href=True) if sib.name in ("ul", "ol", "p") else None
                if a:
                    regelverk = a["href"]
                    break
            break

    # Søknadsfrist: maskinlesbar <time datetime="2026-08-18T13:00:00+02:00">
    # under "Søknadsfrist"-overskriften. Gjelder neste/kommende runde uansett
    # om søknadsskjemaet er åpent eller ikke åpnet ennå.
    frister = []
    h2_frist = soup.find("h2", string=lambda s: s and "søknadsfrist" in s.lower())
    if h2_frist:
        ul = h2_frist.find_next_sibling("ul")
        if ul:
            frister = [t["datetime"][:10] for t in ul.find_all("time", datetime=True)]

    forvalter = ""
    p_forvalter = soup.find("p", string=lambda s: s and "forvaltes av" in s.lower())
    if p_forvalter is None:
        for p in soup.find_all("p"):
            if "forvaltes av" in p.get_text(" ", strip=True).lower():
                p_forvalter = p
                break
    if p_forvalter:
        tekst = p_forvalter.get_text(" ", strip=True)
        forvalter = tekst.split("forvaltes av", 1)[-1].strip().rstrip(".").strip()

    return {
        "slug": slug,
        "tittel": tittel,
        "url": f"{BASE}/tilskuddsordninger/{slug}",
        "formaal": formaal,
        "hvem": hvem,
        "hva": hva,
        "kriterier": kriterier,
        "rapportering": rapportering,
        "hvordan": hvordan,
        "regelverk": regelverk,
        "frister": frister,
        "forvalter": forvalter,
    }


def main():
    slugs = hent_slugs()
    print(f"Fant {len(slugs)} ordningssider")

    resultat = []
    for i, slug in enumerate(slugs, 1):
        try:
            data = hent_ordning(slug)
            resultat.append(data)
            print(f"  [{i}/{len(slugs)}] {slug} -> '{data['tittel'][:60]}'")
        except requests.RequestException as e:
            print(f"  ! Feil for {slug}: {e}")
        time.sleep(PAUSE)

    Path(OUT).write_text(json.dumps(resultat, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSkrevet {len(resultat)} ordninger til {OUT}")

    # Sjekk treffrate mot våre ordningsnavn
    grad = pd.read_csv(GRAD_FIL, sep=";", encoding="utf-8-sig")
    vare_navn = {n.strip().lower() for n in grad["tilskuddsordning"]}
    skrapte_navn = {d["tittel"].strip().lower() for d in resultat}
    print(f"\nTreff (navn finnes i begge): {len(vare_navn & skrapte_navn)} av {len(vare_navn)} av våre ordninger")
    print(f"Skrapte sider uten match i vårt datasett: {len(skrapte_navn - vare_navn)}")


if __name__ == "__main__":
    main()
