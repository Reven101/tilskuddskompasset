#!/usr/bin/env python3
"""
NFI tildelinger – henter alle tildelinger fra nfi.no/tildelinger (2020–i dag)
=============================================================================
Teknisk:
  - nfi.no kjører Craft CMS + Sprig (HTMX).  Data er server-rendret i HTML,
    men lastes via sprig-core/components/render med HMAC-signert config.
  - Strategien: hent forsiden én gang for å få CraftSessionId + sprig:config,
    kall deretter renderpunktet per år og side.
  - Filtrerer på year=YYYY og paginerer til neste-knapp er disabled.

Felter per tildeling:
  tittel, dato, soeker, tildelt_kr, ordning, omraade, format,
  regissør, manus, produsent, [pluss eventuelle ukjente felt]

Avhengigheter: kun standardbibliotek (urllib, html.parser, re, json, csv)
Kjøring:       python hent_nfi_tildelinger.py
"""

import csv
import json
import re
import sys
import time
import urllib.parse
import urllib.request
import http.cookiejar
from html.parser import HTMLParser
from pathlib import Path

# ──────────────────────────────────── konfig ────────────────────────────────

BASE_URL   = "https://www.nfi.no"
LISTING    = f"{BASE_URL}/tildelinger"
SPRIG_EP   = f"{BASE_URL}/actions/sprig-core/components/render"
YEARS      = list(range(2020, 2027))   # 2020–2026
PAGE_LIMIT = 20                        # NFI sitt fast valg – endre ikke her
PAUSE      = 0.6                       # sekunder mellom forespørsler
TIMEOUT    = 20

HEADERS = {
    "User-Agent":       "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/125.0.0.0 Safari/537.36",
    "Accept":           "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language":  "no-NO,no;q=0.9,en;q=0.5",
}

SPRIG_HEADERS = {
    "HX-Request":     "true",
    "HX-Current-URL": LISTING,
    "HX-Target":      "this",
    "User-Agent":     HEADERS["User-Agent"],
    "Accept":         "text/html, */*",
    "Referer":        LISTING,
}

# ──────────────────────────────────── nettverk ──────────────────────────────

def lag_session() -> urllib.request.OpenerDirector:
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    opener.addheaders = list(HEADERS.items())
    return opener


def hent(opener: urllib.request.OpenerDirector, url: str,
         extra_headers: dict | None = None) -> str | None:
    req = urllib.request.Request(url)
    for k, v in (extra_headers or {}).items():
        req.add_header(k, v)
    for forsok in range(3):
        try:
            resp = opener.open(req, timeout=TIMEOUT)
            return resp.read().decode("utf-8")
        except Exception as e:
            vent = 2 ** forsok
            print(f"  ! {e} – venter {vent}s", file=sys.stderr)
            time.sleep(vent)
    return None


# ──────────────────────────────────── sprig-config ──────────────────────────

def hent_sprig_config(opener: urllib.request.OpenerDirector) -> str:
    html = hent(opener, LISTING)
    if not html:
        raise RuntimeError("Klarte ikke å laste forsiden")
    m = re.search(r'sprig:config&quot;:&quot;(.*?)&quot;\}', html)
    if not m:
        raise RuntimeError("sprig:config ikke funnet i HTML")
    # HTML-attributten bruker " som JSON-escape for "
    return json.loads('"' + m.group(1) + '"')


def sprig_url(config_val: str, year: str, page: int) -> str:
    params = urllib.parse.urlencode({
        "sprig:config": config_val,
        "year":         year,
        "query":        "",
        "page":         str(page),
    })
    return f"{SPRIG_EP}?{params}"


# ──────────────────────────────────── HTML-parsing ──────────────────────────

def _tekst(fragment: str) -> str:
    """Rens HTML-tags og whitespace fra et HTML-fragment."""
    ren = re.sub(r"<[^>]+>", " ", fragment)
    ren = re.sub(r"\s+", " ", ren).strip()
    return ren


def _parse_belop(s: str) -> int | None:
    """'✕1\xa0000\xa0000,-' eller '1 000 000,-' → 1000000"""
    m = re.search(r"([\d\s\xa0]+),-", s)
    if not m:
        return None
    return int(re.sub(r"[\s\xa0]", "", m.group(1)))


def parse_rad(row_html: str) -> dict | None:
    """
    Parser én <tr>...</tr>.
    Strategien: finn alle label:verdi-par ved å lete etter
      <span class="...font-medium font-body...">LABEL:</span>
      <span ...>VERDI</span>
    Dette er mønsteret for ALLE felter, både mobil og desktop.
    """
    # Samle alle label+verdi-span-par
    par = re.findall(
        r'<span[^>]*font-medium font-body[^>]*>\s*([^<]+?)\s*</span>'
        r'\s*<span[^>]*>\s*(.*?)\s*</span>',
        row_html, re.DOTALL
    )

    if not par:
        return None

    felt = {}
    for label, verdi_html in par:
        label = label.strip().rstrip(":").strip().lower()
        verdi = _tekst(verdi_html)
        if verdi:
            felt[label] = verdi

    if not felt:
        return None

    # Normaliser feltnavnene
    def f(key: str) -> str:
        return felt.get(key, "")

    tittel = f("prosjekttittel")
    if not tittel:
        # Mobil-tittelen sitter i en <div> uten label
        m = re.search(
            r'text-xl font-medium font-body[^>]*>.*?'
            r'<div[^>]*overflow[^>]*>([^<]+)<',
            row_html, re.DOTALL
        )
        tittel = m.group(1).strip() if m else ""

    if not tittel:
        return None

    tildelt_raw = f("tildelt")
    tildelt_kr  = _parse_belop(tildelt_raw) if tildelt_raw else None

    return {
        "tittel":       tittel,
        "dato":         f("dato for vedtak"),
        "soeker":       f("søker"),
        "tildelt_raa":  tildelt_raw,
        "tildelt_kr":   tildelt_kr,
        "ordning":      f("tilskuddsordning") or f("ordning"),
        "omraade":      f("tilskuddsområde"),
        "produsent":    f("produsent"),
        "regissør":     f("regissør"),
        "manus":        f("manus"),
        "format":       f("format"),
    }


def parse_side(html: str) -> list[dict]:
    tbody = re.search(r"<tbody[^>]*>(.*?)</tbody>", html, re.DOTALL)
    if not tbody:
        return []
    rader = []
    for row_html in re.findall(r"<tr[^>]*>(.*?)</tr>", tbody.group(1), re.DOTALL):
        rad = parse_rad(row_html)
        if rad:
            rader.append(rad)
    return rader


def er_siste_side(html: str) -> bool:
    nav = re.search(r'<nav[^>]*aria-label[^>]*Pagination[^>]*>(.*?)</nav>',
                    html, re.DOTALL)
    if not nav:
        return True
    next_btn = re.search(r'aria-label="Next page"[^>]+>', nav.group(1))
    if not next_btn:
        return True
    return "disabled" in next_btn.group(0)


# ──────────────────────────────────── hoved ─────────────────────────────────

def main() -> None:
    utmappe = Path("tilskudd_data")
    utmappe.mkdir(exist_ok=True)

    opener = lag_session()

    print("Henter sprig:config fra forsiden …")
    config_val = hent_sprig_config(opener)
    print("  OK\n")

    alle: list[dict] = []

    for year in YEARS:
        print(f"=== {year} ===")
        side = 1
        while True:
            url  = sprig_url(config_val, str(year), side)
            html = hent(opener, url, SPRIG_HEADERS)
            time.sleep(PAUSE)

            if html is None:
                print(f"  ! Side {side} feilet, stopper for {year}")
                break

            rader = parse_side(html)
            if not rader:
                print(f"  ! Ingen rader på side {side}, avslutter {year}")
                break

            for rad in rader:
                rad["aar"] = year
            alle.extend(rader)

            siste = er_siste_side(html)
            print(f"  Side {side:3d}: {len(rader):3d} rader  (totalt: {len(alle)})")

            if siste:
                break
            side += 1

        print()

    # Deduplication – noen tildelinger dukker opp på to påfølgende sider
    sett: set[tuple] = set()
    unik: list[dict] = []
    for r in alle:
        nøkkel = (r["tittel"], r["dato"], r.get("soeker", ""), r.get("tildelt_raa", ""))
        if nøkkel not in sett:
            sett.add(nøkkel)
            unik.append(r)
    if len(unik) < len(alle):
        print(f"Duplikater fjernet: {len(alle) - len(unik)}")
    alle = unik

    print(f"Ferdig: {len(alle)} tildelinger hentet\n")

    # ── Lagre JSON ──
    json_fil = utmappe / "nfi_tildelinger.json"
    json_fil.write_text(
        json.dumps(alle, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print(f"Skrevet: {json_fil}")

    # ── Lagre CSV ──
    if alle:
        felter = list(alle[0].keys())
        csv_fil = utmappe / "nfi_tildelinger.csv"
        with csv_fil.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=felter, delimiter=";",
                               extrasaction="ignore")
            w.writeheader()
            w.writerows(alle)
        print(f"Skrevet: {csv_fil}")

    # ── Statistikk ──
    print("\n=== Statistikk per år ===")
    for y in YEARS:
        aar_rader = [r for r in alle if r["aar"] == y]
        tildelt = [r["tildelt_kr"] for r in aar_rader if r["tildelt_kr"]]
        total   = sum(tildelt)
        print(f"  {y}: {len(aar_rader):5d} tildelinger, "
              f"total tildelt: {total:>15,.0f} kr")


if __name__ == "__main__":
    main()
