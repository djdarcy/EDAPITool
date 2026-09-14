"""POC: try to REFUTE the observation-store schema before it is built.

Design under test:
  2026-09-14__18-22-16__dev-workflow-process__the-observation-store-and-what-custody-means.md

    sources(source_id, kind, machine, locator, identity_hash,
            first_seen, last_verified, liveness)
    every observation carries source_id
    recoverability is COMPUTED: drop a row only if its source is 'present'
    AND its identity_hash still verifies.

This script exists to KILL hypotheses, not to demonstrate a store. Each arm
states a prediction, a pass criterion and a fallback BEFORE it runs, and one
arm is a CONTROL that is predicted to FAIL -- if the control passes, the
instrument cannot detect failure and no result here means anything.

Run:  python tests/one-offs/thinking/observation-store/poc.py [journal-dir]
"""

import hashlib
import json
import os
import sqlite3
import sys
import time
from collections import defaultdict
from pathlib import Path

DEFAULT_DIR = Path(
    os.path.expanduser("~/Saved Games/Frontier Developments/Elite Dangerous")
)
DB_PATH = Path(__file__).with_name("poc_store.db")

DEPOT = "ColonisationConstructionDepot"
CONTRIB = "ColonisationContribution"
BGS_EVENTS = ("FSDJump", "Location", "CarrierJump")
TXN = ("MarketBuy", "MarketSell")

results = []


def record(arm, prediction, observation, verdict, fallback=""):
    results.append((arm, prediction, observation, verdict, fallback))
    print(f"\n[{verdict}] {arm}")
    print(f"    predicted : {prediction}")
    print(f"    observed  : {observation}")
    if fallback and verdict in ("REFUTED", "DIED"):
        print(f"    fallback  : {fallback}")


# ---------------------------------------------------------------------------
# Shared load. Read every file once, keeping the raw line and byte offset so
# the alternative keys in H2 can be tested without a second pass.
# ---------------------------------------------------------------------------


def load_events(files):
    """-> list of (path, offset, seq_in_file, event_dict, raw_line_bytes)."""
    out = []
    for path in files:
        seq = 0
        with path.open("rb") as fh:
            offset = 0
            for raw in fh:
                n = len(raw)
                stripped = raw.strip()
                if stripped:
                    try:
                        ev = json.loads(stripped)
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        offset += n
                        continue
                    name = ev.get("event")
                    if name == DEPOT or name == CONTRIB or name in BGS_EVENTS \
                            or name in TXN:
                        out.append((path, offset, seq, ev, stripped))
                        seq += 1
                offset += n
    return out


# ---------------------------------------------------------------------------
# H1 -- liveness verification cheap enough to actually run?
# ---------------------------------------------------------------------------


def h1_liveness(files):
    prediction = "full SHA-256 over the corpus completes in under 10s"

    t0 = time.perf_counter()
    total_bytes = 0
    full_hashes = {}
    for p in files:
        h = hashlib.sha256()
        with p.open("rb") as fh:
            while True:
                chunk = fh.read(1 << 20)
                if not chunk:
                    break
                total_bytes += len(chunk)
                h.update(chunk)
        full_hashes[p] = h.hexdigest()
    full_secs = time.perf_counter() - t0

    # the cheaper identity, in case the full hash is too slow
    t0 = time.perf_counter()
    cheap = {}
    for p in files:
        st = p.stat()
        h = hashlib.sha256()
        with p.open("rb") as fh:
            h.update(fh.read(65536))
            if st.st_size > 131072:
                fh.seek(-65536, os.SEEK_END)
                h.update(fh.read(65536))
        cheap[p] = (st.st_size, st.st_mtime_ns, h.hexdigest())
    cheap_secs = time.perf_counter() - t0

    mb = total_bytes / (1024 * 1024)
    obs = (
        f"{len(files)} files, {mb:.1f} MB; "
        f"full sha256 {full_secs:.2f}s ({mb/full_secs:.0f} MB/s); "
        f"cheap identity {cheap_secs:.3f}s"
    )
    verdict = "SURVIVED" if full_secs < 10 else "DIED"
    record(
        "H1 liveness verification cost", prediction, obs, verdict,
        "use (size, mtime_ns, sha256 of first+last 64KB) as identity",
    )

    # cheap side-check: duplicate files already in the corpus?
    seen = defaultdict(list)
    for p, digest in full_hashes.items():
        seen[digest].append(p.name)
    dupes = {d: n for d, n in seen.items() if len(n) > 1}
    print(f"    aside     : duplicate-content journal files: {len(dupes)}")
    for names in list(dupes.values())[:3]:
        print(f"                {names}")

    return full_hashes, cheap


# ---------------------------------------------------------------------------
# H2 -- does a natural key make re-import idempotent?
# ---------------------------------------------------------------------------


def key_collisions(rows, keyfunc):
    """-> (n_keys, n_colliding_keys, n_colliding_with_DIFFERENT_content)."""
    buckets = defaultdict(list)
    for path, offset, seq, ev, raw in rows:
        buckets[keyfunc(path, offset, seq, ev)].append(raw)
    colliding = {k: v for k, v in buckets.items() if len(v) > 1}
    differing = {k: v for k, v in colliding.items() if len(set(v)) > 1}
    return len(buckets), len(colliding), len(differing)


def h2_natural_key(events):
    depot = [e for e in events if e[3].get("event") == DEPOT]
    bgs = [e for e in events if e[3].get("event") in BGS_EVENTS
           and e[3].get("Factions")]
    txn = [e for e in events if e[3].get("event") in TXN]

    print(f"\n--- H2 corpus: depot={len(depot)} bgs={len(bgs)} txn={len(txn)}")

    # CONTROL ARM. Keyed on MarketID alone, collisions are certain. If this
    # reports zero collisions the instrument is broken and nothing else here
    # can be trusted.
    n, coll, diff = key_collisions(
        depot, lambda p, o, s, ev: (ev.get("MarketID"),)
    )
    control_ok = coll > 0 and diff > 0
    record(
        "CONTROL (MarketID alone -- predicted to FAIL)",
        "collisions with DIFFERING content are detected (proves the instrument works)",
        f"{n} distinct keys, {coll} colliding, {diff} with differing content",
        "CONTROL-OK" if control_ok else "METHOD-BROKEN",
    )
    if not control_ok:
        print("\n*** CONTROL PASSED WHEN IT SHOULD HAVE FAILED -- "
              "instrument cannot detect collisions. Discarding all results. ***")
        return None

    # the proposed key
    prediction = "(MarketID, timestamp) is unique for depot observations"
    n, coll, diff = key_collisions(
        depot, lambda p, o, s, ev: (ev.get("MarketID"), ev.get("timestamp"))
    )
    obs = f"{n} distinct keys from {len(depot)} events; {coll} colliding, {diff} with DIFFERING content"
    verdict = "SURVIVED" if diff == 0 else "DIED"
    record(
        "H2a depot (MarketID, timestamp)", prediction, obs, verdict,
        "key on a content hash of the raw event line",
    )

    # same question for BGS and transactions
    for label, rows, kf, pred in (
        ("H2b BGS (SystemAddress, timestamp)", bgs,
         lambda p, o, s, ev: (ev.get("SystemAddress"), ev.get("timestamp")),
         "unique per system-visit"),
        ("H2c transactions (MarketID, timestamp, Type)", txn,
         lambda p, o, s, ev: (ev.get("MarketID"), ev.get("timestamp"),
                              ev.get("Type")),
         "unique per transaction"),
    ):
        n, coll, diff = key_collisions(rows, kf)
        obs = f"{n} distinct keys from {len(rows)} events; {coll} colliding, {diff} differing"
        record(label, pred, obs, "SURVIVED" if diff == 0 else "DIED",
               "key on a content hash of the raw event line")

    # the fallback candidate, tested rather than assumed
    prediction = "sha256(raw event line) is collision-free AND dedups identical re-reads"
    n, coll, diff = key_collisions(
        depot, lambda p, o, s, ev: hashlib.sha256(
            json.dumps(ev, sort_keys=True).encode()).hexdigest()
    )
    obs = (f"{n} distinct content hashes from {len(depot)} depot events; "
           f"{coll} repeated, {diff} with differing content (must be 0 by construction)")
    record("H2d fallback: content hash", prediction, obs,
           "SURVIVED" if diff == 0 else "METHOD-BROKEN")

    return {"depot": depot, "bgs": bgs, "txn": txn}


# ---------------------------------------------------------------------------
# H3 / H4 -- build the store for real, measure it, then test the merge.
# ---------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE sources (
    source_id     INTEGER PRIMARY KEY,
    kind          TEXT NOT NULL,
    machine       TEXT NOT NULL,
    locator       TEXT NOT NULL,
    identity_hash TEXT NOT NULL,
    first_seen    TEXT NOT NULL,
    last_verified TEXT,
    liveness      TEXT NOT NULL DEFAULT 'present',
    UNIQUE (machine, locator)
);
CREATE TABLE depot_observation (
    obs_hash    TEXT PRIMARY KEY,
    source_id   INTEGER NOT NULL REFERENCES sources(source_id),
    market_id   INTEGER NOT NULL,
    observed_at TEXT NOT NULL,
    progress    REAL,
    complete    INTEGER,
    failed      INTEGER
);
CREATE TABLE depot_resource (
    obs_hash   TEXT NOT NULL REFERENCES depot_observation(obs_hash),
    symbol     TEXT NOT NULL,
    name       TEXT,
    required   INTEGER NOT NULL,
    provided   INTEGER NOT NULL,
    payment    INTEGER,
    PRIMARY KEY (obs_hash, symbol)
);
CREATE TABLE faction_observation (
    obs_hash    TEXT PRIMARY KEY,
    source_id   INTEGER NOT NULL REFERENCES sources(source_id),
    system_addr INTEGER,
    system_name TEXT,
    observed_at TEXT NOT NULL
);
CREATE TABLE faction_state (
    obs_hash  TEXT NOT NULL REFERENCES faction_observation(obs_hash),
    faction   TEXT NOT NULL,
    influence REAL,
    state     TEXT,
    happiness TEXT,
    PRIMARY KEY (obs_hash, faction)
);
CREATE TABLE txn (
    obs_hash    TEXT PRIMARY KEY,
    source_id   INTEGER NOT NULL REFERENCES sources(source_id),
    market_id   INTEGER,
    observed_at TEXT NOT NULL,
    symbol      TEXT,
    count       INTEGER,
    buy_price   INTEGER,
    sell_price  INTEGER
);
CREATE TABLE contribution (
    obs_hash    TEXT PRIMARY KEY,
    source_id   INTEGER NOT NULL REFERENCES sources(source_id),
    market_id   INTEGER,
    observed_at TEXT NOT NULL
);
CREATE INDEX ix_depot_site_time ON depot_observation(market_id, observed_at);
CREATE INDEX ix_res_symbol ON depot_resource(symbol);
CREATE INDEX ix_faction_sys ON faction_observation(system_addr, observed_at);
"""


def obs_hash(ev):
    return hashlib.sha256(json.dumps(ev, sort_keys=True).encode()).hexdigest()


def build_store(db, events, machine, hashes):
    """Ingest with INSERT OR IGNORE so re-import must be a no-op."""
    cur = db.cursor()
    src_ids = {}
    now = "2026-09-14T00:00:00Z"
    for path, offset, seq, ev, raw in events:
        if path not in src_ids:
            cur.execute(
                "INSERT OR IGNORE INTO sources"
                "(kind,machine,locator,identity_hash,first_seen,last_verified,liveness)"
                " VALUES ('journal',?,?,?,?,?, 'present')",
                (machine, path.name, hashes[path], now, now),
            )
            cur.execute(
                "SELECT source_id FROM sources WHERE machine=? AND locator=?",
                (machine, path.name),
            )
            src_ids[path] = cur.fetchone()[0]
        sid = src_ids[path]
        name = ev.get("event")
        h = obs_hash(ev)
        ts = ev.get("timestamp")

        if name == DEPOT:
            cur.execute(
                "INSERT OR IGNORE INTO depot_observation VALUES (?,?,?,?,?,?,?)",
                (h, sid, ev.get("MarketID"), ts, ev.get("ConstructionProgress"),
                 int(bool(ev.get("ConstructionComplete"))),
                 int(bool(ev.get("ConstructionFailed")))),
            )
            for r in ev.get("ResourcesRequired", []):
                cur.execute(
                    "INSERT OR IGNORE INTO depot_resource VALUES (?,?,?,?,?,?)",
                    (h, r.get("Name"), r.get("Name_Localised"),
                     r.get("RequiredAmount", 0), r.get("ProvidedAmount", 0),
                     r.get("Payment")),
                )
        elif name in BGS_EVENTS and ev.get("Factions"):
            cur.execute(
                "INSERT OR IGNORE INTO faction_observation VALUES (?,?,?,?,?)",
                (h, sid, ev.get("SystemAddress"), ev.get("StarSystem"), ts),
            )
            for f in ev["Factions"]:
                cur.execute(
                    "INSERT OR IGNORE INTO faction_state VALUES (?,?,?,?,?)",
                    (h, f.get("Name"), f.get("Influence"),
                     f.get("FactionState"), f.get("Happiness_Localised")),
                )
        elif name in TXN:
            cur.execute(
                "INSERT OR IGNORE INTO txn VALUES (?,?,?,?,?,?,?,?)",
                (h, sid, ev.get("MarketID"), ts, ev.get("Type"),
                 ev.get("Count"), ev.get("BuyPrice"), ev.get("SellPrice")),
            )
        elif name == CONTRIB:
            cur.execute(
                "INSERT OR IGNORE INTO contribution VALUES (?,?,?,?)",
                (h, sid, ev.get("MarketID"), ts),
            )
    db.commit()


def counts(db):
    cur = db.cursor()
    out = {}
    for t in ("sources", "depot_observation", "depot_resource",
              "faction_observation", "faction_state", "txn", "contribution"):
        out[t] = cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    return out


def h3_h4(files, events, hashes):
    if DB_PATH.exists():
        DB_PATH.unlink()
    db = sqlite3.connect(DB_PATH)
    db.executescript(SCHEMA)

    t0 = time.perf_counter()
    build_store(db, events, "this-machine", hashes)
    ingest_secs = time.perf_counter() - t0
    base = counts(db)

    db.commit()
    size = DB_PATH.stat().st_size
    db.execute("VACUUM")
    vacuumed = DB_PATH.stat().st_size

    rows = sum(v for k, v in base.items() if k != "sources")
    obs = (f"{rows} observation rows, db {size/1e6:.1f} MB "
           f"({vacuumed/1e6:.1f} MB vacuumed), ingest {ingest_secs:.1f}s")
    record("H3 store size in tens of MB",
           "our own observations are tens of MB, not GB",
           obs, "SURVIVED" if vacuumed < 200e6 else "DIED",
           "partition by year or store resources as a JSON blob")
    for t, n in base.items():
        print(f"    {t:22} {n}")

    # --- H4: re-import identical, then overlapping as a second machine
    build_store(db, events, "this-machine", hashes)
    after_same = counts(db)
    idem = after_same == base
    record("H4a re-import is idempotent",
           "importing the same corpus twice changes no observation counts",
           f"identical={idem}",
           "SURVIVED" if idem else "DIED",
           "key includes source_id -- merge across machines then impossible")

    n = len(files)
    a = set(files[: int(n * 0.65)])
    b = set(files[int(n * 0.45):])
    ev_b = [e for e in events if e[0] in b]
    build_store(db, ev_b, "machine-b", hashes)
    after_b = counts(db)

    same_obs = all(after_b[t] == base[t] for t in base if t != "sources")
    more_src = after_b["sources"] > base["sources"]
    obs = (f"observation counts unchanged={same_obs}; "
           f"sources {base['sources']} -> {after_b['sources']} "
           f"(overlap of {len(a & b)} files imported twice under two machines)")
    record("H4b multi-machine merge dedups",
           "two machines sharing files yield 2x sources but 1x observations",
           obs, "SURVIVED" if (same_obs and more_src) else "DIED",
           "drop source_id from the observation key; track it in a join table")
    return db


# ---------------------------------------------------------------------------
# H5 -- is the delta query actually faster, and can it answer PER COMMODITY?
# ---------------------------------------------------------------------------


def h5_delta(db, files, site=3957057282, site2=4312376579):
    # from the store
    t0 = time.perf_counter()
    cur = db.cursor()
    row = cur.execute(
        """
        WITH totals AS (
          SELECT o.obs_hash, o.observed_at, SUM(r.provided) AS provided
          FROM depot_observation o JOIN depot_resource r USING (obs_hash)
          WHERE o.market_id = ? GROUP BY o.obs_hash, o.observed_at
        )
        SELECT MIN(provided), MAX(provided), COUNT(*) FROM totals
        """, (site,)).fetchone()
    mine = cur.execute(
        "SELECT COUNT(*) FROM contribution WHERE market_id=?", (site,)
    ).fetchone()[0]
    store_secs = time.perf_counter() - t0

    # per-commodity delta -- what the settlement tab actually needs
    t0 = time.perf_counter()
    per_commodity = cur.execute(
        """
        WITH ordered AS (
          SELECT r.symbol, r.provided, o.observed_at,
                 ROW_NUMBER() OVER (PARTITION BY r.symbol ORDER BY o.observed_at) AS rn,
                 COUNT(*)   OVER (PARTITION BY r.symbol) AS n
          FROM depot_observation o JOIN depot_resource r USING (obs_hash)
          WHERE o.market_id = ?
        )
        SELECT symbol,
               MAX(CASE WHEN rn = n THEN provided END)
             - MAX(CASE WHEN rn = 1 THEN provided END) AS delivered
        FROM ordered GROUP BY symbol
        HAVING delivered > 0 ORDER BY delivered DESC LIMIT 5
        """, (site2,)).fetchall()
    per_secs = time.perf_counter() - t0

    # the same answer the old way: re-parse every journal file
    t0 = time.perf_counter()
    lo = hi = None
    seen = 0
    for p in files:
        with p.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if DEPOT not in line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if ev.get("event") != DEPOT or ev.get("MarketID") != site:
                    continue
                tot = sum(r.get("ProvidedAmount", 0)
                          for r in ev.get("ResourcesRequired", []))
                lo = tot if lo is None else min(lo, tot)
                hi = tot if hi is None else max(hi, tot)
                seen += 1
    scan_secs = time.perf_counter() - t0

    agrees = (row[0] == lo and row[1] == hi and row[2] == seen)
    speedup = scan_secs / store_secs if store_secs else float("inf")
    obs = (f"store {store_secs*1000:.1f}ms vs full scan {scan_secs:.2f}s "
           f"({speedup:.0f}x); both report {lo} -> {hi} t over {seen} events, "
           f"own contributions={mine}; agrees={agrees}")
    record("H5 delta query is faster from the store",
           "the store turns a multi-second scan into a sub-100ms query, same answer",
           obs, "SURVIVED" if (agrees and speedup > 10) else "DIED",
           "the index half is unjustified; keep only the archive half")

    print(f"\n    per-commodity delta for site {site2} "
          f"({per_secs*1000:.1f}ms) -- what a settlement tab needs:")
    for symbol, delivered in per_commodity:
        print(f"      {symbol:28} +{delivered} t")


# ---------------------------------------------------------------------------


def asides(events):
    depot = [e for e in events if e[3].get("event") == DEPOT]
    total = loc = 0
    for _, _, _, ev, _ in depot:
        for r in ev.get("ResourcesRequired", []):
            total += 1
            if r.get("Name_Localised"):
                loc += 1
    print(f"\n    aside: depot resource rows with Name_Localised: "
          f"{loc}/{total}" + ("  (catalog.py resolution MANDATORY)"
                              if loc < total else "  (always present)"))

    bgs = [e for e in events if e[3].get("event") in BGS_EVENTS
           and e[3].get("Factions")]
    with_addr = sum(1 for _, _, _, ev, _ in bgs if ev.get("SystemAddress"))
    print(f"    aside: Factions[] events carrying SystemAddress: "
          f"{with_addr}/{len(bgs)}")


def main(journal_dir):
    files = sorted(journal_dir.glob("Journal.*.log"))
    print(f"corpus: {len(files)} files in {journal_dir}")

    hashes, _cheap = h1_liveness(files)

    t0 = time.perf_counter()
    events = load_events(files)
    print(f"\nloaded {len(events)} events of interest in "
          f"{time.perf_counter()-t0:.1f}s")

    buckets = h2_natural_key(events)
    if buckets is None:
        return 1

    asides(events)
    db = h3_h4(files, events, hashes)
    h5_delta(db, files)

    print("\n" + "=" * 72)
    print("VERDICTS")
    print("=" * 72)
    for arm, _pred, _obs, verdict, _fb in results:
        print(f"  {verdict:14} {arm}")
    print(f"\nartifact kept: {DB_PATH}")
    return 0


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DIR
    sys.exit(main(target))
