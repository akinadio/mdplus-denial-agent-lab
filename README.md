# OrthoAppeals

A free, plain-language tool that helps a patient (or their surgeon's office)
appeal a denied orthopedic surgery — grounded in the payer's **own published
coverage policy**, not in a model's memory.

This README is the map of the whole project. Everything the tool is made of is
in this repository: the patient app, the AI backend, the policy directories that
make the appeals real, the research that produced them, the deployment scripts,
and the tests.

> Research/product software for a patient-facing tool. Not medical advice, not
> legal advice, not a coverage guarantee.

---

## 1. What it does, end to end

1. A patient answers a short flow — surgery, state, insurer, what conservative
   care they've tried — and can photograph their **denial letter** and
   **insurance card**.
2. The backend reads those images (`synthetic_harness/extract.py`), pulling out
   structured fields with a confidence score on every one: name, insurer, the
   **exact plan**, member/group ID, denial reason, appeal deadline, denied CPT
   codes. Anything blurry or missing is handed back to the patient to confirm —
   never guessed.
3. A retrieval agent finds and reads the payer's **current governing coverage
   policy** for that procedure (`api_runner.py` + `providers.py`), and the app
   tells the patient plainly whether we hold that policy on file.
4. The patient gets an appeal plan, a drafted appeal letter that quotes their
   plan's own rules back at it, a deadline, and a per-carrier
   **"where and how to send it"** (portal / phone / fax / mailing address).

## 2. Repository map

| Path | What lives there |
|---|---|
| `mockups/map/index.html` | **The patient app** — the entire single-file frontend flow. |
| `mockups/assets/data.js` | App content/config: procedures, per-state insurer lists, conservative-care questions, per-carrier policy-access and appeal-submission directories. |
| `mockups/assets/coverage.js` | **Generated.** Per-option coverage map (surgery × state × insurer → do we hold the policy, and where). |
| `mockups/legal.html` | Terms of Use & Privacy Notice. |
| `scripts/build_demo.py` | Builds the self-contained offline demo → `dist/orthoappeal-demo.html`. |
| `synthetic_harness/extract.py` | Denial letter + insurance card reader (vision → structured, confidence-scored fields; plan-pinning; blur guard). |
| `synthetic_harness/server.py` | HTTP API, including `POST /api/intake/read`. |
| `synthetic_harness/api_runner.py`, `providers.py` | The retrieval engine and the multi-provider adapter (Claude / GPT / Gemini) used for the accuracy bake-off. |
| `synthetic_harness/` (rest) | Encryption at rest, retention, rate limiting, spend cap, appeal-letter generation, episode store. |
| `data/policy_platform/` | **The policy directories** — see §4. |
| `deploy/` | `setup.sh` (one-command host stand-up) and `DEPLOY.md` (plain-English hosting guide). |
| `tests/` | 200 passing tests, no API key or network required. |
| `docs/` | Architecture, security review, deploy notes, and the original lab README. |
| `HANDOFF.md` | Backend change log and roadmap. |

## 3. Run it

**The patient app, offline (no key, no server):**

```bash
python3 scripts/build_demo.py
open dist/orthoappeal-demo.html     # entire flow runs against canned data
```

**The tests:**

```bash
python3 -m pytest tests/ -q          # 200 passed, 4 skipped
```

**The live backend** (needs an Anthropic API key as a server secret):

```bash
python3 -m synthetic_harness.server --port 8781 --host 127.0.0.1
```

**Put it on the internet:** follow `deploy/DEPLOY.md`. Short version — rent a
small Linux box (~$6/month), point a domain at it, then:

```bash
sudo ORTHO_DOMAIN=yourdomain.com bash deploy/setup.sh
```

That installs Python + Caddy (automatic HTTPS), the systemd services, a
generated encryption key, and a daily spend cap. Then put your API key in
`/etc/mdplus/mdplus.env` and restart.

## 4. The policy directories — the heart of the product

Appeals are only as good as the document behind them, so coverage is tracked
explicitly and honestly. Nothing is marked verified unless the document was
fetched and confirmed to be the real, current, public medical-necessity criteria
for that specific procedure. A code list, a utilization matrix, a search page,
or a login wall does **not** count.

| File | What it is |
|---|---|
| `app_option_policy_directory.csv` | **6,776 rows — one for every surgery option the live app offers** (14 surgeries × 51 states × each state's insurers + Medicare + Medicaid), each with status and anchored policy URL. |
| `app_option_imaging_directory.csv` | **1,936 rows — the advanced-imaging options** (4 MRI codes × the same 484 state × insurer pairs). Kept in a separate file on purpose; see the note below. |
| `full_surgery_policy_directory.csv` | 7,020 rows at payer × plan × line-of-business × state × surgery. |
| `policy_registry_v2.csv` | One row per distinct policy document (the research registry). |
| `url_verification_ledger.json` | Per-(URL, procedure) verdicts with effective dates and verbatim criteria quotes. |
| `research/`, `research2/` | Raw findings from every research sweep, payer by payer. |
| `medicaid_coverage_by_state.json`, `insurers_by_state.json` | State Medicaid entry points; per-state insurer lists. |

**Current coverage** (regenerate anytime; see §5):

**Surgery — 6,776 options, 301 distinct policy documents, nothing left unresearched:**

- **3,436 (50.7%) end in a complete, actionable answer.** That is 2,217 anchored
  to a document that actually contains medical-necessity criteria for that
  procedure; 547 honestly resolved as *Medicare: no LCD exists* (general medical
  necessity governs — itself useful in an appeal); 540 where we confirmed the
  payer publishes no policy; and 132 where the payer's own precertification list
  does not include the code, so **no permission is needed at all** — the
  strongest answer a patient can get.
- **3,278 (48.4%) are vendor-locked or blocked** — the payer keeps criteria in a
  private tool (InterQual, MCG, eviCore portal, TurningPoint, Evolent-gated
  markets), or the document is behind a login, stale, or a code list with no
  criteria. Labeled as such, never papered over, and each carries an
  insurer-specific route to demand the criteria used in the denial.
- **62 (0.9%) are a correct, current, public document whose criteria section we
  located but could not extract** — the Carelon Joint Surgery bundle, which
  truncates inside the Hip section on every route tried. See §6.

**Advanced imaging — 1,936 options, 11 distinct documents, newly opened:**

- **524 (27.1%) complete**, including 279 anchored to a vendor guideline that
  names the CPT explicitly (eviCore V1.0.2026, Carelon RBM03/RBM05, Aetna CPB
  0171/0236) and 191 resolved as Medicare NCD 220.2 — which expressly declines
  to give site-specific criteria.
- **252 (13.0%) document found, text blocked** — the UnitedHealthcare V3.0.2026
  and 2026 Evolent manuals are the right current documents but truncate before
  their MRI sections.
- **1,064 (55.0%) not yet researched.** This is a brand-new procedure area
  opened in August 2026 and the research budget ran out partway through the
  vendor map. It is the largest single open item in the project.

> **Why imaging is a separate file.** A payer's *imaging* vendor is frequently
> not its *surgery* vendor. Molina routes imaging to Evolent while using MCG
> elsewhere; Simply Healthcare delegates Carelon for radiology only and sends
> podiatry to a different vendor entirely; Florida Blue uses NIA/RadMD for
> imaging while reviewing joint surgery itself. Folding imaging into the surgery
> directory would have let a surgery finding silently fill an imaging cell.
> `tests/test_imaging_directory.py` makes that structural.

The app never pretends. If a patient picks a combination we don't hold, the
result page says so and asks them to upload their policy.

> **Why "verified" moved twice.** An August 2026 audit re-read every state
> Medicaid document behind a `VERIFIED` cell against a strict test: *does this
> document contain indication-level criteria for this procedure — imaging
> findings, symptom duration, failed conservative care — that a patient could
> quote?* Most state Medicaid manuals do not. 565 cells moved to the new
> `PROCESS DOC ONLY` state, and 4 California cells moved the other way. A
> second sweep then researched the three procedures that had never been covered
> (partial knee, knee arthroscopy, shoulder labral repair) across every national
> payer and every Medicare contractor, and caught that **the entire Cigna
> eviCore guideline series had version-bumped to V1.0.2026 on 2026-08-04**,
> making 380 URLs we served stale. Those are refreshed. Both numbers moved
> because the underlying facts were checked, not because the target changed.

## 5. Regenerating everything

```bash
python3 scripts/build_full_surgery_directory.py   # payer × plan × state × surgery
python3 scripts/build_imaging_directory.py        # -> app_option_imaging_directory.csv
python3 scripts/build_coverage_js.py              # -> mockups/assets/coverage.js
python3 scripts/build_demo.py                     # -> dist/orthoappeal-demo.html
python3 scripts/coverage_report.py                # -> dist/coverage.html dashboard
```

## 6. Honest limits

- Some payers publish **no public criteria at all** (UnitedHealthcare defers to
  InterQual; others to MCG/eviCore). Those cells can never become "verified" —
  they are labeled, not papered over.
- A handful of state Medicaid sites are login-gated or block automated access
  (Kansas, New Hampshire, Nevada, Missouri, South Carolina, DC).
- The accuracy evaluation across providers has not been run against real
  denials yet. Do that before real patients rely on the output.
- No auth or per-user rate limiting on the API yet; the daily spend cap is the
  current cost guard.
- Most **state Medicaid** programs publish no procedure-specific orthopedic
  criteria at all — only Massachusetts, North Carolina and California do, and
  even they only for some procedures. Everywhere else the real criteria sit
  with the member's managed-care plan, in InterQual or MCG.
- **The Carelon Joint Surgery knee sections are still unread.** Six independent
  routes tried; every one truncates inside the Hip section, which sits before
  Knee. The section anchors are same-page fragments, not separate URLs; the
  WordPress REST API returns empty; `?print=print` returns only the nav. The
  link is safe to give a patient — someone still needs to read the knee
  sections by hand. Nothing is quoted, because an early attempt invented knee
  criteria past the truncation point that contradicted the document's own code
  table.
- **A legal question worth resolving before launch.** The Carelon guideline page
  carries a notice that the Guidelines are proprietary and "cannot be sold,
  assigned, leased, licensed, reproduced or distributed without the written
  consent of Carelon," and prohibits use by an "external AI entity." Quoting the
  criteria a payer applied to a patient's own denial, back at that payer in that
  patient's own appeal, is a different act from redistributing the guideline —
  but that distinction needs a lawyer's read, not ours.
- **The citation cache is live but small** — 8 seeded entries in
  `data/policy_platform/known_citations.json`, none human-reviewed yet. Every
  hit is cross-checked against our own verification record and handed to the
  retrieval agent as a lead with that verdict attached, never as an answer.
  Check its size with
  `python3 -c "from synthetic_harness import citation_cache as c; print(len(c._load()))"`.

See `HANDOFF.md` for the full roadmap.
