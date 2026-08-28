"""DataQorp rows are leads, never answers. The importer must be structurally
incapable of writing to the app directory."""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = (ROOT / "scripts/ingest_dataqorp.py").read_text()


def test_importer_never_writes_the_directory():
    # it may READ the directory to spot gaps; it must only WRITE the leads file
    assert "dataqorp_leads.json" in SRC
    for line in SRC.splitlines():
        if "app_option_policy_directory" in line or "app_option_imaging" in line:
            assert "write" not in line.lower(), line


def test_leads_are_labelled_unverified():
    assert "LEAD — unverified, do not cite" in SRC


def test_column_mapping_fails_loudly_not_silently():
    assert "could not find columns" in SRC
