"""Slår sammen tildelinger_alle.csv (hoveddatasett fra tilskudd.no, alle år 2021-2026)
med innvilgede søknader fra nkf_flb_organisasjoner_2021_2026_alle_status.csv
(Kulturråd/Fond for lyd og bilde/Kulturdirektoratet-data).

Beriker NKF/FLB-radene med:
- sektorkode/sektor fra brreg_lookup.csv
- ICNPO-kategori: 1100 (Kunst og kultur) for NKF/FLB/de fleste KUL-ordninger,
  7100 (Interesseorganisasjoner) for minoritets-/rettighetsordninger
- finansieringskilder avledet fra forvalternavn

Bekreftet:
- Ingen overlapp i tilskudds_id (DT-xxxx vs NKF/FLB/KUL-xxx): 0 felles IDer.
"""
import pandas as pd

# --- Filstier ---
BULK = "tildelinger_alle.csv"
NKF_KILDE = "nkf_flb_organisasjoner_2021_2026_alle_status.csv"
BRREG = "brreg_lookup.csv"
OUT_CSV = "tildelinger_samlet_2021_2026.csv"

# --- ICNPO-mapping for NKF/FLB ---
# Minoritets-/rettighetsordninger → 7100 Interesseorganisasjoner
ICNPO_7100_ORDNINGER = {"KUL-KND", "KUL-KNP", "KUL-NMD", "KUL-NMP", "KUL-KRT", "KUL-MKO", "KUL-AFR"}

# --- Les kilder ---
print("Leser data...")
bulk = pd.read_csv(BULK, sep=";", encoding="utf-8-sig", low_memory=False)
nkf_alle = pd.read_csv(NKF_KILDE, sep=";", encoding="utf-8-sig", low_memory=False)
brreg = pd.read_csv(BRREG, sep=";", encoding="utf-8-sig", low_memory=False)

print(f"  Bulk (tilskudd.no): {len(bulk):,} rader")
print(f"  NKF/FLB alle statuser: {len(nkf_alle):,} rader")
print(f"  Brreg-lookup: {len(brreg):,} rader")

# --- Filtrer NKF/FLB til kun innvilgede ---
nkf = nkf_alle[nkf_alle["status"] == "Innvilget"].copy()
print(f"  NKF/FLB innvilget: {len(nkf):,} rader")

# --- Berik NKF/FLB med sektorkode fra brreg ---
brreg["organisasjonsnummer"] = brreg["organisasjonsnummer"].astype(str)
nkf["mottaker_organisasjonsnummer"] = (
    nkf["mottaker_organisasjonsnummer"].astype(str).str.replace(r"\.0$", "", regex=True)
)

brreg_sektor = brreg[["organisasjonsnummer", "sektorkode", "sektor"]].drop_duplicates(subset="organisasjonsnummer")
mangler_sektor = nkf["mottaker_sektorkode"].isnull()

# Merge sektorkode for rader som mangler
nkf_merge = nkf[mangler_sektor].merge(
    brreg_sektor,
    left_on="mottaker_organisasjonsnummer",
    right_on="organisasjonsnummer",
    how="left",
    suffixes=("", "_brreg"),
)
nkf.loc[mangler_sektor, "mottaker_sektorkode"] = nkf_merge["sektorkode"].values
nkf.loc[mangler_sektor, "mottaker_sektor"] = nkf_merge["sektor"].values

beriket = mangler_sektor.sum() - nkf["mottaker_sektorkode"].isnull().sum()
print(f"  Beriket {beriket:,} rader med sektorkode fra brreg")

# --- Sett ICNPO for NKF/FLB ---
nkf["icnpo_nr"] = nkf["tilskudds_id"].apply(
    lambda x: 7100.0 if x in ICNPO_7100_ORDNINGER else 1100.0
)
nkf["icnpo_kategori"] = nkf["icnpo_nr"].map({
    1100.0: "Kunst og kultur",
    7100.0: "Interesseorganisasjoner",
})

# --- Avled finansieringskilder ---
nkf["finansieringskilder"] = nkf["tilskuddsforvalter"].apply(
    lambda f: "Spillemidler" if "Spillemidler" in str(f) else "Statsbudsjettet"
)

# --- Harmoniser budsjettar ---
nkf["budsjettar"] = nkf["budsjettar"].astype("Int64")
bulk["budsjettar"] = bulk["budsjettar"].astype("Int64")

# --- Kildefil for sporbarhet ---
bulk["kildefil"] = "tildelinger_alle.csv"
nkf["kildefil"] = "nkf_flb_organisasjoner_2021_2026_alle_status.csv"

# --- Felles kolonner ---
kolonner = [
    "tilskuddsforvalter", "ansvarlig_departement", "tilskudds_id", "tilskuddsordning",
    "budsjettar", "fylke", "kommune", "mottaker_organisasjonsnummer", "mottakernavn",
    "mottaker_sektorkode", "mottaker_sektor", "icnpo_nr", "icnpo_kategori",
    "type_tilskudd", "soknadsbelop", "tildelt_belop", "tiltak", "kort_beskrivelse_av_tiltak",
    "finansieringskilder", "kildefil",
]

samlet = pd.concat([bulk[kolonner], nkf[kolonner]], ignore_index=True)

# --- Sanity-sjekker ---
print(f"\n{'='*50}")
print(f"SAMLET DATASETT")
print(f"{'='*50}")
print(f"  Rader: {len(samlet):,}")
assert len(samlet) == len(bulk) + len(nkf), "Radantall stemmer ikke"

print(f"\n  Budsjettår-fordeling:")
print(samlet["budsjettar"].value_counts(dropna=False).sort_index().to_string())

print(f"\n  Kildefil-fordeling:")
print(samlet["kildefil"].value_counts().to_string())

print(f"\n  Finansieringskilder:")
print(samlet["finansieringskilder"].value_counts().to_string())

print(f"\n  Sum tildelt per kildefil:")
print(samlet.groupby("kildefil")["tildelt_belop"].sum().to_string())

print(f"\n  ICNPO-dekning:")
print(f"    Med ICNPO: {samlet['icnpo_nr'].notna().sum():,} ({samlet['icnpo_nr'].notna().mean()*100:.1f}%)")
print(f"    Uten ICNPO: {samlet['icnpo_nr'].isna().sum():,} ({samlet['icnpo_nr'].isna().mean()*100:.1f}%)")

print(f"\n  Sektorkode-dekning:")
print(f"    Med sektor: {samlet['mottaker_sektorkode'].notna().sum():,} ({samlet['mottaker_sektorkode'].notna().mean()*100:.1f}%)")
print(f"    Uten sektor: {samlet['mottaker_sektorkode'].isna().sum():,} ({samlet['mottaker_sektorkode'].isna().mean()*100:.1f}%)")

# --- Skriv ut ---
samlet.to_csv(OUT_CSV, sep=";", encoding="utf-8-sig", index=False)
print(f"\nSkrevet til {OUT_CSV}")
