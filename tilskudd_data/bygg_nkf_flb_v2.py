"""Bygger nkf_flb-datasettet på nytt fra de nye eksportene som inkluderer
avslag (nkf_flb_organisasjoner_2021_23_med_avslag.xlsx og
vedtak_20260616_115010.csv). Disse erstatter de forrige Innvilget-only-
filene siden de er bredere (flere rader) og lar oss beregne innvilgelsesgrad
per ordning - akkurat den statistikken v4-siden allerede viser for
tilskudd.no-ordninger (DT-xxxx), men som manglet for Kulturråd/FLB.

Output:
  1. nkf_flb_organisasjoner_2021_2026_alle_status.xlsx/.csv
     - Alle søknader (Innvilget/Avslått/Ubesluttet), til bruk for
       innvilgelsesgrad-beregning.
  2. nkf_flb_innvilgelsesgrad_per_ordning.csv
     - Aggregert: antall søknader, antall innvilget, andel innvilget,
       per tilskudds_id - samme struktur som "oppsummering" i
       ordninger_utvidet.json (grantedApplications/totalApplications).
  3. nkf_flb_organisasjoner_2021_2026.xlsx/.csv
     - Kun Innvilget-rader (erstatter forrige versjon), til bruk for join
       mot tildelinger_alle_renset (faktiske tildelinger/beløp).

Bevisst utelatt: "Statens kunstnerstipend" (51 914 rader i 2024-26-filen) -
individuelle kunstnerstipend, ikke organisasjonstilskudd, og finnes ikke i
2021-23-dataene. Etter avtale med bruker.
"""
import pandas as pd

F21 = "nkf_flb_organisasjoner_2021_23_med_avslag.xlsx"
F24 = "vedtak_20260616_115010.csv"

OUT_ALLE_XLSX = "nkf_flb_organisasjoner_2021_2026_alle_status.xlsx"
OUT_ALLE_CSV = "nkf_flb_organisasjoner_2021_2026_alle_status.csv"
OUT_GRAD_CSV = "nkf_flb_innvilgelsesgrad_per_ordning.csv"
OUT_INNVILGET_XLSX = "nkf_flb_organisasjoner_2021_2026.xlsx"
OUT_INNVILGET_CSV = "nkf_flb_organisasjoner_2021_2026.csv"

# ============================================================ 2021-23
df21 = pd.read_excel(F21, sheet_name="Sheet1")
before = len(df21)
df21 = df21.drop_duplicates().reset_index(drop=True)
print(f"2021-23: fjernet {before - len(df21)} duplikatrader ({before} -> {len(df21)})")

df21["status"] = df21["tildelt_belop"].apply(lambda x: "Innvilget" if x and x > 0 else "Avslått")
print("2021-23 status-fordeling:")
print(df21["status"].value_counts())

kode_til_navn = dict(zip(df21["tilskudds_id"], df21["tilskuddsordning"]))

# Manuelle navn for koder som ikke finnes i 2021-23-oppslaget (nye/omdøpte
# ordninger fra 2024+). Identifisert ved å sammenligne tiltak/mottakere mot
# de skrapte sidetitlene fra kulturdirektoratet.no (hent_kulturdirektoratet_innhold.py):
# FLB omstrukturerte til 4 brede kategorier i 2024, og noen Kulturråd-koder
# matcher temaet i tiltakene mot en eksisterende, skrapet ordningsside.
kode_til_navn.update({
    "FLB-AUDIO": "Fond for lyd og bilde Musikk",
    "FLB-CINE": "Fond for lyd og bilde Film",
    "FLB-LIVE": "Fond for lyd og bilde Scene",
    "FLB-MEDIA": "Fond for lyd og bilde Markedsføring",
    "KUL-AFR": "Markering av FNs tiår for mennesker av afrikansk opprinnelse",
    "KUL-FMN": "Faglige museumsnettverk - treårig",
    "NKF-UKA": "Utviklingstiltak for kulturaktører",
    "NKF-FSV": "Scenekunst – etablerte virksomheter",
})
# KUL-DATA, KUL-IND og NKF-IBK er fortsatt uidentifiserte - vi fant ingen
# ordningsside som matcher tiltakene deres trygt nok til å gi dem et navn.

df21_h = pd.DataFrame({
    "tilskuddsforvalter": df21["tilskuddsforvalter"],
    "ansvarlig_departement": df21["ansvarlig_departement"],
    "tilskudds_id": df21["tilskudds_id"],
    "tilskuddsordning": df21["tilskuddsordning"],
    "budsjettar": df21["budsjett"],
    "status": df21["status"],
    "fylke": df21["fylke"],
    "kommune": df21["kommune"],
    "mottaker_organisasjonsnummer": df21["mottaker_organisasjonsnummer"],
    "mottakernavn": df21["mottakernavn"],
    "mottaker_sektorkode": df21["mottaker_sektorkode"],
    "mottaker_sektor": df21["mottaker_sektor"],
    "soker_type": pd.NA,
    "icnpo_nr": df21["icnpo"],
    "icnpo_kategori": df21["icnpo_kategori"],
    "type_tilskudd": df21["type_tilskudd"],
    "soknadsbelop": df21["soknadsbelop"],
    "tildelt_belop": df21["tildelt_belop"],
    "tiltak": df21["tiltak"],
    "kort_beskrivelse_av_tiltak": df21["kort_beskrivelse_av_tiltak"],
    "soknadsfrist": pd.NaT,
    "bevilgningsaar_usikker": False,
    "kildefil": F21,
})

# ============================================================ 2024-26
df24 = pd.read_csv(F24, sep=";", encoding="utf-8-sig", low_memory=False)
before = len(df24)
df24 = df24[df24["hovedfinansieringskilde"] != "Statens kunstnerstipend"].reset_index(drop=True)
print(f"\n2024-26: fjernet {before - len(df24)} rader fra Statens kunstnerstipend ({before} -> {len(df24)})")

before = len(df24)
df24 = df24.drop_duplicates().reset_index(drop=True)
print(f"2024-26: fjernet {before - len(df24)} duplikatrader ({before} -> {len(df24)})")

df24["soknadsfrist"] = pd.to_datetime(df24["soknadsfrist"], errors="coerce")

# Upålitelig bevilgningsaar: verifisert mot data at gyldig vindu er [2018,2035] -
# alt utenfor er placeholder/tastefeil (f.eks 2010/2011/2627/7777), mens ekte
# flerårige søknader/utbetalinger ligger innenfor dette vinduet.
usikker = (df24["bevilgningsaar"] < 2018) | (df24["bevilgningsaar"] > 2035)
df24["bevilgningsaar_usikker"] = usikker
df24.loc[usikker, "bevilgningsaar"] = pd.NA
print(f"2024-26: flagget {usikker.sum()} rader med upålitelig bevilgningsaar (utenfor [2018,2035])")

print("\n2024-26 status-fordeling:")
print(df24["soknad_vedtak"].value_counts())

mangler_navn = sorted(set(df24["ordning_kode"]) - set(kode_til_navn))
print(f"\nOrdningskoder i 2024-26 uten navn i 2021-23-oppslaget ({len(mangler_navn)}): {mangler_navn}")

df24_h = pd.DataFrame({
    "tilskuddsforvalter": df24["hovedfinansieringskilde"],
    "ansvarlig_departement": "Kultur- og likestillingsdepartementet",
    "tilskudds_id": df24["ordning_kode"],
    "tilskuddsordning": df24["ordning_kode"].map(kode_til_navn).fillna(
        "Uidentifisert ordning (" + df24["hovedfinansieringskilde"] + ", kode " + df24["ordning_kode"] + ")"
    ),
    "budsjettar": df24["bevilgningsaar"],
    "status": df24["soknad_vedtak"],
    "fylke": df24["soker_fylke"],
    "kommune": pd.NA,
    "mottaker_organisasjonsnummer": df24["soker_organisasjonsnummer"],
    "mottakernavn": df24["soker_navn"],
    "mottaker_sektorkode": pd.NA,
    "mottaker_sektor": pd.NA,
    "soker_type": df24["soker_type"],
    "icnpo_nr": pd.NA,
    "icnpo_kategori": pd.NA,
    "type_tilskudd": df24["verdi_type"],
    "soknadsbelop": df24["verdi_omsokt"],
    "tildelt_belop": df24["verdi_innvilget"],
    "tiltak": df24["tiltak_tittel"],
    "kort_beskrivelse_av_tiltak": df24["tiltak_sammendrag"],
    "soknadsfrist": df24["soknadsfrist"],
    "bevilgningsaar_usikker": df24["bevilgningsaar_usikker"],
    "kildefil": F24,
})

# ============================================================ Fyll orgnr for "(Innvilget Deltakelse)"-rader
# Noen rader i NKF-IBK har mottakernavn med en status-suffiks og mangler
# orgnr. Mange av disse søkerne har søkt (med orgnr) i andre ordninger/år -
# slå opp eksakt navnematch (uten suffiks) mot resten av datasettet.
navn_lookup = pd.concat([
    df21_h[["mottakernavn", "mottaker_organisasjonsnummer"]],
    df24_h[["mottakernavn", "mottaker_organisasjonsnummer"]],
]).dropna(subset=["mottaker_organisasjonsnummer"])
navn_lookup["navn_upper"] = navn_lookup["mottakernavn"].str.upper().str.strip()
navn_til_orgnr = navn_lookup.drop_duplicates("navn_upper").set_index("navn_upper")["mottaker_organisasjonsnummer"]

mangler_orgnr = df24_h["mottakernavn"].str.contains(r"\(Innvilget Deltakelse\)", na=False) & df24_h["mottaker_organisasjonsnummer"].isna()
navn_uten_suffiks = df24_h.loc[mangler_orgnr, "mottakernavn"].str.replace(r"\s*\(Innvilget Deltakelse\)", "", regex=True).str.strip().str.upper()
funnet_orgnr = navn_uten_suffiks.map(navn_til_orgnr)
df24_h.loc[mangler_orgnr, "mottaker_organisasjonsnummer"] = funnet_orgnr
print(f"\n'(Innvilget Deltakelse)'-rader: fylte inn orgnr for {funnet_orgnr.notna().sum()} av {mangler_orgnr.sum()} via navnematch")

# ============================================================ Slå sammen
kolonner = list(df21_h.columns)
samlet = pd.concat([df21_h, df24_h[kolonner]], ignore_index=True)

# Ekskluder enkeltpersoner: nettstedet/datasettet gjelder tilskudd til
# organisasjoner. soker_type finnes kun i 2024-26-delen (NaN i 2021-23, som
# derfor ikke kan filtreres - de blir stående siden vi ikke vet typen).
before = len(samlet)
samlet = samlet[samlet["soker_type"] != "Person"].reset_index(drop=True)
print(f"\nFjernet {before - len(samlet)} rader med soker_type=Person ({before} -> {len(samlet)})")

# Restduplikater som ble identiske etter at bevilgningsaar ble nullet
cols_uten_kilde = [c for c in samlet.columns if c != "kildefil"]
n_dupe = samlet.duplicated(subset=cols_uten_kilde).sum()
if n_dupe:
    before = len(samlet)
    samlet = samlet.drop_duplicates(subset=cols_uten_kilde).reset_index(drop=True)
    print(f"\nFjernet {before - len(samlet)} restduplikater (identiske etter rensing)")

print(f"\nTotalt i samlet datasett (alle statuser): {len(samlet)}")
print(samlet["status"].value_counts(dropna=False))

samlet.to_excel(OUT_ALLE_XLSX, sheet_name="nkf_flb_alle_status", index=False)
samlet.to_csv(OUT_ALLE_CSV, sep=";", encoding="utf-8-sig", index=False)
print(f"Skrevet til {OUT_ALLE_XLSX} / {OUT_ALLE_CSV}")

# ============================================================ Innvilgelsesgrad per ordning
grad = (
    samlet[samlet["status"].isin(["Innvilget", "Avslått", "Ubesluttet"])]
    .groupby(["tilskudds_id", "tilskuddsordning", "tilskuddsforvalter"])["status"]
    .agg(
        totalApplications="count",
        grantedApplications=lambda s: (s == "Innvilget").sum(),
    )
    .reset_index()
)
grad["grad"] = (grad["grantedApplications"] / grad["totalApplications"]).round(3)
grad = grad.sort_values("totalApplications", ascending=False)
grad.to_csv(OUT_GRAD_CSV, sep=";", encoding="utf-8-sig", index=False)
print(f"\nSkrevet innvilgelsesgrad for {len(grad)} ordninger til {OUT_GRAD_CSV}")
print(grad.head(10).to_string())

# ============================================================ Innvilget-only (for join mot tildelinger)
innvilget = samlet[samlet["status"] == "Innvilget"].drop(columns=["status"]).reset_index(drop=True)
print(f"\nInnvilget-only rader (til join mot hoveddatasett): {len(innvilget)}")
innvilget.to_excel(OUT_INNVILGET_XLSX, sheet_name="nkf_flb_2021_2026", index=False)
innvilget.to_csv(OUT_INNVILGET_CSV, sep=";", encoding="utf-8-sig", index=False)
print(f"Skrevet til {OUT_INNVILGET_XLSX} / {OUT_INNVILGET_CSV}")
