"""
`serve --once` says what it is NOT publishing, as the watch path does.

Found live by the v0.10.1 checklist, step 3.3: with no usable Frontier
login the once-path printed "Publishing 3 target(s) once." and nothing
about the carrier, while the watch path prints the daemon's gaps before
it starts. A partial setup must not look like a complete one on either
path. The worker is a fake: nothing is read or written.
"""

import json

import pytest

from APITool import cli, settings
from APITool.cli import main


class FakeWorker:
    def publishers(self):
        return []

    def describe_gaps(self):
        return ["NOT published: FreighterData -- no Frontier login (edapitool auth)"]


@pytest.fixture
def planted(monkeypatch, tmp_path):
    directory = tmp_path / "cfg"
    directory.mkdir()
    (directory / "config.json").write_text(json.dumps({"targets": {"my-workbook": {
        "kind": "gsheet", "id": "FAKE_SHEET_ID_NEVER_CONTACTED",
        "regions": [{"region": "Hauling!H1:N200", "data": "market"}],
    }}}), encoding="utf-8")
    monkeypatch.setenv("ED_CONFIG_DIR", str(directory))
    monkeypatch.setattr(settings, "CONFIG_FILE", directory / "config.json")
    monkeypatch.delenv("ED_SHEET_ID", raising=False)
    monkeypatch.setattr(cli, "_build_worker", lambda *a, **k: FakeWorker())


def test_serve_once_names_what_it_does_not_publish(planted, capsys):
    assert main(["serve", "--once", "--journal-dir", "."]) == 0
    out = capsys.readouterr().out
    assert "NOT published: FreighterData -- no Frontier login" in out
