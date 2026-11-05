"""Turn Wikipedia's 2026 results tables into data/results.json.

Two steps, so each can be checked on its own:

  1. SNAPSHOT  (--live)  Download the three Wikipedia result pages and save one
     plain-text line per race in data/raw/*.txt. Needs internet.
  2. BUILD     (default) Read the data/raw/*.txt snapshots, apply any hand
     corrections from data/overrides.json, and write data/results.json.

Run:
  python scripts/scrape.py            # build from the saved snapshots
  python scripts/scrape.py --live     # refresh snapshots from Wikipedia, then build

Ground rules (from the plan):
  * A race is only "called" when the source marks a winner. We never pick a
    winner from vote counts.
  * Corrections go in overrides.json, never into this file.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RAW = DATA / "raw"

PAGES = {
    "house": "https://en.wikipedia.org/wiki/2026_United_States_House_of_Representatives_elections",
    "senate": "https://en.wikipedia.org/wiki/2026_United_States_Senate_elections",
    "governors": "https://en.wikipedia.org/wiki/2026_United_States_gubernatorial_elections",
}

STATES = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR", "California": "CA",
    "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE", "Florida": "FL", "Georgia": "GA",
    "Hawaii": "HI", "Idaho": "ID", "Illinois": "IL", "Indiana": "IN", "Iowa": "IA",
    "Kansas": "KS", "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD",
    "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN", "Mississippi": "MS",
    "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV",
    "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY",
    "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK",
    "Oregon": "OR", "Pennsylvania": "PA", "Rhode Island": "RI", "South Carolina": "SC",
    "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX", "Utah": "UT", "Vermont": "VT",
    "Virginia": "VA", "Washington": "WA", "West Virginia": "WV", "Wisconsin": "WI",
    "Wyoming": "WY",
}
KEY_RE = re.compile(r"^(H-[A-Z]{2}-\d{2}|S-[A-Z]{2}(-SP)?|G-[A-Z]{2})$")
STATUSES = {"called", "uncalled", "runoff", "rcv-pending"}


def party_code(text: str) -> str:
    """'Democratic' -> 'D'. Minnesota's DFL and North Dakota's Dem-NPL count as D."""
    if re.search(r"Democratic|DFL|Farmer", text):
        return "D"
    if "Republican" in text:
        return "R"
    if "Independent" in text:
        return "I"
    if "Libertarian" in text:
        return "L"
    return "O"


# ---------------------------------------------------------------- step 1: snapshot

def parse_candidates(cell) -> list[dict]:
    """Each <li> in the Candidates cell is one candidate; the winner is in bold."""
    out = []
    for li in cell.find_all("li"):
        text = re.sub(r"\[\w+\]", "", li.get_text(" ", strip=True)).lstrip("▌✓ ").strip()
        # Name = text before the first " (", party = what the parentheses say
        # (handles nested labels like "U.S. Taxpayers (Michigan)").
        name, sep, rest = text.partition(" (")
        out.append({
            "name": name.strip(),
            "party": party_code(rest if sep else ""),
            "won": li.find("b") is not None,
        })
    return out


def parse_table_rows(table, key_for):
    """Yield one snapshot line per race row. key_for(first_cell_text) -> key or None."""
    for row in table.find_all("tr")[1:]:
        cells = row.find_all(["td", "th"])
        if len(cells) < 3:
            continue
        key = key_for(" ".join(cells[0].get_text(" ", strip=True).split()))
        if not key:
            continue  # header rows, or a second incumbent in a redrawn district
        status_text = cells[-2].get_text(" ", strip=True)
        cands = parse_candidates(cells[-1])
        winners = [c for c in cands if c["won"]]
        if len(winners) == 1:
            w, status = winners[0], "called"
        else:
            w, status = None, ("runoff" if "Runoff" in cells[-1].get_text() else "uncalled")
        others = ";".join(f"{c['name']}/{c['party']}" for c in cands if c is not w)
        if key.startswith("H-"):
            others = ""  # House tooltips show the winner only
        # Context: partisan lean (Cook PVI) and who held the seat before.
        texts = [" ".join(c.get_text(" ", strip=True).split()) for c in cells]
        pvi = next((t for t in texts if re.fullmatch(r"[DR]\+\d+|EVEN", t)), "")
        held = ""
        for t in texts[1:-2]:
            if re.search(r"new seat", t, re.I):
                held = "N"; break
            if re.match(r"Vacant", t, re.I):
                held = "V"; break
            if len(t) < 40 and re.match(r"(Democratic|Republican|Independent|Libertarian|DFL)\b", t):
                held = party_code(t); break
        yield "|".join([
            key, w["party"] if w else "-", "1" if (w and re.search(r"\bgain\b", status_text)) else "0",
            w["name"] if w else "", status, others, pvi, held,
        ])


def house_key(text: str):
    m = re.match(r"^([A-Za-z ]+?) (\d+|at-large)$", text, re.I)
    if not m or m.group(1) not in STATES:
        return None
    num = "00" if m.group(2).lower() == "at-large" else m.group(2).zfill(2)
    return f"H-{STATES[m.group(1)]}-{num}"


def state_key(prefix: str):
    def key(text: str):
        name = re.sub(r"\[\w+\]|\s*\(.*$", "", text).strip()
        return f"{prefix}-{STATES[name]}" if name in STATES else None
    return key


def snapshot_from_html(office: str, html: str) -> list[str]:
    """Pull every race out of one Wikipedia page's HTML."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    tables = soup.select("table.wikitable")
    # Race tables are the ones whose header row ends in a "Candidates" column.
    race_tables = [t for t in tables if "Candidates" in t.find("tr").get_text()]
    key_for = house_key if office == "house" else state_key("S" if office == "senate" else "G")
    lines = [line for t in race_tables for line in parse_table_rows(t, key_for)]
    # Keep the first line per key (later tables can repeat a race in a summary).
    seen, unique = set(), []
    for line in lines:
        k = line.split("|", 1)[0]
        if k not in seen:
            seen.add(k)
            unique.append(line)
    return unique


def snapshot_live() -> None:
    import requests

    RAW.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    for office, url in PAGES.items():
        resp = requests.get(url, timeout=30, headers={"User-Agent": "midterm-cartogram/1.0"})
        resp.raise_for_status()
        lines = snapshot_from_html(office, resp.text)
        header = f"# Source: {url}\n# Snapshot read {stamp}\n# Format: key|winner party|flip|winner|status|others|lean|held by before\n"
        (RAW / f"{office}.txt").write_text(header + "\n".join(lines) + "\n")
        print(f"{office}: {len(lines)} races saved")


# ---------------------------------------------------------------- step 2: build

def read_snapshot(path: Path) -> dict[str, dict]:
    races = {}
    for line in path.read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split("|") + [""] * 8
        key, party, flip, winner, status, others, pvi, held = parts[:8]
        office, state = key[0], key[2:4]
        others_list = []
        for item in filter(None, others.split(";")):
            name, _, p = item.rpartition("/")
            others_list.append({"n": name, "p": p})
        races[key] = {
            "office": office,
            "state": state,
            "district": int(key[5:7]) if office == "H" else None,
            "special": key in ("S-FL", "S-OH") or key.endswith("-SP"),
            "called": party != "-",
            "status": status or ("called" if party != "-" else "uncalled"),
            "winner": None if party == "-" else party,
            "winner_name": winner or None,
            "flip": flip == "1",
            "margin": None,  # Wikipedia's summary tables have no vote shares
            "others": others_list,
            "pvi": pvi or None,          # Cook partisan lean, e.g. "R+5"; none for governors
            "held_by": held or None,     # party before the election; N = new seat, V = vacant
        }
    return races


def snapshot_time(path: Path) -> str:
    for line in path.read_text().splitlines():
        m = re.search(r"(\d{4}-\d{2}-\d{2})[ T]~?(\d{2}:\d{2}) UTC", line)
        if m:
            return f"{m.group(1)}T{m.group(2)}:00Z"
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def apply_overrides(races: dict, path: Path) -> int:
    """overrides.json: {"H-WA-03": {"winner": "D", "winner_name": "...", "note": "..."}}"""
    if not path.exists():
        return 0
    fixes = json.loads(path.read_text())
    for key, patch in fixes.items():
        if key.startswith("_"):
            continue  # comments
        if key not in races:
            raise KeyError(f"override for unknown race {key}")
        races[key].update(patch)
        races[key]["called"] = races[key].get("winner") is not None
        races[key]["overridden"] = True
    return sum(1 for k in fixes if not k.startswith("_"))


def validate(races: dict) -> None:
    """Fail loudly instead of drawing a wrong map."""
    counts = {o: sum(1 for r in races.values() if r["office"] == o) for o in "HSG"}
    assert counts == {"H": 435, "S": 35, "G": 36}, f"race counts are off: {counts}"
    for key, r in races.items():
        assert KEY_RE.match(key), f"bad key {key}"
        assert r["status"] in STATUSES, f"{key}: unknown status {r['status']}"
        assert r["called"] == (r["winner"] is not None), f"{key}: called/winner mismatch"
        assert r["called"] or not r["flip"], f"{key}: an uncalled race can't be a flip"


def update_history(races: dict, updated: str) -> list[dict]:
    """Keep a running record of called seats, one entry per snapshot.

    The previous results.json carries the history so far; a new entry is added
    only when the called-seat counts changed, so the "calls over time" chart
    gets one point per real change. Counts are races won in 2026 (seats not up
    this year are added by the page).
    """
    old = []
    path = DATA / "results.json"
    if path.exists():
        old = json.loads(path.read_text()).get("history", [])
    counts = {}
    for office in "HSG":
        rs = [r for r in races.values() if r["office"] == office]
        counts[office] = [sum(r["winner"] == "D" for r in rs),
                          sum(r["winner"] == "R" for r in rs),
                          sum(not r["called"] for r in rs)]
    if old and {k: old[-1][k] for k in "HSG"} == counts:
        return old  # nothing new was called
    return old + [{"t": updated, **counts}]


def build() -> dict:
    races = {}
    for office in PAGES:
        races.update(read_snapshot(RAW / f"{office}.txt"))
    n_fix = apply_overrides(races, DATA / "overrides.json")
    validate(races)
    context = json.loads((DATA / "context.json").read_text())
    updated = snapshot_time(RAW / "house.txt")
    import counties  # county tables for Senate and governor races (scripts/counties.py)
    import turnout   # eligible-voter turnout (scripts/turnout.py)
    county_results, county_sources, county_report = counties.build_all()
    out = {
        "updated": updated,
        "source": {name: url for name, url in PAGES.items()},
        "context": context,
        "history": update_history(races, updated),
        "races": dict(sorted(races.items())),
        # {race: {county FIPS: [Democratic votes, Republican votes, total votes]}}
        "counties": county_results,
        "county_sources": county_sources,
        # {"2022": {state: [turnout %, ballots, eligible voters]}, "2026": ..., "notes": ...}
        "turnout": turnout.build(),
    }
    (DATA / "results.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
    called = sum(r["called"] for r in races.values())
    print(f"wrote {len(races)} races ({called} called, {n_fix} overrides) to data/results.json")
    for line in county_report:
        print("  county results", line)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--live", action="store_true", help="re-download Wikipedia before building")
    args = ap.parse_args()
    if args.live:
        snapshot_live()
    build()


if __name__ == "__main__":
    main()
