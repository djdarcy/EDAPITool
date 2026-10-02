"""
Smokes for the service running an ordered list of bound steps (slice 1,
unit 3; scenarios S1, S2, S3).

S1 is the configuration the stock config's header has recommended since
v0.7.8 -- a totals target beside a jsonl target -- which silently wrote
nothing until the pipeline. Everything here runs against fakes: a grid in
memory for the sheet, a file under tmp_path for the log.
"""

import json

from test_service import ROWS, FakeWorksheet, docked_event, make_journal, ryman_market_json, totals_grid

from APITool.catalog import load_catalog
from APITool.loader import build_enforcer
from APITool.plugins import jsonl, totals
from APITool.plugins.totals.layout import SheetLayout
from APITool.service import MarketRefreshService, StepSpec
from APITool.sheets.writer import MarkerPlan


def _totals_spec(worksheet) -> StepSpec:
    layout = SheetLayout()
    return StepSpec("totals-workbook", totals, layout, build_enforcer("gsheet", layout.writes()),
                    worksheet=worksheet)


def _jsonl_spec(path) -> StepSpec:
    layout = jsonl.layout(path=str(path))
    return StepSpec("market-log", jsonl, layout, build_enforcer("jsonl", layout.writes()))


def _service(tmp_path, specs) -> MarketRefreshService:
    journal = make_journal(tmp_path, [docked_event()], ryman_market_json())
    return MarketRefreshService(journal_dir=journal, catalog=load_catalog(),
                                layout=specs[0].layout, guard=specs[0].guard,
                                target=specs[0].target, steps=specs)


def _record(path) -> dict:
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1, "one record per refresh"
    return json.loads(lines[0])


def test_the_totals_and_jsonl_targets_both_run_and_the_log_carries_the_matches(tmp_path):
    """S1: the P4 configuration, end to end."""
    sheet = FakeWorksheet(totals_grid(ROWS))
    log = tmp_path / "market.jsonl"
    service = _service(tmp_path, [_totals_spec(sheet), _jsonl_spec(log)])

    result = service.refresh(worksheet=sheet, write=True)

    assert result.ok and result.matches, "the comparison ran against the totals grid"
    assert isinstance(result.plan, MarkerPlan), "totals reported its plan"
    record = _record(log)
    assert [r["name"] for r in record["requirements"]] == [m.requirement.name for m in result.matches]


def test_totals_listed_after_jsonl_still_reads_its_own_worksheet(tmp_path):
    """
    S2: the requirements supplier runs in the totals plugin's own view, not
    the caller's. The refresh is handed a decoy worksheet with no rows; the
    totals step carries the real grid. If the supplier ran in the caller's
    view the log would carry no requirements at all.
    """
    real = FakeWorksheet(totals_grid(ROWS))
    decoy = FakeWorksheet(totals_grid([]))
    log = tmp_path / "market.jsonl"
    service = _service(tmp_path, [_jsonl_spec(log), _totals_spec(real)])

    result = service.refresh(worksheet=decoy, write=True)

    assert result.matches, "requirements came from the totals grid"
    assert len(_record(log)["requirements"]) == len(result.matches)
    assert service.suppliers.offered_by["requirements"] == "totals-workbook"


def test_a_jsonl_only_pipeline_logs_without_any_worksheet(tmp_path):
    """S3: a file step needs no worksheet; nothing reaches for one."""
    log = tmp_path / "market.jsonl"
    service = _service(tmp_path, [_jsonl_spec(log)])

    result = service.refresh(worksheet=None, write=True)

    assert result.ok
    record = _record(log)
    assert record["station"] == "Ryman Enterprise"
    assert record["requirements"] == [], "no totals plugin, so nothing to compare"
