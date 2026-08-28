"""Where the patient sends the appeal: per-insurer routes, honestly sourced.

A wrong appeals address can cost a patient their deadline, so every specific
route must carry its source, and a route we could not verify must say so
instead of guessing.
"""
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
ROUTES = json.loads(
    (ROOT / "data/policy_platform/appeal_submission_routes.json").read_text())
SUBMIT_JS = (ROOT / "mockups/assets/submit.js").read_text()
APP = (ROOT / "mockups/map/index.html").read_text()


def test_every_route_names_its_source():
    for r in ROUTES["routes"]:
        assert r["source_url"].startswith("http"), r["insurer"]
        assert r["confidence"] in ("high", "medium", "low"), r["insurer"]


def test_low_confidence_routes_never_state_an_address_as_fact():
    """If we could not verify the address, the mail field must say so and
    point at the denial letter -- never a guessed PO box."""
    for r in ROUTES["routes"]:
        if r["confidence"] == "low":
            m = r["mail"].lower()
            assert ("could not verify" in m or "no published" in m
                    or "denial letter" in m or "local office" in m
                    or "benefit handbook" in m), r["insurer"]


def test_generated_js_matches_the_data():
    for r in ROUTES["routes"]:
        for token in r["match"]:
            assert json.dumps(token) in SUBMIT_JS or f'"{token}"' in SUBMIT_JS


def test_app_checks_extended_routes_first_and_longest_token_wins():
    assert "APPEAL_SUBMIT_EXT" in APP
    assert "k.length > best.length" in APP


def test_hcsc_portals_only_serve_hcsc_states():
    """The five-state HCSC entry must never be served to other Blues --
    a Premera member told to log in at bcbsil.com is a wrong answer."""
    i = APP.index("function submitFor")
    seg = APP[i:i + 3000]
    assert "has('illinois', 'texas', 'oklahoma', 'new mexico', 'montana')" in seg


def test_demo_inlines_the_routes():
    demo = (ROOT / "dist/orthoappeal-demo.html").read_text()
    assert "APPEAL_SUBMIT_EXT" in demo
