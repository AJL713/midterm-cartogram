"""Build the cartogram layouts.

Writes two files:
  data/hex.json    one hexagon per House district (435), grouped by state
  data/tiles.json  one hexagon per state, for the Senate and governor views

Why generate instead of download?
  A cartogram gives every seat the same area. Published district hexmaps are
  drawn for one set of district lines, and several states redrew their maps
  for 2026. Generating the layout from seat counts keeps it correct for any
  map, and needs no download.

How the House layout works: see scripts/hexlayout.py. In short, the real map is
squeezed east-west where seats are sparse (WARP_X), a hexagon grid is laid over
the squeezed outline, every state grows from its label point at once, and the
cells are re-dealt so states are compact and in one piece. The functions below
(grow_all, assign_optimally, join_pieces, ...) are the earlier unsqueezed method,
kept for comparison.
  4. Inside each state, district 1 gets the north-west-most hexagon and the
     numbers run left-to-right, top-to-bottom, so the layout reads like a page.

Run:  python scripts/build_hex.py
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

# House seats per state, from the 2020 census apportionment (valid 2022-2030).
SEATS = {
    "AL": 7, "AK": 1, "AZ": 9, "AR": 4, "CA": 52, "CO": 8, "CT": 5, "DE": 1,
    "FL": 28, "GA": 14, "HI": 2, "ID": 2, "IL": 17, "IN": 9, "IA": 4, "KS": 4,
    "KY": 6, "LA": 6, "ME": 2, "MD": 8, "MA": 9, "MI": 13, "MN": 8, "MS": 4,
    "MO": 8, "MT": 2, "NE": 3, "NV": 4, "NH": 2, "NJ": 12, "NM": 3, "NY": 26,
    "NC": 14, "ND": 1, "OH": 15, "OK": 5, "OR": 6, "PA": 17, "RI": 2, "SC": 7,
    "SD": 1, "TN": 9, "TX": 38, "UT": 4, "VT": 1, "VA": 11, "WA": 10, "WV": 2,
    "WI": 8, "WY": 1,
}

# Rough geographic centre of each state (longitude, latitude). Alaska and
# Hawaii are moved to the lower-left, the way most US maps inset them.
ANCHORS = {
    "AL": (-86.8, 32.8), "AK": (-122.5, 27.0), "AZ": (-111.7, 34.3),
    "AR": (-92.4, 34.9), "CA": (-119.6, 37.2), "CO": (-105.5, 39.0),
    "CT": (-72.7, 41.6), "DE": (-75.5, 39.0), "FL": (-81.7, 28.6),
    "GA": (-83.4, 32.7), "HI": (-112.0, 25.5), "ID": (-114.6, 44.4),
    "IL": (-89.2, 40.0), "IN": (-86.3, 39.9), "IA": (-93.5, 42.1),
    "KS": (-98.4, 38.5), "KY": (-85.3, 37.5), "LA": (-92.0, 31.0),
    "ME": (-69.2, 45.4), "MD": (-76.8, 39.0), "MA": (-71.8, 42.3),
    "MI": (-84.7, 43.6), "MN": (-94.3, 46.3), "MS": (-89.7, 32.7),
    "MO": (-92.5, 38.4), "MT": (-109.6, 47.0), "NE": (-99.8, 41.5),
    "NV": (-116.6, 39.3), "NH": (-71.6, 43.7), "NJ": (-74.7, 40.2),
    "NM": (-106.1, 34.4), "NY": (-75.5, 42.9), "NC": (-79.4, 35.6),
    "ND": (-100.5, 47.4), "OH": (-82.8, 40.3), "OK": (-97.5, 35.6),
    "OR": (-120.5, 43.9), "PA": (-77.8, 40.9), "RI": (-71.5, 41.7),
    "SC": (-80.9, 33.9), "SD": (-100.2, 44.4), "TN": (-86.3, 35.9),
    "TX": (-99.3, 31.5), "UT": (-111.7, 39.3), "VT": (-72.7, 44.0),
    "VA": (-78.8, 37.5), "WA": (-120.4, 47.4), "WV": (-80.6, 38.6),
    "WI": (-89.8, 44.6), "WY": (-107.6, 43.0),
}

# State tile grid (row, column) for the Senate and governor views: the common
# "tile grid map" arrangement used by many newsrooms.
TILE_GRID = {
    "AK": (0, 0), "ME": (0, 10),
    "VT": (1, 9), "NH": (1, 10),
    "WA": (2, 0), "ID": (2, 1), "MT": (2, 2), "ND": (2, 3), "MN": (2, 4),
    "IL": (2, 5), "WI": (2, 6), "MI": (2, 7), "NY": (2, 8), "RI": (2, 9),
    "MA": (2, 10),
    "OR": (3, 0), "NV": (3, 1), "WY": (3, 2), "SD": (3, 3), "IA": (3, 4),
    "IN": (3, 5), "OH": (3, 6), "PA": (3, 7), "NJ": (3, 8), "CT": (3, 9),
    "CA": (4, 0), "UT": (4, 1), "CO": (4, 2), "NE": (4, 3), "MO": (4, 4),
    "KY": (4, 5), "WV": (4, 6), "VA": (4, 7), "MD": (4, 8), "DE": (4, 9),
    "AZ": (5, 1), "NM": (5, 2), "KS": (5, 3), "AR": (5, 4), "TN": (5, 5),
    "NC": (5, 6), "SC": (5, 7),
    "OK": (6, 3), "LA": (6, 4), "MS": (6, 5), "AL": (6, 6), "GA": (6, 7),
    "HI": (7, 0), "TX": (7, 3), "FL": (7, 8),
}

SQRT3 = math.sqrt(3)
# Axial-coordinate neighbours of a pointy-top hexagon.
NEIGHBOURS = [(1, 0), (1, -1), (0, -1), (-1, 0), (-1, 1), (0, 1)]
# Grid units per degree. Tuned so the 48 contiguous states hold 435 hexes with
# a little breathing room; change it and re-run if the layout looks crowded.
SCALE = 0.7
# 0 = true geography, 1 = spread by seat share (see anchor_xy).
EQUALIZE = 0.5
# Rounds of shape tidying in build_house.
ROUNDS = 4


def hex_to_xy(q: int, r: int) -> tuple[float, float]:
    """Centre of hexagon (q, r) in flat x/y, for hexagons of radius 1."""
    return SQRT3 * (q + r / 2), 1.5 * r


def _seat_cdf(value: float, axis: int) -> float:
    """Share of all seats in states whose anchor lies west of (or north of) value."""
    below = sum(SEATS[s] for s, a in ANCHORS.items() if s not in ("AK", "HI") and a[axis] < value)
    at = sum(SEATS[s] for s, a in ANCHORS.items() if s not in ("AK", "HI") and a[axis] == value)
    return (below + at / 2) / sum(SEATS[s] for s in SEATS if s not in ("AK", "HI"))


def anchor_xy(state: str) -> tuple[float, float]:
    """Project a state's (lon, lat) anchor to flat x/y on the hex grid.

    Plain geography leaves the sparse West full of gaps, because a cartogram
    gives Montana's 2 seats far less room than its land area. So each axis is a
    blend of true position and "seat position" (what share of all seats lies to
    the west / north). EQUALIZE = 0 is pure geography, 1 is pure seat share.
    """
    lon, lat = ANCHORS[state]
    width, height = 58 * math.cos(math.radians(38)), 25  # degrees, mainland
    fx = (lon + 125) / 58
    fy = (50 - lat) / 25
    if state not in ("AK", "HI"):  # the insets keep their hand-picked spots
        fx = (1 - EQUALIZE) * fx + EQUALIZE * _seat_cdf(lon, 0)
        fy = (1 - EQUALIZE) * fy + EQUALIZE * (1 - _seat_cdf(lat, 1))
    return fx * width * SCALE * SQRT3, fy * height * SCALE * 1.5


def nearest_free(occupied: set, ax: float, ay: float, allowed: set | None = None) -> tuple[int, int]:
    """Free hexagon whose centre is closest to (ax, ay); inside `allowed` if given."""
    r0 = round(ay / 1.5)
    q0 = round(ax / SQRT3 - r0 / 2)
    best, best_d = None, math.inf
    for dr in range(-12, 13):
        for dq in range(-12, 13):
            cell = (q0 + dq, r0 + dr)
            if cell in occupied or (allowed is not None and cell not in allowed):
                continue
            x, y = hex_to_xy(*cell)
            d = (x - ax) ** 2 + (y - ay) ** 2
            if d < best_d:
                best, best_d = cell, d
    if best is None and allowed is not None:  # boxed in: the nearest free cell anywhere inside
        free = [c for c in allowed if c not in occupied]
        best = min(free, key=lambda c: (hex_to_xy(*c)[0] - ax) ** 2 + (hex_to_xy(*c)[1] - ay) ** 2)
    return best


def grow_state(state: str, n: int, occupied: set) -> list[tuple[int, int]]:
    """Claim n contiguous hexagons for one state, as close to its anchor as possible."""
    ax, ay = anchor_xy(state)
    cells = [nearest_free(occupied, ax, ay)]
    occupied.add(cells[0])
    while len(cells) < n:
        frontier = {
            (q + dq, r + dr)
            for q, r in cells
            for dq, dr in NEIGHBOURS
            if (q + dq, r + dr) not in occupied
        }
        if not frontier:  # boxed in: jump to the nearest free cell instead
            cell = nearest_free(occupied, ax, ay)
        else:
            cell = min(
                frontier,
                key=lambda c: (hex_to_xy(*c)[0] - ax) ** 2 + (hex_to_xy(*c)[1] - ay) ** 2,
            )
        cells.append(cell)
        occupied.add(cell)
    return cells


def district_id(state: str, number: int) -> str:
    """'WA-01'. Single-seat (at-large) states use 00, as most election data does."""
    return f"{state}-{'00' if SEATS[state] == 1 else f'{number:02d}'}"


def grow_all(occupied: set, anchors: dict | None = None, allowed: set | None = None,
             seats: dict | None = None) -> dict[str, list[tuple[int, int]]]:
    """Grow every state at once, one hexagon per turn.

    Each turn, the state that is least complete (smallest share of its seats
    placed) claims its best free neighbouring hexagon. Growing together, like
    crystals, stops a big early state from taking a small neighbour's space.
    """
    SEATS = seats or globals()["SEATS"]  # noqa: N806 (the states to grow; all by default)
    anchors = anchors or {s: anchor_xy(s) for s in SEATS}
    cells: dict[str, list] = {}
    # Seeds: small states first, so each gets the spot nearest its anchor.
    for s in sorted(SEATS, key=lambda s: SEATS[s]):
        cells[s] = [nearest_free(occupied, *anchors[s], allowed)]
        occupied.add(cells[s][0])

    def dist(c, s):
        x, y = hex_to_xy(*c)
        ax, ay = anchors[s]
        return (x - ax) ** 2 + (y - ay) ** 2

    while True:
        todo = [s for s in SEATS if len(cells[s]) < SEATS[s]]
        if not todo:
            return cells
        s = min(todo, key=lambda s: (len(cells[s]) / SEATS[s], s))
        frontier = {
            (q + dq, r + dr)
            for q, r in cells[s]
            for dq, dr in NEIGHBOURS
            if (q + dq, r + dr) not in occupied and (allowed is None or (q + dq, r + dr) in allowed)
        }
        cell = min(frontier, key=lambda c: dist(c, s)) if frontier \
            else nearest_free(occupied, *anchors[s], allowed)
        cells[s].append(cell)
        occupied.add(cell)


def assign_optimally(pool: list[tuple[int, int]], anchors: dict, seats: dict | None = None) -> dict[str, list]:
    """Give each state exactly SEATS[state] hexagons from the pool so that the
    total squared distance from every hexagon to its state's anchor is as small
    as possible (an "optimal transport" assignment, solved exactly by SciPy).

    Squared-distance assignments carve the pool into compact, convex-ish
    regions, which is what keeps states in one piece.
    """
    from scipy.optimize import linear_sum_assignment
    import numpy as np

    seats = seats or SEATS
    slots = [s for s in sorted(seats) for _ in range(seats[s])]  # one slot per seat
    pts = np.array([hex_to_xy(*c) for c in pool])
    anc = np.array([anchors[s] for s in slots])
    cost = ((pts[:, None, :] - anc[None, :, :]) ** 2).sum(axis=2)
    rows, cols = linear_sum_assignment(cost)
    out: dict[str, list] = {s: [] for s in seats}
    for r, c in zip(rows, cols):
        out[slots[c]].append(pool[r])
    return out


def compact(regions: dict[str, list]) -> dict[str, list]:
    """Gravity compaction: repeatedly slide each whole state one hexagon toward
    the map's centre of mass, as long as every hexagon it moves into is empty.
    Shapes never change; only the gaps between states close up. Alaska and
    Hawaii stay put as insets.
    """
    movable = [s for s in regions if s not in ("AK", "HI")]
    pts = [hex_to_xy(*c) for s in movable for c in regions[s]]
    cx = sum(p[0] for p in pts) / len(pts)
    # Slide sideways only: up/down moves let small states slip past each other
    # and end up north of a state that is really north of them.
    sideways = [(1, 0), (-1, 0)]

    def centre(cells):
        xs = [hex_to_xy(*c) for c in cells]
        return sum(p[0] for p in xs) / len(xs), sum(p[1] for p in xs) / len(xs)

    moved = True
    while moved:
        moved = False
        occupied = {c for cells in regions.values() for c in cells}
        # States nearest the centre settle first; outer states then slide in.
        for s in sorted(movable, key=lambda s: abs(centre(regions[s])[0] - cx)):
            own = set(regions[s])
            here = abs(centre(regions[s])[0] - cx)
            best = None
            for dq, dr in sideways:
                shifted = [(q + dq, r + dr) for q, r in regions[s]]
                if any(c in occupied and c not in own for c in shifted):
                    continue
                d = abs(centre(shifted)[0] - cx)
                if d < here - 0.5 and (best is None or d < best[0]):
                    best = (d, shifted)
            if best:
                occupied -= own
                regions[s] = best[1]
                occupied |= set(best[1])
                moved = True
    return regions


# Mainland hexagons to fit inside the outline, as a multiple of the 432 mainland
# seats. A little slack keeps every state reachable; too much leaves empty slots.
OUTLINE_SLACK = 1.06


def country_outline():
    """(country shape, mainland shape, label points) from data/geo.json, in map pixels."""
    from shapely.geometry import Polygon
    from shapely.ops import unary_union

    geo = json.loads((DATA / "geo.json").read_text())
    shapes, labels = {}, {}
    for st in geo["states"]:
        polys = []
        for sub in re.findall(r"M([^M]+)", st["path"]):
            pts = [tuple(map(float, p.split(","))) for p in re.findall(r"[-\d.]+,[-\d.]+", sub)]
            if len(pts) >= 3:
                polys.append(Polygon(pts).buffer(0))
        shapes[st["state"]] = unary_union(polys)
        labels[st["state"]] = (float(st["x"]), float(st["y"]))
    country = unary_union(list(shapes.values()))
    mainland = unary_union([g for st, g in shapes.items() if st not in ("AK", "HI")])
    return country, mainland, labels


def outline_cells(country, mainland, k: float):
    """Hexagons whose centre lies inside the country, at k map pixels per hex unit."""
    from shapely.geometry import Point

    minx, miny, maxx, maxy = country.bounds
    inside, on_mainland = set(), 0
    for r in range(int(miny / k / 1.5) - 2, int(maxy / k / 1.5) + 3):
        for q in range(int(minx / k / SQRT3) - r // 2 - 3, int(maxx / k / SQRT3) - r // 2 + 4):
            x, y = hex_to_xy(q, r)
            pt = Point(x * k, y * k)
            if country.contains(pt):
                inside.add((q, r))
                on_mainland += mainland.contains(pt)
    return inside, on_mainland


def pieces(cells: list) -> list[set]:
    """Connected groups of hexagons (a state in one piece has exactly one)."""
    left, out = set(cells), []
    while left:
        todo, seen = [left.pop()], set()
        while todo:
            c = todo.pop()
            seen.add(c)
            for dq, dr in NEIGHBOURS:
                n = (c[0] + dq, c[1] + dr)
                if n in left:
                    left.remove(n)
                    todo.append(n)
        out.append(seen)
    return sorted(out, key=len, reverse=True)


def join_pieces(regions: dict[str, list]) -> dict[str, list]:
    """The optimal deal can leave a state in two pieces (two hexagons of Idaho
    on either side of a neighbour). Swap a stray hexagon for one that touches
    the state's main piece, as long as the other state stays in one piece."""
    owner = {c: s for s, cells in regions.items() for c in cells}
    for _ in range(500):
        split = [(s, pieces(regions[s])) for s in regions]
        split = [(s, ps) for s, ps in split if len(ps) > 1]
        if not split:
            return regions
        s, ps = split[0]
        main, stray = ps[0], ps[-1]
        done = False
        for c in sorted(stray):
            for m in main:
                for dq, dr in NEIGHBOURS:
                    d = (m[0] + dq, m[1] + dr)
                    t = owner.get(d)
                    if t is None or t == s:
                        continue
                    new_t = [x for x in regions[t] if x != d] + [c]
                    if len(pieces(new_t)) > len(pieces(regions[t])):
                        continue
                    regions[t] = new_t
                    regions[s] = [x for x in regions[s] if x != c] + [d]
                    owner[d], owner[c] = s, t
                    done = True
                    break
                if done:
                    break
            if done:
                break
        if not done:
            raise RuntimeError(f"could not join {s} into one piece")
    raise RuntimeError("too many swaps while joining pieces")


# How much to squeeze the map east-west where seats are sparse before laying out
# hexagons (see hexlayout.warp_map): 0 = the real map, 1 = every seat the same width.
WARP_X = 0.85


def build_house() -> list[dict]:
    """The House cartogram: see scripts/hexlayout.py for the method."""
    import hexlayout as hl

    field = hl.Field(hl.Hex(), OUTLINE_SLACK, hl.warp_map(WARP_X))
    return hl.to_records(hl.Hex(), hl.deal_outline(field, ROUNDS))


def build_tiles() -> list[dict]:
    out = []
    for state, (row, col) in TILE_GRID.items():
        # Odd rows shift half a hexagon right so the tiles interlock.
        x = SQRT3 * (col + (0.5 if row % 2 else 0))
        y = 1.5 * row
        out.append({"id": state, "state": state, "x": round(x, 3), "y": round(y, 3)})
    return out


def main() -> None:
    assert sum(SEATS.values()) == 435, "seat counts must add up to 435"
    house = build_house()
    tiles = build_tiles()
    DATA.mkdir(exist_ok=True)
    (DATA / "hex.json").write_text(json.dumps(house, indent=1))
    (DATA / "tiles.json").write_text(json.dumps(tiles, indent=1))
    print(f"wrote {len(house)} district hexes and {len(tiles)} state tiles to {DATA}")


if __name__ == "__main__":
    main()
