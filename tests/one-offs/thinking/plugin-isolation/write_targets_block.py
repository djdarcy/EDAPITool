"""
Rewrite this install's config into the ``targets`` shape (R1, slice D).

Written as a script rather than done by hand because the file holds a client
id that must not be echoed into a transcript, and because the transformation
is mechanical: three top-level keys become one named target, keeping the one
key core still owns.

    before                          after
    ------                          -----
    client_id                       client_id
    sheet_id                        targets.settlement-workbook.id
    construction_regions            targets.settlement-workbook.config.*

Idempotent: a file that already has ``targets`` is left alone and says so.
The write goes through a temporary file in the same directory and an atomic
replace, for the reason ``settings.save`` does -- this file holds region
bindings somebody typed by hand and there is no copy but the backup.
"""

import json
import os
import sys
from pathlib import Path

TARGET_NAME = "settlement-workbook"
PLUGIN = "settlement"
KIND = "gsheet"
# What core reads at the top level. Everything else belongs to the plugin.
CORE_KEYS = {"client_id", "sheet_id", "plugin_dir", "targets"}


def main() -> int:
    path = Path(os.environ.get("ED_CONFIG_DIR", Path.home() / "edapitool")) / "config.json"
    if not path.exists():
        print(f"no config at {path}")
        return 1

    data = json.loads(path.read_text())
    if data.get("targets") is not None:
        print("already in the targets shape; nothing to do")
        return 0

    sheet_id = data.get("sheet_id")
    if not sheet_id:
        print('no "sheet_id" to carry into a target')
        return 1

    block = {k: v for k, v in data.items() if k not in CORE_KEYS}
    out = {k: v for k, v in data.items() if k in CORE_KEYS and k != "sheet_id"}
    out["targets"] = {
        TARGET_NAME: {
            "kind": KIND,
            "id": sheet_id,
            "plugin": PLUGIN,
            "config": block,
        }
    }

    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(out, indent=2) + "\n")
    os.replace(tmp, path)

    print(f"rewrote {path}")
    print(f"  top level now: {', '.join(sorted(out))}")
    print(f"  target {TARGET_NAME!r}: kind={KIND} plugin={PLUGIN} "
          f"id=<{len(sheet_id)} chars>")
    print(f"  moved into its config block: {', '.join(sorted(block)) or '(nothing)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
