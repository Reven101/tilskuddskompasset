#!/usr/bin/env python3
"""
NFI tilskuddsordninger – henter alle søkbare ordninger fra nfi.no/tilskudd
===========================================================================
Felter per ordning:
  navn, url, kategori, ingress, hvem_kan_soke, hva_kan_sokes, vilkaar,
  prioritering, saksbehandlingstid, lovdata_url, soknadsportal_url,
  soknadsfrister (liste over datoer fra nfi.no/soeknadsfrister)

Avhengigheter: kun standardbibliotek
Kjøring:       python hent_nfi_ordninger.py
"""

import csv
import json
import re
import sys
import time
import urllib.parse
import urllib.request
import http.cookiejar
from pathlib import Path

# ──────────────────────────────────────── konfig ────────────────────────────

BASE_URL    = "https://www.nfi.no"
FRISTER_URL = f"{BASE_URL}/soeknadsfrister"
SPRIG_EP    = f"{BASE_URL}/actions/sprig-core/components/render"
PAUSE       = 0.6
TIMEOUT     = 20

CATEGORY_URLS = [
    f"{BASE_URL}/tilskudd/utvikling",
    f"{BASE_URL}/tilskudd/produksjon",
    f"{BASE_URL}/tilskudd/lansering-profilering-og-distribusjon",
    f"{BASE_URL}/tilskudd/kompetanseheving-2",
    f"{BASE_URL}/tilskudd/formidling-2",
]

# Hardkodet insentivordning (egen kategori uten felles kategori-side)
EKSTRA_ORDNINGER = [
    f"{BASE_URL}/tilskudd/insentiv/insentivordningen-2023",
]

# Ekskluder informasjonssider fra category-crawl
EKSKLUDER = {"slik-saksbehandler", "kvalitetskriteriene", "kulturtesten",
             "egenmelding", "rapportering"}

HEADERS = {
    "User-Agent":       "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/125.0.0.0 Safari/537.36",
    "Accept":           "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language":  "no-NO,no;q=0.9,en;q=0.5",
}

SPRIG_HEADERS = {
    "HX-Request":     "true",
    "HX-Current-URL": FRISTER_URL,
    "HX-Target":      "this",
    "User-Agent":     HEADERS["User-Agent"],
    "Accept":         "text/html, */*",
    "Referer":        FRISTER_URL,
}

# ──────────────────────────────────────── nettverk ──────────────────────────

def lag_session() -> urllib.request.OpenerDirector:
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    opener.addheaders = list(HEADERS.items())
    return opener


def _encode_url(url: str) -> str:
    """Percent-encode non-ASCII characters in URL path (e.g. Norwegian slugs)."""
    parsed = urllib.parse.urlparse(url)
    encoded_path = urllib.parse.quote(parsed.path, safe="/")
    return parsed._replace(path=encoded_path).geturl()


def hent(opener: urllib.request.OpenerDirector, url: str,
         extra_headers: dict | None = None) -> str | None:
    req = urllib.request.Request(_encode_url(url))
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


# ──────────────────────────────────────── URL-discovery ─────────────────────

def hent_alle_ordning_urls(opener: urllib.request.OpenerDirector) -> list[str]:
    """Crawl alle kategorisider og returner deduplisert liste over ordning-URLer."""
    funnet: list[str] = []
    sett: set[str] = set()

    for cat_url in CATEGORY_URLS:
        html = hent(opener, cat_url)
        time.sleep(PAUSE)
        if not html:
            print(f"  ! Klarte ikke å laste {cat_url}", file=sys.stderr)
            continue

        # Matcher enhver /tilskudd/{kategori}/{slug} – to nivåer under /tilskudd
        lenker = re.findall(
            r'href="(https://www\.nfi\.no/tilskudd/[^"/]+/[^"/]+)"',
            html
        )
        for url in lenker:
            slug = url.split("/")[-1]
            if slug not in EKSKLUDER and url not in sett:
                sett.add(url)
                funnet.append(url)
        print(f"  {cat_url.split('/')[-1]}: {len([u for u in funnet if u not in sett - {u}])} ordninger funnet")

    for url in EKSTRA_ORDNINGER:
        if url not in sett:
            sett.add(url)
            funnet.append(url)

    return funnet


# ──────────────────────────────────────── HTML-parsing ──────────────────────

def _tekst(html_fragment: str) -> str:
    """Rens HTML-tags, HTML-entiteter og whitespace fra et HTML-fragment."""
    import html as _html
    ren = re.sub(r"<script[^>]*>.*?</script>", " ", html_fragment, flags=re.DOTALL)
    ren = re.sub(r"<[^>]+>", " ", ren)
    ren = _html.unescape(ren)
    ren = re.sub(r"\s+", " ", ren).strip()
    return ren


def _parse_seksjon(main_html: str, heading_partial: str) -> str:
    """Returner renset tekst for en seksjon med gitt H2-overskrift (partiell match)."""
    m = re.search(
        r"<h2[^>]*>[^<]*" + re.escape(heading_partial) + r"[^<]*</h2>(.*?)(?=<h2|$)",
        main_html, re.DOTALL | re.IGNORECASE
    )
    if not m:
        return ""
    return _tekst(m.group(1))


def _parse_accordion(main_html: str, label_partial: str) -> str:
    """Returner innhold fra accordion-item der knapp-teksten matcher label_partial."""
    items = re.findall(
        r'data-accordion-item[^>]*>(.*?)(?=data-accordion-item|</section>|$)',
        main_html, re.DOTALL
    )
    for item in items:
        btn = re.search(r'data-accordion-btn[^>]*>(.*?)</button>', item, re.DOTALL)
        if not btn:
            continue
        btn_tekst = re.sub(r"<[^>]+>", " ", btn.group(1))
        btn_tekst = re.sub(r"\s+", " ", btn_tekst).strip()
        if label_partial.lower() in btn_tekst.lower():
            content_m = re.search(
                r'data-accordion-content[^>]*>(.*?)(?=</div>\s*</div>)',
                item, re.DOTALL
            )
            if content_m:
                return _tekst(content_m.group(1))
    return ""


def parse_ordning_side(html: str, url: str) -> dict:
    """Trekk ut alle felter fra en ordning-side."""

    # Kategori fra URL: /tilskudd/{kategori}/{slug}
    parts = url.rstrip("/").split("/")
    kategori = parts[-2] if len(parts) >= 2 else ""

    # H1 → navn
    h1 = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.DOTALL)
    navn = _tekst(h1.group(1)) if h1 else ""

    # Finn main-innhold
    main_m = re.search(r"<main[^>]*>(.*?)</main>", html, re.DOTALL)
    main_html = main_m.group(1) if main_m else html

    # Ingress: første <p> med ren tekst (ingen inner HTML) etter H1
    h1_m = re.search(r"<h1[^>]*>.*?</h1>", main_html, re.DOTALL)
    search_from = main_html[h1_m.end():] if h1_m else main_html
    ingress = ""
    for p_match in re.finditer(r"<p[^>]*>([^<]{50,})</p>", search_from):
        ingress = p_match.group(1).strip()
        break
    # Fallback: første <p> med tekst (kan inneholde inner HTML)
    if not ingress:
        for p_match in re.finditer(r"<p[^>]*>(.*?)</p>", search_from, re.DOTALL):
            tekst = _tekst(p_match.group(1))
            if len(tekst) > 50:
                ingress = tekst
                break

    # Seksjoner (H2-basert)
    hvem_kan_soke  = _parse_seksjon(main_html, "Hvem kan s")
    hva_kan_sokes  = _parse_seksjon(main_html, "Dette kan du")
    vilkaar        = _parse_seksjon(main_html, "Vilk")
    prioritering   = _parse_seksjon(main_html, "Prioritering")

    # Saksbehandlingstid: prøv H2-basert, fall tilbake på accordion
    saksbeh_raw = _parse_seksjon(main_html, "Saksbehandling")
    if not saksbeh_raw:
        saksbeh_raw = _parse_accordion(main_html, "Saksbehandling")
    saksbeh = saksbeh_raw[:300] if saksbeh_raw else ""

    # Lovdata-lenke
    lovdata_m = re.search(r'href="(https://lovdata\.no/[^"]+)"', html)
    lovdata_url = lovdata_m.group(1) if lovdata_m else ""

    # Søknadsportal
    portal_m = re.search(r'href="(https://tilskudd\.nfi\.no[^"]*)"', html)
    soknadsportal_url = portal_m.group(1) if portal_m else ""

    return {
        "navn":               navn,
        "url":                url,
        "kategori":           kategori,
        "ingress":            ingress,
        "hvem_kan_soke":      hvem_kan_soke,
        "hva_kan_sokes":      hva_kan_sokes,
        "vilkaar":            vilkaar,
        "prioritering":       prioritering,
        "saksbehandlingstid": saksbeh,
        "lovdata_url":        lovdata_url,
        "soknadsportal_url":  soknadsportal_url,
        "soknadsfrister":     [],   # fylles ut i steg 3
    }


# ──────────────────────────────────────── søknadsfrister ────────────────────

def er_siste_side(html: str) -> bool:
    nav = re.search(r'<nav[^>]*aria-label[^>]*Pagination[^>]*>(.*?)</nav>',
                    html, re.DOTALL)
    if not nav:
        return True
    next_btn = re.search(r'aria-label="Next page"[^>]+>', nav.group(1))
    if not next_btn:
        return True
    return "disabled" in next_btn.group(0)


def hent_sprig_config(opener: urllib.request.OpenerDirector, side_url: str) -> str:
    html = hent(opener, side_url)
    if not html:
        raise RuntimeError(f"Klarte ikke å laste {side_url}")
    m = re.search(r'sprig:config&quot;:&quot;(.*?)&quot;\}', html)
    if not m:
        raise RuntimeError("sprig:config ikke funnet")
    return json.loads('"' + m.group(1) + '"')


def hent_frister(opener: urllib.request.OpenerDirector) -> dict[str, list[str]]:
    """
    Henter søknadsfrister fra nfi.no/soeknadsfrister via Sprig-paginering.
    Returnerer dict: ordning_url → [dato_frist, ...]
    """
    print("Henter søknadsfrister …")
    try:
        config_val = hent_sprig_config(opener, FRISTER_URL)
    except RuntimeError as e:
        print(f"  ! {e}", file=sys.stderr)
        return {}

    frister: dict[str, list[str]] = {}
    side = 1

    while True:
        params = urllib.parse.urlencode({
            "sprig:config": config_val,
            "page":         str(side),
        })
        url  = f"{SPRIG_EP}?{params}"
        html = hent(opener, url, SPRIG_HEADERS)
        time.sleep(PAUSE)

        if not html:
            break

        # Sprig-responsen er strukturert som <article> per dato med ordning-lenker
        artikler = re.findall(r'<article[^>]*>(.*?)</article>', html, re.DOTALL)
        for artikkel in artikler:
            dato_m = re.search(r'<h2[^>]*>(\d{1,2}\.\s+\w+\s+\d{4})</h2>', artikkel)
            if not dato_m:
                continue
            dato = re.sub(r"\s+", " ", dato_m.group(1)).strip()
            for ord_url in re.findall(
                r'href="(https://www\.nfi\.no/tilskudd/[^"]+)"', artikkel
            ):
                frister.setdefault(ord_url, [])
                if dato not in frister[ord_url]:
                    frister[ord_url].append(dato)

        antall = sum(len(v) for v in frister.values())
        print(f"  Side {side}: totalt {antall} frister")

        if er_siste_side(html):
            break
        side += 1

    return frister


# ──────────────────────────────────────── hoved ─────────────────────────────

def main() -> None:
    utmappe = Path("tilskudd_data")
    utmappe.mkdir(exist_ok=True)

    opener = lag_session()

    # ── Steg 1: Finn alle ordning-URLer ──────────────────────────────────────
    print("=== Steg 1: Crawl kategorisider ===")
    ordning_urls = hent_alle_ordning_urls(opener)
    print(f"Totalt {len(ordning_urls)} ordninger funnet\n")

    # ── Steg 2: Hent og parse hver ordning-side ───────────────────────────────
    print("=== Steg 2: Hent ordning-sider ===")
    ordninger: list[dict] = []

    for i, url in enumerate(ordning_urls, 1):
        slug = url.split("/")[-1]
        html = hent(opener, url)
        time.sleep(PAUSE)

        if not html:
            print(f"  [{i}/{len(ordning_urls)}] FEILET: {slug}")
            continue

        ordning = parse_ordning_side(html, url)
        ordninger.append(ordning)
        print(f"  [{i:3d}/{len(ordning_urls)}] {ordning['kategori']}/{slug[:45]}")

    print(f"\n{len(ordninger)} ordninger hentet\n")

    # ── Steg 3: Søknadsfrister ───────────────────────────────────────────────
    print("=== Steg 3: Søknadsfrister ===")
    frister_map = hent_frister(opener)
    frister_treff = 0
    for ordning in ordninger:
        frister = frister_map.get(ordning["url"], [])
        ordning["soknadsfrister"] = frister
        if frister:
            frister_treff += 1
    print(f"  {frister_treff} ordninger har kommende frister\n")

    # ── Steg 4: Lagre ────────────────────────────────────────────────────────
    json_fil = utmappe / "nfi_ordninger.json"
    json_fil.write_text(
        json.dumps(ordninger, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print(f"Skrevet: {json_fil}")

    if ordninger:
        felter = list(ordninger[0].keys())
        csv_fil = utmappe / "nfi_ordninger.csv"
        with csv_fil.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=felter, delimiter=";",
                               extrasaction="ignore")
            w.writeheader()
            for o in ordninger:
                rad = dict(o)
                rad["soknadsfrister"] = " | ".join(o["soknadsfrister"])
                w.writerow(rad)
        print(f"Skrevet: {csv_fil}")

    # ── Statistikk ──────────────────────────────────────────────────────────
    print("\n=== Statistikk per kategori ===")
    from collections import Counter
    for kat, antall in sorted(Counter(o["kategori"] for o in ordninger).items()):
        print(f"  {kat:<50} {antall:3d} ordninger")

    print(f"\nFelter med innhold:")
    for felt in ["ingress", "hvem_kan_soke", "hva_kan_sokes", "vilkaar",
                 "prioritering", "saksbehandlingstid", "lovdata_url",
                 "soknadsportal_url"]:
        n = sum(1 for o in ordninger if o.get(felt))
        print(f"  {felt:<30} {n:3d} / {len(ordninger)}")


if __name__ == "__main__":
    main()
