"""
The location cells are written only when asked -- #25's second half.

v0.7.6 stopped `market --update-sheet` blanking a marker column that holds
formulas. It kept writing the two location cells unconditionally, and #25's own
body names them: in the incident that opened the issue, C2 and G2 "were also
overwritten", invisibly, because the literal happened to match what the formula
had been resolving to. On a sheet whose C2/G2 read the generated MarketData tab,
every `market --update-sheet` replaced the formulas with a snapshot.

`serve` learned this earlier and gates the cells behind `--write-location`,
off by default. These tests hold `market` to the same rule, and hold `serve`
to still honouring the flag now that the plan itself defaults to no location.

Skip-if-occupied was weighed for these cells in v0.7.7 and dropped: a stale
literal the skip left in place would never refresh, so an opt-in was the
honest shape. v0.8.1's writes ledger removes that objection -- the tool's own
last literal is refreshed -- so the cells, when asked for, now obey the same
rule as the glyph markers: a formula there is held.
"""

from __future__ import annotations

import pytest

from test_marker_skip_occupied import RangeAwareWorksheet, _cli


SYSTEM_FORMULA = "=MarketData!$E$1"
STATION_FORMULA = "=MarketData!$C$1"


def _grid_with_location_formulas():
    """The suite's totals grid, with C2 and G2 reading MarketData."""
    from test_service import ROWS, totals_grid

    grid = totals_grid(ROWS)
    grid[1][2] = SYSTEM_FORMULA     # C2
    grid[1][6] = STATION_FORMULA    # G2
    return grid


def _written(sheet) -> set[str]:
    return {u["range"] for batch in sheet.batches for u in batch}


def test_update_sheet_leaves_location_formulas_alone(
        tmp_path, monkeypatch, capsys, configured_totals):
    sheet = RangeAwareWorksheet(_grid_with_location_formulas())
    code = _cli(tmp_path, monkeypatch, sheet)
    out = capsys.readouterr().out

    assert code == 0, out
    written = _written(sheet)
    assert "C2" not in written and "G2" not in written, (
        f"market --update-sheet wrote over the location formulas: {written}\n{out}"
    )
    # ...and it still did its actual job: the marker column was written.
    assert any(r.startswith("L") for r in written), written


def test_write_location_fills_empty_location_cells(
        tmp_path, monkeypatch, capsys, configured_totals):
    from test_service import ROWS, totals_grid

    sheet = RangeAwareWorksheet(totals_grid(ROWS))
    code = _cli(tmp_path, monkeypatch, sheet, "--write-location")
    out = capsys.readouterr().out

    assert code == 0, out
    values = {u["range"]: u["values"] for batch in sheet.batches for u in batch}
    assert values.get("C2") == [["Lhou Mans"]], values
    assert values.get("G2") == [["Ryman Enterprise"]], values


def test_write_location_leaves_location_formulas_alone_since_v081(
        tmp_path, monkeypatch, capsys, configured_totals):
    """
    Until v0.8.0, `--write-location` overwrote whatever C2/G2 held. From
    v0.8.1 the location cells obey the writes ledger like the glyph markers
    (slice 4, decision 1): a formula the tool never wrote is someone else's,
    held and reported. The formulas pointing at MarketData are exactly what
    this issue asked people to put there.
    """
    sheet = RangeAwareWorksheet(_grid_with_location_formulas())
    code = _cli(tmp_path, monkeypatch, sheet, "--write-location")
    out = capsys.readouterr().out

    assert code == 0, out
    written = _written(sheet)
    assert "C2" not in written and "G2" not in written, written
    assert "C2" in out and "G2" in out, "the held cells are reported, not silently skipped"


def test_force_still_writes_the_location_cells(
        tmp_path, monkeypatch, capsys, configured_totals):
    sheet = RangeAwareWorksheet(_grid_with_location_formulas())
    code = _cli(tmp_path, monkeypatch, sheet, "--write-location", "--force")
    out = capsys.readouterr().out

    assert code == 0, out
    values = {u["range"]: u["values"] for batch in sheet.batches for u in batch}
    assert values.get("C2") == [["Lhou Mans"]], values


def test_the_dry_run_names_the_location_cells_only_when_asked(
        tmp_path, monkeypatch, capsys, configured_totals):
    """#25 criterion 5: what will be written is visible before it is."""
    sheet = RangeAwareWorksheet(_grid_with_location_formulas())
    _cli(tmp_path, monkeypatch, sheet, "--dry-run")
    quiet = capsys.readouterr().out

    _cli(tmp_path, monkeypatch, sheet, "--dry-run", "--write-location")
    asked = capsys.readouterr().out

    assert sheet.batches == []
    assert "C2" not in quiet and "G2" not in quiet, quiet
    assert "C2" in asked and "G2" in asked, asked


def test_a_context_that_forgot_to_carry_write_location_does_not_write_it():
    """
    The plugin reads the option with `.get(..., False)`: a refresh context
    assembled without it must come out as "leave the cells alone".
    """
    from test_marker_skip_occupied import (
        Layout, RecordingWorksheet, Renderer, Snapshot, _result_at,
    )

    from APITool.plugins import totals
    from APITool.registry import Refresh
    from APITool.sheets import WriteGuard

    layout = Layout()
    ctx = Refresh(
        {"requirements": lambda ctx: Snapshot([5])},
        worksheet=RecordingWorksheet(),
        layout=layout,
        guard=WriteGuard.build(layout.writes()),
        catalog=None,
        renderer=Renderer(),
        options={"write": False, "write_header": False, "show_covered": True,
                 "apply_colour": False, "include_markers": True},
        target="",
        result=_result_at(rows=[5]),
        checked_at="",
    )
    plan = totals._publish_markers(ctx)

    ranges = {u["range"] for u in plan.updates}
    assert layout.system_cell not in ranges and layout.station_cell not in ranges, ranges


@pytest.mark.parametrize("flag", [True, False])
def test_serve_still_honours_its_own_flag(monkeypatch, tmp_path, flag):
    """
    `serve --write-location` shares the plan builder, whose default is now
    "no location". The daemon has to ask for the cells itself, or the flag
    would silently stop working.

    Capture-and-abort (rule 1b): the service stand-in records what the market
    publisher asked it for and raises, and the exporter is a stand-in, so no
    real spreadsheet is reachable whatever the code under test does.
    """
    import APITool.google as google_mod
    from APITool import daemon
    from APITool.plugins.totals.layout import SheetLayout

    class Stop(Exception):
        pass

    seen: dict = {}

    class Service:
        def __init__(self, **kwargs):
            pass

        def refresh(self, **kwargs):
            seen.update(kwargs)
            raise Stop

    class Exporter:
        def __init__(self, *args, **kwargs):
            pass

        def worksheet(self, sheet_id, tab):
            return object()

    monkeypatch.setattr(daemon, "MarketRefreshService", Service)
    monkeypatch.setattr(google_mod, "GoogleSheetsExporter", Exporter)

    worker = daemon.build(
        sheet_id="unused", journal_dir=tmp_path, layout=SheetLayout(),
        write_location=flag, publish_carrier=False, log=lambda _: None,
    )
    publisher = next(p for p in worker.publishers() if p.name == "market")
    with pytest.raises(Stop):
        publisher.publish()

    assert seen["options"]["write_location"] is flag     # the plugin's word, sealed
    assert seen["write"] is flag                          # core's word, in the open
    # serve's market publish never paints glyphs: MarketData is the data and
    # the sheet's own formulas draw from it. The daemon says so in the
    # plugin's word; a sweep found nothing reading it.
    assert seen["options"]["no_markers"] is True
