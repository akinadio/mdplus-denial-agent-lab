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
| `tests/` | 168 passing tests, no API key or network required. |
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
python3 -m pytest tests/ -q          # 168 passed, 4 skipped
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
| `app_option_policy_directory.csv` | **6,776 rows — one for every option the live app offers** (14 surgeries × 51 states × each state's insurers + Medicare + Medicaid), each with status and anchored policy URL. |
| `full_surgery_policy_directory.csv` | 7,020 rows at payer × plan × line-of-business × state × surgery. |
| `policy_registry_v2.csv` | One row per distinct policy document (the research registry). |
| `url_verification_ledger.json` | Per-(URL, procedure) verdicts with effective dates and verbatim criteria quotes. |
| `research/`, `research2/` | Raw findings from every research sweep, payer by payer. |
| `medicaid_coverage_by_state.json`, `insurers_by_state.json` | State Medicaid entry points; per-state insurer lists. |

**Current coverage** (regenerate anytime; see §5):

- **2,125 app options anchored to a verified public policy document**
- **394** honestly resolved as *Medicare: no LCD exists* (general medical
  necessity governs — itself useful in an appeal)
- **1,435** where the payer keeps criteria in a private tool (InterQual, MCG,
  eviCore portal, TurningPoint) — labeled as such, with the patient told they
  can demand the criteria used in their denial
- **2,163** not yet researched (mostly 3 app procedures added after the main
  research set, plus the long tail of small regional payers)

The app never pretends. If a patient picks a combination we don't hold, the
result page says so and asks them to upload their policy.

## 5. Regenerating everything

```bash
python3 scripts/build_full_surgery_directory.py   # payer × plan × state × surgery
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

See `HANDOFF.md` for the full roadmap.
