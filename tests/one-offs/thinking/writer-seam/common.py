"""
Shared fixtures for the writer-seam POC.

Question: does keeping the sheet WRITER generic (taking a renderer) buy real
reuse for a second presenter, or would moving it wholesale into a markers
module cost nothing?

Both arms below implement the SAME second presenter -- a ship-outfitting
availability sheet -- and we count how much non-presentation logic each is
forced to write. The second presenter is deliberately unlike the market one:
binary available/unavailable rather than a five-level fill scale, a different
symbol vocabulary, different columns, no colour ramp.
"""

from dataclasses import dataclass, field


# --- the generic mechanics both structures share (abbreviated from sheets.py) ---

class WriteRefused(Exception):
    pass


@dataclass(frozen=True)
class Guard:
    """Stand-in for WriteGuard: allowed A1 ranges per tab."""
    allowed: tuple = ()

    def check(self, tab, a1):
        col = a1.split(":")[0].rstrip("0123456789")
        if (tab, col) not in self.allowed:
            raise WriteRefused(f"refusing {tab}!{a1}")


@dataclass
class Plan:
    updates: list = field(default_factory=list)
    formats: list = field(default_factory=list)
    marked_rows: list = field(default_factory=list)

    def ranges(self):
        return [u["range"] for u in self.updates]


class FakeWorksheet:
    def __init__(self):
        self.batches = []
        self.format_batches = []

    def batch_update(self, data, **kw):
        self.batches.append([dict(d) for d in data])

    def batch_format(self, formats):
        self.format_batches.append([dict(f) for f in formats])


# --- the domain objects (stand-ins for Match / RequirementSnapshot) ---

@dataclass(frozen=True)
class Row:
    """One spreadsheet row's worth of state, domain-agnostic."""
    row: int
    name: str
    need: int
    available: int          # stock, or 1/0 for a module being in stock
    price: int


@dataclass(frozen=True)
class Snapshot:
    rows: tuple
    first_data_row: int
    last_data_row: int


def market_rows():
    """Settlement commodities -- the existing domain."""
    return Snapshot(
        rows=(Row(5, "Aluminium", 0, 1115586, 2122),
              Row(6, "Biowaste", 42, 49267, 51),
              Row(7, "Grain", 231, 0, 0)),
        first_data_row=5, last_data_row=7,
    )


def outfitting_rows():
    """Ship modules -- the SECOND domain. Availability is binary."""
    return Snapshot(
        rows=(Row(4, "6A Power Plant", 1, 1, 18000000),
              Row(5, "5A Thrusters", 1, 0, 5100000),
              Row(6, "Guardian FSD Booster", 2, 1, 3000000)),
        first_data_row=4, last_data_row=6,
    )
