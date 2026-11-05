"""Turnout of eligible voters, 2026 vs the 2022 midterm.

Source: UF Election Lab (Michael McDonald), the standard US turnout figures.
"Turnout" here means ballots counted divided by the voting-eligible
population (adults who are citizens and not barred by a felony conviction),
which is comparable between states and between years. Registered-voter
turnout is not, because states keep their rolls differently.

Files in data/turnout_raw/, one per election, written by the scheduled update
from scripts/extract_turnout.js:

    # Source: <page URL>
    # Snapshot: <the page's own date note>; read <time> UTC
    US|49.42|124330000|251588219      <- state|turnout %|ballots counted|eligible voters

The 2026 figures are estimates until states certify (late November to
December): they start from AP's election-night turnout estimates and are
revised as counting finishes.

    python scripts/turnout.py --from-page data/turnout_raw/2026_page.txt 2026
converts text copied from the page's table ("Alabama 44.22% 1,751,000 3,959,631 ...")
into that format.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "turnout_raw"
STATES = {
    "United States": "US", "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR",
    "California": "CA", "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE",
    "District of Columbia": "DC", "Florida": "FL", "Georgia": "GA", "Hawaii": "HI", "Idaho": "ID",
    "Illinois": "IL", "Indiana": "IN", "Iowa": "IA", "Kansas": "KS", "Kentucky": "KY",
    "Louisiana": "LA", "Maine": "ME", "Maryland": "MD", "Massachusetts": "MA", "Michigan": "MI",
    "Minnesota": "MN", "Mississippi": "MS", "Missouri": "MO", "Montana": "MT", "Nebraska": "NE",
    "Nevada": "NV", "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM",
    "New York": "NY", "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH",
    "Oklahoma": "OK", "Oregon": "OR", "Pennsylvania": "PA", "Rhode Island": "RI",
    "South Carolina": "SC", "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX", "Utah": "UT",
    "Vermont": "VT", "Virginia": "VA", "Washington": "WA", "West Virginia": "WV",
    "Wisconsin": "WI", "Wyoming": "WY",
}
CODES = set(STATES.values())


def from_page(text: str) -> list[str]:
    """'New York 47.41% 6,845,000 14,437,679 ...' -> 'NY|47.41|6845000|14437679'."""
    out = []
    for line in text.splitlines():
        m = re.match(r"(\D+?) ([\d.]+)% ([\d,]+) ([\d,]+)", line.strip())
        if m and m[1] in STATES:
            out.append("|".join([STATES[m[1]], m[2], m[3].replace(",", ""), m[4].replace(",", "")]))
    return out


def read(path: Path) -> tuple[dict, list[str]]:
    """({state: [turnout %, ballots, eligible]}, header notes). Raises on a bad row."""
    rows, notes = {}, []
    for line in path.read_text().splitlines():
        if line.startswith("# "):
            notes.append(line[2:])
            continue
        if not line.strip() or line.startswith("#"):
            continue
        st, rate, ballots, vep = line.split("|")
        rate, ballots, vep = float(rate), int(ballots), int(vep)
        if st not in CODES:
            raise ValueError(f"{path.name}: unknown state {st}")
        # The rate must agree with its own two numbers; a shifted column would not.
        if abs(100 * ballots / vep - rate) > 0.05:
            raise ValueError(f"{path.name}: {st} rate {rate} != {ballots}/{vep}")
        rows[st] = [rate, ballots, vep]
    if set(rows) != CODES:
        raise ValueError(f"{path.name}: missing {sorted(CODES - set(rows))}")
    return rows, notes


def build(raw_dir: Path = RAW) -> dict:
    """{"2022": {...}, "2026": {...} or absent, "notes": {...}} for results.json."""
    out, notes = {}, {}
    for year in ("2022", "2026"):
        p = raw_dir / f"{year}.txt"
        if p.exists():
            out[year], notes[year] = read(p)
    if out:
        out["notes"] = notes
    return out


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--from-page":
        lines = from_page(Path(sys.argv[2]).read_text())
        print("\n".join(lines))
        print(f"# {len(lines)} rows", file=sys.stderr)
    else:
        t = build()
        for y in ("2022", "2026"):
            if y in t:
                print(y, "US turnout", t[y]["US"][0], "%")
