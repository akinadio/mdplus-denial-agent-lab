#!/usr/bin/env python3
"""Consolidate the per-state Medicaid coverage-portal research into CSV + JSON."""
import csv, json
from pathlib import Path

# state -> (program_name, coverage_policy_url, prior_auth_basis, notes)
M = {
"Alabama":("Alabama Medicaid Agency","https://medicaid.alabama.gov/content/7.0_Providers/7.6_Manuals.aspx","FFS: medically necessary per Physician program rules; PA for select procedures; AL largely FFS","Provider Billing Manual Ch.28 Physician; PA page 7.7_Prior_Authorization."),
"Alaska":("Alaska Medical Assistance","https://health.alaska.gov/en/education/service-authorizations/","FFS: medical necessity; service authorization required for surgical/inpatient (Conduent/Gainwell)","Mostly FFS; detail in Provider Billing Manuals."),
"Arizona":("AHCCCS","https://www.azahcccs.gov/shared/MedicalPolicyManual/","Mostly MCO-administered (UM criteria); FFS uses AMPM Ch.800/820 PA","AMPM is master policy; most members in ACC managed care."),
"Arkansas":("Arkansas Medicaid","https://humanservices.arkansas.gov/divisions-shared-services/medical-services/","FFS: medical necessity; PA/UR via AFMC; PASSE managed care for some","Provider manuals + AFMC surgical PA."),
"California":("Medi-Cal","https://www.dhcs.ca.gov/providers-partners/prior-authorization-overview/","FFS via Treatment Authorization Request (TAR); most in managed care using InterQual/MCG","DHCS Provider Manual; majority in managed care plans."),
"Colorado":("Health First Colorado","https://hcpf.colorado.gov/par","FFS: medical necessity; PA via ColoradoPAR (Acentra) using state criteria + InterQual","Physical health largely FFS with RAEs coordinating."),
"Connecticut":("HUSKY Health","https://www.huskyhealthct.org/providers/prior-authorization.html","Self-insured FFS (ASO by CHNCT); medical necessity, PA per HUSKY clinical policies","Single FFS model, no full-risk medical MCOs."),
"Delaware":("Delaware Medicaid (DMMA)","https://medicaidpublications.dhss.delaware.gov/","Mostly MCO (AmeriHealth Caritas DE, Highmark) using InterQual/MCG; DMMA policy manual","Diamond State Health Plan mostly MCO-administered."),
"Florida":("Florida Medicaid (AHCA)","https://ahca.myflorida.com/provider/policy.html","Orthopedic Services Coverage Policy (Rule 59G-4.211); PA per 59G-1.053; SMMC plans administer PA","Dedicated Orthopedic Services Coverage Policy exists."),
"Georgia":("Georgia Medicaid (DCH)","https://www.mmis.georgia.gov/portal/PubPart/AllPolicyManuals/tabId/70/Default.aspx","FFS: medical necessity; prior approval (DMA-610) for select surgery; CMOs run own PA","Part II Physician Services manual via GAMMIS; most in Georgia Families CMOs."),
"Hawaii":("Med-QUEST (QUEST Integration)","https://medquest.hawaii.gov/en/plans-providers/fee-for-service/provider-manual.html","FFS PA per provider manual; QUEST Integration MCOs use InterQual/MCG","Mostly MCO-administered."),
"Idaho":("Idaho Medicaid (Healthy Connections)","https://healthandwelfare.idaho.gov/providers/idaho-medicaid-providers/information-medicaid-providers","FFS PA per state criteria; surgery PA form (Telligen/Gainwell UR)","Largely FFS; handbook Medical/Hospital modules at idmedicaid.com."),
"Illinois":("HealthChoice Illinois","https://hfs.illinois.gov/medicalproviders/mpac.html","FFS PA per HFS Medical Prior Approval Criteria (MPAC); MCOs use InterQual/MCG","Practitioner Handbook Ch.A-200; most in HealthChoice MCOs."),
"Indiana":("IHCP (HIP / Hoosier Healthwise / Hoosier Care Connect)","https://www.in.gov/medicaid/providers/clinical-services/prior-authorization/","FFS PA per IHCP criteria; MCEs use InterQual/MCG","Predominantly MCO/MCE-administered."),
"Iowa":("IA Health Link","https://hhs.iowa.gov/medicaid/provider-services/covered-services-rates-and-payments/prior-authorization","FFS PA per Iowa Medicaid criteria; MCOs (Iowa Total Care, Wellpoint) use InterQual/MCG","Mostly MCO-administered."),
"Kansas":("KanCare (KMAP)","https://portal.kmap-state-ks.us/PublicPage/Public/ProviderManuals","FFS PA per KMAP manual; KanCare MCOs use InterQual/MCG","Nearly all in KanCare MCOs (Aetna, Sunflower, Healthy Blue)."),
"Kentucky":("Kentucky Medicaid (DMS)","https://www.chfs.ky.gov/agencies/dms/provider/pages/default.aspx","FFS PA per DMS criteria (KYHealth Net e-PA); MCOs use InterQual/MCG","Predominantly MCO-administered."),
"Louisiana":("Healthy Louisiana (LDH)","https://ldh.la.gov/medicaid/medicaid-services","FFS PA per LDH provider-manual (PC-PM); Healthy Louisiana MCOs use InterQual/MCG","Mostly MCO-administered."),
"Maine":("MaineCare","https://www.maine.gov/sos/rulemaking/agency-rules/mainecare-benefits-manual","FFS PA per MaineCare Benefits Manual (UR via Kepro/Acentra)","Primarily FFS; MBM Ch.II Section 90 Physician / 45 Hospital."),
"Maryland":("Maryland Medicaid / HealthChoice","https://health.maryland.gov/mmcp/pages/preauthorization-information.aspx","FFS PA per state criteria; HealthChoice MCOs use InterQual/MCG","Mostly MCO-administered."),
"Massachusetts":("MassHealth","https://www.mass.gov/prior-authorization-for-masshealth-providers","FFS PA per 130 CMR + medical-necessity guidelines; ACOs/MCOs use InterQual/MCG","Some ortho items (e.g., knee arthroscopy) have specific PA."),
"Michigan":("Michigan Medicaid (MDHHS)","https://www.michigan.gov/mdhhs/doing-business/providers/providers/medicaid/policyforms/medicaid-provider-manual","FFS PA per Provider Manual/FFS criteria; Medicaid Health Plans use InterQual/MCG","Most in Medicaid Health Plans (CHCP)."),
"Minnesota":("Minnesota Health Care Programs","https://www.dhs.state.mn.us/ID_008925/","FFS authorization per MHCP Provider Manual (Acentra); MCOs use own criteria","Prepaid Medical Assistance MCOs administer PA."),
"Mississippi":("Mississippi Medicaid (DOM)","https://medicaid.ms.gov/prior-authorization/","FFS PA via Telligen per Admin Code; MississippiCAN MCOs use InterQual/MCG","Procedure-code PA list; Title 23 Admin Code."),
"Missouri":("MO HealthNet","https://mydss.mo.gov/mhd/provider-manuals","FFS PA per Physician manual medical necessity; Managed Care plans run own PA","Manuals also at manuals.momed.com."),
"Montana":("Montana Healthcare Programs","https://medicaidprovider.mt.gov/priorauthorization","Primarily FFS; PA per provider manuals + Admin Rules of Montana","Largely FFS (Passport PCCM); surgery-facility manuals exist."),
"Nebraska":("Nebraska Medicaid (Heritage Health)","https://dhhs.ne.gov/Pages/Medicaid-Provider-Handbooks.aspx","FFS PA per 471 NAC (Gainwell); Heritage Health MCOs use InterQual/MCG","Criteria/forms at nebraska.fhsc.com; most in MCOs."),
"Nevada":("Nevada Medicaid","https://www.nevadamedicaid.nv.gov/resources/medicaid-services-manual/","FFS PA per Medicaid Services Manual (Ch.600 Physician; Gainwell); MCOs use InterQual/MCG","DHCFP MSM governs coverage."),
"New Hampshire":("New Hampshire Medicaid","https://www.dhhs.nh.gov/programs-services/medicaid/medicaid-provider-relations","FFS PA per General Billing manuals + He-W rules; MCM MCOs use InterQual/MCG","Manuals on nhmmis.nh.gov; most in Medicaid Care Management MCOs."),
"New Jersey":("NJ FamilyCare","https://www.njmmis.com","FFS PA per manuals + N.J.A.C. Title 10; NJ FamilyCare MCOs use InterQual/MCG","Predominantly MCO-administered; fiscal agent njmmis.com."),
"New Mexico":("New Mexico Medicaid (Turquoise Care)","https://www.hca.nm.gov/turquoise-care/","Mostly MCO (Turquoise Care) using InterQual/MCG; FFS PA per MAD criteria","MAD Managed Care Policy Manual + 8.302 NMAC."),
"New York":("NY Medicaid","https://www.emedny.org/ProviderManuals/Physician/index.aspx","FFS: prior approval per eMedNY Physician Manual; MCOs use own UM criteria","Most in Medicaid Managed Care."),
"North Carolina":("NC Medicaid","https://medicaid.ncdhhs.gov/providers/programs-and-services/prior-approval-and-due-process","FFS PA per NC Clinical Coverage Policies (1A surgical series); PHPs/Tailored Plans","Numbered Clinical Coverage Policies; much of pop in managed care."),
"North Dakota":("North Dakota Medicaid","https://www.hhs.nd.gov/sites/www/files/documents/medicaid-policies/service-authorizations.pdf","FFS service authorization per ND Billing and Policy Manual; medical necessity","Predominantly FFS."),
"Ohio":("Ohio Medicaid (ODM)","https://medicaid.ohio.gov/resources-for-providers/billing/prior-authorization-requirements/prior-authorization-requirements","FFS PA per ODM; Next Generation MCOs use InterQual/MCG","Most in Next Generation managed care."),
"Oklahoma":("SoonerCare (OHCA)","https://oklahoma.gov/ohca/providers/claim-tools/prior-authorization.html","FFS PA per OAC Title 317; SoonerSelect MCOs administer PA","SoonerSelect MCOs now cover most members."),
"Oregon":("Oregon Health Plan","https://www.oregon.gov/oha/hsd/ohp/pages/prioritized-list.aspx","Coverage by HERC Prioritized List line; PA to OHA (FFS) or member's CCO","Major joint surgery on covered lines; most in CCOs."),
"Pennsylvania":("PA Medical Assistance","https://www.pa.gov/agencies/dhs/resources/for-providers/promise/promise-provider-handbooks-guides","FFS PA per PROMISe handbooks + 55 Pa Code Ch.1101/1150; HealthChoices MCOs administer PA","Most in HealthChoices managed care."),
"Rhode Island":("RI Medicaid (EOHHS)","https://eohhs.ri.gov/providers-partners/provider-manuals-guidelines/medicaid-provider-manual/physician","FFS PA per EOHHS Provider Manual; MCOs administer PA","Most in MCOs (Neighborhood, UHC, Tufts)."),
"South Carolina":("SC Healthy Connections","https://www.scdhhs.gov/providers/manuals/physicians-services-provider-manual","FFS PA per SCDHHS Physicians Services Manual; MCOs use InterQual/MCG","Most in Healthy Connections managed care."),
"South Dakota":("South Dakota Medicaid","https://dss.sd.gov/medicaid/providers/billingmanuals/","FFS: medical necessity per SD Billing and Policy Manual; PA per state criteria","Largely FFS (no full-risk MCOs)."),
"Tennessee":("TennCare","https://www.tn.gov/tenncare/providers/managed-care-contractors.html","~100% managed care; MCCs administer PA (InterQual/MCG) + TennCare rules","No central FFS medical policy; delegated to MCCs."),
"Texas":("Texas Medicaid","https://www.tmhp.com/resources/provider-manuals/tmppm","FFS PA via TMHP per TMPPM (PA chapter 1.05); STAR MCOs use InterQual/MCG","TMHP is claims/PA administrator; most in STAR."),
"Utah":("Utah Medicaid","https://medicaid.utah.gov/utah-medicaid-criteria/","FFS PA per Utah Medicaid coverage criteria; ACOs apply own criteria","Physician Services Provider Manual defines covered surgery."),
"Vermont":("Vermont Medicaid (DVHA)","http://ovha.vermont.gov/for-providers/clinical-coverage-guidelines","Primarily FFS; PA per DVHA Clinical Coverage Guidelines","Largely FFS (no full-risk MCOs)."),
"Virginia":("Virginia Medicaid (Cardinal Care)","https://vamedicaid.dmas.virginia.gov/manuals/provider-manuals-library","FFS service authorization per DMAS manuals; Cardinal Care MCOs use InterQual/MCG","Practitioner manual Ch.IV; most in Cardinal Care MCOs."),
"Washington":("Apple Health (WA)","https://www.hca.wa.gov/billers-providers-partners/prior-authorization-claims-and-billing","FFS PA per HCA billing guides + WAC; Apple Health MCOs use InterQual/MCG","Most in Integrated Managed Care."),
"West Virginia":("West Virginia Medicaid","https://bms.wv.gov/chapter-519-practitioner-services","FFS per BMS Ch.519 Practitioner Services (519.16 Surgical); MCOs apply own criteria","Dedicated Surgical Services policy; most in Mountain Health Trust."),
"Wisconsin":("ForwardHealth (BadgerCare Plus)","https://www.forwardhealth.wi.gov/kw/pdf/phy_medicine_surgery.pdf","FFS PA per ForwardHealth Online Handbook; HMOs apply own criteria","Physician 'Medicine and Surgery' handbook."),
"Wyoming":("Wyoming Medicaid","https://www.wyomingmedicaid.com/portal/Provider-Manuals-and-Bulletins","FFS PA via Telligen (state UM/QIO) per state/InterQual criteria; medical necessity","FFS statewide (no full-risk MCOs)."),
}

out_dir = Path("data/policy_platform")
out_dir.mkdir(parents=True, exist_ok=True)
csv_path = out_dir / "medicaid_coverage_by_state.csv"
with csv_path.open("w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["state","program_name","coverage_policy_url","prior_auth_basis","notes"])
    for st in sorted(M):
        prog, url, pa, notes = M[st]
        w.writerow([st, prog, url, pa, notes])

directory = {
    "meta": {
        "description": "Reach OrthoAppeals Medicaid coverage directory: per state, the official Medicaid coverage-policy/provider-manual entry point and how prior authorization works. Medicaid ortho surgery (e.g., TKA 27447) is generally covered as medically necessary; most states delegate the criteria to MCOs (InterQual/MCG) or a state FFS manual — so this is a per-STATE entry point, not per-procedure criteria.",
        "state_count": len(M),
        "caveat": "Unlike the commercial directory, Medicaid rarely publishes procedure-specific public policies; coverage is medical-necessity + PA via the state FFS manual or the member's managed-care plan. The URL is the authoritative starting point; the live agent should confirm the member's specific plan (FFS vs a named MCO).",
    },
    "states": {st: {"program_name": M[st][0], "coverage_policy_url": M[st][1],
                    "prior_auth_basis": M[st][2], "notes": M[st][3]} for st in sorted(M)},
}
(out_dir / "medicaid_coverage_by_state.json").write_text(
    json.dumps(directory, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"states: {len(M)}  wrote {csv_path} + medicaid_coverage_by_state.json")
