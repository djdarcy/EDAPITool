"""
move-code, 2026-09-26: lift export_cargo's steps 1-3 into carrier_rows(), verbatim.

The block (exporter.py lines 536-572 at ca00b11 + this session's work) is cut
byte-for-byte, dedented by four spaces (method body -> function body), and
placed above carrier_grid, which it feeds. export_cargo gets one call in its
place. Nothing is retyped; run once, then `git diff` shows the move.
"""
import pathlib

path = pathlib.Path(__file__).resolve().parents[2] / "APITool" / "google" / "exporter.py"
raw = path.read_bytes().decode("utf-8")
nl = "\r\n" if "\r\n" in raw else "\n"
lines = raw.split(nl)

start = next(i for i, l in enumerate(lines) if l == "        # Step 1: Filter cargo based on flags")
end = next(i for i, l in enumerate(lines) if l == '        data.sort(key=lambda x: x["display_name"])')
assert end - start == 36, (start, end)          # the 37 lines captured by Read
block = lines[start:end + 1]
assert all(l == "" or l.startswith("    ") for l in block)
moved = [l[4:] if l else l for l in block]

function = [
    "def carrier_rows(",
    "    carrier: FleetCarrier,",
    "    include_stolen: bool = False,",
    "    include_mission: bool = False,",
    ") -> list[dict]:",
    '    """',
    "    The carrier's hold, one row per commodity, for :func:`carrier_grid`.",
    "",
    "    Moved verbatim out of ``export_cargo`` (v0.8.2) so the FreighterData grid",
    "    can be built without writing it -- the daemon places the same grid in",
    "    any region bound to the carrier.",
    '    """',
    *moved,
    "    return data",
    "",
    "",
]

# Replace the block with the call, then insert the function above carrier_grid.
lines[start:end + 1] = ["        data = carrier_rows(carrier, include_stolen, include_mission)"]
anchor = next(i for i, l in enumerate(lines) if l == '@generates_tab("FreighterData")')
lines[anchor:anchor] = function

path.write_bytes(nl.join(lines).encode("utf-8"))
print(f"moved {len(block)} lines; carrier_rows inserted at line {anchor + 1}")
