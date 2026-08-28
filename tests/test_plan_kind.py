"""Same insurer name, different rights: the Medicare Advantage layer.

The coverage map is keyed by insurer name, which used to hand a UHC Medicare
Advantage member the commercial InterQual answer. These tests pin the fix.
"""
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
OVERRIDES = json.loads(
    (ROOT / "data/policy_platform/ma_plan_overrides.json").read_text())
COVERAGE = (ROOT / "mockups/assets/coverage.js").read_text()
APP = (ROOT / "mockups/map/index.html").read_text()


def test_every_override_cites_a_document_and_a_reason():
    for ov in OVERRIDES["overrides"]:
        assert ov["policy_url"].startswith("http"), ov
        assert ov["why"].strip(), ov
        assert ov["evidence"].strip(), ov
        assert ov["code"] in ("A", "L", "V"), ov
        assert ov["cpts"], ov


def test_coverage_js_carries_the_ma_map():
    m = re.search(r'"ma":\{(.*?)\}\}', COVERAGE)
    assert '"ma":' in COVERAGE
    total = sum(len(ov["cpts"]) for ov in OVERRIDES["overrides"])
    for ov in OVERRIDES["overrides"]:
        for cpt in ov["cpts"]:
            assert f'"{ov["insurer"]}|{cpt}"' in COVERAGE


def test_app_asks_plan_kind_and_uses_it():
    assert "drawPlanKind" in APP
    assert "'plankind'" in APP
    # Medicare/Medicaid pickers skip the question
    assert "/^(medicare|medicaid)$/i.test(A.insurer" in APP
    # covFor consults the MA map only for MA members
    assert "A.planKind === 'ma' && C.ma" in APP


def test_ma_members_get_the_federal_transparency_argument():
    """42 CFR 422.101(b)(6): an MA plan's internal criteria must be publicly
    accessible. For a vendor-locked denial this is the appeal's spine, so the
    app must render it for MA members."""
    assert "422.101(b)" in APP
    assert "CMS-4201-F" in APP
    assert "publicly accessible" in APP


def test_demo_build_includes_the_ma_layer():
    demo = (ROOT / "dist/orthoappeal-demo.html").read_text()
    assert "drawPlanKind" in demo
    assert '"ma":' in demo


def test_imaging_flow_asks_for_xray_not_mri():
    """The MRI itself was denied -- the flow must ask about the x-ray that
    every vendor's MRI criteria require first, not about an MRI."""
    data = (ROOT / "mockups/assets/data.js").read_text()
    m = re.search(r"imaging: \[([^\]]*)\]", data)
    assert m and '"xray"' in m.group(1) and '"mri"' not in m.group(1)
