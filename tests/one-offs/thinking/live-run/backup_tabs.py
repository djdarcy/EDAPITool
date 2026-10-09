"""
The live run's ground (goal 2026-10-09__04-49-57, slice A, unit A0): read
every tab of the workbook the configuration names and save its values as
JSON, one file per tab, under a stamped directory. A read, never a write;
the exporter's own client, so the credential files are the tool's to open.

    python tests/one-offs/thinking/live-run/backup_tabs.py [--sheet-id ID] [--out DIR]

Restoring from these is a person's job (paste, or a one-off written then);
their purpose is that a step which goes wrong can be compared against what
the tab held before it.
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from APITool import settings  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheet-id", default=None, help="default: the first gsheet target's id")
    ap.add_argument("--out", default=None, help="default: the session scratchpad's live-run/<stamp>")
    args = ap.parse_args()

    sheet_id = args.sheet_id or settings.get_sheet_id()
    if not sheet_id:
        print("no sheet id: pass --sheet-id or configure a gsheet target")
        return 1
    stamp = datetime.now().strftime("%Y-%m-%d__%H-%M-%S")
    out = Path(args.out) if args.out else Path(os.environ.get("CLAUDE_SCRATCHPAD", Path.cwd() / "test_runs")) / "live-run" / stamp
    out.mkdir(parents=True, exist_ok=True)

    from APITool.google import GoogleSheetsExporter

    book = GoogleSheetsExporter()._get_client().open_by_key(sheet_id)
    manifest = {"sheet_id": sheet_id, "title": book.title, "stamp": stamp, "tabs": []}
    for ws in book.worksheets():
        values = ws.get_all_values()
        safe = "".join(c if c.isalnum() or c in "-_. ()" else "_" for c in ws.title)
        path = out / f"{safe}.json"
        path.write_text(json.dumps({"title": ws.title, "id": ws.id, "hidden": ws.isSheetHidden,
                                    "rows": len(values), "cols": max((len(r) for r in values), default=0),
                                    "values": values}, ensure_ascii=False), encoding="utf-8")
        manifest["tabs"].append({"title": ws.title, "rows": len(values), "file": path.name})
        print(f"  {ws.title:<28} {len(values):>5} rows -> {path.name}")
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"{len(manifest['tabs'])} tabs of '{book.title}' saved under {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
