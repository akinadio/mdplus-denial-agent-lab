"""The advanced-imaging directory must stay separate from, and consistent with,
the surgery directory.

The rule this file defends: a payer's imaging vendor is frequently not its
surgery vendor, so an imaging cell must never be filled by inheriting a
surgery finding. These tests make that structural rather than a matter of
remembering.
"""
import csv
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
PLAT = ROOT / "data" / "policy_platform"
IMAGING = PLAT / "app_option_imaging_directory.csv"
SURGERY = PLAT / "app_option_policy_directory.csv"

IMAGING_CPTS = {"73721", "73221", "72148", "72141"}


def _rows(path):
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def test_imaging_directory_exists_and_covers_every_pair():
    img = _rows(IMAGING)
    surg = _rows(SURGERY)
    pairs = {(r["state"], r["insurance_company"]) for r in surg}
    img_pairs = {(r["state"], r["insurance_company"]) for r in img}
    assert img_pairs == pairs
    assert len(img) == len(pairs) * len(IMAGING_CPTS)


def test_imaging_rows_carry_only_imaging_codes():
    assert {r["cpt"] for r in _rows(IMAGING)} == IMAGING_CPTS


def test_surgery_directory_carries_no_imaging_codes():
    """The two files must not overlap -- that is the whole point of the split."""
    assert not IMAGING_CPTS & {r["cpt"] for r in _rows(SURGERY)}


def test_every_settled_imaging_row_has_a_note():
    """A status other than NOT RESEARCHED is a claim, and a claim needs evidence."""
    unexplained = [r for r in _rows(IMAGING)
                   if r["status"] != "NOT RESEARCHED" and not r["note"].strip()]
    assert not unexplained, unexplained[:5]


def test_no_imaging_url_points_at_a_surgery_document():
    """Guards the exact near-miss this split exists to prevent."""
    surgery_urls = {r["policy_url"] for r in _rows(SURGERY) if r["policy_url"].strip()}
    leaked = [r for r in _rows(IMAGING)
              if r["policy_url"].strip() and r["policy_url"] in surgery_urls]
    assert not leaked, leaked[:5]


def test_aetna_shoulder_mri_is_not_claimed_as_verified():
    """Aetna CPB 0171 has NO shoulder criteria -- verified negative, twice.

    Reusing its knee language for a 73221 denial would cite criteria that do
    not exist, so this cell must never read VERIFIED.
    """
    for r in _rows(IMAGING):
        if r["insurance_company"] == "Aetna" and r["cpt"] == "73221":
            assert not r["status"].startswith("VERIFIED"), r
