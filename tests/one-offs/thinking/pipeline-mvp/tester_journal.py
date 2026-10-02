"""One-off: write an offline journal dir for the pipeline-mvp checklist run. usage: tester_journal.py <outdir>"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from test_service import make_journal, docked_event, ryman_market_json
out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
make_journal(out, [docked_event()], ryman_market_json())
print(out)
