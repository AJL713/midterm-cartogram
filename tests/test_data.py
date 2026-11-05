"""Checks that run in a second, with no internet:   python -m pytest

They guard the three things that would silently produce a wrong map:
  * the layout (every seat exactly once, every state in one piece)
  * the results file (right counts, sane fields)
  * the join between them (every hexagon has a race and vice versa)
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build_hex  # noqa: E402
import scrape  # noqa: E402

HEX = json.loads((ROOT / "data" / "hex.json").read_text())
TILES = json.loads((ROOT / "data" / "tiles.json").read_text())
RESULTS = json.loads((ROOT / "data" / "results.json").read_text())


# ---------------------------------------------------------------- layout

def test_one_hex_per_district():
    assert len(HEX) == 435
    assert len({h["id"] for h in HEX}) == 435
    assert len({(h["q"], h["r"]) for h in HEX}) == 435, "two districts share a hexagon"


def test_each_state_gets_its_seat_count():
    for state, n in build_hex.SEATS.items():
        assert sum(h["state"] == state for h in HEX) == n, state


def test_every_state_is_one_piece():
    cells = {}
    for h in HEX:
        cells.setdefault(h["state"], set()).add((h["q"], h["r"]))
    for state, cs in cells.items():
        start = next(iter(cs))
        seen, stack = set(), [start]
        while stack:
            c = stack.pop()
            if c in seen:
                continue
            seen.add(c)
            stack += [(c[0] + dq, c[1] + dr) for dq, dr in build_hex.NEIGHBOURS if (c[0] + dq, c[1] + dr) in cs]
        assert seen == cs, f"{state} is split into pieces"


def test_state_tiles():
    assert len(TILES) == 50 and len({t["state"] for t in TILES}) == 50


# ---------------------------------------------------------------- results

def test_result_counts_and_fields():
    races = RESULTS["races"]
    scrape.validate(races)  # same rules the build uses


def test_majority_numbers():
    ctx = RESULTS["context"]
    assert sum(ctx["senate"]["not_up"].values()) == 65   # 100 seats - 35 up
    assert len(ctx["governors"]["not_up"]) == 14         # 50 states - 36 races


def test_no_governor_race_in_a_not_up_state():
    up = {r["state"] for r in RESULTS["races"].values() if r["office"] == "G"}
    assert not up & set(RESULTS["context"]["governors"]["not_up"])


# ---------------------------------------------------------------- join

def test_every_hexagon_has_a_race_and_back():
    hex_ids = {f"H-{h['id']}" for h in HEX}
    house = {k for k in RESULTS["races"] if k.startswith("H-")}
    assert hex_ids - house == set(), "hexagons with no race"
    assert house - hex_ids == set(), "races with no hexagon"


def test_every_statewide_race_has_a_tile():
    tiles = {t["state"] for t in TILES}
    for r in RESULTS["races"].values():
        if r["office"] in "SG":
            assert r["state"] in tiles


# ---------------------------------------------------------------- parser

def test_parser_on_sample_html():
    html = (ROOT / "tests" / "fixtures" / "house_sample.html").read_text()
    lines = scrape.snapshot_from_html("house", html)
    rows = {line.split("|")[0]: line.split("|") for line in lines}
    assert set(rows) == {"H-WA-01", "H-WA-03", "H-OH-07", "H-WY-00"}  # redistricted row skipped
    assert rows["H-WA-01"][1:5] == ["D", "0", "Suzan DelBene", "called"]
    assert rows["H-WA-03"][1:5] == ["-", "0", "", "uncalled"]          # nobody in bold: not called
    assert rows["H-OH-07"][1:3] == ["D", "1"]                          # "gain" means a flip
    assert rows["H-WY-00"][3] == "Chuck Gray"


def test_nested_party_label():
    from bs4 import BeautifulSoup
    html = (ROOT / "tests" / "fixtures" / "house_sample.html").read_text()
    cell = BeautifulSoup(html, "html.parser").find_all("tr")[-1].find_all("td")[-1]
    names = {c["name"]: c["party"] for c in scrape.parse_candidates(cell)}
    assert names["Pat Doe"] == "O"


def test_party_codes():
    assert scrape.party_code("Democratic–Farmer–Labor") == "D"
    assert scrape.party_code("Republican") == "R"
    assert scrape.party_code("Green") == "O"


# ---------------------------------------------------------------- geography

GEO = json.loads((ROOT / "data" / "geo.json").read_text())


def test_fifty_state_outlines():
    assert sorted(s["state"] for s in GEO["states"]) == sorted(build_hex.SEATS)


def test_dots_add_up_to_the_population():
    people = len(GEO["dots"]) // 3 * GEO["meta"]["dot_people"]
    total = GEO["meta"]["population_total"]
    assert abs(people - total) / total < 0.01, "dots should represent the whole population within 1%"


def test_dots_sit_inside_the_map():
    xs, ys = GEO["dots"][0::3], GEO["dots"][1::3]
    assert 0 <= min(xs) and max(xs) <= 975 and 0 <= min(ys) and max(ys) <= 610


# ---------------------------------------------------------------- context fields

def test_lean_and_previous_holder():
    import re
    for key, r in RESULTS["races"].items():
        if r["office"] in "HS":
            assert r["pvi"] and re.fullmatch(r"[DR]\+\d+|EVEN", r["pvi"]), f"{key}: bad lean {r['pvi']}"
        assert r["held_by"] in {"D", "R", "I", "N", "V"}, f"{key}: unknown previous holder"
        if r["flip"]:
            assert r["held_by"] != r["winner"], f"{key}: a party gain must change the party"


def test_history_matches_current_counts():
    hist = RESULTS["history"]
    assert hist, "history should have at least one entry"
    last = hist[-1]
    for office in "HSG":
        rs = [r for r in RESULTS["races"].values() if r["office"] == office]
        assert last[office] == [sum(r["winner"] == "D" for r in rs), sum(r["winner"] == "R" for r in rs),
                                sum(not r["called"] for r in rs)], f"history out of date for {office}"


def test_county_lines_for_every_state():
    assert set(GEO["county_lines"]) == set(build_hex.SEATS)
    for st, d in GEO["county_lines"].items():
        assert d.startswith("M"), st


def test_district_shapes_match_house_seats():
    hex_ids = {h["id"] for h in HEX}
    paths = GEO["district_paths"]
    assert set(paths) <= hex_ids, "every district shape must be a real House seat"
    skipped = set(GEO["districts_not_current"])
    assert skipped == {"AL", "FL", "LA", "MO", "TN"}
    assert not any(k[:2] in skipped for k in paths), "states with outdated lines must have no districts"
    for st, n in build_hex.SEATS.items():
        if n > 1 and st not in skipped:
            got = sum(k.startswith(st + "-") for k in paths)
            assert got == n, f"{st}: {got} district shapes for {n} seats"


# ---------------------------------------------------------------- county results

import counties  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "counties"
SAMPLES = {"tx_senate_2024": "TX", "va_senate_2024": "VA", "la_senate_2022": "LA",
           "ga_senate_2022": "GA", "mi_senate_2024": "MI", "pa_governor_2022": "PA"}


def test_county_tables_match_every_county():
    """Real Wikipedia county tables (earlier elections) match the map county for county."""
    mc = counties.map_counties()
    for name, st in SAMPLES.items():
        got, problems = counties.match(st, counties.read_raw(FIX / f"{name}.txt"), mc[st])
        assert not problems, f"{name}: {problems}"
        assert set(got) == set(mc[st]), name


def test_virginia_cities_and_counties_stay_apart():
    mc = counties.map_counties()
    got, _ = counties.match("VA", counties.read_raw(FIX / "va_senate_2024.txt"), mc["VA"])
    assert got["51059"][2] == 582104   # Fairfax County
    assert got["51600"][2] == 13342    # Fairfax City
    assert got["51760"][0] == 89672    # Richmond City
    assert got["51159"][0] == 1562     # Richmond County
    assert got["51036"][2] == 4203     # Charles City County (a county despite its name)


def test_incomplete_or_third_party_tables_are_skipped(tmp_path):
    lines = (FIX / "mi_senate_2024.txt").read_text().splitlines()
    (tmp_path / "S-MI.txt").write_text("\n".join(lines[:-5]) + "\n")         # 5 counties missing
    rows = [l.split("|") for l in lines if not l.startswith("#")]
    (tmp_path / "G-MI.txt").write_text("\n".join(f"{n}|{d}|1|{int(t) + 10 * int(d)}" for n, d, r, t in rows) + "\n")  # R tiny, "other" huge
    (tmp_path / "S-PA.txt").write_text((FIX / "pa_governor_2022.txt").read_text())
    rows_ga = [l.split("|") for l in (FIX / "ga_senate_2022.txt").read_text().splitlines() if not l.startswith("#")]
    (tmp_path / "G-GA.txt").write_text("\n".join(f"{n}|{int(d) + int(r)}|0|{t}" for n, d, r, t in rows_ga) + "\n")  # two Democrats
    results, _, report = counties.build_all(tmp_path)
    assert set(results) == {"S-PA"}, report
    assert any("G-GA: skipped (not a Democrat-versus-Republican race)" in r for r in report)
    assert any("S-MI: skipped" in r and "no row" in r for r in report)
    assert any("G-MI: skipped (a third candidate" in r for r in report)


# ---------------------------------------------------------------- turnout

import turnout  # noqa: E402


def test_turnout_tables_are_complete_and_consistent():
    t = turnout.build()
    for year in ("2022", "2026"):
        assert set(t[year]) == turnout.CODES, year          # 50 states + DC + US
        for st, (rate, ballots, vep) in t[year].items():
            assert 20 < rate < 80, f"{year} {st}: implausible turnout {rate}"
            assert abs(100 * ballots / vep - rate) <= 0.05
    assert RESULTS["turnout"]["2022"]["US"][0] == 46.12     # the published 2022 national figure


def test_turnout_rejects_a_shifted_column(tmp_path):
    good = (turnout.RAW / "2022.txt").read_text().splitlines()
    bad = [l if not l.startswith("TX|") else "TX|41.75|19523011|8151590" for l in good]  # ballots and VEP swapped
    (tmp_path / "2022.txt").write_text("\n".join(bad))
    import pytest
    with pytest.raises(ValueError, match="TX"):
        turnout.build(tmp_path)


def test_turnout_from_page_text():
    assert turnout.from_page("New York 47.41% 6,845,000 14,437,679 16,148,400 10.40% 31,287") == ["NY|47.41|6845000|14437679"]


# ---------------------------------------------------------------- runoff dates

def test_runoff_dates_are_official_and_well_formed():
    import datetime
    import re
    from urllib.parse import urlparse
    runoffs = {k: v for k, v in RESULTS["context"].get("runoffs", {}).items() if not k.startswith("_")}
    for key, entry in runoffs.items():
        st, office = key.split("-")
        assert st in build_hex.SEATS and office in "HSG", key
        datetime.date.fromisoformat(entry["date"])                       # a real YYYY-MM-DD date
        host = urlparse(entry["source"]).hostname or ""
        assert re.search(r"(\.gov|\.us)$", host), f"{key}: runoff dates must come from an official election site"


# ---------------------------------------------------------------- link preview

def test_link_preview_tags_only_with_a_site_address():
    import bundle
    assert bundle.site_tags("") == ""                     # the claude.ai version gets no address tags
    tags = bundle.site_tags("https://example.github.io/midterm-cartogram")
    assert 'content="https://example.github.io/midterm-cartogram/preview.png"' in tags
    assert '<link rel="canonical" href="https://example.github.io/midterm-cartogram/">' in tags
    page = (ROOT / "web" / "index.html").read_text()
    assert 'property="og:title"' in page and "<!--SITE_TAGS-->" in page


def test_feedback_link_is_the_form_and_opens_safely():
    """The page links to the feedback form (twice) and to no other Google service.
    The link opens in a new tab with rel="noopener", so the form can't control the page."""
    import re
    page = (ROOT / "web" / "index.html").read_text()
    links = re.findall(r'<a href="(https://docs\.google\.com[^"]*)"([^>]*)>', page)
    assert len(links) == 2
    for url, attrs in links:
        assert url == "https://docs.google.com/forms/d/e/1FAIpQLSe3xU336rEL3261p4J6LMn-C82QrbYm8YPACOikHYaEpKunyg/viewform"
        assert 'target="_blank"' in attrs and 'rel="noopener"' in attrs
