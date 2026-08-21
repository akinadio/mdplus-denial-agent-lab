# MD+ Denial Agent Lab

An internal, synthetic-patient prototype that lets an operator enter a denial
letter and insurance details, then launches two isolated AI agents:

1. **Library agent** — searches only a configured internal policy library.
2. **Web agent** — performs fresh retrieval of official online policy sources.

The UI streams a patient-readable retrieval trace, displays the selected source,
requires a source-review decision, asks targeted follow-up questions, and shows
the next evidence-supported action.

> This is research software for synthetic or de-identified cases. It is not a
> production patient portal, medical advice, legal advice, or a coverage
> guarantee.

## What is included

- React/Vite intake and review UI
- Python HTTP API and episode orchestrator
- Codex CLI subprocess launch for both retrieval agents
- Separate work orders and result schemas
- macOS read barrier separating the live-web agent from the policy library
- Hash-chained episode and review logs
- Source confirmation, rejection, replacement upload, and correction runs
- Patient follow-up loop
- Optional sealed-case evaluation and human adjudication
- Unit tests and architecture documentation

Real patient records, episode outputs, controller keys, and the internal policy
library are intentionally excluded.

## Requirements

- macOS for the web agent's `sandbox-exec` isolation
- Python 3.11+
- Node.js 20+
- Codex CLI installed and authenticated

Check the CLI:

```bash
codex --version
```

## Quick start

```bash
git clone <your-repository-url>
cd mdplus-denial-agent-lab
./scripts/run_denial_simulation_lab.sh
```

Then open `http://127.0.0.1:8766`.

The first `npm ci` uses the committed lockfile. The Python runtime uses the
standard library.

## Configure the library agent

By default:

- policy documents: `data/policy_library/`
- registry metadata: `data/policy_platform/`
- private run output: `outputs/synthetic_patient_simulations/`

For an existing private library:

```bash
export MDPLUS_POLICY_LIBRARY_ROOT="/absolute/path/to/policy_library"
export MDPLUS_POLICY_PLATFORM_ROOT="/absolute/path/to/policy_platform"
./scripts/run_denial_simulation_lab.sh
```

The platform folder should contain:

- `source_registry.json`
- `source_registry.csv`
- `criteria_extractions.json`

Empty starter files are included so the application can start without
publishing proprietary policy content. The library agent will return a blocker
until useful sources are configured.

## Patient intake

The current UI accepts:

- denial-letter text
- payer and plan name
- state and product clue
- procedure/test and optional CPT
- patient-visible notes
- retrieval mode: both, library only, or web only

Starting an episode writes the patient-visible submission into an isolated
episode and starts the selected agents concurrently.

## Data boundaries

- Only patient-visible messages are copied into agent work orders.
- The library agent has no live-web permission in its prompt and sandbox.
- The web agent is wrapped in an OS-level read barrier denying the internal
  library, platform metadata, sealed truth, controller keys, and sibling arm.
- Selected sources are labeled as governing policies or supporting documents.
- Observable retrieval events are logged; private chain-of-thought is neither
  requested nor stored.

See [SECURITY.md](SECURITY.md), [docs/synthetic_harness_architecture.md](docs/synthetic_harness_architecture.md),
and [docs/synthetic_patient_simulation_protocol.md](docs/synthetic_patient_simulation_protocol.md).

## Tests

```bash
python3 -m unittest tests.test_synthetic_harness
cd ui && npm ci && npm run build
```

## Important limitations

- The UI is currently optimized for internal synthetic-case testing.
- Intake currently uses pasted denial-letter text; replacement policy documents
  can be uploaded during source review.
- The web isolation implementation is macOS-specific.
- The prototype launches the locally authenticated Codex CLI and therefore
  inherits that environment's model access and cost.
- A retrieved document may still require human review for plan, product, state,
  effective-date, and procedure applicability.
