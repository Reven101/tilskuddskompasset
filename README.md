# Tilskuddskompasset

Finn tilskuddsordninger for frivillige organisasjoner – se hvem som har fått, hvor mye de fikk, og rekk fristen.

De fleste ordningene er statlige, men registeret omfatter også regionale kulturfond forvaltet av fylkeskommunene, ordninger frivilligheten forvalter selv på delegasjon (Frifond, LAM) og noen forvaltet av stiftelser. Finansieringen er dels statsbudsjettet, dels spillemidler.

Bygget på åpne data fra [tilskudd.no](https://tilskudd.lottstift.no) (Lotteri- og stiftelsestilsynet), [kulturdirektoratet.no](https://www.kulturdirektoratet.no) og [nfi.no](https://www.nfi.no).

---

## Hva som er i repoet

### Nettsted (GitHub → Vercel)
| Fil | Beskrivelse |
|-----|-------------|
| `index.html` | Hovednettside |
| `ordninger_v4.js` | Datafil – genereres lokalt av `lag_v4_data.py` |
| `om.html` | Om-siden |
| `robots.txt` | SEO |
| `sitemap.xml` | SEO |

### Datapipeline (GitHub, men kjøres lokalt)
| Fil | Beskrivelse |
|-----|-------------|
| `hent_bulk_tildelinger.py` | Laster ned tildelinger fra tilskudd.no |
| `hent_utvidet_data.py` | Henter ordningsmetadata fra tilskudd.no |
| `hent_kulturdirektoratet_innhold.py` | Skraper mål/formål/frister fra kulturdirektoratet.no |
| `hent_nfi_tildelinger.py` | Skraper tildelingsdata fra nfi.no |
| `hent_nfi_ordninger.py` | Skraper ordningsmetadata (frister, beskrivelse) fra nfi.no |
| `lag_v4_data.py` | Bygger `ordninger_v4.js` fra alle datakilder |
| `tilskudd_data/bygg_nkf_flb_v2.py` | Renser NKF/FLB-data og bygger innvilgelsesgrad-tabell |
| `tilskudd_data/hent_brreg_lookup.py` | Slår opp org.nr mot Brønnøysundregisteret |
| `tilskudd_data/berik_nkf_flb_brreg.py` | Beriker NKF/FLB-data med Brreg-info |
| `tilskudd_data/slaa_sammen_hoveddatasett.py` | **Påkrevd:** slår tilskudd.no- og NKF/FLB-tildelingene sammen til `tildelinger_samlet_2021_2026.csv`, som er filen `lag_v4_data.py` faktisk leser |
| `tilskudd_data/rens_tildelinger.py` | Renser råtildelinger (kun for egen analyse i Python/Excel) |
| `tilskudd_data/fyll_icnpo.py` | Fyller ICNPO-kategori der ordningsnavnet er entydig (kun for egen analyse) |
| `ci/kontroller_v4.py` | Kontrollerer `ordninger_v4.js` før publisering (kjøres av GitHub Actions) |

### Ikke i repoet (genereres/lastes ned lokalt)
Rådata i `tilskudd_data/` (CSV, Excel, JSON) er ekskludert via `.gitignore` — de er enten for store for GitHub eller kan regenereres ved å kjøre pipeline-en.

---

## Oppdatere dataene

### 1. tilskudd.no-data (helautomatisk, ~20 min)

```bash
python hent_bulk_tildelinger.py        # Last ned tildelinger (~5 sek)
python hent_utvidet_data.py            # Hent ordningsmetadata (~15 min)
```

### 2. Kulturråd / Fond for lyd og bilde (manuell nedlasting, halvårlig)

Kulturdirektoratet.no har ingen åpen API. Last ned manuelt fra kulturdirektoratet.no/vedtak:

- Filter: Status = Innvilget + Avslått
- Finansieringskilde = Kulturrådet / Fond for lyd og bilde / Kulturdirektoratet / Kulturdirektoratet Spillemidler
- Last ned CSV for 2021–2023 og 2024–2026 separat, legg i `tilskudd_data/`

Deretter, fra `tilskudd_data/`:

```bash
python bygg_nkf_flb_v2.py             # Rens + bygg innvilgelsesgrad-tabell (~10 sek)
python hent_brreg_lookup.py           # Brreg-oppslag (kun ved nye org.nr, ~5 min)
python berik_nkf_flb_brreg.py         # Fyll kommune/sektor/fylke (~10 sek)
```

Fra `tilskuddskompasset/`:

```bash
python hent_kulturdirektoratet_innhold.py   # Skrape mål/formål/frister (~1 min)
```

### 3. NFI – Norsk filminstitutt (helautomatisk, ~5 min)

```bash
python hent_nfi_tildelinger.py         # Skrape tildelinger fra nfi.no (~3 min)
python hent_nfi_ordninger.py           # Skrape ordningsmetadata fra nfi.no (~1 min)
```

Produserer `tilskudd_data/nfi_tildelinger_YYYY_YYYY.xlsx` og `tilskudd_data/nfi_ordninger.json`.

### 4. Bygg datafil og publiser

`lag_v4_data.py` leser `tilskudd_data/tildelinger_samlet_2021_2026.csv` — ikke
`tildelinger_alle.csv` direkte. Hopper du over sammenslåingen, bygges nettsiden på forrige
kjørings tildelingsdata: nøkkeltallene blir ferske, mens mottakertabeller, fylkesfordeling
og konkurransetall står stille under dagens dato.

```bash
cd tilskudd_data
python slaa_sammen_hoveddatasett.py    # Slår sammen tildelingene (~1 min)
cd ..
python lag_v4_data.py                  # Genererer ordninger_v4.js (~10 sek)
python ci/kontroller_v4.py             # Sjekker at filen ser sunn ut

git add ordninger_v4.js
git commit -m "Oppdater data"
git push
```

Vercel deployer automatisk når du pusher til GitHub.

---

## Anbefalt oppdateringskadense

| Hyppighet | Hva |
|-----------|-----|
| Månedlig | **Automatisk** via GitHub Actions (se under) — tilsvarer steg 1 + 4 |
| Halvårlig | Steg 2 + steg 4 (NKF/FLB-data) + oppdater `data-grunnlag`-releasen |
| Halvårlig | Steg 3 + steg 4 (NFI-data) + oppdater `data-grunnlag`-releasen |

## Automatisk oppdatering (GitHub Actions)

Workflowen [.github/workflows/oppdater-data.yml](.github/workflows/oppdater-data.yml)
kjører den månedlige rutinen uten deg, natt til den 2. hver måned:
henter ferske tilskudd.no-data, skraper frister fra kulturdirektoratet.no,
bygger `ordninger_v4.js`, kontrollerer at den er sunn
(`ci/kontroller_v4.py` — minst 250 ordninger, bygget i dag), og pusher.
Vercel deployer som vanlig. Går kontrollen ikke gjennom, publiseres
ingenting — nettsiden beholder forrige versjon.

De halvårlige, manuelt bygde filene er for store for git og ligger bare på din
maskin. Workflowen henter dem derfor fra en GitHub-release.

Releasen skal kun inneholde de seks filene workflowen faktisk trenger — resten av
`tilskudd_data/` regenereres av skrapestegene i hver kjøring, eller brukes ikke av
nettsiden. Hele mappa er 1,2 GB; disse seks er 61 MB:

| Fil | Hvem trenger den |
|-----|------------------|
| `nkf_flb_organisasjoner_2021_2026_alle_status.csv` | `slaa_sammen_hoveddatasett.py` |
| `nkf_flb_organisasjoner_2021_2026.csv` | `lag_v4_data.py` (mottakere/beløp for NKF/FLB) |
| `nkf_flb_innvilgelsesgrad_per_ordning.csv` | `lag_v4_data.py` (innvilgelsesgrad) |
| `brreg_lookup.csv` | `slaa_sammen_hoveddatasett.py` (sektorkode) |
| `nfi_tildelinger_2020_juni2026.xlsx` | `lag_v4_data.py` (NFI-tildelinger) |
| `nfi_ordninger.json` | `lag_v4_data.py` (NFI-frister og metadata) |

**Førstegangsoppsett (én gang):**

1. Bygg zip-en fra repo-roten:
   `python lag_datagrunnlag_zip.py`
2. På GitHub: Releases → «Draft a new release» → tag `data-grunnlag` →
   dra `tilskudd_data.zip` inn som vedlegg → «Publish release»
3. Actions-fanen → «Oppdater tilskuddsdata» → «Run workflow» — sjekk at
   testkjøringen blir grønn

**Halvårlig vedlikehold:** etter den manuelle NKF/FLB- eller NFI-rutinen,
bygg ny zip (punkt 1) og last den opp på nytt på `data-grunnlag`-releasen
(slett det gamle vedlegget først). Selve cron-kjøringen krever at
workflow-filen ligger på main-grenen.

Filnavnene med årstall (`nfi_tildelinger_2020_juni2026.xlsx`) er hardkodet i
`lag_v4_data.py`. Endrer navnet seg ved neste NFI-nedlasting, må både scriptet og
`lag_datagrunnlag_zip.py` oppdateres — ellers hopper byggingen stille over NFI.

---

## Teknisk

Tilskuddskompasset er en ren statisk HTML/JS-side uten byggsteg eller rammeverk. `ordninger_v4.js` eksporterer én global variabel (`ORDNINGER`) som `index.html` leser direkte. Ingen server, ingen database.

Data for 2021–2023 er hentet fra Kulturdirektoratets gamle nettplattform før den ble erstattet i 2026.

---

En tjeneste fra [Impromptu Analytics](https://impromptu.no).
