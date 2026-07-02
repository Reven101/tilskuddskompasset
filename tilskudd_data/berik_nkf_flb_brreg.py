"""Beriker nkf_flb-datasettene med data fra Brønnøysundregisteret
(brreg_lookup.csv, laget av hent_brreg_lookup.py): fyller kommune,
mottaker_sektorkode og mottaker_sektor via organisasjonsnummer, og avleder
fylke fra kommunenummer der fylke mangler (kun 2021-23-delen - 2024-26 har
allerede fylke fra søkerens oppgitte fylke).

Fyller KUN tomme celler - rører ikke verdier som allerede finnes.
"""
import pandas as pd

LOOKUP = "brreg_lookup.csv"
FILER = [
    "nkf_flb_organisasjoner_2021_2026_alle_status",
    "nkf_flb_organisasjoner_2021_2026",
]

# Kommunenummer-prefiks (2 første sifre) -> fylkesnavn, gjeldende fylkesstruktur (2024-)
FYLKE_PREFIKS = {
    "03": "Oslo", "11": "Rogaland", "15": "Møre og Romsdal", "18": "Nordland",
    "31": "Østfold", "32": "Akershus", "33": "Buskerud", "34": "Innlandet",
    "39": "Vestfold", "40": "Telemark", "42": "Agder", "46": "Vestland",
    "50": "Trøndelag", "55": "Troms", "56": "Finnmark",
}


def avled_fylke(kommunenummer):
    if pd.isna(kommunenummer):
        return pd.NA
    prefiks = str(kommunenummer).zfill(4)[:2]
    return FYLKE_PREFIKS.get(prefiks, pd.NA)


def main():
    lookup = pd.read_csv(LOOKUP, sep=";", encoding="utf-8-sig", dtype={"organisasjonsnummer": str})
    lookup["fylke_avledet"] = lookup["kommunenummer"].apply(avled_fylke)
    lookup = lookup.set_index("organisasjonsnummer")

    for navn in FILER:
        df = pd.read_csv(f"{navn}.csv", sep=";", encoding="utf-8-sig", low_memory=False)
        orgnr_str = df["mottaker_organisasjonsnummer"].astype(str).str.strip().str.replace(r"\.0$", "", regex=True)

        før_kommune = df["kommune"].notna().sum()
        før_sektor = df["mottaker_sektor"].notna().sum()
        før_fylke = df["fylke"].notna().sum()

        df["kommune"] = df["kommune"].where(df["kommune"].notna(), orgnr_str.map(lookup["kommune"]))
        df["mottaker_sektorkode"] = df["mottaker_sektorkode"].where(
            df["mottaker_sektorkode"].notna(), orgnr_str.map(lookup["sektorkode"])
        )
        df["mottaker_sektor"] = df["mottaker_sektor"].where(
            df["mottaker_sektor"].notna(), orgnr_str.map(lookup["sektor"])
        )
        df["fylke"] = df["fylke"].where(df["fylke"].notna(), orgnr_str.map(lookup["fylke_avledet"]))

        print(f"\n=== {navn} ===")
        print(f"kommune:  {før_kommune} -> {df['kommune'].notna().sum()} ({len(df)} rader totalt)")
        print(f"sektor:   {før_sektor} -> {df['mottaker_sektor'].notna().sum()}")
        print(f"fylke:    {før_fylke} -> {df['fylke'].notna().sum()}")

        df.to_csv(f"{navn}.csv", sep=";", encoding="utf-8-sig", index=False)
        df.to_excel(f"{navn}.xlsx", index=False)
        print(f"Skrevet til {navn}.csv / {navn}.xlsx")


if __name__ == "__main__":
    main()
