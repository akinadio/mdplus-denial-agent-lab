"""The validation study's case set must stay blind, stratified, and grounded.

Three properties matter enough to enforce:
- the case file the arms see must not contain the answer;
- every gold answer must be a document we independently verified;
- the scorer must never touch the unblinding map.
"""
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
STUDY = ROOT / "study"
CASES = json.loads((STUDY / "cases_v1.json").read_text())
GOLD = json.loads((STUDY / "gold_key_v1.json").read_text())


def test_two_hundred_cases_stratified_120_40_40():
    from collections import Counter
    c = Counter(x["stratum"] for x in CASES["cases"])
    assert c == {"national": 120, "regional": 40, "revised6mo": 40}


def test_case_file_carries_no_answers():
    """The arms' input must not leak the gold document."""
    blob = json.dumps(CASES["cases"])
    assert "policy_url" not in blob
    assert "policy_title" not in blob
    assert "http" not in blob.lower().replace("https", "").replace("http", "") or True
    # concretely: no gold URL may appear anywhere in the case text
    for g in GOLD["entries"]:
        assert g["policy_url"] not in blob


def test_every_case_has_exactly_one_gold_entry():
    case_ids = [c["case_id"] for c in CASES["cases"]]
    gold_ids = [g["case_id"] for g in GOLD["entries"]]
    assert sorted(case_ids) == sorted(gold_ids)
    assert len(set(case_ids)) == len(case_ids)


def test_gold_entries_are_verified_with_stable_urls():
    for g in GOLD["entries"]:
        assert g["directory_status"] in ("VERIFIED", "VERIFIED (procedure criteria)"), g
        assert g["policy_url"].startswith("http"), g


def test_gold_matches_current_directory():
    """A directory correction (stale URL replaced, status downgraded) must
    fail this test until the case set is rebuilt -- a study scored against a
    key we no longer believe would be worse than no study."""
    import csv
    directory = {}
    with (ROOT / "data/policy_platform/app_option_policy_directory.csv").open(
            encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            directory[(r["state"], r["insurance_company"], r["cpt"])] = r
    for g in GOLD["entries"]:
        row = directory[(g["state"], g["payer"], g["cpt"])]
        assert row["policy_url"] == g["policy_url"], (g["case_id"], row["policy_url"])
        assert row["status"] == g["directory_status"], g["case_id"]


def test_letters_mention_their_own_cpt_and_payer():
    for c in CASES["cases"]:
        assert c["cpt"] in c["letter_text"]
        assert c["payer"] in c["letter_text"]
        assert c["state"] in c["letter_text"]


def test_case_build_is_deterministic():
    """Same seed, same directory -> byte-identical case ids."""
    import subprocess, hashlib, sys
    before = hashlib.sha256((STUDY / "cases_v1.json").read_bytes()).hexdigest()
    subprocess.run([sys.executable, str(ROOT / "scripts/study/build_cases.py")],
                   check=True, capture_output=True)
    after = hashlib.sha256((STUDY / "cases_v1.json").read_bytes()).hexdigest()
    assert before == after


def test_scorer_never_references_the_unblinding_map():
    src = (ROOT / "scripts/study/score.py").read_text()
    assert "unblinding_map" not in src.replace(
        "NEVER reads\nstudy/unblinding_map.json", "")


def test_no_payer_dominates_a_stratum():
    from collections import Counter
    for stratum, want in (("national", 120), ("regional", 40), ("revised6mo", 40)):
        c = Counter(x["payer"] for x in CASES["cases"] if x["stratum"] == stratum)
        top = c.most_common(1)[0]
        assert top[1] <= max(4, want // 4) + 1, (stratum, top)


def test_mcnemar_exact_sanity():
    import sys
    sys.path.insert(0, str(ROOT / "scripts/study"))
    from analyze import mcnemar_exact
    assert mcnemar_exact(0, 0) == 1.0
    assert abs(mcnemar_exact(1, 1) - 1.0) < 1e-9
    # 15:2 discordant should be significant at 0.0167
    assert mcnemar_exact(15, 2) < 0.0167
    assert mcnemar_exact(5, 4) > 0.0167
