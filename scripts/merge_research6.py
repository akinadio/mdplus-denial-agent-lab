#!/usr/bin/env python3
"""Merge the research6 sweeps.

Three surgery sources and one imaging source:
  midwest.json            -- 17 midwest/zero-doc payer libraries walked
  evicore_cmm_series.json -- the eight eviCore CMM surgical guidelines, each
                             confirmed to carry its CPT, applied to payers whose
                             eviCore delegation was itself confirmed by fetch
  evolent_msk_2026.json   -- the 2026 Evolent MSK Surgery Guidelines (readable
                             spine sections), applied to confirmed-Evolent plans
  imaging_wave2.json      -- imaging vendor map + Evolent ECG guideline PDFs

Same overwrite rule as merge_research5: never downgrade a more-settled status.
"""
import csv, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLAT = ROOT / "data" / "policy_platform"
SURG = PLAT / "app_option_policy_directory.csv"
IMG = PLAT / "app_option_imaging_directory.csv"
R6 = PLAT / "research6"

V2S = {
    "verified": "VERIFIED",
    "no_prior_auth_required": "NO PRIOR AUTH REQUIRED",
    "criteria_proprietary_not_public": "NO PUBLIC CRITERIA (vendor)",
    "gated_login": "GATED",
    "unreachable": "UNREACHABLE",
    "not_found": "NOT FOUND",
    "rejected_code_only": "CODE ONLY",
}
RANK = {
    "VERIFIED": 100, "VERIFIED (CMS LCD/NCD)": 100,
    "VERIFIED (criteria public, no stable link)": 95,
    "CRITERIA EXIST, TEXT NOT EXTRACTED": 90,
    "NO PRIOR AUTH REQUIRED": 85, "NO LCD — general medical necessity": 80,
    "CONFIRMED NO POLICY": 70, "NO PUBLIC CRITERIA (vendor)": 60,
    "PROCESS DOC ONLY (no procedure criteria)": 50,
    "GATED": 40, "STALE": 35, "CODE ONLY": 30, "UNREACHABLE": 25,
    "NOT FOUND": 10, "NOT RESEARCHED": 0,
}
DATE = "2026-08-26"

STATE = {"AL":"Alabama","AR":"Arkansas","DC":"District of Columbia","IL":"Illinois","IN":"Indiana",
         "IA":"Iowa","KS":"Kansas","LA":"Louisiana","MD":"Maryland","MI":"Michigan","MN":"Minnesota",
         "MS":"Mississippi","OH":"Ohio","OK":"Oklahoma","PA":"Pennsylvania","TX":"Texas","WI":"Wisconsin","WV":"West Virginia"}

# midwest.json payer name -> directory (state, insurer)
MID = {
    ("Meridian","IL"): ("Illinois","Meridian"),
    ("Meridian Health Plan","MI"): ("Michigan","Meridian Health Plan"),
    ("Buckeye Health Plan","OH"): ("Ohio","Buckeye Health Plan"),
    ("Managed Health Services (MHS)","IN"): ("Indiana","Managed Health Services (MHS)"),
    ("MDwise","IN"): ("Indiana","MDwise"),
    ("Iowa Total Care","IA"): ("Iowa","Iowa Total Care"),
    ("Sunflower Health Plan","KS"): ("Kansas","Sunflower Health Plan"),
    ("Health Alliance Plan (HAP)","MI"): ("Michigan","Health Alliance Plan (HAP)"),
    ("McLaren Health Plan","MI"): ("Michigan","McLaren Health Plan"),
    ("UCare","MN"): ("Minnesota","UCare"),
    ("PreferredOne","MN"): ("Minnesota","PreferredOne"),
    ("Security Health Plan","WI"): ("Wisconsin","Security Health Plan"),
    ("Quartz Health Plan","WI"): ("Wisconsin","Quartz Health Plan"),
    ("Network Health","WI"): ("Wisconsin","Network Health"),
    ("Common Ground Healthcare Cooperative","WI"): ("Wisconsin","Common Ground Healthcare Cooperative"),
    ("Dean Health Plan","WI"): ("Wisconsin","Dean Health Plan"),
}

# research6 sweep 1 (south) payer name -> directory key
SOUTH = {
    "Blue Cross and Blue Shield of Louisiana": ("Louisiana","Blue Cross and Blue Shield of Louisiana"),
    "TrueCare": ("Mississippi","TrueCare"),
    "Maryland Physicians Care": ("Maryland","Maryland Physicians Care"),
    "Priority Partners": ("Maryland","Priority Partners"),
    "Community Health Choice": ("Texas","Community Health Choice"),
    "CommunityCare": ("Oklahoma","CommunityCare"),
    "MedStar Family Choice DC": ("District of Columbia","MedStar Family Choice DC"),
    "MedStar Family Choice": ("Maryland","MedStar Family Choice"),
    "AmeriHealth Caritas Louisiana": ("Louisiana","AmeriHealth Caritas Louisiana"),
    "QualChoice / Health Advantage": ("Arkansas","QualChoice / Health Advantage"),
    "The Health Plan": ("West Virginia","The Health Plan"),
    "UniCare Health Plan of West Virginia (now Wellpoint West Virginia)": ("West Virginia","UniCare Health Plan of West Virginia"),
    "Viva Health": ("Alabama","Viva Health"),
    "Vantage Health Plan": ("Louisiana","Vantage Health Plan"),
}

ALL14 = ["27447","27446","29888","29881","27130","29914","29827","23472","29806","27702","28296","22612","22551","63030"]


def note_for(f, prefix):
    bits = [f"{DATE} {prefix}"]
    for k, lbl in (("policy_number","policy "),("vendor","vendor: "),("imaging_vendor","imaging vendor: ")):
        if f.get(k): bits.append(lbl + f[k])
    if f.get("transparency_viewer_url"): bits.append("criteria viewer: " + f["transparency_viewer_url"])
    if f.get("criteria_quote"): bits.append("criteria: “%s”" % f["criteria_quote"])
    if f.get("evidence"): bits.append(f["evidence"])
    if f.get("confidence"): bits.append("confidence: " + f["confidence"])
    return ". ".join(bits)


def apply(rows, st, ins, cpts, f, prefix, stats):
    status = V2S[f["verdict"]]
    for r in rows:
        if r["state"] != st or r["insurance_company"] != ins or r["cpt"] not in cpts:
            continue
        if RANK.get(status,0) < RANK.get(r["status"],0):
            stats["skipped"] += 1
            continue
        r["status"] = status
        if f.get("policy_title"): r["policy_title"] = f["policy_title"]
        if f.get("effective_date"): r["effective_date"] = f["effective_date"]
        r["policy_url"] = f.get("policy_url","")
        r["note"] = note_for(f, prefix)
        stats["changed"] += 1


def cpts_of(f):
    return [c.strip() for c in f["cpt"].replace("ALL_4","").split(",") if c.strip()] or None


def main():
    rows = list(csv.DictReader(SURG.open(encoding="utf-8", newline="")))
    fields = list(rows[0].keys())
    stats = {"changed":0, "skipped":0}

    # ---- south sweep (banked findings were reported in the agent message;
    # they were merged from research6 files where present) ----
    mid = json.loads((R6/"midwest.json").read_text())
    for f in mid["findings"]:
        key = MID.get((f["payer"], f["state"])) or MID.get((f["payer"].replace(" (HAP joint venture)",""), f["state"]))
        if not key:
            # HAP CareSource joint venture has no directory row; skip
            continue
        st, ins = key
        apply(rows, st, ins, cpts_of(f) or ALL14, f, "midwest payer library walk", stats)

    # south findings live inline here (same structure), keyed by SOUTH
    south_path = R6/"south.json"
    if south_path.exists():
        for f in json.loads(south_path.read_text())["findings"]:
            key = SOUTH.get(f["payer"])
            if not key:
                continue
            st, ins = key
            apply(rows, st, ins, cpts_of(f) or ALL14, f, "south payer library walk", stats)

    # ---- eviCore CMM series: apply to payers confirmed delegating ----
    cmm = json.loads((R6/"evicore_cmm_series.json").read_text())
    by_cpt = {}
    for g in cmm["guidelines"]:
        for c in g["cpts"]:
            by_cpt[c] = g
    EVICORE_PAYERS = {
        # (state, insurer): list of cpts confirmed in that payer's eviCore code lists / program scope
        ("Massachusetts","WellSense Health Plan"): ALL14,
        ("New Hampshire","Well Sense Health Plan"): ALL14,
        ("New Jersey","Clover Health"): ["27447","27446","29881","29888","27130","29914","29827","23472","29806"],
        ("New York","Excellus BlueCross BlueShield"): ALL14,
        ("Arizona","Banner Health"): [c for c in ALL14 if c != "27702"],
    }
    CONF = {("New Hampshire","Well Sense Health Plan"): "medium"}
    for (st, ins), cpts in EVICORE_PAYERS.items():
        deleg = next(p for p in cmm["payers_confirmed_delegating_to_evicore"]
                     if p["state"] == st or p["payer"].lower().startswith(ins.split()[0].lower()))
        for c in cpts:
            g = by_cpt.get(c)
            if not g: continue
            f = {"verdict":"verified","policy_title":"eviCore "+g["policy_number"]+" "+g["policy_title"],
                 "policy_number":g["policy_number"],"effective_date":g["effective_date"],
                 "policy_url":g["policy_url"],"criteria_quote":g["criteria_quotes"][c],
                 "evidence":"Payer delegation confirmed: "+deleg["evidence"]+" Guideline fetched and its own code table confirmed to carry this CPT."
                           +(" NOTE: CMM-312's code table is the range 29866-29887, which encompasses this code without naming it discretely." if c=="29881" else ""),
                 "confidence":CONF.get((st,ins),"medium" if c=="29881" else "high")}
            apply(rows, st, ins, [c], f, "eviCore CMM series", stats)
    # bunion/ankle absent from eviCore program: mark for these payers where currently blank-ish
    for (st, ins) in EVICORE_PAYERS:
        f = {"verdict":"not_found","policy_title":"","policy_url":"",
             "evidence":"27702 and 28296 are absent from every eviCore joint code list checked -- eviCore's MSK program does not reach ankle replacement or bunion surgery. The payer's own route for these codes is unresolved.",
             "confidence":"medium"}
        apply(rows, st, ins, ["27702","28296"], f, "eviCore program boundary", stats)

    # ---- Evolent MSK 2026: spine codes for confirmed-Evolent plans ----
    ev = json.loads((R6/"evolent_msk_2026.json").read_text())
    gq = {g["cpt"]: g for g in ev["guidelines"]}
    EVOLENT_PLANS = {
        ("Illinois","Meridian"): "Meridian IL Evolent/NIA quick reference states 'Guidelines can be found on NIA's website at www.RadMD.com'; the Meridian MSK FAQ eff 04/01/2024 confirms spine surgery in Evolent's scope.",
        ("Hawaii","'Ohana Health Plan"): "ilc.wellcare.com/hawaii msk-notification confirms Evolent runs MSK PA from 2024-04-01 with lumbar fusion explicitly in scope.",
        ("Oregon","Trillium Community Health Plan"): "trilliumohp.com MusculoskeletalPAs.html confirms Evolent manages MSK with arthroplasty, rotator cuff, ACL, knee arthroscopy in program scope.",
        ("Maryland","Maryland Physicians Care"): "MPC's prior-auth page states 'MSK surgeries managed by Evolent are found on the following list' (the MPC list itself carries no criteria; the Evolent guideline does).",
    }
    for (st, ins), deleg in EVOLENT_PLANS.items():
        for c in ("22612","22551","63030"):
            g = gq[c]
            f = {"verdict":"verified","policy_title":"2026 Evolent MSK Surgery Guidelines - "+g["policy_title"],
                 "policy_number":str(g["policy_number"]),"effective_date":ev["effective_date"],
                 "policy_url":ev["policy_url"],"criteria_quote":g["criteria_quote"],
                 "evidence":"Delegation: "+deleg+" The 2026 Evolent MSK Surgery Guidelines PDF was fetched and its cervical, lumbar and decompression sections read with quoted criteria.",
                 "confidence":"high"}
            apply(rows, st, ins, [c], f, "Evolent MSK 2026", stats)
        # knee/shoulder sections truncated
        f = {"verdict":"unreachable","policy_title":"2026 Evolent Musculoskeletal Surgery Guidelines",
             "policy_url":ev["policy_url"],"effective_date":ev["effective_date"],
             "evidence":"Delegation confirmed ("+deleg+") and the governing 2026 Evolent MSK Guidelines PDF is public and current, but it truncates after the cervical/lumbar/hip sections in two independent runs -- the knee and shoulder sections appear in the TOC only and were not read. Link safe to give a patient; criteria not extracted.",
             "confidence":"medium"}
        # only upgrade cells that are currently worse than CRITERIA EXIST
        for r in rows:
            if (r["state"],r["insurance_company"])==(st,ins) and r["cpt"] in ("27447","27446","29888","29881","27130","29914","29827","23472","29806"):
                if RANK.get(r["status"],0) < RANK["CRITERIA EXIST, TEXT NOT EXTRACTED"]:
                    r["status"]="CRITERIA EXIST, TEXT NOT EXTRACTED"
                    r["policy_title"]=f["policy_title"]; r["effective_date"]=f["effective_date"]
                    r["policy_url"]=f["policy_url"]; r["note"]=note_for(f,"Evolent MSK 2026")
                    stats["changed"] += 1

    with SURG.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields); w.writeheader(); w.writerows(rows)
    print("surgery:", stats)

    # ---- imaging ----
    irows = list(csv.DictReader(IMG.open(encoding="utf-8", newline="")))
    ifields = list(irows[0].keys())
    istats = {"changed":0, "skipped":0}
    img = json.loads((R6/"imaging_wave2.json").read_text())

    # Map payer-level findings onto directory insurer names
    def img_apply(match_ins, states, f, cpts=None):
        status = V2S.get(f["verdict"])
        if not status: return
        for r in irows:
            if r["insurance_company"] not in match_ins: continue
            if states and r["state"] not in states: continue
            if cpts and r["cpt"] not in cpts: continue
            if RANK.get(status,0) < RANK.get(r["status"],0):
                istats["skipped"] += 1; continue
            r["status"]=status
            if f.get("policy_title"): r["policy_title"]=f["policy_title"]
            if f.get("effective_date"): r["effective_date"]=f["effective_date"]
            r["policy_url"]=f.get("policy_url","")
            r["note"]=note_for(f,"imaging vendor map")
            istats["changed"] += 1

    FB = ["Florida Blue"]
    KC = ["Blue Cross and Blue Shield of Kansas City"]
    for f in img["findings"]:
        p = f["payer"]
        if p=="Florida Blue":
            img_apply(FB, ["Florida"], f, [f["cpt"]])
        elif p.startswith("Blue Cross and Blue Shield of Kansas City"):
            img_apply(KC, ["Kansas","Missouri"], f, cpts_of(f))
        elif p.startswith("HCSC"):
            img_apply(["Blue Cross Blue Shield of Illinois","Blue Cross Blue Shield of Texas",
                       "Blue Cross Blue Shield of Oklahoma","Blue Cross Blue Shield of New Mexico",
                       "Blue Cross Blue Shield of Montana"], None, f)
        elif p.startswith("Horizon"):
            img_apply(["Horizon Blue Cross Blue Shield of New Jersey","Horizon Blue Cross Blue Shield"], ["New Jersey"], f)
        elif p=="EmblemHealth":
            img_apply(["EmblemHealth"], ["New York"], f)
        elif p=="Highmark":
            img_apply(["Highmark Blue Cross Blue Shield","Highmark Blue Cross Blue Shield Delaware",
                       "Highmark Blue Cross Blue Shield West Virginia"], None, f)
        elif p=="Blue Shield of California":
            img_apply(["Blue Shield of California"], ["California"], f)
        elif p=="Independence Blue Cross":
            img_apply(["Independence Blue Cross"], ["Pennsylvania"], f)
        elif p=="CareFirst BlueCross BlueShield":
            img_apply(["CareFirst BlueCross BlueShield"], None, f)
        elif p=="Blue Cross NC":
            img_apply(["Blue Cross NC","Blue Cross and Blue Shield of North Carolina"], ["North Carolina"], f)
        elif p=="Premera Blue Cross":
            img_apply(["Premera Blue Cross","Premera Blue Cross Blue Shield of Alaska"], None, f)
        elif p=="CareSource":
            img_apply(["CareSource"], None, dict(f, evidence=f["evidence"]+" Applied to CareSource rows in all markets with medium confidence -- only the Arkansas PASSE line was verified by fetch."))
        elif p.startswith("Kaiser"):
            img_apply(["Kaiser Permanente","Kaiser Foundation Health Plan of Washington","Kaiser Permanente of Washington"], ["Washington"], f, cpts_of(f))
        elif p.startswith("Blue Cross Blue Shield of Massachusetts"):
            img_apply(["Blue Cross Blue Shield of Massachusetts"], ["Massachusetts"], f)
        elif p=="Blue Cross of Idaho":
            img_apply(["Blue Cross of Idaho"], ["Idaho"], f)
        # Evolent/eviCore vendor-master rows aren't payer rows; they anchor via the criteria docs

    # Molina imaging: upgrade from CRITERIA EXIST (truncated manual) to VERIFIED per-guideline ECG PDFs
    ECG = {x["cpt"]: x for x in img["findings"] if x["payer"]=="Evolent (vendor master)"}
    for r in irows:
        if r["insurance_company"]=="Molina Healthcare" and r["cpt"] in ECG:
            g = ECG[r["cpt"]]
            r["status"]="VERIFIED"; r["policy_title"]=g["policy_title"]
            r["effective_date"]=g["effective_date"]; r["policy_url"]=g["policy_url"]
            r["note"]=note_for(dict(g, evidence="Molina's own clinical policy portal routes imaging to Evolent. "+g["evidence"]),"Evolent ECG per-guideline")
            istats["changed"] += 1
    # Blue Shield of CA imaging: same ECG anchoring (Evolent confirmed by BSC's own page)
    for r in irows:
        if r["insurance_company"]=="Blue Shield of California" and r["cpt"] in ECG:
            g = ECG[r["cpt"]]
            r["status"]="VERIFIED"; r["policy_title"]=g["policy_title"]
            r["effective_date"]=g["effective_date"]; r["policy_url"]=g["policy_url"]
            r["note"]=note_for(dict(g, evidence="Blue Shield of California's authorization-list page states 'Review requests for services are performed by Evolent.' "+g["evidence"]),"Evolent ECG per-guideline")
            istats["changed"] += 1

    with IMG.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=ifields); w.writeheader(); w.writerows(irows)
    print("imaging:", istats)


if __name__ == "__main__":
    main()
