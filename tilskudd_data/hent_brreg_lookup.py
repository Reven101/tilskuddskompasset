"""Slår opp organisasjonsnumrene i nkf_flb-datasettet mot Brønnøysundregisterets
Enhetsregister-API (data.brreg.no), for å hente:
  - kommune / kommunenummer (forretningsadresse)
  - institusjonell sektorkode + beskrivelse (samme klassifikasjonssystem som
    mottaker_sektorkode/mottaker_sektor i hoveddatasettet, f.eks. 7000 =
    "Ideelle organisasjoner")

Bruker batch-søk (organisasjonsnummer=nr1,nr2,...) i stedet for ett kall per
orgnr - 14 000 enkeltkall ville tatt unødvendig lang tid og belastet APIet
mer enn nødvendig.

Resultatet caches til brreg_lookup.csv, så vi ikke trenger å kjøre dette på
nytt med mindre datasettet får nye organisasjonsnumre.

Kjøring: python hent_brreg_lookup.py
"""
import time

import pandas as pd
import requests

KILDE = "nkf_flb_organisasjoner_2021_2026_alle_status.csv"
CACHE = "brreg_lookup.csv"
API = "https://data.brreg.no/enhetsregisteret/api/enheter"
BATCH = 300
PAUSE = 0.3

session = requests.Session()
session.headers.update({"User-Agent": "Tilskuddskompasset-databerikelse (kontakt: kontakt@impromptu.no)"})


def hent_batch(orgnumre: list[str]) -> list[dict]:
    csv_param = ",".join(orgnumre)
    r = session.get(API, params={"organisasjonsnummer": csv_param, "size": len(orgnumre)}, timeout=30)
    r.raise_for_status()
    data = r.json()
    return data.get("_embedded", {}).get("enheter", [])


def main():
    df = pd.read_csv(KILDE, sep=";", encoding="utf-8-sig", low_memory=False)
    rå = df["mottaker_organisasjonsnummer"].dropna().astype(str).str.strip()
    rå = rå.str.replace(r"\.0$", "", regex=True)
    gyldig = rå.str.fullmatch(r"\d{9}")
    print(f"Ugyldige organisasjonsnummer-verdier (filtrert ut): {(~gyldig).sum()}")
    if (~gyldig).sum():
        print(rå[~gyldig].unique()[:10])
    orgnumre = sorted(rå[gyldig].unique())
    print(f"Unike organisasjonsnumre å slå opp: {len(orgnumre)}")

    rader = []
    for i in range(0, len(orgnumre), BATCH):
        batch = orgnumre[i : i + BATCH]
        try:
            enheter = hent_batch(batch)
        except requests.RequestException as e:
            print(f"  ! Feil på batch {i}-{i+len(batch)}: {e}")
            time.sleep(2)
            continue
        for e in enheter:
            adresse = e.get("forretningsadresse") or e.get("postadresse") or {}
            sektor = e.get("institusjonellSektorkode") or {}
            rader.append({
                "organisasjonsnummer": e.get("organisasjonsnummer"),
                "navn_brreg": e.get("navn"),
                "kommune": adresse.get("kommune"),
                "kommunenummer": adresse.get("kommunenummer"),
                "sektorkode": sektor.get("kode"),
                "sektor": sektor.get("beskrivelse"),
                "organisasjonsform": (e.get("organisasjonsform") or {}).get("kode"),
            })
        print(f"  {i + len(batch)}/{len(orgnumre)} slått opp, {len(enheter)} treff i denne batchen")
        time.sleep(PAUSE)

    resultat = pd.DataFrame(rader)
    resultat.to_csv(CACHE, sep=";", encoding="utf-8-sig", index=False)
    print(f"\nFant data for {len(resultat)} av {len(orgnumre)} organisasjonsnumre")
    print(f"Skrevet til {CACHE}")
    print("\nSektorkode-fordeling (topp 10):")
    print(resultat["sektor"].value_counts().head(10))


if __name__ == "__main__":
    main()
