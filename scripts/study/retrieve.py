#!/usr/bin/env python3
"""Run the proof-of-concept: ChatGPT free-tier model vs OrthoAppeals.

Three systems, one run per case (Kassam: one comparator first; expand later):
  chatgpt          GPT-5.6 Luna, the model the ChatGPT free tier serves,
                   with the same web_search / http_fetch tools.
  ortho-sonnet     OrthoAppeals pipeline on Sonnet.

Both OrthoAppeals builds share one code path; only the model differs, so any
gap between them is model, and any gap against ChatGPT on the same Sonnet
class is architecture.

Stratum C matters here. OrthoAppeals must NOT invent a document when it holds
none -- it returns the abstention plus the insurer-specific route from
criteria_access_directory.json. That behaviour is the thing under test.

Keys come from the environment as server secrets:
  ANTHROPIC_API_KEY, OPENAI_API_KEY
Never passed on the command line, never written to disk.

  python3 scripts/study/retrieve.py --systems all
  python3 scripts/study/retrieve.py --systems ortho-sonnet --limit 3   # dry check
"""
from __future__ import annotations
import argparse, csv, hashlib, json, os, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
# api_runner's tool layer imports policy_eval.webtools, which lives under
# scripts/, so that directory has to be importable too.
sys.path.insert(0, str(ROOT / "scripts"))

# Keys live in gitignored env files beside the repo root, never in argv and
# never in the run records. openai.env is separate from .env purely so it can
# be edited without touching the working file.
#
# Parsed here rather than via python-dotenv: that package is not installed on
# every machine that runs this, and a missing import silently loaded nothing,
# which reported both keys absent when one was present.
def _load_env_files():
    import os as _os
    for name in ("openai.env", ".env"):
        f = ROOT / name
        if not f.exists():
            continue
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:]
            if "=" not in line:
                continue
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k and v and k not in _os.environ:
                _os.environ[k] = v


_load_env_files()


PLACEHOLDERS = {"PASTE_YOUR_KEY_HERE", "sk-your-key-here", "", "changeme"}


def _key_status():
    """True only for a key that is actually usable.

    The placeholder in openai.env is a non-empty string, so a plain truthiness
    check reports it as set and the run fails later with a 401 instead of
    here. Reject the placeholder and anything too short to be a real key.
    """
    import os as _os
    out = {}
    for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        v = (_os.environ.get(k) or "").strip().strip('"').strip("'")
        out[k] = bool(v) and v not in PLACEHOLDERS and len(v) > 20
    return out
STUDY = ROOT / "study"
RUNS = STUDY / "runs"
PLAT = ROOT / "data" / "policy_platform"

SYSTEMS = {
    "chatgpt":      ("openai",    os.environ.get("POC_OPENAI_MODEL", "gpt-5.6-luna")),
    # One OrthoAppeals arm. Policy retrieval is a directory lookup with no
    # model call, so a second arm on a different model returns identical rows
    # -- the first pilot ran "ortho-opus" and "ortho-sonnet" and got a table
    # with two identical lines, which is a property of the design, not a
    # finding. The model matters when the LETTER is written (phase 2), and
    # that is where a model comparison belongs if one is wanted.
    "ortho-sonnet": ("anthropic", os.environ.get("POC_SONNET_MODEL", "claude-sonnet-5")),
}

SYSTEM_PROMPT = (
    "You are helping a patient respond to a health insurance denial. Answer "
    "precisely and only from evidence you actually retrieve. If you cannot "
    "find the governing policy, say so plainly rather than naming a document "
    "you are unsure of.")

INSTRUCTION = """
Above is a denial letter. Using web search as needed:

1. Identify the payer's governing medical policy for the denied procedure --
   the specific document containing the medical-necessity criteria this payer
   applies to this CPT code.
2. Give its title, policy number, URL, and effective or last-revised date.
3. Quote the medical-necessity criteria the patient must address.
4. State the appeal deadline.
5. State where and how to submit the appeal.

If no such document is publicly available, say so explicitly and explain how
the patient can obtain the criteria that were applied to them.

Answer as JSON with keys: policy_found (true/false), policy_title,
policy_number, policy_url, effective_date, criteria_quotes (list),
appeal_deadline, submission_route, how_to_obtain_criteria, confidence, notes.
""".strip()


def _load_access():
    p = PLAT / "criteria_access_directory.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _directory_row(case):
    with (PLAT / "app_option_policy_directory.csv").open(encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            if (r["state"] == case["state"] and r["insurance_company"] == case["payer"]
                    and r["cpt"] == case["cpt"]):
                return r
    return None


def _access_route(payer, note, access):
    ins = (payer or "").lower().strip()
    if ins in access:
        return access[ins]
    for k, v in access.items():
        if k.startswith("_"):
            continue
        if k in ins or ins in k:
            return v
    n = (note or "").lower()
    for v in ("evolent", "carelon", "evicore", "turningpoint", "interqual", "mcg"):
        if v in n and "_" + v in access:
            return access["_" + v]
    return {}



def _route_for(case):
    """The real appeal route for this payer, not a placeholder."""
    from synthetic_harness.policy_text import submission_route
    return submission_route(case["payer"], case.get("plan_type", ""))


def _document_criteria(row, cpt):
    """The plan's own words, read out of the plan's own document."""
    from synthetic_harness.policy_text import criteria_for
    return criteria_for(row["policy_url"], cpt)["quotes"]


def run_ortho(case, model):
    """The production path, exactly as the app answers it."""
    row = _directory_row(case)
    access = _load_access()
    # "VERIFIED (criteria public, no stable link)" is 72 rows whose URL is a
    # policy INDEX the patient has to browse from, not the governing document.
    # The page says so correctly; this path did not, and would have cited an
    # index page as though it were the criteria.
    NO_STABLE_LINK = "VERIFIED (criteria public, no stable link"
    if (row and row["status"].startswith("VERIFIED")
            and not row["status"].startswith(NO_STABLE_LINK)
            and row["policy_url"].strip()):
        return {"answer": {
            "policy_found": True,
            "policy_title": row["policy_title"], "policy_number": "",
            "policy_url": row["policy_url"], "effective_date": row["effective_date"],
            # Our own research note is not the plan's language. Passing it
            # here as "criteria" is what taught the letter writer to invent
            # quotations. Real criteria come from the document itself.
            "criteria_quotes": _document_criteria(row, case["cpt"]),
            "appeal_deadline": case["appeal_deadline"],
            "submission_route": _route_for(case),
            "how_to_obtain_criteria": "",
            "confidence": "high",
            "notes": f"directory hit; status={row['status']}",
        }, "source": "policy_directory", "model": model}
    if row and row["status"].startswith(NO_STABLE_LINK) and row["policy_url"].strip():
        return {"answer": {
            "policy_found": True,
            "policy_title": row["policy_title"], "policy_number": "",
            "policy_url": row["policy_url"], "effective_date": row["effective_date"],
            "criteria_quotes": [],
            "appeal_deadline": case["appeal_deadline"],
            "submission_route": _route_for(case),
            "how_to_obtain_criteria": (
                "Your plan publishes these criteria but gives the document no "
                "permanent address. Open the policy list above and click through "
                "to the policy for your surgery -- that document is what your "
                "appeal should quote."),
            "confidence": "high",
            "notes": f"browse entry point, not a stable document; status={row['status']}",
        }, "source": "policy_index_entry", "model": model}

    # The payer's own policy is public and names the code, but sends criteria to
    # a private vendor tool. Abstaining here withholds a document we are holding
    # -- the pilot caught us doing exactly that on six UnitedHealthcare letters
    # while ChatGPT handed the patient the right PDF. Cite it AND route.
    if row and row["status"].startswith("DOCUMENT PUBLIC") and row["policy_url"].strip():
        r = _access_route(case["payer"], row.get("note", ""), access)
        return {"answer": {
            "policy_found": True,
            "policy_title": row["policy_title"], "policy_number": "",
            "policy_url": row["policy_url"], "effective_date": row["effective_date"],
            "criteria_quotes": [],
            "appeal_deadline": case["appeal_deadline"],
            "submission_route": _route_for(case),
            "how_to_obtain_criteria": (r.get("how") or
                "This policy governs your procedure code but sends the medical "
                "criteria to a private review tool. Ask the plan in writing for "
                "the exact criteria used in your denial."),
            "confidence": "high",
            "notes": f"payer policy public, criteria vendor-held; status={row['status']}",
        }, "source": "policy_directory_vendor_held", "route": r, "model": model}

    r = _access_route(case["payer"], (row or {}).get("note", ""), access)
    return {"answer": {
        "policy_found": False,
        "policy_title": "", "policy_number": "", "policy_url": "",
        "effective_date": "", "criteria_quotes": [],
        "appeal_deadline": case["appeal_deadline"],
        "submission_route": _route_for(case),
        "how_to_obtain_criteria": (r.get("how") or
            "This plan does not publish criteria for this procedure. Ask the "
            "plan in writing for the exact criteria used in your denial."),
        "confidence": "high",
        "notes": "no public criteria on file; abstained and routed",
    }, "source": "abstention_route", "route": r, "model": model}



class SearchBackendDown(RuntimeError):
    """The search backend stopped answering mid-run.

    On 2026-09-04 the Brave key hit its monthly spend cap partway through the
    ChatGPT arm. Every later web_search returned HTTP 402 with zero results,
    the model fell back to guessing URLs -- 265 of its 762 fetches 404'd -- and
    the harness scored the whole arm anyway, producing a clean-looking 20%
    accuracy table for a run that had no search engine. A comparison arm that
    silently loses its tools is worse than one that crashes, so this stops the
    run instead."""


_QUOTA_MARKERS = ("HTTP 402", "HTTP 401", "HTTP 429", "USAGE_LIMIT", "quota")


def _guarded(tool_call):
    """Wrap the tool layer so a dead search backend aborts rather than degrades."""
    def call(name, args):
        out = tool_call(name, args)
        if name == "web_search" and isinstance(out, dict):
            err = str(out.get("error") or "")
            if any(m in err for m in _QUOTA_MARKERS):
                raise SearchBackendDown(err[:300])
        return out
    return call

def run_llm(system, case, out_dir):
    from synthetic_harness.api_runner import (_resolve, _make_client, _ToolRunner,
                                              MAX_TOOL_ITERATIONS, MAX_OUTPUT_TOKENS)
    from synthetic_harness.agent_runner import extract_json
    import spend
    provider_name, model = SYSTEMS[system]
    prov, model = _resolve(provider_name, model)
    if not prov.available():
        return {"skipped": f"{prov.key_env} not set or SDK missing"}
    client = _make_client(prov, 900)
    runner = _ToolRunner(out_dir / "tools.jsonl", case["case_id"])
    usage = {"input_tokens": 0, "output_tokens": 0}
    t0 = time.time()
    text, transcript, stop = prov.run(
        client=client, model=model, system=SYSTEM_PROMPT,
        prompt=case["letter_text"] + "\n\n---\n\n" + INSTRUCTION,
        tool_call=_guarded(runner.call), deadline=t0 + 900, usage=usage,
        max_iters=MAX_TOOL_ITERATIONS, max_tokens=MAX_OUTPUT_TOKENS)
    usd = spend.cost(model, usage)
    spend.record("retrieve", model, usage, case["case_id"])
    return {"answer": extract_json(text) or {}, "raw_text": text, "usd": usd,
            # Phase 2 continues this same chat to ask for the appeal letter, so
            # the transcript has to survive the run.
            "transcript": transcript,
            "stop_reason": stop, "usage": usage, "model": model,
            "elapsed_s": round(time.time() - t0, 1)}



def _save_key(mapping):
    """Arms are run separately (the ChatGPT arm needs a machine that can reach
    api.openai.com), so the unblinding key accumulates instead of being
    replaced. Also called on an aborted run, so a partial arm stays readable."""
    keyfile = STUDY / "unblinding.json"
    if keyfile.exists():
        prior = json.loads(keyfile.read_text())
        prior.update(mapping)
        mapping = prior
    keyfile.write_text(json.dumps(mapping, indent=1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--systems", default="all")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--resume", action="store_true")
    a = ap.parse_args()

    systems = list(SYSTEMS) if a.systems == "all" else [s.strip() for s in a.systems.split(",")]
    cases = json.loads((STUDY / "cases.json").read_text())["cases"]
    if a.limit:
        cases = cases[:a.limit]
    salt = os.environ.get("STUDY_BLIND_SALT", "poc")
    RUNS.mkdir(parents=True, exist_ok=True)

    import spend
    if "chatgpt" in systems:
        n = sum(1 for c in cases if not (a.resume and (RUNS / ("r-" + hashlib.sha256(
            f"{salt}|{c['case_id']}|chatgpt".encode()).hexdigest()[:12]) / "result.json").exists()))
        spend.banner("retrieve", n, SYSTEMS["chatgpt"][1], 60000, 4000)
    mapping, done, skipped = {}, 0, 0
    for c in cases:
        for s in systems:
            rid = "r-" + hashlib.sha256(f"{salt}|{c['case_id']}|{s}".encode()).hexdigest()[:12]
            mapping[rid] = {"case_id": c["case_id"], "system": s}
            d = RUNS / rid
            if a.resume and (d / "result.json").exists():
                prior = json.loads((d / "result.json").read_text())
                if not ("error" in prior or "skipped" in prior):
                    continue
            d.mkdir(exist_ok=True)
            try:
                res = (run_ortho(c, SYSTEMS[s][1]) if s.startswith("ortho")
                       else run_llm(s, c, d))
            except SearchBackendDown as e:
                print(f"\n  SEARCH BACKEND DOWN: {e}\n"
                      "  Stopping. Every remaining answer would be produced without a\n"
                      "  search engine, which is not the system we are measuring.\n"
                      "  Top up WEB_SEARCH_API_KEY's plan and re-run with --resume.")
                _save_key(mapping)
                raise SystemExit(2)
            except Exception as e:  # noqa: BLE001
                res = {"error": f"{type(e).__name__}: {e}"}
                import spend
                if spend.is_funding_error(e):
                    res["run_id"], res["case_id"] = rid, c["case_id"]
                    (d / "result.json").write_text(json.dumps(res, indent=1))
                    _save_key(mapping)
                    print(f"\n  STOPPED, out of funds at the provider: {str(e)[:120]}\n"
                          f"  {done} runs saved; add credit and re-run with --resume.")
                    raise SystemExit(2)
            res["run_id"] = rid
            res["case_id"] = c["case_id"]
            (d / "result.json").write_text(json.dumps(res, indent=1))
            if "skipped" in res or "error" in res:
                skipped += 1
                print(f"  {rid} {s:13s} SKIP/ERR {res.get('skipped') or res.get('error')}")
            else:
                done += 1
                print(f"  {rid} {s:13s} ok")
    _save_key(mapping)
    print(f"\n{done} runs completed, {skipped} skipped/errored -> {RUNS}")
    spend.report()


if __name__ == "__main__":
    main()
