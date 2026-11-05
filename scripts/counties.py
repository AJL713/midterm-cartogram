"""County results for Senate and governor races.

Wikipedia race pages add a "By county" table once states report county
counts. scripts/extract_counties.js reads that table in a browser and the
scheduled update saves it as data/county_raw/<race>.txt (e.g. S-TX.txt):

    # Source: <page URL>
    # Snapshot: page last edited <time> UTC, read <time> UTC
    county name|Democratic votes|Republican votes|total votes

This module matches those county names to the map's county codes (FIPS) and
returns vote counts for scrape.py to store in results.json.

A state is used only if EVERY row matches exactly one county and every county
on the map is covered. Anything less (a renamed county, a half-filled table)
is reported and skipped, so the map never shows a partial or mismatched state.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "county_raw"
FIPS_STATE = {
    "01": "AL", "02": "AK", "04": "AZ", "05": "AR", "06": "CA", "08": "CO", "09": "CT",
    "10": "DE", "12": "FL", "13": "GA", "15": "HI", "16": "ID", "17": "IL", "18": "IN",
    "19": "IA", "20": "KS", "21": "KY", "22": "LA", "23": "ME", "24": "MD", "25": "MA",
    "26": "MI", "27": "MN", "28": "MS", "29": "MO", "30": "MT", "31": "NE", "32": "NV",
    "33": "NH", "34": "NJ", "35": "NM", "36": "NY", "37": "NC", "38": "ND", "39": "OH",
    "40": "OK", "41": "OR", "42": "PA", "44": "RI", "45": "SC", "46": "SD", "47": "TN",
    "48": "TX", "49": "UT", "50": "VT", "51": "VA", "53": "WA", "54": "WV", "55": "WI",
    "56": "WY",
}


def county_source() -> Path:
    """The us-atlas county file: data/source/ locally, or an npm install of us-atlas@3."""
    for p in (ROOT / "data" / "source" / "counties-albers-10m.json",
              ROOT / "node_modules" / "us-atlas" / "counties-albers-10m.json"):
        if p.exists():
            return p
    raise FileNotFoundError("counties-albers-10m.json not found: run `npm install us-atlas@3.0.1` in the project folder")


def norm(name: str) -> str:
    """'St. John the Baptist' -> 'stjohnthebaptist'; 'La Salle' == 'LaSalle'; 'Doña Ana' == 'Dona Ana'."""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\bsaint\b", "st", s)
    return re.sub(r"[^a-z]", "", s)


def map_counties() -> dict[str, dict[str, str]]:
    """{state: {fips: county name}} from the map file."""
    geoms = json.loads(county_source().read_text())["objects"]["counties"]["geometries"]
    out: dict[str, dict[str, str]] = {}
    for g in geoms:
        st = FIPS_STATE.get(g["id"][:2])
        if st:
            out.setdefault(st, {})[g["id"]] = g["properties"]["name"]
    return out


def is_city(fips: str) -> bool:
    """Independent cities (Virginia, Baltimore, St. Louis, Carson City) have codes x5xx and up."""
    return int(fips[2:]) >= 500


def match(state: str, rows: list[tuple], counties: dict[str, str]) -> tuple[dict, list[str]]:
    """Match table rows to county codes. Returns ({fips: [D, R, total]}, problems)."""
    by_name: dict[str, list[str]] = {}
    for fips, name in counties.items():
        by_name.setdefault(norm(name), []).append(fips)
    out, problems = {}, []
    for name, d, r, total in rows:
        n = norm(name)
        options = by_name.get(n, [])
        # "Fairfax County" / "Fairfax City" / "Richmond City": strip the word and
        # pick the county or the independent city it names. "Charles City" is
        # itself a county name, so it matched exactly above and never gets here.
        if len(options) != 1:
            for word, want_city in (("county", False), ("parish", False), ("borough", False), ("city", True)):
                if n.endswith(word) and n[: -len(word)] in by_name:
                    options = [f for f in by_name[n[: -len(word)]] if is_city(f) == want_city] or by_name[n[: -len(word)]]
                    break
        if len(options) == 2 and not n.endswith(("city", "county")):
            options = [f for f in options if not is_city(f)]  # a bare name means the county
        if len(options) != 1:
            problems.append(f"{name}: {'no match' if not options else 'ambiguous'}")
            continue
        if options[0] in out:
            problems.append(f"{name}: county {options[0]} appears twice")
            continue
        out[options[0]] = [d, r, total]
    missing = sorted(set(counties) - set(out))
    if missing:
        problems.append(f"{len(missing)} map counties have no row: " + ", ".join(counties[f] for f in missing[:5]))
    return out, problems


def read_raw(path: Path) -> list[tuple]:
    rows = []
    for line in path.read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        name, d, r, total = line.split("|")
        rows.append((name, int(d), int(r), int(total)))
    return rows


def build_all(raw_dir: Path = RAW) -> tuple[dict, dict, list[str]]:
    """Every saved county table that matches completely.

    Returns (results {race: {fips: [D, R, total]}}, sources {race: header lines}, report lines).
    """
    if not raw_dir.exists():
        return {}, {}, []
    counties = map_counties()
    results, sources, report = {}, {}, []
    for path in sorted(raw_dir.glob("*.txt")):
        race = path.stem          # "S-TX", "G-PA", "S-OH-SP" ...
        st = race.split("-")[1]
        if st not in counties:
            report.append(f"{race}: unknown state")
            continue
        got, problems = match(st, read_raw(path), counties[st])
        if problems:
            report.append(f"{race}: skipped ({'; '.join(problems[:3])})")
            continue
        # The map shades Democratic minus Republican. If a third candidate (e.g. an
        # independent) out-polled one of the two parties statewide, that picture
        # would mislead, so leave the race out.
        d, r, t = (sum(v[i] for v in got.values()) for i in range(3))
        if not d or not r:
            # e.g. a California or Washington top-two race between two Democrats
            report.append(f"{race}: skipped (not a Democrat-versus-Republican race)")
            continue
        if t - d - r > min(d, r):
            report.append(f"{race}: skipped (a third candidate finished in the top two)")
            continue
        results[race] = got
        sources[race] = [l[2:] for l in path.read_text().splitlines() if l.startswith("# ")]
        report.append(f"{race}: {len(got)} counties")
    return results, sources, report


if __name__ == "__main__":
    for line in build_all()[2]:
        print(line)
