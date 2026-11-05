# Seats, not acres — 2026 midterm cartogram

A one-page map of the November 3, 2026 US midterm results where every House
district, Senate race and governorship is the same size. A normal map makes
Montana's 2 House seats look bigger than New York City's 13; a cartogram fixes
that by giving each seat one hexagon.

## Quick start

```bash
pip install -r requirements.txt     # once
python scripts/build_hex.py         # make the hexagon layouts   -> data/hex.json, data/tiles.json
node scripts/project_districts.mjs data/source/districts_2026.geojson data/source/districts_albers.json   # only when the district file changes
python scripts/build_geo.py         # state shapes, county and district lines, population dots -> data/geo.json
python scripts/scrape.py            # build results from snapshots -> data/results.json
python scripts/bundle.py            # make the single-file page   -> dist/index.html
python -m pytest                    # check everything (27 tests, ~1 second)
```

Then double-click `dist/index.html`.

**Refreshing the results** (needs internet; run this on your own computer):

```bash
python scripts/scrape.py --live && python scripts/bundle.py
```

That re-reads the three Wikipedia results pages, saves fresh snapshots in
`data/raw/`, rebuilds `results.json`, and repacks the page. Compare the new
snapshot with the old one (`git diff data/raw`) before publishing.

**Editing the page:** the readable source is in `web/`. To see edits without
re-bundling, run `python -m http.server` from the project folder and open
http://localhost:8000/web/ (a server is needed because browsers block
`fetch()` of local files).

## Public site

The public copy is served by GitHub Pages from the `docs/` folder:
**https://ajl713.github.io/midterm-cartogram/**

```bash
python scripts/bundle.py --pages    # rebuilds dist/, the preview image and docs/
git add docs data && git commit -m "Results as of …" && git push
```

**Keeping it current:** the scheduled updates publish new results to the claude.ai page
only (scheduled runs can't push to GitHub). About 25 minutes after each update, a Claude
chat session reads the live claude.ai page and runs
`python scripts/sync_from_artifact.py <saved page>`, which copies its results into
`data/results.json` and rebuilds `docs/`; then it commits and pushes. `data/results.json`
is what the page shows; the `data/raw/` snapshots in this repo can trail it.

`docs/index.html` is the same page as `dist/index.html`, plus what a plain web host
needs: a doctype, the language tag, a tab icon, and the link-preview tags pointing at
`docs/preview.png`. `data/source/` (Census and us-atlas files) is committed so anyone
can rebuild the map from scratch.

## Experiment branch

Changes are tried on the `experiment` branch first; `main` is what the public site
serves. `python scripts/bundle.py --experimental` builds `dist/experimental.html` with a
yellow "Experimental version" banner, published as a separate claude.ai page. When an
experiment is ready: `git checkout main && git merge experiment`, rebuild with
`--pages`, publish the real artifact, push. Results syncs always go to `main`; rebase the
branch on `main` now and then (`git rebase main`) so it keeps the latest results.

## Feedback

The page links to an anonymous Google Form, "Seats, not acres: feedback" (in Alberto's
Google Drive), from the summary under the map and from "Sources and notes". The form
doesn't collect email addresses and doesn't limit people to one response, so no sign-in
is needed. Answers go to the Google Sheet "Seats not acres: feedback" and are never shown
on the page. The link opens in a new tab with `rel="noopener"`; the page still loads
nothing from outside when it opens. A test checks the link.

## How it fits together

```
Wikipedia tables ──scrape.py──> data/raw/*.txt ──scrape.py──> data/results.json ─┐
                                 + overrides.json                                ├─ bundle.py ─> dist/index.html
seat counts + US outline (geo.json) ──build_hex.py──> data/hex.json, tiles.json ──┤
Census boundaries + population ─────build_geo.py──> data/geo.json ─────────────┘
```

| File | What it is |
| --- | --- |
| `scripts/build_hex.py` + `scripts/hexlayout.py` | Generates the House layout. The real map is first squeezed east-west where seats are sparse and stretched where they are dense (`WARP_X`), so the empty Mountain West doesn't leave a gap and New York sits on the coast. A hexagon grid is laid over the squeezed outline, every state grows from its label point at once, the hexagons are re-dealt so states stay compact, and a repair step keeps each state in one piece. Alaska and Hawaii are fixed insets. Needs `data/geo.json` first (`build_geo.py`). Knobs: `WARP_X`, `OUTLINE_SLACK`, `ROUNDS`. Chosen on Nov 5 from the comparison of ten options (option C). |
| `scripts/extract_wikipedia.js` | The same table-reading rules as `scrape.py`, run inside a browser on the Wikipedia pages (used by the scheduled update). |
| `scripts/scrape.py` | Snapshot step (`--live`) and build step. Only marks a race called when Wikipedia shows a winner in bold; never infers a winner from votes. |
| `scripts/build_geo.py` | Reads the Census boundary files in `data/source/` and writes state outlines, county lines (shown only when zoomed into a state), and one dot per 25,000 residents, scattered inside each resident's county. |
| `scripts/extract_counties.js` | Browser script: reads the November county table from every Senate and governor race page. |
| `scripts/counties.py` | Matches county tables to map counties (FIPS codes) and applies the safety rules. |
| `scripts/extract_turnout.js` | Browser script: reads the state turnout table from the UF Election Lab page. |
| `scripts/turnout.py` | Checks the turnout tables (every rate must equal ballots ÷ eligible voters) and adds them to `results.json`. |
| `data/turnout_raw/2022.txt`, `2026.txt` | Turnout per state: `state|turnout %|ballots counted|eligible voters`. 2022 is final; 2026 is refreshed by the scheduled update. |
| `scripts/bundle.py` | Inlines the CSS, script and data into one HTML file. `--site-url <address>` adds the link-preview and canonical tags for public hosting. |
| `scripts/preview.py` | Makes the 1200×630 link-preview image (`dist/preview.png`) from the built page. |
| `LICENSE.md` | Code license (MIT) and each data source's license. |
| `data/raw/*.txt` | One line per race, readable by eye: `key|party|flip|winner|status|others|lean|held by before`. |
| `data/overrides.json` | Hand corrections, applied last. Use it when a second source (e.g. AP) confirms a call Wikipedia hasn't added yet. |
| `data/context.json` | Seats not up this year and majority lines. |
| `web/` | The page: `index.html`, `style.css`, `app.js` (plain JavaScript, no libraries). |
| `tests/test_data.py` | Layout, results and join checks, plus a parser test on sample HTML. |

## Map styles

The page has three ways to draw each office, chosen with the Cartogram / Map / Population switch (links remember the choice, e.g. `#senate-dots`):

- **Cartogram:** one equal hexagon per seat.
- **Map:** real state shapes. For the House, each state is shaded by its delegation (all-D to all-R among called seats).
- **Population:** one dot per 25,000 residents, colored by the result covering them.

Around the map:

- **Find a race:** the search box beside the tabs; search by state, district ("WA-3") or candidate; the map jumps there and opens the state's card.
- **State card and zoom:** tap any state or seat (or search for one) to zoom the map to that state and see its governor, Senate and House results together. Other states fade back; in the Map and Population styles faint county lines appear. "← Whole country", tapping the ocean or any empty part of the map, the card's ×, or Escape zooms back out.
- **Path to a majority:** the line under the tally says who has passed the majority line, or, if nobody has, how many more seats each party needs from the uncalled races (and when one can no longer get there). It is plain arithmetic on called races, never a projection.
- **Runoff dates:** races in a runoff show the runoff day on the map tooltip, state card, race list and "Still being counted" panel. Dates live in `data/context.json` under `runoffs` (keyed like `LA-H`), and only come from the state's official election site; a test rejects any other source. A runoff with no date on file just says "Headed to a runoff". Louisiana's open U.S. House general election is December 12, 2026 ([Louisiana Secretary of State](https://www.sos.la.gov/elections-voting/election-dates)).
- **Pan and zoom by hand:** drag to move around once zoomed in (mouse, or one finger on a phone); pinch with two fingers or a trackpad; Ctrl/⌘ + scroll wheel; or the + / − buttons (also reachable by keyboard). A plain scroll wheel, and one finger at the country view, still scroll the page, so the map never traps someone scrolling past it; a short hint explains Ctrl/⌘ + scroll. A drag never counts as a click.
- **Changed party:** one line in the summary under the map, with a button that shows only those seats on the map.
- **"?" buttons:** one-tap explanations of terms like *not yet called*, *majority* and *changed party*.

**Layout, top to bottom:** tabs and search; the seat tally; the map (edge to edge on phones, with a "tap a state to zoom in" hint); a short summary (majority, seats that changed party, results time); the two count panels; a quieter "Background" row (lean, turnout); the full race list; and "Sources and notes", collapsed to one line.

The panels follow the selected office (turnout is the same for all offices):

- **Still being counted:** uncalled races, most competitive places first, with who held each seat before.
- **How the count moved:** seats per party after each update. `scrape.py` keeps this history in `results.json`, adding a point only when called seats change; the chart appears once there are two points.
- **Turnout:** the share of eligible voters who cast a ballot in each state, against the 2022 midterm (bar = 2026, tick = 2022, last column = change in points). It is the same for every office, and each state card repeats its own line. Hidden if either year's table is missing.
- **Won against the lean:** winners in districts or states that usually lean the other way (Cook PVI, e.g. R+5), biggest surprises first. Hidden for governors, whose Wikipedia table has no lean figures.

## Accessibility

Checked Nov 4 with axe-core (no violations in any view, light or dark) and Lighthouse (accessibility 100).

- **Keyboard:** Tab reaches the toggles, search, a "Skip past the map" link, then each state (or, in the House cartogram, the seats of the state you've zoomed into; all 435 at once would be too many tab stops, so the map's label points to the search box). Enter or Space opens a state or seat like a click; Escape closes the pop-up, then zooms out.
- **Screen readers:** every shape has a label with its race and result; the map is linked to the summary sentence; the toggles are buttons that report whether they're on; the page declares English.
- **Color blindness:** every pair of map colors was checked under simulated protanopia, deuteranopia and tritanopia (Machado 2009). The closest pair is ΔE 11 or more after a small dark-mode adjustment. Party is also always written out in pop-ups, cards and lists, never shown by color alone.

## Decisions and limits

- **Trust notes:** the masthead says the results are unofficial and compiled from Wikipedia. After the last scheduled update day (`updates.race_calls_end` in `data/context.json`, Pacific time) a "Final snapshot" banner appears on its own, giving the date of the last race calls and turnout refresh. If the updates are restarted, move that date too.
- **No third-party requests:** the page uses each device's own fonts (a condensed system font for headings where one exists) instead of Google Fonts, so opening it contacts no outside server.

- **Turnout source and meaning:** [UF Election Lab](https://election.lab.ufl.edu/voter-turnout/) (Michael McDonald), the figures the national exit poll uses. Turnout = ballots counted ÷ voting-eligible population (adult citizens, minus people barred by a felony conviction where that applies). Registered-voter turnout isn't used because states keep their rolls differently, so it can't be compared between states or years. The 2026 numbers start as AP-based election-night estimates (rounded to the nearest thousand ballots) and become final after states certify, in late November and December; California and Washington, which count late-arriving mail ballots, move the most. DC is in the data but not on the map. There is no county-level turnout: it isn't published in a comparable form.

- **Source:** Wikipedia's results pages (CC BY-SA 4.0). They follow AP calls but can lag by a few hours; on Nov 4 at 16:14 UTC Wikipedia showed 225 D / 138 R House calls while AP (via Fox News) showed 228 / 139.
- **No margin shading yet:** Wikipedia's summary tables have no vote shares, so seats are coloured by winner only. `results.json` already has a `margin` field for when a vote-count source is added.
- **"Party gain"** follows Wikipedia and includes seats that changed hands because district lines were redrawn.
- **Generated layout instead of the Downballot hexmap:** that hexmap is drawn for 2022 district lines and several states redrew for 2026. Positions inside a state are approximate.
- **Population dots, not county results:** no 2026 county-level vote counts were available, so dots show where people live under each result, not how each county voted. A county-results view can be added once states publish county data.
- **Population figures:** 2020 Census state totals, spread across counties using each county's share in an older (~2012) Census estimate ([plotly/datasets](https://github.com/plotly/datasets)). Within-state shifts since then aren't captured.
- **District lines (House, zoomed in):** from the Census Bureau's 120th Congressional Districts file (January 1, 2026 vintage), downloaded to `data/source/districts_2026.geojson`, projected by `scripts/project_districts.mjs` and trimmed to each state's coastline by `build_geo.py`. In the Map style each district is filled with its own result; in the Population style only the borders are drawn, because dots are spread across whole counties and their district isn't reliable. Five states are left out because the lines used in 2026 differ from that file: Alabama, Florida, Louisiana and Tennessee redrew in April–May 2026, and Missouri used its 2022 map after a referendum petition paused its 2025 map.
- **County results (Senate and governor, zoomed in):** filled in automatically as Wikipedia's race pages add their November "By county" tables. `scripts/extract_counties.js` reads all 71 race pages in a browser (primary and runoff tables are never used), the scheduled update saves each table to `data/county_raw/<race>.txt`, and `scripts/counties.py` matches county names to the map. A race is used only if every county matches exactly once and the race is Democrat versus Republican; races where a third candidate made the top two, or where both finalists are from one party, are skipped. The Map style shades each county by margin (Democratic minus Republican share of all votes); the Population style colors each dot by its county's margin. Alaska (no counties) and Connecticut (results by town) will keep the "not available" note. As of Nov 4 no race page had a November county table yet.
- **County lines are from 2017** (us-atlas 3.0.1, Census 1:10 million scale, lightly simplified): Connecticut shows its 8 former counties rather than the 9 planning regions the Census has used since 2022, and Alaska's Valdez-Cordova Census Area appears before its 2019 split into Chugach and Copper River. Every other county matches. They are guide lines only; no results depend on them.
- **No 2026 district lines:** the House Map and Population styles color whole states, not districts, because 2026 boundaries for the six redrawn states weren't available.
- **No 2024 comparison toggle:** redrawn districts make a seat-by-seat 2024 comparison misleading; the "seats that changed party" filter covers the same question.
