# Tilskuddskompasset

Finn statlige tilskuddsordninger for frivillige organisasjoner – se hvem som har fått, hvor mye de fikk, og rekk fristen.

Bygget på åpne data fra [tilskudd.no](https://tilskudd.lottstift.no) (Lotteri- og stiftelsestilsynet) og [kulturdirektoratet.no](https://www.kulturdirektoratet.no).

---

## Filer som publiseres (GitHub → Vercel)

| Fil | Beskrivelse |
|-----|-------------|
| `index.html` | Hovednettside |
| `ordninger_v4.js` | Datafil – genereres lokalt av `lag_v4_data.py` |
| `om.html` | Om-siden |
| `robots.txt` | SEO |
| `sitemap.xml` | SEO |

Alt annet (Python-skript, rådata, Excel-filer) er lokal pipeline og skal ikke lastes opp.

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

### 3. Bygg datafil og publiser

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
| Månedlig | Steg 1 + steg 3 (tilskudd.no-data) |
| Halvårlig | Steg 2 + steg 3 (NKF/FLB-data) |

---

## Teknisk

Tilskuddskompasset er en ren statisk HTML/JS-side uten byggsteg eller rammeverk. `ordninger_v4.js` eksporterer én global variabel (`ORDNINGER`) som `index.html` leser direkte. Ingen server, ingen database.

Data for 2021–2023 er hentet fra Kulturdirektoratets gamle nettplattform før den ble erstattet i 2026.

---

En tjeneste fra [Impromptu Analytics](https://impromptu.no).
