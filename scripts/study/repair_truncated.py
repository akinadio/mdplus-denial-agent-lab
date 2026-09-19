#!/usr/bin/env python3
"""Find runs this harness cut short and mark them, so they stop being evidence.

A run that ended because WE stopped it -- the tool budget, the iteration
ceiling, a timeout, a cut-off output -- is not a measurement of the model. Until
2026-09-19 nothing said so: three Gemini runs ended at exactly the tool ceiling
with an empty answer, carried no error, and would have been scored as Gemini
failing to find the policy. --resume also thought they were finished.

retrieve.py now marks these as it writes them. This repairs runs recorded before
that, and is safe to re-run: a run that already carries an error is left alone.

  python3 scripts/study/repair_truncated.py           # report only
  python3 scripts/study/repair_truncated.py --apply   # mark them
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "study"))
from retrieve import NATURAL_STOPS  # noqa: E402

RUNS = ROOT / "study" / "runs"
KEY = ROOT / "study" / "unblinding.json"


def suspects():
    key = json.loads(KEY.read_text()) if KEY.exists() else {}
    for rid, info in sorted(key.items()):
        f = RUNS / rid / "result.json"
        if not f.exists():
            continue
        try:
            r = json.loads(f.read_text())
        except ValueError:
            continue
        if "error" in r or "skipped" in r:
            continue
        # The OrthoAppeals arm is a local pipeline, not a tool loop: it has no
        # stop_reason and no raw_text, and an empty one of those means nothing.
        if info.get("system", "").startswith("ortho"):
            continue
        stop = r.get("stop_reason")
        why = None
        if stop not in NATURAL_STOPS:
            why = f"cut short by the harness: stop_reason={stop!r}"
        elif not (r.get("raw_text") or "").strip():
            why = f"empty answer (stop_reason={stop!r})"
        if why:
            yield rid, info.get("system", "?"), f, r, why


def main() -> int:
    apply = "--apply" in sys.argv
    found = list(suspects())
    for rid, system, f, r, why in found:
        print(f"  {rid} {system:13s} {why}")
        if apply:
            r["error"] = why + " -- not a model failure"
            f.write_text(json.dumps(r, indent=1))
    if not found:
        print("  no truncated runs on disk")
        return 0
    print(f"\n{len(found)} run(s)" + (" marked; --resume will redo them."
          if apply else " would be marked. Re-run with --apply."))
    return 0


if __name__ == "__main__":
    sys.exit(main())
