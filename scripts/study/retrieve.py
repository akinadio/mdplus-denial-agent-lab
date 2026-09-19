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
  python3 scripts/study/retrieve.py --systems gemini --limit 30 --workers 5 --resume
"""
from __future__ import annotations
import argparse, csv, hashlib, json, os, sys, threading, time
from concurrent.futures import ThreadPoolExecutor, as_completed
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

# Four arms: the three free chatbots a patient could actually use, and
# OrthoAppeals. Every comparison is a chatbot against OrthoAppeals on the same
# letter; the chatbots are not compared to each other.
#
# claude-free is the controlled one. It is the SAME model OrthoAppeals runs on,
# with the same web tools, and without the policy library -- so whatever
# separates it from ortho-sonnet is the library, not the model.
#
# Only one OrthoAppeals arm: policy retrieval is a directory read with no model
# call, so a second arm on a different model returns identical rows.
SYSTEMS = {
    "chatgpt":      ("openai",    os.environ.get("POC_OPENAI_MODEL",      "gpt-5.6-luna")),
    "gemini":       ("google",    os.environ.get("POC_GEMINI_MODEL",      "gemini-3.5-flash")),
    "claude-free":  ("anthropic", os.environ.get("POC_CLAUDE_FREE_MODEL", "claude-sonnet-5")),
    "ortho-sonnet": ("anthropic", os.environ.get("POC_SONNET_MODEL",      "claude-sonnet-5")),
    # Same code path, same library lookup, same criteria -- only the letter
    # writer differs, because OrthoAppeals' retrieval step has no model in it.
    # Measured on the 30 in-library cases (2026-09-19, paired, McNemar exact):
    # Opus grounded 6 letters Sonnet did not and broke none of Sonnet's,
    # P=0.031. Keeping BOTH arms matters: ortho-sonnet holds the model constant
    # against Claude-free, so any gap there is architecture, while ortho-opus is
    # what we would actually ship.
    "ortho-opus":   ("anthropic", os.environ.get("POC_OPUS_MODEL",        "claude-opus-5")),
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


def _document_criteria(row, cpt, reason=""):
    """The plan's own words, read out of the plan's own document.

    `reason` is the denial reason from the notice, so the criteria that speak
    to it come first. A letter that quotes the BMI rule at someone denied for
    imaging findings has quoted the policy and argued nothing.
    """
    from synthetic_harness.policy_text import criteria_for
    return criteria_for(row["policy_url"], cpt, reason=reason)["quotes"]


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
            "criteria_quotes": _document_criteria(row, case["cpt"],
                                                 case.get("denial_reason", "")),
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



# What each provider calls a model that finished because it was done talking.
# Anything else -- an exhausted loop, a timeout, a cut-off output, a run still
# asking for tools -- means WE stopped it, and a run we stopped is not evidence
# about the model. On 2026-09-19 three Gemini runs ended at exactly the tool
# ceiling with no answer, and because nothing marked them they would have been
# scored as Gemini finding no policy.
NATURAL_STOPS = {"end_turn", "stop", "stop_sequence", "completed", "end"}


from synthetic_harness.api_runner import ToolBudgetExhausted  # noqa: E402


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


def _jsonable(obj):
    """A transcript that survives being written to disk and read back.

    Providers hand back their own SDK objects -- google.genai types.Content,
    Anthropic content blocks -- and json.dumps refuses them, which killed the
    run AFTER the model had already been paid for. Pydantic models (both SDKs
    use them) round-trip through model_dump, and every SDK accepts plain dicts
    back in, so phase 2 can still continue the chat. Anything else is kept as
    text rather than losing the run.
    """
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    for attr in ("model_dump", "to_json_dict", "dict"):
        fn = getattr(obj, attr, None)
        if callable(fn):
            try:
                return _jsonable(fn())
            except Exception:  # noqa: BLE001
                pass
    return str(obj)


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
    answer = extract_json(text) or {}
    out = {"answer": answer, "raw_text": text, "usd": usd,
            # Phase 2 continues this same chat to ask for the appeal letter, so
            # the transcript has to survive the run.
            "transcript": _jsonable(transcript),
            "stop_reason": stop, "usage": usage, "model": model,
            "tool_calls": runner._calls if hasattr(runner, "_calls") else 0,
            "elapsed_s": round(time.time() - t0, 1)}
    # An error here is doing one job: keeping a run WE cut short out of the
    # scores, and making --resume try it again. The tokens are already paid for
    # and already in the ledger either way.
    if stop not in NATURAL_STOPS:
        out["error"] = (f"cut short by the harness: stop_reason={stop!r} after "
                        f"{out['tool_calls']} tool calls -- not a model failure")
    elif not (text or "").strip():
        out["error"] = (f"empty answer after {out['tool_calls']} tool calls "
                        f"(stop_reason={stop!r}) -- nothing to score")
    return out



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


def _rid(case_id: str, system: str, salt: str = "poc") -> str:
    return "r-" + __import__("hashlib").sha256(
        f"{salt}|{case_id}|{system}".encode()).hexdigest()[:12]


def _is_done(case_id: str, system: str, salt: str = "poc", runs=None) -> bool:
    """True only for a run that finished cleanly.

    A result.json holding an error or a skip is NOT done: --resume has to
    retry it, or the one case that failed on a blip is missing from the arm
    forever and nothing says so.
    """
    f = (runs or RUNS) / _rid(case_id, system, salt) / "result.json"
    if not f.exists():
        return False
    try:
        prior = json.loads(f.read_text())
    except ValueError:
        return False
    return not ("error" in prior or "skipped" in prior)


def plan(cases, systems, salt="poc", resume=False, limit=0, runs=None):
    """The (case, system) pairs this invocation should actually run.

    --limit is "do this many MORE", not "look at the first this many". Slicing
    the case list instead meant `--limit 20 --resume` re-examined the same 20
    cases forever and never reached case 21 -- exactly the knob you reach for
    when running 400 letters in batches.
    """
    work = [(c, s) for c in cases for s in systems
            if not (resume and _is_done(c["case_id"], s, salt, runs))]
    return work[:limit] if limit else work


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--systems", default="all")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--workers", type=int, default=1,
                    help="cases to run at once (default 1). A case is ~90s of "
                         "mostly waiting, so this is the difference between a "
                         "three-hour arm and a thirty-minute one. Searches are "
                         "paced process-wide, so raising this does not raise "
                         "the search rate; keep it at or below 6 unless you "
                         "know the provider's concurrency limit.")
    a = ap.parse_args()

    systems = list(SYSTEMS) if a.systems == "all" else [s.strip() for s in a.systems.split(",")]
    cases = json.loads((STUDY / "cases.json").read_text())["cases"]
    salt = os.environ.get("STUDY_BLIND_SALT", "poc")
    RUNS.mkdir(parents=True, exist_ok=True)

    import spend

    # The whole key, so an aborted run still unblinds cleanly.
    mapping = {_rid(c["case_id"], s, salt): {"case_id": c["case_id"], "system": s}
               for c in cases for s in systems}

    work = plan(cases, systems, salt, a.resume, a.limit)

    if "chatgpt" in systems:
        spend.banner("retrieve", sum(1 for _, s in work if s == "chatgpt"),
                     SYSTEMS["chatgpt"][1], 60000, 4000)

    workers = max(1, a.workers)
    lock = threading.Lock()
    broke: set[str] = set()      # arms whose provider has no credit left
    search_down: list[str] = []  # non-empty once the search backend quits
    done = skipped = 0

    def one(item):
        """Run a single case. Returns a line to print, or None if not attempted."""
        nonlocal done, skipped
        c, s = item
        with lock:
            if s in broke or search_down:
                return None
        rid = _rid(c["case_id"], s, salt)
        d = RUNS / rid
        d.mkdir(exist_ok=True)
        try:
            res = run_ortho(c, SYSTEMS[s][1]) if s.startswith("ortho") else run_llm(s, c, d)
        except ToolBudgetExhausted as e:
            # Recorded as an error so it stays out of the scores and --resume
            # retries it. A model that ignores the wrap-up warning is a run we
            # cut, not an answer.
            res = {"error": f"cut short by the harness: {e}"}
        except SearchBackendDown as e:
            with lock:
                search_down.append(str(e)[:300])
            return None
        except Exception as e:  # noqa: BLE001
            res = {"error": f"{type(e).__name__}: {e}"}
            if spend.is_funding_error(e):
                # Out of funds is per PROVIDER, not per run. Drop this arm and
                # keep going: on 2026-09-18 an empty Google AI Studio balance
                # stopped the Anthropic arm too, which has nothing to do with
                # Google.
                res["run_id"], res["case_id"] = rid, c["case_id"]
                (d / "result.json").write_text(json.dumps(_jsonable(res), indent=1))
                with lock:
                    first = s not in broke
                    broke.add(s)
                if not first:
                    # With N workers, N-1 more cases of the same arm are already
                    # in flight when the balance runs out, and each comes back
                    # with its own 429. Say it once; they are all recorded as
                    # errors and --resume redoes them either way.
                    return None
                return (f"\n  {s}: out of funds at the provider -- dropping this arm.\n"
                        f"    {str(e)[:110]}\n"
                        f"    Add credit and re-run with --resume to pick it up.\n")
        res["run_id"], res["case_id"] = rid, c["case_id"]
        (d / "result.json").write_text(json.dumps(_jsonable(res), indent=1))
        with lock:
            if "skipped" in res or "error" in res:
                skipped += 1
                return f"  {rid} {s:13s} SKIP/ERR {res.get('skipped') or res.get('error')}"
            done += 1
            return f"  {rid} {s:13s} ok"

    if workers == 1:
        for item in work:
            line = one(item)
            if line:
                print(line, flush=True)
            if search_down or set(systems) <= broke:
                break
    else:
        print(f"  {len(work)} to run, {workers} at a time")
        # as_completed, not map: map yields in SUBMISSION order, so one slow
        # case holds back every line behind it and the run looks hung. A Gemini
        # case can take ten minutes and 70 searches while three others finish.
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(one, item) for item in work]
            for fut in as_completed(futures):
                line = fut.result()
                if line:
                    print(line, flush=True)

    _save_key(mapping)

    if search_down:
        print(f"\n  SEARCH BACKEND DOWN: {search_down[0]}\n"
              "  Stopping. Every remaining answer would be produced without a\n"
              "  search engine, which is not the system we are measuring.\n"
              "  Top up WEB_SEARCH_API_KEY's plan and re-run with --resume.")
        raise SystemExit(2)

    left = sum(1 for c in cases for s in systems if not _is_done(c["case_id"], s, salt))
    print(f"\n{done} runs completed, {skipped} skipped/errored -> {RUNS}")
    if left:
        print(f"{left} still to do -- re-run the same command to continue.")
    spend.report()
    if set(systems) <= broke:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
