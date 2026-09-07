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
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LEDGER = ROOT / "study" / "spend.json"

# $ per million tokens (input, output). Overridable per model from .env.
_DEFAULT = {
    "gpt-5.6-luna": (1.00, 6.00),
    "claude-sonnet-5": (3.00, 15.00),
    "claude-opus-5": (15.00, 75.00),
}
_CREDIT = re.compile(r"credit balance|insufficient_quota|billing|usage limit|"
                     r"Error code: 402|exceeded your current quota", re.I)


class OutOfFunds(RuntimeError):
    """The provider refused for money, not for anything we did."""


def is_funding_error(exc: Exception | str) -> bool:
    return bool(_CREDIT.search(str(exc)))


def price(model: str) -> tuple[float, float]:
    key = re.sub(r"[^A-Z0-9]", "_", (model or "").upper())
    i = os.environ.get(f"MDPLUS_PRICE_{key}_IN")
    o = os.environ.get(f"MDPLUS_PRICE_{key}_OUT")
    base = next((v for k, v in _DEFAULT.items() if k in (model or "")), (5.00, 25.00))
    return (float(i) if i else base[0], float(o) if o else base[1])


def cost(model: str, usage: dict) -> float:
    pi, po = price(model)
    return round((usage.get("input_tokens", 0) * pi + usage.get("output_tokens", 0) * po) / 1e6, 4)


def _load() -> list:
    try:
        return json.loads(LEDGER.read_text())
    except Exception:  # noqa: BLE001
        return []


def record(step: str, model: str, usage: dict, ref: str = "") -> float:
    """Append one paid call. Returns the running total for the whole study."""
    rows = _load()
    c = cost(model, usage)
    rows.append({"t": time.strftime("%Y-%m-%d %H:%M:%S"), "step": step, "model": model,
                 "in": usage.get("input_tokens", 0), "out": usage.get("output_tokens", 0),
                 "usd": c, "ref": ref})
    LEDGER.write_text(json.dumps(rows))
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
    pi, po = price(model)
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
