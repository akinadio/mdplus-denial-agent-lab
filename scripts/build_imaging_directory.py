#!/usr/bin/env python3
"""Build the advanced-imaging option directory.

Imaging is tracked in its own file rather than folded into the surgery
directory, for one reason: a payer's IMAGING vendor is frequently not its
SURGERY vendor. Simply Healthcare delegates Carelon for radiology only and
routes podiatry elsewhere; Molina sends imaging to Evolent and other criteria
to MCG; Florida Blue uses NIA/RadMD for imaging while reviewing joint surgery
itself. Inheriting a surgery finding into an imaging cell would be exactly the
kind of near-miss this project refuses to ship.

So every imaging cell starts at NOT RESEARCHED and is only filled from
evidence about imaging specifically, banked in research5/imaging.json and
research5/imaging_vendor_map.json.
"""
import csv, pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
PLAT = ROOT / "data" / "policy_platform"
SRC = PLAT / "app_option_policy_directory.csv"
OUT = PLAT / "app_option_imaging_directory.csv"

CODES = [
    ("73721", "MRI of the knee / lower-extremity joint"),
    ("73221", "MRI of the shoulder / upper-extremity joint"),
    ("72148", "MRI of the lower back (lumbar spine)"),
    ("72141", "MRI of the neck (cervical spine)"),
]

EVICORE_MSK = ("eviCore Musculoskeletal Imaging Guidelines V1.0.2026", "2026-02-03",
               "https://palerts2016.s3.amazonaws.com/multisite_documents/bcbs_kansas_city/files/Musculoskeletal%20Imaging%20Guidelines.pdf")
EVICORE_SPINE = ("eviCore Spine Imaging Guidelines V1.0.2026", "2026-02-03",
                 "https://palerts2016.s3.amazonaws.com/multisite_documents/bcbs_kansas_city/files/Spine%20Imaging%20Guidelines.pdf")
CIGNA_MSK = ("Cigna Medical Coverage Policies - Radiology: Musculoskeletal Imaging Guidelines V1.0.2026", "2026-02-03",
             "https://www.evicore.com/sites/default/files/clinical-guidelines/2025-10/Cigna_Musculoskeletal%20Imaging%20Guidelines_V1.0.2026_eff02.03.2026_PUB10.29.2025.pdf")
CIGNA_SPINE = ("Cigna Medical Coverage Policies - Radiology: Spine Imaging Guidelines V1.0.2026", "2026-02-03",
               "https://www.evicore.com/sites/default/files/clinical-guidelines/2025-10/Cigna_Spine%20Imaging%20Guidelines_V1.0.2026_eff02.03.2026_PUB10.29.2025.pdf")
CARELON_EXT = ("Carelon Imaging of the Extremities RBM03-1125.1", "2025-11-15",
               "https://guidelines.carelonmedicalbenefitsmanagement.com/imaging-of-the-extremities-2025-11-15/")
CARELON_SPINE = ("Carelon Imaging of the Spine RBM05-1125.1", "2025-11-15",
                 "https://guidelines.carelonmedicalbenefitsmanagement.com/imaging-of-the-spine-2025-11-15/")
AETNA_EXT = ("Aetna CPB 0171 - MRI of the Extremities", "last reviewed 2026-03-31",
             "https://www.aetna.com/cpb/medical/data/100_199/0171.html")
AETNA_SPINE = ("Aetna CPB 0236 - MRI and CT of the Spine", "last reviewed 2026-04-09",
               "https://www.aetna.com/cpb/medical/data/200_299/0236.html")
NCD = ("NCD 220.2 - Magnetic Resonance Imaging", "2018-04-10",
       "https://www.cms.gov/medicare-coverage-database/view/ncd.aspx?ncdid=177")
LCD_LUMBAR = ("LCD L34220 - Lumbar MRI (Noridian)", "revision effective 2025-10-23",
              "https://www.cms.gov/medicare-coverage-database/view/lcd.aspx?LCDId=34220")
EVOLENT = ("2026 Evolent Clinical Guidelines - Advanced Imaging v2", "2026-01-01 to 2026-12-31",
           "https://www1.radmd.com/sites/default/files/2025-12/2026%20Evolent%20Clinical%20Guidelines%20-%20Advanced%20Imaging%20v2.pdf")
UHC_RAD = ("UnitedHealthcare Radiology Prior Authorization and Notification", "current as of 2026-08-25",
           "https://www.uhcprovider.com/en/prior-auth-advance-notification/radiology-prior-authorization.html")
UHC_GUIDE = ("UnitedHealthcare Cardiology and Radiology Imaging Guidelines V3.0.2026", "2026-05-04",
             "https://www.uhcprovider.com/content/dam/provider/docs/public/prior-auth/r-c/COMM-Exchange-Rad-Card-Guidelines-May-2026.pdf")
UHC_OH = ("UnitedHealthcare Community Plan Adult Spine Imaging Guidelines (Ohio) CSRAD014OH.D", "2025-11-01",
          "https://www.uhcprovider.com/content/dam/provider/docs/public/prior-auth/radiology/Ohio-Radiology/2025/UN-CSRAD014OH-D-Adult-Spine-11-2025.pdf")
HUMANA = ("Humana Medicare Advantage and D-SNP Prior Authorization and Notification List", "2026-01-01",
          "https://assets.humana.com/is/content/humana/FINAL_Medicare%20and%20DSNP%20Prior%20Authorization%20and%20Notification%20List%20-%201-1-2026pdf")

# Noridian's two jurisdictions, the only ones LCD L34220 binds. Everywhere
# else Medicare falls back to NCD 220.2, which declines to give site-specific
# criteria. A companion LCD L37281 covers another jurisdiction and has not
# been read, so it is not applied here.
NORIDIAN = {"California", "Hawaii", "Nevada", "Alaska", "Arizona", "Idaho", "Montana",
            "North Dakota", "Oregon", "South Dakota", "Utah", "Washington", "Wyoming"}

EXT_CODES = {"73721", "73221"}

NOTE = "2026-08-25 imaging sweep. "


def rule(insurer, state, plan_type, cpt):
    """-> (status, title, eff, url, note) or None to leave NOT RESEARCHED."""
    ext = cpt in EXT_CODES

    if insurer == "Cigna":
        t, e, u = CIGNA_MSK if ext else CIGNA_SPINE
        return ("VERIFIED", t, e, u, NOTE + "Cigna's provider prior-authorization page states 'We collaborate "
                "with EviCore by Evernorth' and lists 'Radiology Imaging, High- and Low-Technology' among the "
                "eviCore-managed services. This is the eviCore-authored, Cigna-branded guideline; the code is "
                "named in it explicitly.")

    if insurer == "Aetna":
        if cpt == "73721":
            return ("VERIFIED", AETNA_EXT[0], AETNA_EXT[1], AETNA_EXT[2], NOTE + "73721 is listed under 'CPT "
                    "codes covered if selection criteria are met' and the policy body carries knee-specific criteria.")
        if cpt == "73221":
            return ("CONFIRMED NO POLICY", AETNA_EXT[0], AETNA_EXT[1], AETNA_EXT[2], NOTE + "Verified negative, on "
                    "two independent fetches: CPB 0171's code table covers the 73218-73223 range but the policy body "
                    "contains NO shoulder-specific criteria at all -- its detailed criteria address knee, foot and hand "
                    "only. No separate Aetna shoulder-MRI CPB exists. Aetna's knee language must NOT be reused for a "
                    "shoulder MRI denial.")
        return ("VERIFIED", AETNA_SPINE[0], AETNA_SPINE[1], AETNA_SPINE[2], NOTE + "The code is listed under 'CPT "
                "codes covered if selection criteria are met'. Aetna applies one combined spine criteria set to "
                "cervical, thoracic and lumbar.")

    if insurer == "Medicare":
        if cpt == "72148" and state in NORIDIAN:
            return ("VERIFIED (CMS LCD/NCD)", LCD_LUMBAR[0], LCD_LUMBAR[1], LCD_LUMBAR[2], NOTE + "Worth quoting in "
                    "an appeal: the LCD says a non-red-flag lumbar MRI 'may be appropriate after 1 month of symptoms' "
                    "where 'the patient has not responded to a reasonable trial of conservative management lasting at "
                    "least four weeks' -- four weeks, shorter than the six weeks every commercial vendor demands. "
                    "Caveat: the CMS code table sits behind an AMA license click-through, so 72148 itself was not "
                    "visible; the LCD is titled Lumbar MRI and 72148 is the lumbar MRI-without-contrast code, but that "
                    "last link is inference.")
        return ("NO LCD — general medical necessity", NCD[0], NCD[1], NCD[2], NOTE + "NCD 220.2 covers MRI as a "
                "modality and expressly declines to enumerate site-specific indications: 'Use the following "
                "descriptions as general guidelines or examples of what may be considered covered rather than as a "
                "restrictive list of specific covered indications.' No procedure-specific national criteria exist, so "
                "general reasonable-and-necessary standards govern -- which is itself useful in an appeal.")

    if insurer == "UnitedHealthcare":
        if plan_type == "Medicare / Medicare Advantage":
            return ("NO PRIOR AUTH REQUIRED", UHC_RAD[0], UHC_RAD[1], UHC_RAD[2], NOTE + "UHC's radiology page states "
                    "plainly: 'For Medicare Advantage and Dual Special Needs Plan (D-SNP) benefit plans, prior "
                    "authorization is not required for a CT, MRI or MRA.'")
        if state == "Ohio" and plan_type == "Medicaid" and cpt in ("72148", "72141"):
            return ("VERIFIED", UHC_OH[0], UHC_OH[1], UHC_OH[2], NOTE + "Ohio Community Plan only -- NOT a national "
                    "UHC policy. The procedure code table names the code explicitly.")
        return ("CRITERIA EXIST, TEXT NOT EXTRACTED", UHC_GUIDE[0], UHC_GUIDE[1], UHC_GUIDE[2], NOTE + "This is the "
                "correct current governing document (V3.0.2026, effective 05/04/2026; a V6/Oct-2026 edition is "
                "published but not yet effective). Its table of contents shows musculoskeletal and spine sections, but "
                "every fetch truncated inside Abdomen Imaging before the criteria. The link is safe to give a patient; "
                "the criteria still need to be read by hand. UHC names no radiology benefit manager on its own "
                "radiology page.")

    if insurer == "Humana":
        return ("NO PUBLIC CRITERIA (vendor)", HUMANA[0], HUMANA[1], HUMANA[2], NOTE + "MRI sits under "
                "'Diagnostic/cardiac imaging' requiring authorization, delegated to Cohere Health except in Florida "
                "where Humana manages it directly. This is a PA-requirement list, not a criteria document, and no "
                "public Cohere imaging criteria document was located. Humana has publicly announced dropping prior "
                "authorization for certain CT/MR exams; whether these codes are among them is unverified.")

    if insurer == "Molina Healthcare":
        return ("CRITERIA EXIST, TEXT NOT EXTRACTED", EVOLENT[0], EVOLENT[1], EVOLENT[2], NOTE + "Molina's own "
                "clinical policy portal routes imaging to Evolent ('For Evolent Radiology policies, please click "
                "here'). The 2026 Evolent manual is public and current and its contents page names this code, but "
                "every fetch truncates inside the Abdomen CT section on page 9 of 23, well before the MRI criteria. "
                "Evolent publishes 2026 only as one combined manual -- the per-guideline PDFs that existed for 2025 "
                "return 404 for 2026.")

    if insurer == "Blue Cross Blue Shield of Michigan":
        t, e, u = (CARELON_EXT if ext else CARELON_SPINE)
        return ("VERIFIED", t, e, u, NOTE + "BCBSM's own radiology page states 'Carelon Medical Benefits Management "
                "manages prior authorization for high-tech radiology services for: Blue Cross Blue Shield of Michigan "
                "commercial ... Blue Care Network commercial members.' The Carelon guideline names this code "
                "explicitly. Caveat: BCBSM publishes a Carelon exclusion list of services that do NOT need PA, which "
                "was not read, so it is possible this code is excluded.")

    return None


def main():
    seen, out = set(), []
    for r in csv.DictReader(SRC.open(encoding="utf-8", newline="")):
        key = (r["state"], r["insurance_company"])
        if key in seen:
            continue
        seen.add(key)
        for cpt, label in CODES:
            got = rule(r["insurance_company"], r["state"], r["plan_type"], cpt)
            status, title, eff, url, note = got if got else ("NOT RESEARCHED", "", "", "", "")
            out.append({"state": r["state"], "insurance_company": r["insurance_company"],
                        "plan_type": r["plan_type"], "surgery": label, "cpt": cpt,
                        "status": status, "policy_title": title, "effective_date": eff,
                        "policy_url": url, "note": note})
    with OUT.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out[0].keys()))
        w.writeheader()
        w.writerows(out)
    import collections
    c = collections.Counter(r["status"] for r in out)
    print(f"{len(out)} imaging rows across {len(seen)} state x insurer pairs")
    for k, v in c.most_common():
        print(f"  {v:5d}  {k}")


if __name__ == "__main__":
    main()
