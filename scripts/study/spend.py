"""Know what the study is costing while it runs, and stop cleanly when told to.

Every paid call is appended to study/spend.json as it happens -- step, model,
tokens, dollars -- so the total is on screen at each checkpoint and nothing
has to be reconstructed after the fact. Prices are per million tokens and are
ESTIMATES: set MDPLUS_PRICE_<MODEL>_IN / _OUT to your console's rates.

A run that hits the account's credit limit stops at once with the reason,
instead of burning through a hundred failing calls. Everything already done is
on disk; --resume picks up from the first thing that failed.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LEDGER = ROOT / "study" / "spend.json"

# ---------------------------------------------------------------------------
# PRICES. $ per million tokens: (input, output, cache_write, cache_read).
#
# READ THIS BEFORE TRUSTING A DOLLAR FIGURE FROM THIS FILE.
#
# Until 2026-09-19 this table carried a comment saying it had been "checked
# against each vendor's published rates". It had not been. All four entries were
# wrong, and not in the same direction, so the errors did not even cancel:
#
#   gpt-5.6-luna      was  1.00/6.00   actually 0.20/0.90   10x too HIGH
#   gemini-3.5-flash  was  0.75/4.50   actually 1.50/9.00    2x too LOW
#   claude-sonnet-5   was  3.00/15.00  actually 2.00/10.00 1.5x too HIGH
#   claude-opus-5     was 15.00/75.00  actually 5.00/25.00   3x too HIGH
#
# The ledger is the only thing standing between this study and running out of
# money with no warning, so a guessed price is worse than no price. Rules:
#
#   1. Every rate below is quoted from the vendor's own pricing page, fetched on
#      VERIFIED. The page is in SOURCES. If you cannot point at the page, the
#      number does not go here.
#   2. There is NO silent fallback. An unpriced model raises UnknownPrice and
#      the dry run fails before any paid run starts. The old fallback of (5, 25)
#      is how one Gemini letter came to be reported as $3.96.
#   3. Re-verify whenever a model is added or a vendor changes rates. Gemini 3.5
#      Flash has already tripled its price once.
VERIFIED = "2026-09-19"
SOURCES = {
    "openai": "https://developers.openai.com/api/docs/pricing",
    "anthropic": "https://platform.claude.com/docs/en/about-claude/pricing",
    "google": "https://ai.google.dev/gemini-api/docs/pricing",
}
# gpt-5.6-luna is quoted at OpenAI's LONG-context tier (0.20/0.90), not short
# (0.10/0.60): our prompts carry fetched policy pages and run to ~85k input
# tokens, and if the tier boundary is crossed the ledger should read high rather
# than low.
_DEFAULT = {
    "gpt-5.6-luna":     (0.20,  0.90, 0.20, 0.02),
    "gemini-3.5-flash": (1.50,  9.00, 1.50, 0.15),
    "claude-sonnet-5":  (2.00, 10.00, 2.50, 0.20),
    "claude-opus-5":    (5.00, 25.00, 6.25, 0.50),
}


class UnknownPrice(RuntimeError):
    """A model with no verified price. Fail loudly rather than guess."""


_CREDIT = re.compile(r"credit balance|insufficient_quota|billing|usage limit|"
                     r"Error code: 402|exceeded your current quota", re.I)


class OutOfFunds(RuntimeError):
    """The provider refused for money, not for anything we did."""


def is_funding_error(exc: Exception | str) -> bool:
    return bool(_CREDIT.search(str(exc)))


def price(model: str) -> tuple[float, float, float, float]:
    """(input, output, cache_write, cache_read) per million tokens.

    Each is overridable per model from the environment, e.g.
    MDPLUS_PRICE_CLAUDE_SONNET_5_IN=1.80 once a discount is negotiated.
    """
    base = next((v for k, v in _DEFAULT.items() if k in (model or "")), None)
    if base is None:
        raise UnknownPrice(
            f"no verified price for model {model!r}. Take it from the vendor's "
            f"pricing page (spend.SOURCES) and add it to spend._DEFAULT before "
            f"running that arm -- a guessed rate makes the whole ledger fiction.")
    key = re.sub(r"[^A-Z0-9]", "_", (model or "").upper())
    return tuple(float(os.environ.get(f"MDPLUS_PRICE_{key}_{n}") or base[i])
                 for i, n in enumerate(("IN", "OUT", "CACHE_WRITE", "CACHE_READ")))


def cost(model: str, usage: dict) -> float:
    """What one call cost, cached tokens included.

    Cached tokens are reported in their OWN fields and are excluded from
    input_tokens, so the four terms add up with no overlap. Summing only
    input_tokens reports a cached run at roughly a tenth of its cost.
    """
    pin, pout, pwrite, pread = price(model)
    micro = (usage.get("input_tokens", 0) * pin
             + usage.get("cache_creation_input_tokens", 0) * pwrite
             + usage.get("cache_read_input_tokens", 0) * pread
             + usage.get("output_tokens", 0) * pout)
    return round(micro / 1e6, 4)


def _load() -> list:
    try:
        return json.loads(LEDGER.read_text())
    except Exception:  # noqa: BLE001
        return []


_record_lock = threading.Lock()


def record(step: str, model: str, usage: dict, ref: str = "") -> float:
    """Append one paid call. Returns the running total for the whole study.

    Read-modify-write, so it needs both locks. The thread lock covers workers
    inside one run (--workers); the flock covers two terminals running
    different arms at once. Without them the loser's calls vanish from the
    ledger and you are watching a total that is quietly too low -- the one
    number that must not be wrong while money is going out.
    """
    with _record_lock:
        LEDGER.parent.mkdir(parents=True, exist_ok=True)
        LEDGER.touch(exist_ok=True)
        with open(LEDGER, "r+", encoding="utf-8") as fh:
            try:
                import fcntl
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            except (ImportError, OSError):
                pass  # no file locking here; the thread lock still holds
            try:
                rows = json.loads(fh.read() or "[]")
            except ValueError:
                rows = []
            c = cost(model, usage)
            rows.append({"t": time.strftime("%Y-%m-%d %H:%M:%S"), "step": step,
                         "model": model, "in": usage.get("input_tokens", 0),
                         "out": usage.get("output_tokens", 0),
                         "cw": usage.get("cache_creation_input_tokens", 0),
                         "cr": usage.get("cache_read_input_tokens", 0),
                         "usd": c, "ref": ref})
            fh.seek(0)
            fh.write(json.dumps(rows))
            fh.truncate()
    return round(sum(r["usd"] for r in rows), 2)


def total(step: str | None = None) -> float:
    return round(sum(r["usd"] for r in _load() if step is None or r["step"] == step), 2)


def budget_left() -> float | None:
    b = os.environ.get("STUDY_BUDGET_USD")
    return None if not b else round(float(b) - total(), 2)


def check_budget() -> None:
    left = budget_left()
    if left is not None and left <= 0:
        raise OutOfFunds(f"STUDY_BUDGET_USD reached (spent ${total():.2f}). Nothing lost; "
                         f"raise the budget and re-run with --resume.")


def banner(step: str, n_calls: int, model: str, est_in: int, est_out: int) -> None:
    # A step can name more than one model ("claude-sonnet-5 / gpt-5.6-luna");
    # price the dearest of them so the estimate is a ceiling, not a hope, and
    # never let an unpriced name turn the banner into a crash.
    rates = []
    for name in re.split(r"[\s/,]+", model or ""):
        try:
            rates.append(price(name))
        except UnknownPrice:
            continue
    if not rates:
        print(f"  spend so far ${total():.2f}  |  this step: ~{n_calls} calls "
              f"x {model} (no verified price -- estimate unavailable)")
        return
    pi = max(r[0] for r in rates)
    po = max(r[1] for r in rates)
    est = n_calls * (est_in * pi + est_out * po) / 1e6
    left = budget_left()
    print(f"  spend so far ${total():.2f}  |  this step: ~{n_calls} calls x {model} "
          f"~= ${est:.2f} estimated"
          + (f"  |  budget left ${left:.2f}" if left is not None else ""))


def report() -> None:
    rows = _load()
    if not rows:
        print("  spend: nothing recorded yet")
        return
    by = {}
    for r in rows:
        by.setdefault(r["step"], [0, 0.0])
        by[r["step"]][0] += 1
        by[r["step"]][1] += r["usd"]
    print("  SPEND (estimated from tokens; set MDPLUS_PRICE_* for exact rates)")
    for k, (n, usd) in by.items():
        print(f"    {k:12s} {n:4d} calls  ${usd:7.2f}")
    print(f"    {'total':12s} {len(rows):4d} calls  ${total():7.2f}")
    cr = sum(r.get("cr", 0) for r in rows)
    cw = sum(r.get("cw", 0) for r in rows)
    if cr or cw:
        # What caching saved, so the line is auditable rather than trusted.
        saved = sum(r.get("cr", 0) * (price(r["model"])[0] - price(r["model"])[3]) / 1e6
                    for r in rows)
        print(f"    cache: {cr/1e6:.1f}M read, {cw/1e6:.1f}M written"
              f"  (${saved:.2f} saved against paying full input rate)")
