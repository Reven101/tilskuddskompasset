"""Renser tildelinger_alle.csv (som allerede er korrekt sitert CSV) og
skriver ut en ren .xlsx og .csv. Den eksisterende xlsx-filen er bygget med
en verktøykjede som ikke respekterte anførselstegn rundt flerlinjede
beskrivelsesfelt, og falt derfor i stykker på hvert linjeskift i teksten.
"""
import pandas as pd

SRC_CSV = "tildelinger_alle.csv"
OUT_XLSX = "Tilskudd_2021_juni2026_renset.xlsx"
OUT_CSV = "tildelinger_alle_renset.csv"

df = pd.read_csv(SRC_CSV, sep=";", encoding="utf-8-sig", engine="python")

# Sanity-sjekk før vi skriver ut
assert df["budsjettar"].astype(str).str.match(r"^\d{4}$").all(), "Ugyldig budsjettar funnet"
assert pd.to_numeric(df["tildelt_belop"], errors="coerce").notna().all(), "Ikke-numerisk tildelt_belop"
gyldige_kilder = {"Spillemidler", "Statsbudsjettet", "Statsbudsjettet og spillemidler"}
assert set(df["finansieringskilder"].dropna().unique()) <= gyldige_kilder, "Uventet verdi i finansieringskilder"

print("Rader:", len(df), "Kolonner:", len(df.columns))
print(df.isnull().sum())

df.to_excel(OUT_XLSX, sheet_name="tildelinger_alle", index=False)
df.to_csv(OUT_CSV, sep=";", encoding="utf-8-sig", index=False)
print(f"\nSkrevet til {OUT_XLSX} og {OUT_CSV}")
