"""Bring the public GitHub Pages copy up to date with the claude.ai page.

The scheduled updates publish new results to the claude.ai artifact but cannot
push to GitHub. A Claude chat session that can push runs this instead:

    python scripts/sync_from_artifact.py <saved artifact HTML>   # from the Artifact tool's "read"

It takes the results embedded in the live claude.ai page (window.CARTO.results),
writes them to data/results.json, and rebuilds docs/ with  bundle.py --pages.
It prints "UNCHANGED" when the page holds the same results as data/results.json
(nothing to commit), otherwise "CHANGED <updated time>" and the new seat counts.
The map files (hex, tiles, geo) in the page must match the repo's; if they don't,
the page was built from newer code, and the script stops so a person can look.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def embedded(html: str) -> dict:
    m = re.search(r"<script>window\.CARTO = (.*?);</script>", html, re.S)
    if not m:
        sys.exit("no window.CARTO data found in the page")
    return json.loads(m.group(1).replace("<\\/", "</"))


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    live = embedded(Path(sys.argv[1]).read_text())
    for name in ("hex", "tiles", "geo"):
        if live[name] != json.loads((ROOT / "data" / f"{name}.json").read_text()):
            sys.exit(f"STOP: data/{name}.json differs from the live page (code or map data changed); sync by hand")
    path = ROOT / "data" / "results.json"
    old = json.loads(path.read_text())
    new = live["results"]
    if new == old:
        print("UNCHANGED", old["updated"])
        return
    path.write_text(json.dumps(new, indent=1, ensure_ascii=False))
    subprocess.run([sys.executable, str(ROOT / "scripts" / "bundle.py"), "--pages"], check=True)
    h = new["history"][-1]
    print(f"CHANGED {new['updated']}  House {h['H']}  Senate {h['S']}  Governors {h['G']}  (D, R, uncalled)")


if __name__ == "__main__":
    main()
