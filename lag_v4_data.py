#!/usr/bin/env python3
"""
Generer ordninger_v4.js for tilskuddskompasset_v4.html.
Kombinerer ordninger_utvidet.json med bulk-tildelingsdata for å berike
hver ordning med:
  - Faktiske mottakere (topp 8, med tiltak-beskrivelse)
  - Geografisk fordeling (fylker)
  - Beløpsfordeling (min, median, max, kvartiler)
  - Konkurranse-indeks (omsøkt vs. tildelt)

Kjøring: python lag_v4_data.py
"""

import csv
import json
import statistics
from collections import defaultdict
from datetime import date
from pathlib import Path

import pandas as pd


def les_tildelinger() -> list[dict]:
    """Les samlet tildelingsfil (tilskudd.no + NKF/FLB). Filtrerer bort budsjettår > 2026."""
    fil = Path("tilskudd_data/tildelinger_samlet_2021_2026.csv")
    if not fil.exists():
        print("FEIL: tildelinger_samlet_2021_2026.csv finnes ikke!")
        raise SystemExit(1)
    with fil.open("r", encoding="utf-8-sig") as f:
        rader = list(csv.DictReader(f, delimiter=";"))
    # Filtrer bort fremtidige år (ubehandlede søknader)
    filtrert = []
    for r in rader:
        try:
            aar = float(r.get("budsjettar") or 0)
        except (ValueError, TypeError):
            aar = 0
        if aar <= 2026:
            filtrert.append(r)
    print(f"  Filtrert bort {len(rader) - len(filtrert)} rader med budsjettår > 2026")
    return filtrert


# Mapping fra mottaker_sektor til forenklet UI-gruppe
SEKTOR_TIL_GRUPPE = {
    "Ideelle organisasjoner": "Frivillig/ideell",
    "Private produsentorienterte organisasjoner uten profittformål": "Frivillig/ideell",
    "Private aksjeselskaper mv.": "Privat virksomhet",
    "Personlig næringsdrivende": "Privat virksomhet",
    "Personlige foretak": "Privat virksomhet",
    "Øvrige finansielle foretak unntatt forsikring": "Privat virksomhet",
    "Kommuneforvaltningen": "Offentlig",
    "Kommunalt eide aksjeselskaper mv.": "Offentlig",
    "Kommunale foretak med ubegrenset ansvar": "Offentlig",
    "Statsforvaltningen": "Offentlig",
    "Statlig eide aksjeselskaper mv.": "Offentlig",
    "Fylkeskommuner": "Offentlig",
}

# Mapping fra mottakerkategorier (tilskudd.no) til samme grupper
KATEGORI_TIL_GRUPPE = {
    "Ideelle og frivillige organisasjoner": "Frivillig/ideell",
    "Private foretak": "Privat virksomhet",
    "Personlig næringsdrivende": "Privat virksomhet",
    "Finansielle foretak": "Privat virksomhet",
    "Kommuner": "Offentlig",
    "Kommunale foretak": "Offentlig",
    "Fylkeskommuner": "Offentlig",
    "Statlige foretak": "Offentlig",
    "Statsforvaltningen": "Offentlig",
}


def aggreger_per_ordning(tildelinger: list[dict]) -> dict:
    """Aggreger tildelingsdata per ordning."""
    ordninger = defaultdict(lambda: {
        "mottakere": [],
        "fylker": defaultdict(int),
        "beloep_tildelt": [],
        "beloep_soekt": [],
        "kommuner": defaultdict(int),
        "avkorting_ratioer": [],  # tildelt/soekt for godkjente der begge > 0
        "icnpo": defaultdict(int),  # teller forekomster per ICNPO-kategori
        "type_tilskudd": defaultdict(int),  # teller forekomster per type
        "sektorer": defaultdict(int),  # teller forekomster per mottaker-sektor
    })

    for r in tildelinger:
        oid = r.get("tilskudds_id", "")
        if not oid:
            continue

        tildelt = float(r.get("tildelt_belop") or 0)
        soekt = float(r.get("soknadsbelop") or 0)

        o = ordninger[oid]

        if tildelt > 0:
            o["mottakere"].append({
                "navn": r.get("mottakernavn", ""),
                "orgnr": r.get("mottaker_organisasjonsnummer", ""),
                "tildelt": int(tildelt),
                "soekt": int(soekt) if soekt else None,
                "tiltak": (r.get("tiltak") or "")[:100],
                "fylke": r.get("fylke", ""),
                "kommune": r.get("kommune", ""),
                "sektor": r.get("mottaker_sektor", ""),
            })
            o["beloep_tildelt"].append(tildelt)

            # Avkorting: hvor mye av omsøkt beløp fikk de som ble innvilget?
            if soekt > 0:
                o["avkorting_ratioer"].append(tildelt / soekt)

            fylke = r.get("fylke", "")
            if fylke:
                o["fylker"][fylke] += 1
            kommune = r.get("kommune", "")
            if kommune:
                o["kommuner"][kommune] += 1

        if soekt > 0:
            o["beloep_soekt"].append(soekt)

        # ICNPO-kategori (telles uavhengig av tildelt/søkt)
        icnpo = r.get("icnpo_kategori", "")
        if icnpo:
            o["icnpo"][icnpo] += 1

        # Type tilskudd (Driftsmidler/Prosjektmidler)
        tt = r.get("type_tilskudd", "")
        if tt and tt in ("Driftsmidler", "Prosjektmidler"):
            o["type_tilskudd"][tt] += 1

        # Sektor (kun for de som fikk tildelt)
        if tildelt > 0:
            sektor = r.get("mottaker_sektor", "")
            gruppe = SEKTOR_TIL_GRUPPE.get(sektor)
            if gruppe:
                o["sektorer"][gruppe] += 1

    return ordninger


def beloepfordeling(beloep: list[float]) -> dict | None:
    """Beregn kvartiler og spredning."""
    if not beloep:
        return None
    sortert = sorted(beloep)
    n = len(sortert)
    return {
        "min": int(sortert[0]),
        "q1": int(sortert[n // 4]) if n >= 4 else int(sortert[0]),
        "median": int(statistics.median(sortert)),
        "q3": int(sortert[3 * n // 4]) if n >= 4 else int(sortert[-1]),
        "max": int(sortert[-1]),
        "snitt": int(statistics.mean(sortert)),
    }


def bygg_nkf_flb_rader() -> list[dict]:
    """Bygg v4-rader for Kulturråd/Fond for lyd og bilde-ordninger.

    Disse ordningene finnes ikke i ordninger_utvidet.json (de skrapes ikke
    fra tilskudd.no), så de mangler beskrivende felt (formål, hvem kan søke,
    frister osv.) - kun statistikk beregnet fra egne data: innvilgelsesgrad
    (fra nkf_flb_innvilgelsesgrad_per_ordning.csv, som inkluderer avslag) og
    mottaker-/beløpsfordeling (fra nkf_flb_organisasjoner_2021_2026.csv, som
    kun har de innvilgede tildelingene).
    """
    grad_fil = Path("tilskudd_data/nkf_flb_innvilgelsesgrad_per_ordning.csv")
    innvilget_fil = Path("tilskudd_data/nkf_flb_organisasjoner_2021_2026.csv")
    innhold_fil = Path("tilskudd_data/kulturdirektoratet_innhold.json")
    if not grad_fil.exists() or not innvilget_fil.exists():
        print("Hopper over NKF/FLB: filer ikke funnet (kjør bygg_nkf_flb_v2.py først)")
        return []

    # Skrapt innhold fra kulturdirektoratet.no (hent_kulturdirektoratet_innhold.py),
    # matchet på ordningsnavn. De 4 nye FLB-kodene har ikke noe navn i vårt
    # datasett (de dukket opp etter at FLB omstrukturerte ordningene sine i
    # 2024), så de mappes manuelt til riktig side ut fra kategori.
    innhold_per_navn = {}
    if innhold_fil.exists():
        for d in json.loads(innhold_fil.read_text(encoding="utf-8")):
            innhold_per_navn[d["tittel"].strip().lower()] = d
    KODE_TIL_FLB_SIDE = {
        "flb-audio": "fond for lyd og bilde musikk",
        "flb-cine": "fond for lyd og bilde film",
        "flb-live": "fond for lyd og bilde scene",
        "flb-media": "fond for lyd og bilde markedsføring",
    }

    grad_df = pd.read_csv(grad_fil, sep=";", encoding="utf-8-sig")
    inn = pd.read_csv(innvilget_fil, sep=";", encoding="utf-8-sig", low_memory=False)
    inn["budsjettar"] = pd.to_numeric(inn["budsjettar"], errors="coerce")
    # Filtrer bort fremtidige år (ubehandlede søknader)
    inn = inn[inn["budsjettar"] <= 2026]

    rader = []
    for _, g in grad_df.iterrows():
        oid = g["tilskudds_id"]
        sub = inn[inn["tilskudds_id"] == oid]

        # Siste rapporterte budsjettår for DENNE ordningen - DT-ordningene fra
        # tilskudd.no sin "totalRecipients"/"totalGrantedAmount" er alltid ett
        # enkelt år ("siste rapporterte budsjettår", jf. footer-teksten), mens
        # nkf_flb-dataene spenner over 2021-2031. Uten å filtrere til siste år
        # her ville f.eks. "Mottakere i år" faktisk telle unike mottakere over
        # 10 år for disse ordningene - ikke sammenlignbart med DT-tallene.
        # Velg siste år som faktisk har tildelinger (ikke bare søknader under behandling)
        sub_med_tildelt = sub[sub["tildelt_belop"].notna() & (sub["tildelt_belop"] > 0)]
        aar_tilgjengelig = sub_med_tildelt["budsjettar"].dropna()
        siste_aar = aar_tilgjengelig.max() if len(aar_tilgjengelig) else None
        sub_siste = sub[sub["budsjettar"] == siste_aar] if siste_aar is not None else sub.iloc[0:0]

        # Topp 8 mottakere (kun siste år - jf. "topp mottakere siste år" i UI)
        sortert = sub_siste.sort_values("tildelt_belop", ascending=False).head(8)
        topp_mottakere = [{
            "n": r["mottakernavn"],
            "t": int(r["tildelt_belop"]) if pd.notna(r["tildelt_belop"]) else None,
            "s": int(r["soknadsbelop"]) if pd.notna(r["soknadsbelop"]) else None,
            "tiltak": str(r["tiltak"])[:100] if pd.notna(r["tiltak"]) else "",
            "f": r["fylke"] if pd.notna(r["fylke"]) else "",
        } for _, r in sortert.iterrows()]

        # Fylker - geografisk fordeling, ikke påstått å være "siste år" i UI,
        # så vi bruker hele perioden for et rikere bilde på små ordninger
        fylker = dict(sub["fylke"].dropna().value_counts().items()) if "fylke" in sub else {}

        # Beløpsfordeling (siste år, samme begrunnelse som topp_mottakere)
        belop_siste = sub_siste["tildelt_belop"].dropna()
        belop_siste = belop_siste[belop_siste > 0].tolist()
        fordeling = beloepfordeling(belop_siste)

        # Konkurranse: total søkt vs. tildelt i siste år (vi har ikke omsøkt
        # beløp for de avslåtte i denne filen, kun de innvilgede)
        soekt_siste = sub_siste["soknadsbelop"].dropna()
        soekt_siste = soekt_siste[soekt_siste > 0]
        konkurranse = None
        if len(soekt_siste) and belop_siste:
            total_soekt, total_tildelt_siste = soekt_siste.sum(), sum(belop_siste)
            if total_tildelt_siste > 0:
                konkurranse = round(total_soekt / total_tildelt_siste, 2)

        # Avkorting: snitt-andel av omsøkt beløp de innvilgede faktisk fikk
        avkorting_nkf = None
        begge = sub_siste[["tildelt_belop", "soknadsbelop"]].dropna()
        begge = begge[(begge["tildelt_belop"] > 0) & (begge["soknadsbelop"] > 0)]
        if len(begge):
            ratioer = begge["tildelt_belop"] / begge["soknadsbelop"]
            avkorting_nkf = round(ratioer.mean(), 3)

        # Tidsserie per budsjettår (hele perioden - dette ER tidsserien)
        ts = sub.dropna(subset=["budsjettar"]).groupby("budsjettar")
        ts_tildelt = [{"x": str(int(aar)), "y": int(d["tildelt_belop"].sum())} for aar, d in ts]
        ts_mottakere = [{"x": str(int(aar)), "y": d["mottakernavn"].nunique()} for aar, d in ts]

        mottakere_n = sub_siste["mottaker_organisasjonsnummer"].nunique()
        total_tildelt = sub_siste["tildelt_belop"].sum()
        typisk = round(total_tildelt / mottakere_n) if mottakere_n else None

        navn_key = KODE_TIL_FLB_SIDE.get(str(oid).strip().lower(), g["tilskuddsordning"].strip().lower())
        innhold = innhold_per_navn.get(navn_key)

        # Typer fra tildelingsdata (type_tilskudd-kolonnen)
        sub_typer = sub_siste["type_tilskudd"].dropna() if "type_tilskudd" in sub.columns else pd.Series(dtype=str)
        typer_counts = sub_typer[sub_typer.isin(["Driftsmidler", "Prosjektmidler"])].value_counts()
        typer_nkf = sorted(typer_counts.index.tolist()) if len(typer_counts) else []

        # Orgform fra mottaker_sektor (siste år med tildelinger)
        orgform_nkf = set()
        if "mottaker_sektor" in sub_siste.columns:
            for sek in sub_siste["mottaker_sektor"].dropna().unique():
                grp = SEKTOR_TIL_GRUPPE.get(sek)
                if grp:
                    orgform_nkf.add(grp)
        orgform_nkf = sorted(orgform_nkf)

        rader.append({
            "id": oid,
            "tittel": g["tilskuddsordning"],
            "beskrivelse": None,
            "forvalter": g["tilskuddsforvalter"],
            "forvalter_kort": g["tilskuddsforvalter"],
            "dep": "Kultur- og likestillingsdepartementet",
            "typer": typer_nkf,
            "mottakerkategorier": [],
            "belop": None,
            "frist": (innhold["frister"][0] if innhold and innhold.get("frister") else None),
            "frister": (innhold.get("frister") if innhold else []) or [],
            "fristtype": None,
            "krever_frivillig": None,
            "grad": g["grad"] if pd.notna(g["grad"]) else None,
            "soekere": None,
            "mottakere_n": mottakere_n or None,
            "soknader": int(g["totalApplications"]),
            "innvilget": int(g["grantedApplications"]),
            "total_soekt": None,
            "total_tildelt": int(total_tildelt) if total_tildelt else None,
            "typisk_tildeling": typisk,
            "ts_tildelt": ts_tildelt,
            "ts_mottakere": ts_mottakere,
            "formaal": (innhold.get("formaal") or None) if innhold else None,
            "hvem": (innhold.get("hvem") or None) if innhold else None,
            "hva": (innhold.get("hva") or None) if innhold else None,
            "kriterier": (innhold.get("kriterier") or None) if innhold else None,
            "rapportering": (innhold.get("rapportering") or None) if innhold else None,
            "hvordan": (innhold.get("hvordan") or None) if innhold else None,
            "soknadslenke": innhold["url"] if innhold else None,
            "regelverk": (innhold.get("regelverk") or None) if innhold else None,
            "topp_mottakere": topp_mottakere,
            "fylker": fylker,
            "fordeling": fordeling,
            "konkurranse": konkurranse,
            "avkorting": avkorting_nkf,
            "icnpo": ["Kunst og kultur"],
            "orgform": orgform_nkf,
        })

    med_innhold = sum(1 for r in rader if r["formaal"])
    print(f"Bygget {len(rader)} NKF/FLB-rader (innvilgelsesgrad fra avslagsdata), {med_innhold} med skrapt innhold fra kulturdirektoratet.no")

    # "Foreldreløse" ordninger: finnes på kulturdirektoratet.no, men har ingen
    # tildelinger/avslag i vedtaksdataene våre ennå (helt nye ordninger, eller
    # ordninger der ingen søknader er avgjort siste runde). Uten dette steget
    # er de usynlige for oss selv om de er åpne for søknad akkurat nå.
    dekkede_navn = {g.strip().lower() for g in grad_df["tilskuddsordning"]}
    nye = 0
    for d in innhold_per_navn.values():
        if d["tittel"].strip().lower() in dekkede_navn:
            continue
        if d["tittel"].strip().lower() == "statens kunstnerstipend":
            continue  # individuelle kunstnerstipend, ikke organisasjonstilskudd - utelatt som avtalt
        rader.append({
            "id": "KD-" + d["slug"],
            "tittel": d["tittel"],
            "beskrivelse": None,
            "forvalter": d.get("forvalter") or "Kulturdirektoratet",
            "forvalter_kort": d.get("forvalter") or "Kulturdirektoratet",
            "dep": "Kultur- og likestillingsdepartementet",
            "typer": [], "mottakerkategorier": [], "belop": None,
            "frist": d["frister"][0] if d.get("frister") else None,
            "frister": d.get("frister") or [],
            "fristtype": None, "krever_frivillig": None,
            "grad": None, "soekere": None, "mottakere_n": None,
            "soknader": None, "innvilget": None,
            "total_soekt": None, "total_tildelt": None, "typisk_tildeling": None,
            "ts_tildelt": [], "ts_mottakere": [],
            "formaal": d.get("formaal") or None,
            "hvem": d.get("hvem") or None,
            "hva": d.get("hva") or None,
            "kriterier": d.get("kriterier") or None,
            "rapportering": d.get("rapportering") or None,
            "hvordan": d.get("hvordan") or None,
            "soknadslenke": d["url"],
            "regelverk": d.get("regelverk") or None,
            "topp_mottakere": [], "fylker": {}, "fordeling": None, "konkurranse": None, "avkorting": None, "icnpo": ["Kunst og kultur"], "orgform": [],
        })
        nye += 1
    print(f"La til {nye} ordninger uten tildelingshistorikk ennå (kun innhold/frist fra kulturdirektoratet.no)")
    return rader


def lag_v4_data():
    # Les ordninger_utvidet
    ordninger_fil = Path("tilskudd_data/ordninger_utvidet.json")
    ordninger = json.loads(ordninger_fil.read_text(encoding="utf-8"))
    print(f"Lest {len(ordninger)} ordninger fra ordninger_utvidet.json")

    # Les og aggreger tildelinger
    tildelinger = les_tildelinger()
    print(f"Lest {len(tildelinger)} tildelinger fra tildelinger_samlet_2021_2026.csv")
    aggregert = aggreger_per_ordning(tildelinger)
    print(f"Aggregert til {len(aggregert)} ordninger")

    # Bygg v4-data
    rader = []
    for o in ordninger:
        oid = o.get("ordning_id", "")
        opps = o.get("oppsummering") or {}
        ts = o.get("tidsserie", {})
        agg = aggregert.get(oid)

        # Beregn innvilgelsesgrad
        grad = None
        if opps.get("totalApplications") and opps.get("grantedApplications"):
            grad = round(opps["grantedApplications"] / opps["totalApplications"], 3)

        # Typisk tildeling
        typisk = None
        if opps.get("totalGrantedAmount") and opps.get("totalRecipients"):
            typisk = round(opps["totalGrantedAmount"] / opps["totalRecipients"])

        # Beriket data fra bulk
        topp_mottakere = []
        fylker = {}
        fordeling = None
        konkurranse = None

        if agg:
            # Topp 8 mottakere sortert etter tildelt beløp
            sortert = sorted(agg["mottakere"], key=lambda x: -x["tildelt"])[:8]
            topp_mottakere = [{
                "n": m["navn"],
                "t": m["tildelt"],
                "s": m["soekt"],
                "tiltak": m["tiltak"],
                "f": m["fylke"],
            } for m in sortert]

            # Fylker (sortert etter antall)
            fylker = dict(sorted(agg["fylker"].items(), key=lambda x: -x[1]))

            # Beløpsfordeling
            fordeling = beloepfordeling(agg["beloep_tildelt"])

            # Konkurranse: total søkt vs. tildelt
            if agg["beloep_soekt"]:
                total_soekt = sum(agg["beloep_soekt"])
                total_tildelt = sum(agg["beloep_tildelt"])
                if total_soekt > 0:
                    konkurranse = round(total_soekt / total_tildelt, 2) if total_tildelt > 0 else None

        # Avkorting: snitt-andel av omsøkt beløp de innvilgede faktisk fikk
        avkorting = None
        if agg and agg["avkorting_ratioer"]:
            snitt = statistics.mean(agg["avkorting_ratioer"])
            avkorting = round(snitt, 3)

        # ICNPO: vanligste kategorier for denne ordningen (topp 3)
        icnpo_list = []
        if agg and agg["icnpo"]:
            icnpo_list = [k for k, _ in sorted(agg["icnpo"].items(), key=lambda x: -x[1])[:3]]

        # Orgform: hvilke organisasjonstyper mottar tilskudd (fra mottakerkategorier + sektorer)
        orgform_set = set()
        for kat in o.get("mottakerkategorier", []):
            g = KATEGORI_TIL_GRUPPE.get(kat)
            if g:
                orgform_set.add(g)
        if agg and agg["sektorer"]:
            orgform_set.update(agg["sektorer"].keys())
        orgform = sorted(orgform_set)

        rader.append({
            "id": oid,
            "tittel": o.get("tittel"),
            "beskrivelse": o.get("beskrivelse"),
            "forvalter": o.get("forvalter_navn"),
            "forvalter_kort": o.get("forvalter_kortnavn"),
            "dep": o.get("eier_navn"),
            "typer": o.get("tilskuddstyper", []) or (sorted(agg["type_tilskudd"].keys()) if agg and agg["type_tilskudd"] else []),
            "mottakerkategorier": o.get("mottakerkategorier", []),
            "belop": o.get("belop"),
            "frist": o.get("frist"),
            "frister": o.get("frister", []),
            "fristtype": o.get("fristtype"),
            "krever_frivillig": o.get("krever_frivilligregisteret"),
            # Statistikk
            "grad": grad,
            "soekere": opps.get("totalApplicants"),
            "mottakere_n": opps.get("totalRecipients"),
            "soknader": opps.get("totalApplications"),
            "innvilget": opps.get("grantedApplications"),
            "total_soekt": opps.get("totalApplicationAmount"),
            "total_tildelt": opps.get("totalGrantedAmount"),
            "typisk_tildeling": typisk,
            # Tidsserie
            "ts_tildelt": ts.get("tildelt_serie", []),
            "ts_mottakere": ts.get("mottakere_serie", []),
            # Innhold
            "formaal": o.get("maal_og_formaal"),
            "hvem": o.get("hvem_kan_soeke"),
            "hva": o.get("hva_kan_brukes_til"),
            "kriterier": o.get("andre_kriterier"),
            "rapportering": o.get("rapporteringskrav"),
            "hvordan": o.get("hvordan_soeke"),
            # Lenker
            "soknadslenke": o.get("soknadslenke"),
            "regelverk": o.get("regelverk_lenke"),
            # NYTT i v4: beriket fra bulk-data
            "topp_mottakere": topp_mottakere,
            "fylker": fylker,
            "fordeling": fordeling,
            "konkurranse": konkurranse,
            "avkorting": avkorting,
            "icnpo": icnpo_list,
            "orgform": orgform,
        })

    # NKF/FLB-ordninger (Kulturråd/Fond for lyd og bilde) - egen kilde, ikke i ordninger_utvidet.json
    rader.extend(bygg_nkf_flb_rader())

    # Skriv ut
    ut = Path("ordninger_v4.js")
    ut.write_text(
        "// Generert fra ordninger_utvidet.json + tildelinger_samlet_2021_2026.csv\n"
        f'const GENERERT = "{date.today().isoformat()}";\n'
        "const ORDNINGER = " + json.dumps(rader, ensure_ascii=False) + ";\n",
        encoding="utf-8",
    )
    print(f"\nSkrev {ut} ({len(rader)} ordninger, {ut.stat().st_size / 1024:.0f} KB)")

    # Statistikk
    med_mottakere = sum(1 for r in rader if r["topp_mottakere"])
    med_fylker = sum(1 for r in rader if r["fylker"])
    med_fordeling = sum(1 for r in rader if r["fordeling"])
    print(f"  Med mottaker-eksempler: {med_mottakere}")
    print(f"  Med fylkesfordeling: {med_fylker}")
    print(f"  Med beløpsfordeling: {med_fordeling}")


if __name__ == "__main__":
    lag_v4_data()
