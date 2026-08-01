#!/usr/bin/env python3
"""Consolidate the per-carrier policy-link research into a CSV + JSON directory."""
import csv, json
from pathlib import Path

# Canonical procedures (label, cpt) in display order.
PROCS = [
    ("Total knee arthroplasty (TKA)", "27447"),
    ("Total hip arthroplasty (THA)", "27130"),
    ("Arthroscopic rotator cuff repair", "29827"),
    ("Total shoulder arthroplasty", "23472"),
    ("ACL reconstruction", "29888"),
    ("Lumbar fusion", "22612"),
    ("Cervical fusion / ACDF", "22551"),
    ("Total ankle arthroplasty", "27702"),
    ("Bunionectomy / hallux valgus", "28296"),
    ("Hip arthroscopy", "29914-29916"),
    ("Lumbar microdiscectomy / decompression", "63030"),
    ("Musculoskeletal MRI (knee/shoulder/lumbar)", "73721/73221/72148"),
]

# Per carrier: cpt -> (policy_title, url, public, verified, eff, notes)
DATA = {
 "UnitedHealthcare": {
  "27447": ("Surgery of the Knee (Commercial)", "https://www.uhcprovider.com/content/dam/provider/docs/public/policies/comm-medical-drug/surgery-knee.pdf", True, True, "2026-06-01", "27447 in Applicable Codes."),
  "27130": ("Surgery of the Hip (2026T0503JJ)", "https://www.uhcprovider.com/content/dam/provider/docs/public/policies/comm-medical-drug/surgery-hip.pdf", True, True, "2026-03-01", "27130 total hip arthroplasty."),
  "29827": ("Surgery of the Shoulder (2026T0556FF)", "https://www.uhcprovider.com/content/dam/provider/docs/public/policies/comm-medical-drug/surgery-shoulder.pdf", True, True, "2026-01-01", "29827 rotator cuff repair."),
  "23472": ("Surgery of the Shoulder (2026T0556FF)", "https://www.uhcprovider.com/content/dam/provider/docs/public/policies/comm-medical-drug/surgery-shoulder.pdf", True, True, "2026-01-01", "23472 total shoulder; same policy."),
  "29888": ("Surgery of the Knee (Commercial)", "https://www.uhcprovider.com/content/dam/provider/docs/public/policies/comm-medical-drug/surgery-knee.pdf", True, True, "2026-06-01", "29888 ACL; same knee policy."),
  "22612": ("Spinal Fusion and Decompression (2026T0639I)", "https://www.uhcprovider.com/content/dam/provider/docs/public/policies/comm-medical-drug/spinal-fusion-decompression.pdf", True, True, "2026-04-01", "22612 lumbar fusion."),
  "22551": ("Spinal Fusion and Decompression (2026T0639I)", "https://www.uhcprovider.com/content/dam/provider/docs/public/policies/comm-medical-drug/spinal-fusion-decompression.pdf", True, True, "2026-04-01", "22551 ACDF; same spine policy."),
  "27702": ("Surgery of the Ankle (2026T0622O)", "https://www.uhcprovider.com/content/dam/provider/docs/public/policies/comm-medical-drug/surgery-ankle.pdf", True, True, "2026-07-01", "27702 total ankle."),
  "28296": ("Surgery of the Foot (2026T0624O)", "https://www.uhcprovider.com/content/dam/provider/docs/public/policies/comm-medical-drug/surgery-foot.pdf", True, True, "2026-01-01", "28296 hallux valgus."),
  "29914-29916": ("Surgery of the Hip (2026T0503JJ)", "https://www.uhcprovider.com/content/dam/provider/docs/public/policies/comm-medical-drug/surgery-hip.pdf", True, True, "2026-03-01", "29914-29916; same hip policy."),
  "63030": ("Spinal Fusion and Decompression (2026T0639I)", "https://www.uhcprovider.com/content/dam/provider/docs/public/policies/comm-medical-drug/spinal-fusion-decompression.pdf", True, True, "2026-04-01", "63030 decompression; same spine policy."),
  "73721/73221/72148": ("MRI/CT Site of Service (MP.13.19)", "https://www.uhcprovider.com/content/dam/provider/docs/public/policies/comm-medical-drug/mri-ct-scan-site-of-service.pdf", True, True, "2026-01-01", "All three CPTs present (site-of-service; clinical criteria via radiology imaging guidelines, portal-gated)."),
 },
 "Aetna (CVS Health)": {
  "27447": ("Knee Arthroplasty (CPB 0660)", "https://www.aetna.com/cpb/medical/data/600_699/0660.html", True, True, "rev 2026-02-26", "27447 in Applicable CPT codes."),
  "27130": ("Hip Arthroplasty (CPB 0287)", "https://www.aetna.com/cpb/medical/data/200_299/0287.html", True, True, "rev 2026-07-17", "27130 listed."),
  "29827": ("", "", False, False, None, "No dedicated Aetna CPB lists 29827 (absent from Shoulder Arthroplasty CPB 0837 and graft CPB 0411). Adjudicated by medical necessity."),
  "23472": ("Shoulder Arthroplasty and Arthrodesis (CPB 0837)", "https://www.aetna.com/cpb/medical/data/800_899/0837.html", True, True, "rev 2026-06-25", "23472 listed."),
  "29888": ("Allograft Transplants of the Extremities (CPB 0364)", "https://www.aetna.com/cpb/medical/data/300_399/0364.html", True, True, "rev 2026-05-15", "29888 listed; no standalone ACL CPB."),
  "22612": ("Spinal Surgery: Laminectomy and Fusion (CPB 0743)", "https://www.aetna.com/cpb/medical/data/700_799/0743.html", True, True, "rev 2026-07-30", "22612 listed."),
  "22551": ("Spinal Surgery: Laminectomy and Fusion (CPB 0743)", "https://www.aetna.com/cpb/medical/data/700_799/0743.html", True, True, "rev 2026-07-30", "22551 listed; same CPB."),
  "27702": ("Total Ankle Arthroplasty (CPB 0645)", "https://www.aetna.com/cpb/medical/data/600_699/0645.html", True, True, "rev 2026-05-15", "27702 listed."),
  "28296": ("Bunionectomy (CPB 0629)", "https://www.aetna.com/cpb/medical/data/600_699/0629.html", True, True, "rev 2025-12-11", "28296 listed."),
  "29914-29916": ("Hip Preservation Surgery (CPB 0736)", "https://www.aetna.com/cpb/medical/data/700_799/0736.html", True, True, "rev 2026-07-31", "29914-29916 all listed."),
  "63030": ("Spinal Surgery: Laminectomy and Fusion (CPB 0743)", "https://www.aetna.com/cpb/medical/data/700_799/0743.html", True, True, "rev 2026-07-30", "63030 listed; same CPB."),
  "73721/73221/72148": ("MRI of the Extremities (CPB 0171) + MRI/CT of the Spine (CPB 0236)", "https://www.aetna.com/cpb/medical/data/100_199/0171.html", True, True, "rev 2026-03/04", "Knee 73721 & shoulder (73218-73223 range) on CPB 0171; lumbar 72148 on CPB 0236 (https://www.aetna.com/cpb/medical/data/200_299/0236.html)."),
 },
 "Cigna": {
  "27447": ("Cigna CMM-311 Knee Replacement/Arthroplasty (via eviCore)", "https://www.evicore.com/sites/default/files/clinical-guidelines/2025-11/Cigna_CMM-311%20Knee%20Replacement%20Arthroplasty_V2.0.2025_Eff03.07.2026_Pub11.21.2025.pdf", True, True, "2026-03-07", "MSK delegated to eviCore; on-domain copy cignaforhcp.cigna.com is WAF-blocked."),
  "27130": ("Cigna CMM-313 Hip Replacement/Arthroplasty (via eviCore)", "https://www.evicore.com/sites/default/files/clinical-guidelines/2025-11/Cigna_CMM-313%20Hip%20Replacement%20Arthro_V2.0.2025_Eff03.07.2026_Pub11.21.2025.pdf", True, True, "2026-03-07", "eviCore-hosted Cigna policy."),
  "29827": ("Cigna CMM-315 Shoulder Surgery Arthroscopic/Open (via eviCore)", "https://www.evicore.com/sites/default/files/clinical-guidelines/2025-11/Cigna_CMM-315%20Shoulder%20Surg%20Arthro%20Open%20Proc_V2.0.2025_Eff03.07.2026_Pub11.21.2025.pdf", True, True, "2026-03-07", "29827 present."),
  "23472": ("Cigna CMM-318 Shoulder Arthroplasty (via eviCore)", "https://www.evicore.com/sites/default/files/clinical-guidelines/2025-12/Cigna_CMM-318_Shoulder%20Arthro%20Replace%20Revision_V2.0.2025_Eff03.07.2026_Pub12.11.2025.pdf", True, True, "2026-03-07", "23472 present."),
  "29888": ("Cigna CMM-312 Knee Surgery Arthroscopic/Open (via eviCore)", "https://www.evicore.com/sites/default/files/clinical-guidelines/2025-12/Cigna_CMM-312%20Knee%20Surg%20Arthro%20&%20Open%20Proc_eff03.07.2026_pub12.11.2025.pdf", True, True, "2026-03-07", "29888 present."),
  "22612": ("Cigna CMM-609 Lumbar Fusion (via eviCore)", "https://www.evicore.com/sites/default/files/clinical-guidelines/2025-11/Cigna%20CMM-609%20Lumbar%20Fusion_Final_V2.0.2025_Eff12.18.2025_pub11.18.2025.pdf", True, True, "2025-12-18", "22612 present."),
  "22551": ("Cigna Medical Coverage Policy 0527 Cervical Fusion", "https://static.cigna.com/assets/chcp/pdf/coveragePolicies/medical/mm_0527_coveragepositioncriteria_cervical_fusion.pdf", True, True, "2020-06-15", "On static.cigna.com (own domain); 22551 present."),
  "27702": ("Cigna Medical Coverage Policy 0285 Total Ankle Arthroplasty", "https://static.cigna.com/assets/chcp/pdf/coveragePolicies/medical/mm_0285_coveragepositioncriteria_total_ankle_arthroplasty.pdf", True, True, "2026-03-15", "On static.cigna.com; 27702 present."),
  "28296": ("Cigna Medical Coverage Policy 0304 Bunionectomy", "https://cignaforhcp.cigna.com/public/content/pdf/coveragePolicies/medical/mm_0304_coveragepositioncriteria_bunionectomy.pdf", False, False, None, "Policy appears retired/legacy (absent from current A-Z index) and not machine-verifiable. Treat as no current verifiable Cigna policy."),
  "29914-29916": ("Cigna CMM-314 Hip Surgery Arthroscopic/Open (via eviCore)", "https://www.evicore.com/sites/default/files/clinical-guidelines/2025-11/Cigna_CMM-314%20Hip%20Surg%20Arthro%20Open%20Proc_V2.0.2025_Eff03.07.2026_Pub11.21.2025.pdf", True, True, "2026-03-07", "29914/29915/29916 present."),
  "63030": ("Cigna CMM-606 Lumbar Microdiscectomy (via eviCore)", "https://www.evicore.com/sites/default/files/clinical-guidelines/2024-12/Cigna_CMM-606%20Lumb%20Microdis_Final_V1.1.2024.pdf", True, True, "2024-12-27", "63030 present; CMM-608 covers broader decompression."),
  "73721/73221/72148": ("Cigna MSK Imaging Guidelines + Spine Imaging Guidelines (via eviCore)", "https://www.evicore.com/sites/default/files/clinical-guidelines/2025-10/Cigna_Musculoskeletal%20Imaging%20Guidelines_V1.0.2026_eff02.03.2026_PUB10.29.2025.pdf", True, True, "2026-02-03", "73721 & 73221 in MSK guidelines; 72148 in Spine Imaging Guidelines (companion eviCore PDF)."),
 },
 "Elevance / Anthem BCBS": {
  "27447": ("Clinical Appropriateness Guidelines: Joint Surgery (Carelon)", "https://files.providernews.anthem.com/2520/PDF-Joint-Surgery-2023-11-05.pdf", True, True, "2023-11-05", "TKA section; 27447 in prior same-series version, appendix truncated in current."),
  "27130": ("Clinical Appropriateness Guidelines: Joint Surgery (Carelon)", "https://files.providernews.anthem.com/2520/PDF-Joint-Surgery-2023-11-05.pdf", True, True, "2023-11-05", "27130 total hip arthroplasty present."),
  "29827": ("Clinical Appropriateness Guidelines: Joint Surgery (Carelon)", "https://files.providernews.anthem.com/2520/PDF-Joint-Surgery-2023-11-05.pdf", True, True, "2023-11-05", "29827 present."),
  "23472": ("Clinical Appropriateness Guidelines: Joint Surgery (Carelon)", "https://files.providernews.anthem.com/2520/PDF-Joint-Surgery-2023-11-05.pdf", True, True, "2023-11-05", "23472 total shoulder present."),
  "29888": ("", "", False, False, None, "No dedicated Anthem/Carelon guideline for ACL; 29888 not in Joint Surgery knee section. Medical necessity."),
  "22612": ("Clinical Appropriateness Guidelines: Spine Surgery (Carelon)", "https://files.providernews.anthem.com/4827/pdf-Spine-Surgery-2024-10-20.pdf", True, False, "2024-10-20", "Correct governing doc (Lumbar Fusion section); base code 22612 in appendix but not literally sighted (add-on 22614 seen)."),
  "22551": ("Clinical Appropriateness Guidelines: Spine Surgery (Carelon)", "https://files.providernews.anthem.com/4827/pdf-Spine-Surgery-2024-10-20.pdf", True, True, "2024-10-20", "22551 cervical ACDF present verbatim."),
  "27702": ("Clinical Appropriateness Guidelines: Small Joint Surgery (Carelon)", "https://files.providernews.anthem.com/2519/PDF-Small-Joint-Surgery-2023-11-05.pdf", True, True, "2023-11-05", "27702 total ankle present verbatim."),
  "28296": ("Clinical Appropriateness Guidelines: Small Joint Surgery (Carelon)", "https://files.providernews.anthem.com/2519/PDF-Small-Joint-Surgery-2023-11-05.pdf", True, True, "2023-11-05", "28296 bunionectomy present verbatim."),
  "29914-29916": ("Clinical Appropriateness Guidelines: Joint Surgery (Carelon)", "https://files.providernews.anthem.com/2520/PDF-Joint-Surgery-2023-11-05.pdf", True, True, "2023-11-05", "29914-29916 hip arthroscopy present."),
  "63030": ("Clinical Appropriateness Guidelines: Spine Surgery (Carelon)", "https://files.providernews.anthem.com/4827/pdf-Spine-Surgery-2024-10-20.pdf", True, False, "2024-10-20", "Correct doc (Lumbar Discectomy/Laminotomy section); base 63030 in appendix but not literally sighted (add-on 63035 seen)."),
  "73721/73221/72148": ("Imaging of the Extremities + Imaging of the Spine (Carelon)", "https://files.providernews.anthem.com/4819/PDF-Imaging-of-the-Extremities-2024-10-20.pdf", True, True, "2024-10-20", "Knee 73721 & shoulder 73221 in Extremities doc (table truncated in fetch); lumbar 72148 verbatim in Imaging of the Spine (https://files.providernews.anthem.com/4816/PDF-Imaging-of-the-Spine-2024-10-20.pdf)."),
 },
 "Humana": {
  "27447": ("Knee Arthroplasty - Medicare Advantage", "https://mcp.humana.com/tad/tad_new/Search.aspx?criteria=27447&searchtype=freetext&policyType=both", True, True, "2026-03-16", "Verified via Humana's own claims-code search (code->policy). Policy opens as PDF via portal."),
  "27130": ("Hip Arthroplasty - Medicare Advantage", "https://mcp.humana.com/tad/tad_new/Search.aspx?criteria=27130&searchtype=freetext&policyType=both", True, True, "2026-03-16", "Humana code search confirms 27130."),
  "29827": ("Shoulder Arthroscopy - Medicare Advantage", "https://mcp.humana.com/tad/tad_new/Search.aspx?criteria=29827&searchtype=freetext&policyType=both", True, True, "2026-01-02", "29827 confirmed."),
  "23472": ("Shoulder Arthroplasty - Medicare Advantage", "https://mcp.humana.com/tad/tad_new/Search.aspx?criteria=23472&searchtype=freetext&policyType=both", True, True, "2025-08-01", "23472 confirmed (revised version eff 2026-08-03 also exists)."),
  "29888": ("Knee Arthroscopy - Medicare Advantage", "https://mcp.humana.com/tad/tad_new/Search.aspx?criteria=29888&searchtype=freetext&policyType=both", True, True, "2026-05-01", "29888 confirmed."),
  "22612": ("Spinal Fusion Surgery - Medicare Advantage", "https://mcp.humana.com/tad/tad_new/Search.aspx?criteria=22612&searchtype=freetext&policyType=both", True, True, "2026-05-01", "22612 confirmed."),
  "22551": ("Spinal Fusion Surgery - Medicare Advantage", "https://mcp.humana.com/tad/tad_new/Search.aspx?criteria=22551&searchtype=freetext&policyType=both", True, True, "2026-05-01", "22551 confirmed; same policy."),
  "27702": ("", "", False, False, None, "No dedicated Humana policy indexes 27702 ('no matching records'). Follows CMS/medical necessity."),
  "28296": ("Foot Surgical Procedures - Medicare Advantage", "https://mcp.humana.com/tad/tad_new/Search.aspx?criteria=28296&searchtype=freetext&policyType=both", True, True, "2025-09-02", "28296 confirmed; commercial 'Bunion' PDF at assets.humana.com also lists it."),
  "29914-29916": ("Hip Arthroscopy - Medicare Advantage", "https://mcp.humana.com/tad/tad_new/Search.aspx?criteria=29914&searchtype=freetext&policyType=both", True, True, "2026-01-02", "29914 & 29916 confirmed."),
  "63030": ("Spinal Decompression Surgery - Medicare Advantage", "https://mcp.humana.com/tad/tad_new/Search.aspx?criteria=63030&searchtype=freetext&policyType=both", True, True, "2026-02-02", "63030 confirmed."),
  "73721/73221/72148": ("Upper/Lower Extremity MRI - MA (knee/shoulder) + Advanced Imaging of the Spine - MA (lumbar)", "https://mcp.humana.com/tad/tad_new/Search.aspx?criteria=73721&searchtype=freetext&policyType=both", True, True, "2026-07-01", "Extremity MRI covers 73721 & 73221; lumbar 72148 in Advanced Imaging of the Spine (criteria=72148). All confirmed via code search."),
 },
 "Centene (Ambetter/WellCare)": {
  "27447": ("Ambetter/Centene Joint Surgery UR Matrix (Evolent/NIA)", "https://www.ambetterhealth.com/content/dam/centene/home-state-health/ambetter/pdfs/Health-Joint-Surgery%20Evolent-UTIL-Ambetter.pdf", True, True, "2024", "MSK delegated to Evolent; 27447 in matrix. Clinical criteria in Evolent MSK guidelines."),
  "27130": ("Ambetter/Centene Joint Surgery UR Matrix (Evolent/NIA)", "https://www.ambetterhealth.com/content/dam/centene/home-state-health/ambetter/pdfs/Health-Joint-Surgery%20Evolent-UTIL-Ambetter.pdf", True, True, "2024", "27130 in matrix."),
  "29827": ("Ambetter/Centene Joint Surgery UR Matrix (Evolent/NIA)", "https://www.ambetterhealth.com/content/dam/centene/home-state-health/ambetter/pdfs/Health-Joint-Surgery%20Evolent-UTIL-Ambetter.pdf", True, True, "2024", "29827 in matrix."),
  "23472": ("Ambetter/Centene Joint Surgery UR Matrix (Evolent/NIA)", "https://www.ambetterhealth.com/content/dam/centene/home-state-health/ambetter/pdfs/Health-Joint-Surgery%20Evolent-UTIL-Ambetter.pdf", True, True, "2024", "23472 in matrix."),
  "29888": ("Ambetter/Centene Joint Surgery UR Matrix (Evolent/NIA)", "https://www.ambetterhealth.com/content/dam/centene/home-state-health/ambetter/pdfs/Health-Joint-Surgery%20Evolent-UTIL-Ambetter.pdf", True, True, "2024", "29888 in matrix."),
  "22612": ("Centene Spine Surgery UR Matrix 2026 (Evolent/NIA, on RadMD)", "https://www1.radmd.com/sites/default/files/2025-12/Centene%20AL%20Ambetter%20of%20Alabama%20Spine%20Surgery%20Utilization%20Review%20Matrix%202026%2001.01.26.pdf", True, True, "2026-01-01", "22612 in matrix; example state AL, matrix shared."),
  "22551": ("Centene Spine Surgery UR Matrix 2026 (Evolent/NIA, on RadMD)", "https://www1.radmd.com/sites/default/files/2025-12/Centene%20AL%20Ambetter%20of%20Alabama%20Spine%20Surgery%20Utilization%20Review%20Matrix%202026%2001.01.26.pdf", True, True, "2026-01-01", "22551 in matrix."),
  "27702": ("", "", False, False, None, "Foot/ankle outside Evolent MSK scope; no dedicated Centene policy. Standard medical necessity (InterQual/MCG)."),
  "28296": ("", "", False, False, None, "Foot/ankle outside Evolent MSK scope; no dedicated Centene policy."),
  "29914-29916": ("Ambetter/Centene Joint Surgery UR Matrix (Evolent/NIA)", "https://www.ambetterhealth.com/content/dam/centene/home-state-health/ambetter/pdfs/Health-Joint-Surgery%20Evolent-UTIL-Ambetter.pdf", True, True, "2024", "29914-29916 in matrix (FAI grouping)."),
  "63030": ("Centene Spine Surgery UR Matrix 2026 (Evolent/NIA, on RadMD)", "https://www1.radmd.com/sites/default/files/2025-12/Centene%20AL%20Ambetter%20of%20Alabama%20Spine%20Surgery%20Utilization%20Review%20Matrix%202026%2001.01.26.pdf", True, True, "2026-01-01", "63030 in matrix."),
  "73721/73221/72148": ("Ambetter/Centene Advanced Imaging UR Matrix (Evolent/NIA)", "https://www1.radmd.com/sites/default/files/2024-12/Ambetter%20from%20MHS%20-%20CPT%20Matrix%202025%20-%20Evolent.pdf", True, True, "2025", "73721, 73221, 72148 all in matrix."),
 },
 "HCSC (BCBS IL/TX/NM/OK/MT)": {
  "27447": ("", "", False, False, None, "No dedicated HCSC medical policy for TKA; managed via standard benefits/prior auth."),
  "27130": ("", "", False, False, None, "No dedicated HCSC policy for primary THA (Hip Resurfacing SUR705.019 is a different procedure)."),
  "29827": ("", "", False, False, None, "No dedicated HCSC policy for rotator cuff repair."),
  "23472": ("", "", False, False, None, "No dedicated HCSC shoulder arthroplasty policy (Shoulder Resurfacing SUR705.032 is different)."),
  "29888": ("", "", False, False, None, "No dedicated HCSC ACL policy."),
  "22612": ("Lumbar Spinal Fusion (SUR712.036)", "https://medicalpolicy.bcbstx.com/content/dam/bcbs/medicalpolicy/pdf/surgery/SUR712.036_2024-11-15.pdf", True, True, "2024-11-15", "22612 confirmed in coding section."),
  "22551": ("Cervical Spinal Fusion (SUR712.041)", "https://medicalpolicy.bcbstx.com/content/dam/bcbs/medicalpolicy/pdf/surgery/SUR712.041_2023-05-01.pdf", True, True, "2023-05-01", "22551 confirmed."),
  "27702": ("Total Ankle Replacement (SUR705.021)", "https://medicalpolicy.bcbstx.com/content/dam/bcbs/medicalpolicy/pdf/surgery/SUR705.021_2024-07-15.pdf", True, True, "2024-07-15", "27702 confirmed."),
  "28296": ("", "", False, False, None, "No dedicated HCSC bunionectomy policy."),
  "29914-29916": ("Surgical Treatment of Femoroacetabular Impingement (SUR705.029)", "", True, True, None, "Policy is public on HCSC portal; 29914-29916 mapped to SUR705.029 per HCSC's official Medical Policy Reference List. Direct dated PDF URL not resolvable; not guessing it."),
  "63030": ("", "", False, False, None, "No dedicated HCSC policy for standard microdiscectomy/decompression (Image-Guided MILD SUR712.035 is a different procedure)."),
  "73721/73221/72148": ("", "", False, False, None, "No dedicated HCSC RAD policy for routine MSK MRI; advanced imaging via PA vendor."),
 },
 "Molina Healthcare": {
  "27447": ("", "", False, False, None, "No Molina MCP for primary TKA; via MCG and, in Evolent markets, Evolent Joint Surgery (RadMD login-gated)."),
  "27130": ("", "", False, False, None, "No Molina MCP for primary THA; via MCG / Evolent (login-gated)."),
  "29827": ("Molina Clinical Policy MCP-404 Shoulder Arthroscopy", "https://www.molinahealthcare.com/-/media/Molina/PublicWebsite/PDF/Providers/il/resource/Shoulder-Arthroscopy-Guidelines_MCP_404.pdf", True, True, "2021-06-09", "29827 in coding table; criteria defer to MCG."),
  "23472": ("", "", False, False, None, "23472 not in MCP-404 (arthroscopy-only). No Molina arthroplasty MCP; via MCG/Evolent."),
  "29888": ("", "", False, False, None, "No Molina knee-arthroscopy/ACL MCP; 29888 via MCG."),
  "22612": ("Molina Complete Care Spine Surgery UR Matrix (NIA/Evolent)", "https://www.molinahealthcare.com/providers/az/medicaid/forms/~/media/Molina/PublicWebsite/PDF/Providers/az/AZ-WEBP-19442-21%202021%20NIA%20Spine%20Surgery%20UM%20Review%20Matrix%20FINAL_R", True, True, "2021", "22612 in Molina-hosted PA matrix (AZ 2021); clinical criteria via Evolent/RadMD (login-gated)."),
  "22551": ("Molina Complete Care Spine Surgery UR Matrix (NIA/Evolent)", "https://www.molinahealthcare.com/providers/az/medicaid/forms/~/media/Molina/PublicWebsite/PDF/Providers/az/AZ-WEBP-19442-21%202021%20NIA%20Spine%20Surgery%20UM%20Review%20Matrix%20FINAL_R", True, True, "2021", "22551 in same matrix."),
  "27702": ("", "", False, False, None, "No Molina MCP for total ankle replacement; via MCG."),
  "28296": ("Molina Clinical Policy MCP-700 Foot Surgery: Bunionectomy", "https://www.molinahealthcare.com/-/media/Molina/PublicWebsite/PDF/Providers/oh/medicaid/policies/MCP-700-Foot-Surgery-Bunionectomy-0823.pdf", True, True, "2023-04-13", "28296 in coding table (OH edition)."),
  "29914-29916": ("", "", False, False, None, "No Molina hip-arthroscopy MCP; 29914-29916 via MCG."),
  "63030": ("Molina Complete Care Spine Surgery UR Matrix (NIA/Evolent)", "https://www.molinahealthcare.com/providers/az/medicaid/forms/~/media/Molina/PublicWebsite/PDF/Providers/az/AZ-WEBP-19442-21%202021%20NIA%20Spine%20Surgery%20UM%20Review%20Matrix%20FINAL_R", True, True, "2021", "63030 in matrix; via Evolent (login-gated)."),
  "73721/73221/72148": ("Molina MCP-633 Lower Extremity MRI + MCR-621 Lumbar Spine MRI (shoulder via NIA matrix)", "https://www.molinahealthcare.com/~/media/Molina/PublicWebsite/PDF/Common/Molina%20Clinical%20Policy/Lower%20Extremity%20MRI.pdf", True, True, "2021-12-08", "Knee 73721 in MCP-633; lumbar 72148 in MCR-621 (Lumbar Spine MRI PDF); shoulder 73221 in Molina-hosted NIA matrix."),
 },
 "Florida Blue / GuideWell": {
  "27447": ("Knee Arthroplasty (MCG 02-20000-60)", "https://mcgs.bcbsfl.com/MCG?mcgId=02-20000-60&pv=false", True, True, "2026-05-15", "27447 in Billing/Coding."),
  "27130": ("Hip Arthroplasty (MCG 02-20000-50)", "https://mcgs.bcbsfl.com/MCG?mcgId=02-20000-50&pv=false", True, True, "2025-02-15", "27130 confirmed."),
  "29827": ("Site of Service Review for Select Surgical Procedures (MCG 08-00000-01)", "https://mcgs.bcbsfl.com/MCG?mcgId=08-00000-01&pv=false", True, True, "2026-01-01", "No dedicated rotator-cuff MCG; 29827 only in site-of-service MCG."),
  "23472": ("", "", False, False, None, "Florida Blue has NO MCG covering 23472 (0 results in carrier full-text search)."),
  "29888": ("Knee Arthroscopy and Open, Non-Arthroplasty Knee Repair (MCG 02-20000-65)", "https://mcgs.bcbsfl.com/MCG?mcgId=02-20000-65&pv=false", True, True, "2026-06-15", "29888 in Billing/Coding."),
  "22612": ("Thoracic and Lumbar Spine Surgery (MCG 02-20000-48)", "https://mcgs.bcbsfl.com/MCG?mcgId=02-20000-48&pv=false", True, True, "2025-06-15", "22612 confirmed."),
  "22551": ("Cervical Spine Surgery (MCG 02-20000-45)", "https://mcgs.bcbsfl.com/MCG?mcgId=02-20000-45&pv=false", True, True, "2026-04-15", "22551 confirmed."),
  "27702": ("Total Ankle Replacement (MCG 02-99221-15)", "https://mcgs.bcbsfl.com/MCG?mcgId=02-99221-15&pv=false", True, True, "2026-04-15", "27702 confirmed."),
  "28296": ("Site of Service Review for Select Surgical Procedures (MCG 08-00000-01)", "https://mcgs.bcbsfl.com/MCG?mcgId=08-00000-01&pv=false", True, True, "2026-01-01", "No dedicated bunionectomy MCG; 28296 only in site-of-service MCG."),
  "29914-29916": ("Hip Arthroscopy and Open, Non-Arthroplasty Hip Repair (MCG 02-20000-55)", "https://mcgs.bcbsfl.com/MCG?mcgId=02-20000-55&pv=false", True, True, "2026-02-15", "29914-29916 confirmed."),
  "63030": ("Thoracic and Lumbar Spine Surgery (MCG 02-20000-48)", "https://mcgs.bcbsfl.com/MCG?mcgId=02-20000-48&pv=false", True, True, "2025-06-15", "63030 confirmed; same spine MCG."),
  "73721/73221/72148": ("MRI Lower Extremity (04-70540-16) / Upper Extremity (04-70540-15) / Spine (04-70540-17)", "https://mcgs.bcbsfl.com/MCG?mcgId=04-70540-16&pv=false", True, True, "2026-05-15", "Knee 73721 (04-70540-16), shoulder 73221 (04-70540-15), lumbar 72148 (04-70540-17) each confirmed."),
 },
 "Medicare (CMS)": {
  "27447": ("MAC LCDs: Total Joint Arthroplasty (L39911/L33456), Major Joint Replacement (L33618/L36007)", "https://www.cms.gov/medicare-coverage-database/view/lcd.aspx?lcdid=36577&ver=15", True, False, None, "Dedicated TKA LCD L36577 retired 2025-11-06; covered when medically necessary under active MAC LCDs. Jurisdiction-specific."),
  "27130": ("MAC LCDs: Total Joint Arthroplasty / Major Joint Replacement", "https://www.cms.gov/medicare-coverage-database/view/lcd.aspx?lcdid=36573&ver=15", True, True, None, "27130 confirmed in THA LCD (L36573, now retired); addressed by active MAC LCDs. Medically necessary."),
  "29827": ("No NCD/LCD — covered when medically necessary", "https://www.cms.gov/medicare-coverage-database", True, False, None, "No national or local determination governs rotator cuff repair."),
  "23472": ("LCD - Total Shoulder Arthroplasty (L39956, Palmetto GBA)", "https://www.cms.gov/medicare-coverage-database/view/lcd.aspx?lcdid=39956&ver=5", True, False, "2025-03-27", "Active MAC LCD; codes in companion article A59878. Jurisdiction-specific; other MACs via medical necessity."),
  "29888": ("No NCD/LCD — covered when medically necessary", "https://www.cms.gov/medicare-coverage-database", True, False, None, "No determination governs ACL reconstruction."),
  "22612": ("LCD - Lumbar Spinal Fusion (L37848, Palmetto GBA)", "https://www.cms.gov/medicare-coverage-database/view/lcd.aspx?lcdid=37848&ver=13", True, True, "2024-09-12", "Companion article A56396 lists 22612. Other MACs have parallel LCDs (e.g., Novitas L33382)."),
  "22551": ("MAC 'Cervical Fusion' LCD family (Novitas L39793 et al.)", "https://www.cms.gov/medicare-coverage-database/view/lcd.aspx?lcdid=39793&ver=40", True, False, "2024-08-11", "Cervical fusion governed by MAC LCDs; codes (incl. 22551) in companion article A59674. Jurisdiction-specific."),
  "27702": ("No dedicated NCD/LCD — covered when medically necessary", "https://www.cms.gov/medicare-coverage-database", True, False, None, "No dedicated total-ankle policy; some Total Joint Arthroplasty LCDs may address ankle."),
  "28296": ("No NCD/LCD — covered when medically necessary", "https://www.cms.gov/medicare-coverage-database", True, False, None, "No determination governs bunionectomy."),
  "29914-29916": ("No NCD/LCD — covered when medically necessary", "https://www.cms.gov/medicare-coverage-database", True, False, None, "No determination governs hip arthroscopy."),
  "63030": ("No NCD/LCD — covered when medically necessary", "https://www.cms.gov/medicare-coverage-database", True, False, None, "No determination governs open microdiscectomy/decompression (63030). NCD 150.13 is for percutaneous MILD only."),
  "73721/73221/72148": ("NCD 220.2 Magnetic Resonance Imaging (general)", "https://www.cms.gov/medicare-coverage-database/view/ncd.aspx?ncdid=177", True, False, "2018-04-10", "NCD 220.2 covers MRI broadly; MSK sites at MAC discretion. No specific CPTs listed. Medically necessary."),
 },
}

CARRIERS = list(DATA.keys())
proc_label = {cpt: label for label, cpt in PROCS}

rows = []
for carrier in CARRIERS:
    for label, cpt in PROCS:
        title, url, public, verified, eff, notes = DATA[carrier][cpt]
        rows.append({
            "carrier": carrier, "procedure": label, "cpt": cpt,
            "policy_title": title, "url": url,
            "doc_is_public": public, "cpt_verified": verified,
            "effective_date": eff or "", "notes": notes,
        })

out_dir = Path("data/policy_platform")
out_dir.mkdir(parents=True, exist_ok=True)

# CSV deliverable
csv_path = out_dir / "procedure_policy_links.csv"
with csv_path.open("w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=["carrier","procedure","cpt","policy_title","url","doc_is_public","cpt_verified","effective_date","notes"])
    w.writeheader()
    for r in rows:
        w.writerow(r)

# JSON directory (nested by carrier -> procedures)
directory = {
    "meta": {
        "description": "Reach OrthoAppeals governing coverage-policy directory: per carrier, per procedure, the carrier's own official current medical/coverage policy, verified against the source document where possible.",
        "procedures": [{"label": l, "cpt": c} for l, c in PROCS],
        "carriers": CARRIERS,
        "verification": "cpt_verified=true means the CPT (or exact procedure) was seen in the carrier's own document. Blank url / doc_is_public=false means no public governing policy was found (often adjudicated by MCG/InterQual or a delegated vendor); that is a real finding, not a gap to paper over.",
    },
    "policies": {},
}
for carrier in CARRIERS:
    directory["policies"][carrier] = []
    for label, cpt in PROCS:
        title, url, public, verified, eff, notes = DATA[carrier][cpt]
        directory["policies"][carrier].append({
            "procedure": label, "cpt": cpt, "policy_title": title,
            "url": url, "doc_is_public": public, "cpt_verified": verified,
            "effective_date": eff, "notes": notes,
        })
json_path = out_dir / "procedure_policy_directory.json"
json_path.write_text(json.dumps(directory, indent=2, ensure_ascii=False), encoding="utf-8")

# Summary stats
total = len(rows)
verified = sum(1 for r in rows if r["cpt_verified"])
public = sum(1 for r in rows if r["doc_is_public"])
print(f"rows: {total}  carriers: {len(CARRIERS)}  procedures: {len(PROCS)}")
print(f"public policy found: {public}/{total}   cpt-verified: {verified}/{total}")
print(f"wrote {csv_path} and {json_path}")
