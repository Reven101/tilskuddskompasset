"""Fyller inn icnpo_nr/icnpo_kategori for ordninger der klassifiseringen er
entydig ut fra ordningsnavnet, men mangler i kildedataene. Ordninger med
blandede mottakertyper (strømstøtte, grasrotandelen, frivilligsentraler m.fl.)
lar vi stå tomme, siden vi ikke kan gjette riktig kategori for dem.
"""
import pandas as pd

SRC = "tildelinger_alle_renset.csv"
OUT_CSV = "tildelinger_alle_renset.csv"
OUT_XLSX = "Tilskudd_2021_juni2026_renset.xlsx"

df = pd.read_csv(SRC, sep=";", encoding="utf-8-sig")

before_missing = df["icnpo_nr"].isna().sum()

# Regelbasert utfylling: ordningsnavn -> (icnpo_nr, icnpo_kategori)
regler = [
    ("politiske partier", 7300.0, "Politiske organisasjoner"),
    ("trus- og livssynssamfunn", 10100.0, "Tros- og livssynsorganisasjoner"),
]

mask_missing = df["icnpo_nr"].isna()
for nokkel, nr, kategori in regler:
    mask = mask_missing & df["tilskuddsordning"].str.contains(nokkel, case=False, na=False)
    df.loc[mask, "icnpo_nr"] = nr
    df.loc[mask, "icnpo_kategori"] = kategori
    print(f"'{nokkel}': fylte ut {mask.sum()} rader")

after_missing = df["icnpo_nr"].isna().sum()
print(f"\nMangler icnpo_nr før: {before_missing}, etter: {after_missing}")

df.to_csv(OUT_CSV, sep=";", encoding="utf-8-sig", index=False)
df.to_excel(OUT_XLSX, sheet_name="tildelinger_alle", index=False)
print(f"Skrevet til {OUT_CSV} og {OUT_XLSX}")
