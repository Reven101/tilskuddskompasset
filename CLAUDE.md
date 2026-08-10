# Tilskuddskompasset

Statisk HTML/JS uten byggsteg og rammeverk. `index.html` leser `ordninger_v4.js`, som
`lag_v4_data.py` genererer lokalt eller i GitHub Actions. Deploy: push til main → Vercel.

## Datastrømmen

```
tilskudd.no      hent_bulk_tildelinger.py   → tilskudd_data/tildelinger_alle.csv
                 hent_utvidet_data.py       → tilskudd_data/ordninger_utvidet.json
kulturdir.no     (manuell CSV-nedlasting)   → bygg_nkf_flb_v2.py → nkf_flb_*.csv
                 hent_kulturdirektoratet_innhold.py → kulturdirektoratet_innhold.json
nfi.no           hent_nfi_tildelinger.py / hent_nfi_ordninger.py

                 slaa_sammen_hoveddatasett.py → tildelinger_samlet_2021_2026.csv
                 lag_v4_data.py               → ordninger_v4.js
                 ci/kontroller_v4.py          → vakt før publisering
```

`lag_v4_data.py` leser **`tildelinger_samlet_2021_2026.csv`**, ikke `tildelinger_alle.csv`.
Hoppes `slaa_sammen_hoveddatasett.py` over, bygges siden på forrige kjørings tildelinger:
nøkkeltallene (fra `ordninger_utvidet.json`) blir ferske, mens mottakertabeller, fylker,
beløpsfordeling og konkurransetall står stille under dagens `GENERERT`-dato. Feilen er stille
— derfor sjekker `ci/kontroller_v4.py` filens skrivetidspunkt når `CI` er satt.

## Fallgruver

- **Sammenlignbarhet:** tilskudd.no-tallene gjelder alltid siste rapporterte budsjettår, mens
  NKF/FLB-rådata spenner 2021–2031. NKF/FLB filtreres derfor til siste år med faktiske
  tildelinger før mottakere/beløp/typisk beregnes. Fylkesfordelingen bruker bevisst hele
  perioden — rikere bilde for små ordninger.
- **Fremtidige budsjettår (> 2026) filtreres bort:** det er ubehandlede søknader, ikke
  tildelinger.
- **NFI har ingen avslagsdata** → innvilgelsesgrad skal alltid være `null` for NFI-ordninger.
- **Innvilgelsesgrad for NKF/FLB krever avslags-eksporten.** Filen med kun innvilgede kan ikke
  gi grad. Konkurransetallet undervurderes uansett, siden omsøkt beløp for avslåtte mangler.
- **`fristtype` speiler tilskudd.no sin `deadlineType`:** `DEADLINE`, `NO_DEADLINE`, `UNKNOWN`
  eller `null` — aldri `CONTINUOUS`. `index.html` sjekket lenge mot `CONTINUOUS`, som skjulte
  15 ordninger uten fast frist bak default-filteret. `ci/kontroller_v4.py` feiler nå på ukjente
  verdier. `NO_DEADLINE` betyr «ingen frist registrert», ikke «løpende» — ikke påstå mer enn
  kilden sier.
- **Frister råtner:** DT-ordninger har konkrete datoer, ingen regel om gjentakelse. `erApen()`
  i `index.html` beholder derfor ordninger med frist utløpt siste 12 måneder, tydelig merket.
- **Norske datoer må til ISO:** NFI-frister kommer som «12. august 2026»; `_norsk_til_iso()`
  konverterer.
- **Dubletter:** sju ordninger finnes både som `DT-` og `KUL-`, med ulik innvilgelsesgrad fordi
  tallene er regnet på ulike perioder. `fjern_dubletter()` beholder DT-raden.
- **«Foreldreløse» ordninger** (frist/innhold, men ingen vedtakshistorikk) må legges til
  eksplisitt, ellers er helt nye ordninger usynlige akkurat når de er søkbare.
- **Statens kunstnerstipend er bevisst utelatt** (individstipend, ikke organisasjonstilskudd).
  `soker_type=Person` filtreres også bort. Ikke «fiks» dette.
- **XSS:** all ordningstekst går gjennom `escHTML`/`escAttr` før `innerHTML`. Behold mønsteret.
- **2021–2023-dataene** kommer fra Kulturdirektoratets gamle plattform, nedlagt 2026. De kan
  ikke re-hentes — behandle filene som uerstattelige.

## Konvensjoner

- Norsk i kode, kommentarer og UI. Kommentarer forklarer *hvorfor*, ikke *hva*.
- UI-endringer skjer i `index.html` (én fil, vanilla JS, ingen moduler). Test ved å åpne
  filen direkte i nettleseren.
- Nye datakilder får en egen `bygg_*_rader()` i `lag_v4_data.py` som produserer komplette rader
  med alle feltene (`null` der data mangler) — UI-et er felt-drevet og tåler `null`.
- Tallene på siden er historikk, ikke løfter. Nye visninger skal ha samme forbehold som de
  eksisterende.
