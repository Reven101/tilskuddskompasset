# Tilskuddskompasset

Finn statlige tilskuddsordninger for frivillige organisasjoner – se hvem som har fått, hvor mye de fikk, og rekk fristen.

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
| `tilskudd_data/rens_tildelinger.py` | Renser råtildelinger (for egen analyse) |
| `tilskudd_data/slaa_sammen_hoveddatasett.py` | Samler alt til ett analysedatasett |

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

```bash
python lag_v4_data.py                  # Genererer ordninger_v4.js (~10 sek)

git add ordninger_v4.js
git commit -m "Oppdater data"
git push
```

Vercel deployer automatisk når du pusher til GitHub.

---

## Anbefalt oppdateringskadense

| Hyppighet | Hva |
|-----------|-----|
| Månedlig | Steg 1 + steg 4 (tilskudd.no-data) |
| Halvårlig | Steg 2 + steg 4 (NKF/FLB-data) |
| Halvårlig | Steg 3 + steg 4 (NFI-data) |

---

## Teknisk

Tilskuddskompasset er en ren statisk HTML/JS-side uten byggsteg eller rammeverk. `ordninger_v4.js` eksporterer én global variabel (`ORDNINGER`) som `index.html` leser direkte. Ingen server, ingen database.

Data for 2021–2023 er hentet fra Kulturdirektoratets gamle nettplattform før den ble erstattet i 2026.

---

En tjeneste fra [Impromptu Analytics](https://impromptu.no).
