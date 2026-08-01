# Reach OrthoAppeals — procedure × carrier policy directory

`procedure_policy_links.csv` and `procedure_policy_directory.json` map each of
the **10 Reach carriers** to its own official current governing coverage policy
for each of the **12 procedures**, built by extending the TKA-anchor retrieval to
every procedure and verifying each link against the source document.

## Coverage (as built)

- 10 carriers: UnitedHealthcare, Aetna (CVS Health), Cigna, Elevance/Anthem BCBS,
  Humana, Centene (Ambetter/WellCare), HCSC (BCBS IL/TX/NM/OK/MT), Molina,
  Florida Blue/GuideWell, Medicare (CMS).
- 12 procedures: TKA 27447, THA 27130, rotator cuff 29827, total shoulder 23472,
  ACL 29888, lumbar fusion 22612, ACDF 22551, total ankle 27702, bunionectomy
  28296, hip arthroscopy 29914–29916, lumbar microdiscectomy/decompression 63030,
  MSK MRI (knee 73721 / shoulder 73221 / lumbar 72148).
- 120 rows total: **99** have a public governing policy located; **87** were
  CPT-verified inside the carrier's own document.

## Columns

`carrier, procedure, cpt, policy_title, url, doc_is_public, cpt_verified,
effective_date, notes`.

- `cpt_verified = true` — the CPT (or the exact procedure) was seen in the
  carrier's own document.
- Blank `url` / `doc_is_public = false` — no public governing policy was found.
  This is usually because the carrier has no dedicated policy for that procedure
  (adjudicated by MCG/InterQual) or delegates it to a vendor whose criteria are
  login-gated. **That is a real finding, not a gap to paper over** — the appeal
  agent should treat it as "no public carrier policy; argue medical necessity."

## Important notes

- **National, not per-state.** These commercial medical policies are published
  nationally per carrier and apply across states; HCSC's set is shared across its
  5 Blue states. Medicaid is genuinely state-specific and is NOT in this file —
  it needs a separate per-state pass.
- **Delegated UM.** Cigna → eviCore; Centene → Evolent/NIA (RadMD); parts of
  Molina → Evolent; Anthem → Carelon. Where the carrier's own copy is WAF-blocked
  or login-gated, the row cites the delegated vendor's official adopted guideline
  and says so in `notes`.
- **Medicare** works differently: many ortho procedures have no NCD/LCD and are
  covered on medical necessity; where a MAC LCD governs, it's jurisdiction-
  specific. The rows capture this.
- **Recheck cadence.** Effective dates are captured where visible; payer policies
  update a few times a year. Re-run the retrieval periodically to refresh links.

Regenerate with `python3 scripts/build_policy_directory.py` (the committed builder).
