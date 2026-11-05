/* 2026 midterm cartogram.
 *
 * Data comes either inlined by scripts/bundle.py (window.CARTO) or, when you
 * run a local server from the project folder, from the JSON files in data/.
 *   hex     : one hexagon per House district  {id, state, q, r, x, y}
 *   tiles   : one hexagon per state           {id, state, x, y}
 *   results : races keyed H-WA-01 / S-WA / G-WA (see scripts/scrape.py)
 */

const STATE_NAMES = {
  AL: "Alabama", AK: "Alaska", AZ: "Arizona", AR: "Arkansas", CA: "California", CO: "Colorado",
  CT: "Connecticut", DE: "Delaware", FL: "Florida", GA: "Georgia", HI: "Hawaii", ID: "Idaho",
  IL: "Illinois", IN: "Indiana", IA: "Iowa", KS: "Kansas", KY: "Kentucky", LA: "Louisiana",
  ME: "Maine", MD: "Maryland", MA: "Massachusetts", MI: "Michigan", MN: "Minnesota",
  MS: "Mississippi", MO: "Missouri", MT: "Montana", NE: "Nebraska", NV: "Nevada",
  NH: "New Hampshire", NJ: "New Jersey", NM: "New Mexico", NY: "New York",
  NC: "North Carolina", ND: "North Dakota", OH: "Ohio", OK: "Oklahoma", OR: "Oregon",
  PA: "Pennsylvania", RI: "Rhode Island", SC: "South Carolina", SD: "South Dakota",
  TN: "Tennessee", TX: "Texas", UT: "Utah", VT: "Vermont", VA: "Virginia", WA: "Washington",
  WV: "West Virginia", WI: "Wisconsin", WY: "Wyoming",
};
const PARTY = { D: "Democrat", R: "Republican", I: "Independent", L: "Libertarian", O: "Other" };
const SVG_NS = "http://www.w3.org/2000/svg";

// Pointy-top hexagon corners for radius 1, clockwise from the top.
const CORNERS = [[0, -1], [0.866, -0.5], [0.866, 0.5], [0, 1], [-0.866, 0.5], [-0.866, -0.5]];
// For each neighbour direction (axial q, r), the two corners of the shared edge.
const EDGES = [
  [[1, 0], 1, 2], [[1, -1], 0, 1], [[0, -1], 5, 0],
  [[-1, 0], 4, 5], [[-1, 1], 3, 4], [[0, 1], 2, 3],
];

const VIEWS = {
  house: { label: "House", office: "H" },
  senate: { label: "Senate", office: "S" },
  governors: { label: "Governors", office: "G" },
};

// How the seats are drawn. "cartogram" = equal hexagons; "map" = real state
// shapes; "dots" = one dot per 25,000 residents, placed by county.
const STYLES = { cartogram: "Cartogram", map: "Map", dots: "Population" };

let DATA;                 // {hex, tiles, results, geo}
let view = "house";
let style = "cartogram";
let flipsOnly = false;
let BASE_VB = [0, 0, 975, 610]; // the whole-country frame of the current style
let zoomState = null;           // two-letter state the map is zoomed into, or null

/* ------------------------------------------------------------------ data */

async function loadData() {
  if (window.CARTO) return window.CARTO;
  const get = (f) => fetch(`../data/${f}`).then((r) => r.json());
  const [hex, tiles, results, geo] = await Promise.all(
    [get("hex.json"), get("tiles.json"), get("results.json"), get("geo.json")]);
  return { hex, tiles, results, geo };
}

/** Everything the geographic styles need to colour one state in the current view. */
function stateInfo(st) {
  const races = DATA.results.races;
  if (view !== "house") {
    const key = `${VIEWS[view].office}-${st}`;
    const race = races[key] ? { key, ...races[key] } : null;
    return { race, fill: fillFor(race), flip: !!(race && race.flip) };
  }
  // House: summarise the state's whole delegation.
  const seats = Object.entries(races).filter(([k]) => k.startsWith(`H-${st}-`)).map(([, r]) => r);
  const n = { D: 0, R: 0, other: 0, pending: 0, flips: 0, total: seats.length };
  for (const r of seats) {
    if (!r.called) n.pending++;
    else if (r.winner === "D" || r.winner === "R") n[r.winner]++;
    else n.other++;
    if (r.flip) n.flips++;
  }
  return { house: n, fill: delegationFill(n), flip: n.flips > 0 };
}

/** Five-step scale from all-Democratic to all-Republican, among seats called so far. */
function delegationFill(n) {
  const called = n.D + n.R;
  if (!called) return "var(--pending)";
  const share = n.D / called;
  if (share >= 0.8) return "var(--dem)";
  if (share > 0.55) return "var(--dem-2)";
  if (share >= 0.45) return "var(--mixed)";
  if (share > 0.2) return "var(--rep-2)";
  return "var(--rep)";
}

function racesFor(office) {
  return Object.entries(DATA.results.races)
    .filter(([, r]) => r.office === office)
    .map(([key, r]) => ({ key, ...r }));
}

/** Seat totals for the tally board, including seats not up this year. */
function tally(viewName) {
  const ctx = DATA.results.context;
  const races = racesFor(VIEWS[viewName].office);
  const won = { D: 0, R: 0, other: 0 };
  for (const r of races) {
    if (!r.called) continue;
    if (r.winner === "D" || r.winner === "R") won[r.winner]++;
    else won.other++;
  }
  const pending = races.filter((r) => !r.called).length;
  let held = { D: 0, R: 0 };
  let seats = 435, majority = 218, heldNote = "";
  if (viewName === "senate") {
    seats = ctx.senate.seats; majority = ctx.senate.majority;
    held = { D: ctx.senate.not_up.D + ctx.senate.not_up.I, R: ctx.senate.not_up.R };
    heldNote = "incl. 2 independents who caucus with Democrats";
  } else if (viewName === "governors") {
    seats = ctx.governors.seats; majority = ctx.governors.majority;
    for (const p of Object.values(ctx.governors.not_up)) held[p]++;
  }
  return { won, held, pending, seats, majority, heldNote };
}

/* ------------------------------------------------------------------ drawing */

function el(name, attrs = {}, parent) {
  const node = document.createElementNS(SVG_NS, name);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  if (parent) parent.appendChild(node);
  return node;
}

function hexPoints(x, y, scale = 1) {
  return CORNERS.map(([cx, cy]) => `${(x + cx * scale).toFixed(3)},${(y + cy * scale).toFixed(3)}`).join(" ");
}

function fillFor(race) {
  if (!race) return "var(--norace)";
  if (!race.called) return "var(--pending)";
  return race.winner === "D" ? "var(--dem)" : race.winner === "R" ? "var(--rep)" : "var(--ink-2)";
}

/** The shapes to draw for the current view: [{id, state, x, y, race}] */
function shapes() {
  const races = DATA.results.races;
  if (view === "house") {
    return DATA.hex.map((h) => ({ ...h, race: { key: `H-${h.id}`, ...races[`H-${h.id}`] } }));
  }
  const prefix = VIEWS[view].office;
  return DATA.tiles.map((t) => {
    const r = races[`${prefix}-${t.state}`];
    return { ...t, race: r ? { key: `${prefix}-${t.state}`, ...r } : null };
  });
}

function drawMap() {
  if (style === "cartogram") drawCartogram();
  else drawGeo();
  drawLegend();
  restoreZoom();
}

/** Real state shapes ("map"), or state outlines with population dots ("dots"). */
function drawGeo() {
  const svg = document.getElementById("map");
  svg.replaceChildren();
  BASE_VB = [0, 0, 975, 610];
  svg.setAttribute("viewBox", BASE_VB.join(" "));
  const geo = DATA.geo;
  const dots = style === "dots";
  const info = Object.fromEntries(geo.states.map((s) => [s.state, stateInfo(s.state)]));
  const dimmed = (st) => flipsOnly && !info[st].flip;

  // Diagonal stripes mark states where a seat changed party (map style).
  const defs = el("defs", {}, svg);
  const pat = el("pattern", { id: "flip-hatch", width: 6, height: 6, patternUnits: "userSpaceOnUse", patternTransform: "rotate(45)" }, defs);
  el("rect", { width: 2, height: 6, class: "hatch-line" }, pat);

  const states = el("g", {}, svg);
  for (const s of geo.states) {
    const g = el("g", {
      class: "seat state" + (dimmed(s.state) ? " dim" : ""),
      tabindex: "0", role: "button", "aria-label": describeState(s.state, info[s.state]).plain,
    }, states);
    g.dataset.id = s.state;
    el("path", { class: "shape" + (dots ? " outline" : ""), d: s.path, fill: dots ? "var(--panel)" : info[s.state].fill }, g);
    if (!dots && info[s.state].flip) el("path", { class: "hatch", d: s.path, fill: "url(#flip-hatch)" }, g);
  }

  // County lines go here, only for the state being zoomed into.
  el("g", { id: "district-layer" }, svg);
  el("g", { id: "county-layer", "aria-hidden": "true" }, svg);
  el("g", { id: "outline-layer", "aria-hidden": "true" }, svg); // top: zoomed state's outline and district borders

  if (dots) {
    el("g", { id: "dot-layer", class: "dots", "aria-hidden": "true" }, svg);
    drawDots(1);
  }
  // State names, on top of everything. Small states and the Population style show
  // them only when zoomed in, where there is room (CSS: #map.zoomed).
  const labels = el("g", { class: "state-labels" + (dots ? " zoom-only" : ""), "aria-hidden": "true" }, svg);
  for (const s of geo.states) {
    const t = el("text", { class: "label geo" + (SMALL_STATES.has(s.state) ? " small" : ""), x: s.x, y: s.y }, labels);
    t.textContent = s.state;
  }
}

/** Population dots. zoom > 1 shrinks each dot so a zoomed state isn't one blob,
 *  and states outside the zoomed one are drawn faint. */
function drawDots(zoom) {
  const layer = document.getElementById("dot-layer");
  if (!layer) return;
  layer.replaceChildren();
  const geo = DATA.geo;
  const info = Object.fromEntries(geo.states.map((s) => [s.state, stateInfo(s.state)]));
  // One <path> per colour holding thousands of tiny circles draws far faster
  // than 13,000 separate <circle> elements.
  const r = 0.95 / Math.sqrt(zoom);
  const dot = (x, y) => `M${(x - r).toFixed(2)} ${y}a${r} ${r} 0 1 0 ${2 * r} 0a${r} ${r} 0 1 0 ${-2 * r} 0`;
  const buckets = new Map();
  const d = geo.dots;
  const key = countyRace();                       // zoomed state with county results
  const votes = key && DATA.results.counties[key];
  for (let i = 0; i < d.length; i += 3) {
    const st = geo.state_order[d[i + 2]];
    // Uncalled races get a darker grey than "no race", so they stay visible as dots.
    let fill = info[st].fill === "var(--pending)" ? "var(--pending-dot)" : info[st].fill;
    // Dots sit inside their own county, so they can take that county's margin.
    if (votes && st === zoomState) {
      const v = votes[geo.county_order[geo.dot_county[i / 3]]];
      if (v) fill = marginFill(v);
    }
    const faint = (flipsOnly && !info[st].flip) || (zoomState && st !== zoomState);
    const key = fill + (faint ? "|dim" : "");
    buckets.set(key, (buckets.get(key) || "") + dot(d[i], d[i + 1]));
  }
  for (const [key, path] of buckets) {
    const [fill, dim] = key.split("|");
    el("path", { d: path, fill, class: dim ? "dim" : "" }, layer);
  }
}

// Northeastern states too small for a label inside their shape.
const SMALL_STATES = new Set(["RI", "DE", "CT", "NJ", "MD", "MA", "NH", "VT", "DC", "HI"]);

/** Tooltip text for one state in the geographic styles. */
function describeState(st, info) {
  if (view !== "house") return describe({ id: st, state: st, race: info.race });
  const n = info.house;
  const title = `${STATE_NAMES[st]} House delegation`;
  const parts = [`<span class="dem">${n.D} D</span>`, `<span class="rep">${n.R} R</span>`];
  if (n.other) parts.push(`${n.other} other`);
  if (n.pending) parts.push(`${n.pending} not called`);
  const flips = n.flips ? `<div class="meta">${n.flips} seat${n.flips > 1 ? "s" : ""} changed party</div>` : "";
  return {
    plain: `${title}: ${n.D} Democrat, ${n.R} Republican, ${n.pending} not called, of ${n.total} seats.`,
    html: `<h3>${title}</h3><span class="call">${parts.join(" · ")}</span><div class="meta">${n.total} seat${n.total > 1 ? "s" : ""}</div>${flips}`,
  };
}

/** The legend changes with the style and the office. */
function drawLegend() {
  const sw = (fill, text, cls = "") => `<span><i class="${cls}" style="background:${fill}"></i>${text}</span>`;
  const items = [];
  if (countyRace()) {
    items.push(sw("var(--dem)", "D+20 or more"), sw("var(--dem-2)", "D+5 to 20"), sw("var(--dem-3)", "D+0 to 5"),
      sw("var(--rep-3)", "R+0 to 5"), sw("var(--rep-2)", "R+5 to 20"), sw("var(--rep)", "R+20 or more"));
  } else if (style !== "cartogram" && view === "house" && !districtsFilled()) {
    items.push(sw("var(--dem)", "80%+ of called seats D"), sw("var(--dem-2)", "Mostly D"),
      sw("var(--mixed)", "About even"), sw("var(--rep-2)", "Mostly R"), sw("var(--rep)", "80%+ R"),
      sw(style === "dots" ? "var(--pending-dot)" : "var(--pending)", "None called yet"));
  } else {
    items.push(sw("var(--dem)", "Democrat won"), sw("var(--rep)", "Republican won"),
      sw(style === "dots" ? "var(--pending-dot)" : "var(--pending)", "Not yet called"), sw("var(--norace)", "No race this year"));
  }
  if (style === "cartogram") items.push(sw("var(--ink-2)", "Ring = seat changed party", "ring"));
  if (style === "map" && !countiesFilled()) items.push(sw("var(--ink-2)", view === "house" && !districtsFilled() ? "Stripes = at least one seat changed party" : "Stripes = seat changed party", "stripes"));
  let note = "";
  if (style === "dots") {
    const m = DATA.geo.meta;
    note = `<p class="legend-note">Each dot is ${m.dot_people.toLocaleString()} residents, placed at random inside their county. ` +
      (view === "house"
        ? "Dots take their state's House delegation colour: they're spread across each county, not placed by district, so their color doesn't show which district a person is in."
        : countyRace()
          ? "Dots take the margin of their own county, so you can see where each side's votes came from."
          : "Dots take the colour of their state's result, so dense areas show how many people that result covers.") + "</p>";
  } else if (style === "map") {
    note = `<p class="legend-note">Land area, not people: big rural states look larger than their population.</p>`;
  }
  document.getElementById("legend").innerHTML = items.join("") + note;
}

function drawCartogram() {
  const svg = document.getElementById("map");
  svg.replaceChildren();
  const items = shapes();
  const pad = 1.6;
  const xs = items.map((d) => d.x), ys = items.map((d) => d.y);
  const minX = Math.min(...xs) - pad, minY = Math.min(...ys) - pad;
  const w = Math.max(...xs) - minX + pad, h = Math.max(...ys) - minY + pad;
  BASE_VB = [minX, minY, w, h];
  svg.setAttribute("viewBox", BASE_VB.join(" "));
  const house = view === "house";
  const size = house ? 1 : 0.94; // small gap between state tiles

  const seats = el("g", {}, svg);
  for (const d of items) {
    const g = el("g", {
      class: "seat" + (flipsOnly && !(d.race && d.race.flip) ? " dim" : ""),
      tabindex: house ? "-1" : "0",
      role: "button",
      "aria-label": describe(d).plain,
    }, seats);
    g.dataset.id = d.id;
    el("polygon", { class: "hex", points: hexPoints(d.x, d.y, size), fill: fillFor(d.race) }, g);
    // Flip ring: inset hexagon outline. On big state tiles it sits outside the label.
    if (d.race && d.race.flip) el("polygon", { class: "ring", points: hexPoints(d.x, d.y, size * (house ? 0.6 : 0.84)) }, g);
    if (!house) {
      const t = el("text", { class: "label" + (d.race && d.race.called ? " on-color" : ""), x: d.x, y: d.y }, g);
      t.textContent = d.state;
    }
  }

  if (house) {
    drawStateBorders(svg, items);
    drawStateLabels(svg, items);
  }
}

/** Thick lines wherever two neighbouring hexagons belong to different states. */
function drawStateBorders(svg, items) {
  const owner = new Map(items.map((d) => [`${d.q},${d.r}`, d.state]));
  let path = "";
  for (const d of items) {
    for (const [[dq, dr], a, b] of EDGES) {
      if (owner.get(`${d.q + dq},${d.r + dr}`) === d.state) continue;
      const [ax, ay] = CORNERS[a], [bx, by] = CORNERS[b];
      path += `M${(d.x + ax).toFixed(3)} ${(d.y + ay).toFixed(3)}L${(d.x + bx).toFixed(3)} ${(d.y + by).toFixed(3)}`;
    }
  }
  el("path", { class: "border", d: path }, svg);
}

/** One label per state, on the hexagon nearest the state's centre. */
function drawStateLabels(svg, items) {
  const byState = {};
  for (const d of items) (byState[d.state] ||= []).push(d);
  const g = el("g", { "aria-hidden": "true" }, svg);
  for (const [st, cells] of Object.entries(byState)) {
    const cx = cells.reduce((s, c) => s + c.x, 0) / cells.length;
    const cy = cells.reduce((s, c) => s + c.y, 0) / cells.length;
    const c = cells.reduce((a, b) => (Math.hypot(a.x - cx, a.y - cy) <= Math.hypot(b.x - cx, b.y - cy) ? a : b));
    const t = el("text", { class: "label house", x: c.x, y: c.y }, g);
    t.textContent = st;
  }
}

/* ------------------------------------------------------------------ text */

function raceTitle(d, v = view) {
  const name = STATE_NAMES[d.state];
  if (v === "house") {
    const n = Number(d.id.slice(3));
    return n === 0 ? `${name} at-large` : `${name} ${ordinal(n)} district`;
  }
  if (v === "senate") return `${name} Senate${d.race && d.race.special ? " (special)" : ""}`;
  return `${name} governor`;
}

function ordinal(n) {
  const s = ["th", "st", "nd", "rd"], v = n % 100;
  return n + (s[(v - 20) % 10] || s[v] || s[0]);
}

/** Tooltip HTML plus a plain-text version for screen readers. */
function describe(d) {
  const title = raceTitle(d);
  const r = d.race;
  if (!r) {
    let line = "No race in 2026.";
    if (view === "governors") {
      const p = DATA.results.context.governors.not_up[d.state];
      if (p) line += ` Current governor: ${PARTY[p]}.`;
    } else if (view === "senate") {
      line += " Both of this state's seats are up in other years.";
    }
    return { plain: `${title}. ${line}`, html: `<h3>${title}</h3><div class="meta">${line}</div>` };
  }
  let call, plainCall;
  if (r.called) {
    const who = r.winner_name ? `${esc(r.winner_name)} (${r.winner})` : PARTY[r.winner];
    call = `<span class="call ${r.winner === "D" ? "dem" : r.winner === "R" ? "rep" : ""}">${who} won</span>` +
      (r.flip ? `<span class="chip flip">${PARTY[r.winner]} gain</span>` : "");
    plainCall = `${r.winner_name || ""} (${PARTY[r.winner]}) won${r.flip ? ", a party gain" : ""}.`;
  } else {
    const why = r.status === "runoff" ? runoffText(r) : "Not yet called";
    call = `<span class="call">${why}</span><span class="chip wait">pending</span>`;
    plainCall = `${why}.`;
  }
  let others = "";
  if (r.others && r.others.length && view !== "house") {
    const shown = r.others.slice(0, 5).map((o) => `<li>${esc(o.n)} (${o.p})</li>`).join("");
    const more = r.others.length > 5 ? `<li>+${r.others.length - 5} more</li>` : "";
    others = `<div class="meta">${r.called ? "Also on the ballot" : "On the ballot"}:</div><ul>${shown}${more}</ul>`;
  }
  return {
    plain: `${title}. ${plainCall}`,
    html: `<h3>${title}</h3>${call}${others}`,
  };
}

function esc(s) {
  return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

/* ------------------------------------------------------------------ tally board */

function drawTally() {
  const t = tally(view);
  const D = t.won.D + t.held.D, R = t.won.R + t.held.R;
  const pct = (n) => `${(100 * n) / t.seats}%`;
  document.getElementById("d-num").textContent = D;
  document.getElementById("r-num").textContent = R;
  document.getElementById("u-num").textContent = t.pending;
  // The House number is just races won, so no sub-line; Senate and governor totals add seats not up.
  const sub = (won, held) => (view === "house" ? "" : `${won} won Tuesday + ${held} not up`);
  document.getElementById("d-sub").textContent = sub(t.won.D, t.held.D);
  document.getElementById("r-sub").textContent = sub(t.won.R, t.held.R);
  // Senate and governor totals include seats with no race this year.
  const note = document.getElementById("held-note");
  const notUp = t.held.D + t.held.R;
  note.innerHTML = view === "house" ? "" :
    `Totals include the ${notUp} ${view === "senate" ? "seats" : "states"} with no race this year` +
    (view === "senate" ? "; the Democratic total includes 2 independents who caucus with Democrats" : "") +
    `. <button type="button" class="q" data-term="notup" aria-label="Why are some seats not up?">?</button>`;
  note.hidden = view === "house";

  const bar = document.getElementById("bar");
  bar.innerHTML =
    `<span class="d hold" style="width:${pct(t.held.D)}"></span>` +
    `<span class="d" style="width:${pct(t.won.D)}"></span>` +
    `<span class="u" style="width:${pct(t.pending + t.won.other)}"></span>` +
    `<span class="r" style="width:${pct(t.won.R)}"></span>` +
    `<span class="r hold" style="width:${pct(t.held.R)}"></span>`;
  bar.setAttribute("aria-label", `Democrats ${D}, not yet called ${t.pending}, Republicans ${R}, of ${t.seats}`);

  const tick = document.getElementById("tick");
  tick.style.setProperty("--at", pct(t.seats / 2));
  tick.querySelector("span").textContent = `${t.majority} for a majority`;

  const what = { house: "House seats", senate: "Senate seats", governors: "governorships" }[view];
  document.getElementById("status").textContent = majorityText(t, D, R, what);
}

/** The official runoff date for a race, as a UTC Date, or null if none is on file. */
function runoffDate(r) {
  const entry = (DATA.results.context.runoffs || {})[`${r.state}-${r.office}`];
  if (!entry) return null;
  const [y, m, d] = entry.date.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d));
}

/** "Runoff on Saturday, December 12" (short: "Runoff Dec 12"); no date on file: "Headed to a runoff". */
function runoffText(r, short = false) {
  const when = runoffDate(r);
  if (!when) return short ? "Runoff" : "Headed to a runoff";
  const fmt = (o) => when.toLocaleDateString("en-US", { timeZone: "UTC", ...o });
  // Once the day has passed, the race is waiting on the runoff count, not on the vote.
  const past = Date.now() > when.getTime() + 864e5;
  if (short) return `${past ? "Runoff held" : "Runoff"} ${fmt({ month: "short", day: "numeric" })}`;
  return past ? `Runoff held ${fmt({ month: "long", day: "numeric" })}, not yet called`
    : `Runoff on ${fmt({ weekday: "long", month: "long", day: "numeric" })}`;
}

/** One sentence on where control stands: who has a majority, or what each party still needs. */
function majorityText(t, D, R, what) {
  const runoffs = shapes().filter((d) => d.race && d.race.status === "runoff");
  const later = runoffs.length
    ? `, ${runoffs.length === 1 ? "one" : runoffs.length} of them in a runoff` +
      (runoffs.length === 1 && runoffDate(runoffs[0].race) ? ` (${runoffText(runoffs[0].race, true).replace("Runoff ", "")})` : "")
    : "";
  const left = t.pending ? ` ${t.pending} ${t.pending === 1 ? "race is" : "races are"} still uncalled${later}.` : "";
  const leader = D >= t.majority ? "Democrats" : R >= t.majority ? "Republicans" : null;
  if (leader) return `${leader} have passed the ${t.majority} ${what} needed for a majority, counting called races.` + left;
  // Neither party has a majority yet: how many of the uncalled races each one needs.
  const need = (n) => t.majority - n;
  const part = (name, n) => need(n) > t.pending ? `${name} can no longer reach ${t.majority}` : `${name} need ${need(n)} more`;
  return `No majority yet: ${part("Democrats", D)} and ${part("Republicans", R)} to reach ${t.majority}.` + left;
}

/* ------------------------------------------------------------------ context panels */

const HELD = { D: "Held by D", R: "Held by R", I: "Held by independent", N: "New seat", V: "Was vacant" };
const PARTY_PLURAL = { D: "Democrats", R: "Republicans", I: "independents" };
const SHOW_FIRST = 6; // rows shown before "Show all", so the panels stay short

/** Number of points in a lean like "R+5" (EVEN = 0). */
const leanSize = (pvi) => (pvi && pvi !== "EVEN" ? Number(pvi.slice(2)) : 0);

/** A short list: the first rows, then the rest behind a "Show all" toggle. */
function shortList(rows, renderRow) {
  const first = rows.slice(0, SHOW_FIRST).map(renderRow).join("");
  const rest = rows.slice(SHOW_FIRST).map(renderRow).join("");
  return `<ul class="rows">${first}</ul>` +
    (rest ? `<details class="more"><summary>Show all ${rows.length}</summary><ul class="rows">${rest}</ul></details>` : "");
}

function partyChip(p, text) {
  const cls = p === "D" ? "d" : p === "R" ? "r" : "n";
  return `<span class="pill ${cls}">${text}</span>`;
}

function drawPanels() {
  const races = shapes().filter((d) => d.race).map((d) => ({ d, r: d.race }));
  const officeName = { house: "House", senate: "Senate", governors: "governor" }[view];

  // Still being counted: uncalled races, closest lean first (most competitive places).
  const open = races.filter(({ r }) => !r.called)
    .sort((a, b) => leanSize(a.r.pvi) - leanSize(b.r.pvi) || a.d.id.localeCompare(b.d.id));
  let html;
  if (!open.length) {
    html = `<p class="lead">Every ${officeName} race has been called.</p>`;
  } else {
    const held = {};
    for (const { r } of open) held[r.held_by || "?"] = (held[r.held_by || "?"] || 0) + 1;
    const parts = ["R", "D", "I"].filter((p) => held[p]).map((p) => `${PARTY_PLURAL[p]} held ${held[p]}`);
    if (held.N) parts.push(`${held.N} ${held.N > 1 ? "are new seats" : "is a new seat"}`);
    if (held.V) parts.push(`${held.V} ${held.V > 1 ? "were vacant" : "was vacant"}`);
    const n = open.length;
    html = `<p class="lead"><strong>${n} ${officeName} race${n > 1 ? "s are" : " is"} still uncalled.</strong> ` +
      `Before the election, ${parts.join(", ")}.</p>` +
      shortList(open, ({ d, r }) =>
        `<li><span class="what">${raceTitle(d)}${r.status === "runoff" ? ` · ${runoffText(r, true).replace(/^Runoff/, "runoff")}` : ""}</span>` +
        `${partyChip(r.held_by, HELD[r.held_by] || "Unknown")}${r.pvi ? `<span class="lean">${r.pvi}</span>` : ""}</li>`);
  }
  document.getElementById("pending-body").innerHTML = html;

  // Won against the lean: called races whose winner's party differs from the lean.
  const card = document.getElementById("lean-card");
  card.hidden = view === "governors"; // the governors table has no lean figures
  if (card.hidden) return;
  const against = races.filter(({ r }) => r.called && r.pvi && r.pvi !== "EVEN" &&
      (r.winner === "D" || r.winner === "R") && r.pvi[0] !== r.winner)
    .sort((a, b) => leanSize(b.r.pvi) - leanSize(a.r.pvi) || a.d.id.localeCompare(b.d.id));
  const byParty = { D: 0, R: 0 };
  for (const { r } of against) byParty[r.winner]++;
  const unit = view === "house" ? "district" : "state";
  const n = against.length;
  // Describe only the parties that actually have such wins.
  const desc = [
    byParty.D && `${byParty.D === n ? (n > 1 ? "all Democrats" : "a Democrat") : `${byParty.D} Democrat${byParty.D > 1 ? "s" : ""}`} in Republican-leaning ${unit}s`,
    byParty.R && `${byParty.R === n ? (n > 1 ? "all Republicans" : "a Republican") : `${byParty.R} Republican${byParty.R > 1 ? "s" : ""}`} in Democratic-leaning ${unit}s`,
  ].filter(Boolean).join(" and ");
  card.querySelector("#lean-body").innerHTML = !n
    ? `<p class="lead">No winner so far carried a ${unit} that leans the other way.</p>`
    : `<p class="lead"><strong>${n} winner${n > 1 ? "s" : ""} carried a ${unit} that leans the other way:</strong> ` +
      `${desc}. Biggest surprises first.</p>` +
      shortList(against, ({ d, r }) =>
        `<li><span class="what">${raceTitle(d)}</span>` +
        `<span class="who ${r.winner === "D" ? "dem" : "rep"}">${esc(r.winner_name || PARTY[r.winner])} (${r.winner})</span>` +
        `<span class="lean">${r.pvi}</span></li>`);
}

/* ------------------------------------------------------------------ turnout */

/** "+3.3" / "−1.2" / "0.0": change in percentage points. */
const pts = (x) => (x > 0.05 ? "+" : x < -0.05 ? "−" : "") + Math.abs(x).toFixed(1);

/** Turnout of eligible voters per state, 2026 against the 2022 midterm. Same for every office. */
function drawTurnout() {
  const t = DATA.results.turnout || {};
  const card = document.getElementById("turnout-card");
  card.hidden = !t["2026"] || !t["2022"];
  if (card.hidden) return;
  const now = t["2026"], then = t["2022"];
  const us = now.US, usThen = then.US;
  const early = /estimate/i.test((t.notes?.["2026"] || []).join(" "));
  // Only the 50 states on the map (DC has no shape here).
  const rows = Object.keys(STATE_NAMES).filter((st) => now[st] && then[st])
    .map((st) => ({ st, rate: now[st][0], change: now[st][0] - then[st][0] }))
    .sort((a, b) => b.rate - a.rate || a.st.localeCompare(b.st));
  const MAX = 80; // bar scale: 0-80% fits every state with room to spare
  const row = ({ st, rate, change }) =>
    `<li data-state="${st}"><span class="what">${STATE_NAMES[st]}</span>` +
    `<span class="tbar" aria-hidden="true"><span class="now" style="width:${(rate / MAX) * 100}%"></span>` +
    `<span class="then" style="left:${(then[st][0] / MAX) * 100}%"></span></span>` +
    `<span class="lean">${rate.toFixed(1)}%</span>` +
    `<span class="lean delta">${pts(change)}</span></li>`;
  const up = rows.filter((r) => r.change > 0.05).length;
  const millions = (n) => `${Math.round(n / 1e6)} million`;
  document.getElementById("turnout-body").innerHTML =
    `<p class="lead"><strong>${us[0].toFixed(1)}% of eligible voters cast a ballot</strong> (about ${millions(us[1])}), ` +
    `${us[0] >= usThen[0] ? "up" : "down"} from ${usThen[0].toFixed(1)}% in the 2022 midterm. Turnout rose in ${up} of 50 states.</p>` +
    `<p class="hint">${early ? "Early estimate based on AP's election-night figures; final numbers come after states certify, in late November and December. " : ""}` +
    `Bars show 2026; the tick marks 2022. Last column: change in percentage points.</p>` +
    shortList(rows, row);
}

/** One line for the state card: this state's turnout and its 2022 figure. */
function turnoutLine(st) {
  const t = DATA.results.turnout || {};
  if (!t["2026"]?.[st] || !t["2022"]?.[st]) return "";
  const now = t["2026"][st][0], then = t["2022"][st][0];
  const early = /estimate/i.test((t.notes?.["2026"] || []).join(" "));
  return `<li><span class="what">Turnout${early ? " (early estimate)" : ""}</span>` +
    `<span><strong>${now.toFixed(1)}%</strong> of eligible voters · 2022: ${then.toFixed(1)}% (${pts(now - then)} pts)</span></li>`;
}

/* ------------------------------------------------------------------ final snapshot */

/** After the scheduled updates end, say so plainly at the top, so nobody reads old
 *  numbers as live. The end dates live in data/context.json ("updates"). */
function drawFinalBanner() {
  const box = document.getElementById("final-banner");
  const u = DATA.results.context.updates;
  if (!box || !u) return;
  // End of the last update day in Pacific time (8:00 UTC the next morning, standard time).
  const endOf = (day) => Date.parse(`${day}T08:00:00Z`) + 864e5;
  box.hidden = Date.now() < endOf(u.race_calls_end);
  if (box.hidden) return;
  const fmt = (d) => d.toLocaleDateString(undefined, { month: "long", day: "numeric", year: "numeric" });
  const calls = fmt(new Date(DATA.results.updated));
  const read = ((DATA.results.turnout?.notes?.["2026"] || []).join(" ").match(/read (\d{4}-\d{2}-\d{2})/) || [])[1];
  const turnout = read ? ` Turnout figures were last refreshed ${fmt(new Date(`${read}T12:00:00Z`))}.` : "";
  box.innerHTML = `<strong>Final snapshot:</strong> this page is no longer updated. Race calls are as of ${calls}; ` +
    `races called after that aren't shown.${turnout} For official results, see each state's election office.`;
}

/* ------------------------------------------------------------------ race list */

function drawTable() {
  const rows = shapes()
    .filter((d) => d.race)
    .sort((a, b) => STATE_NAMES[a.state].localeCompare(STATE_NAMES[b.state]) || a.id.localeCompare(b.id));
  document.getElementById("list-title").textContent = `All ${rows.length} ${VIEWS[view].label.toLowerCase()} races`;
  document.getElementById("rows").innerHTML = rows.map((d) => {
    const r = d.race;
    const result = r.called ? PARTY[r.winner] : r.status === "runoff" ? runoffText(r, true) : "Not called";
    const cls = r.winner === "D" ? "dem" : r.winner === "R" ? "rep" : "";
    return `<tr><td>${raceTitle(d)}</td><td class="party ${cls}">${result}</td>` +
      `<td>${esc(r.winner_name || "")}</td><td>${r.flip ? "Yes" : ""}</td></tr>`;
  }).join("");
}

/* ------------------------------------------------------------------ tooltip */

const tip = () => document.getElementById("tip");

function showTip(target, x, y) {
  let html;
  if (style === "cartogram") {
    const d = shapes().find((s) => s.id === target.dataset.id);
    if (!d) return;
    html = describe(d).html;
  } else if (target.classList.contains("county")) {
    html = describeCounty(target.dataset.id, countyRace()).html;
  } else if (target.classList.contains("district")) {
    const id = target.dataset.id;
    html = describe({ id, state: id.slice(0, 2), race: { key: `H-${id}`, ...DATA.results.races[`H-${id}`] } }).html;
  } else {
    html = describeState(target.dataset.id, stateInfo(target.dataset.id)).html;
  }
  document.querySelectorAll(".seat.active").forEach((n) => n.classList.remove("active"));
  target.classList.add("active");
  const box = tip();
  box.innerHTML = html;
  box.hidden = false;
  // Keep the card on screen: prefer below-right of the pointer, flip if needed.
  const r = box.getBoundingClientRect();
  let left = x + 14, top = y + 14;
  if (left + r.width > innerWidth - 8) left = Math.max(8, x - r.width - 14);
  if (top + r.height > innerHeight - 8) top = Math.max(8, y - r.height - 14);
  box.style.left = `${left}px`;
  box.style.top = `${top}px`;
}

/** Open the tooltip beside a seat, wherever it is on screen now. */
function tipAtSeat(seat) {
  const b = seat.getBoundingClientRect();
  showTip(seat, b.left + b.width / 2, b.top + b.height / 2);
}

function hideTip() {
  tip().hidden = true;
  document.querySelectorAll(".seat.active").forEach((n) => n.classList.remove("active"));
}

function wireTooltip() {
  const svg = document.getElementById("map");
  svg.addEventListener("pointermove", (e) => {
    const seat = e.target.closest(".seat");
    if (seat && e.pointerType === "mouse") showTip(seat, e.clientX, e.clientY);
    else if (!seat && e.pointerType === "mouse") hideTip();
  });
  svg.addEventListener("pointerleave", (e) => { if (e.pointerType === "mouse") hideTip(); });
  // Tap or click: a seat shows its details and opens its state's card;
  // a "?" button shows a short explanation; anywhere else closes the tooltip.
  document.addEventListener("click", (e) => {
    if (performance.now() - lastDragEnd < 400 && e.target.closest && e.target.closest("#map")) return; // that was a drag
    const q = e.target.closest && e.target.closest(".q");
    if (q) { showTerm(q); return; }
    const seat = e.target.closest && e.target.closest(".seat");
    if (seat) {
      const st = seatState(seat);
      if (st === zoomState) showTip(seat, e.clientX, e.clientY);
      // On a phone the pop-up would cover the state just zoomed into; the state card
      // right under the map already has its results, so skip it on the first tap.
      else showState(st, matchMedia("(max-width: 600px)").matches ? undefined : () => tipAtSeat(seat));
    } else if ((zoomState || isZoomedIn()) && e.target.closest && e.target.closest("#map")) {
      zoomOut(); // zoomed in and clicked the ocean or empty space: back to the whole country
    } else hideTip();
  });
  svg.addEventListener("focusin", (e) => {
    const seat = e.target.closest(".seat");
    if (!seat) return;
    const b = seat.getBoundingClientRect();
    showTip(seat, b.right, b.top);
  });
  svg.addEventListener("focusout", hideTip);
  svg.addEventListener("keydown", (e) => {
    if (e.key !== "Enter" && e.key !== " ") return;
    const seat = e.target.closest(".seat");
    if (!seat) return;
    e.preventDefault();
    const st = seatState(seat);
    if (st === zoomState) tipAtSeat(seat);
    else showState(st, () => { seat.focus?.(); tipAtSeat(seat); });
  });
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    if (!tip().hidden) hideTip(); else zoomOut(); // first Escape closes the tooltip, the next zooms out
  });
  addEventListener("scroll", hideTip, { passive: true });
}

/* ------------------------------------------------------------------ explainers */

// Short answers behind the small "?" buttons. Kept to two sentences each.
const TERMS = {
  pending: "A race is “called” once a news organization is confident who won; this page follows the calls listed on Wikipedia, which come from the Associated Press. Until then votes are still being counted, often mail ballots that arrive after Election Day.",
  majority: "A party controls a chamber with a majority: 218 of the 435 House seats, or 51 of the 100 Senate seats (at 50, the Vice President's tie-breaking vote decides). Governors aren't a chamber; the count shows which party leads more states.",
  gain: "A seat changed party when its winner is from a different party than whoever held it before. Following Wikipedia, this includes seats that changed hands because district lines were redrawn.",
  turnout: "Turnout is the share of eligible voters (adult citizens, minus people barred by a felony conviction in some states) who cast a ballot. Using eligible voters rather than registered voters keeps states and years comparable, because states keep their voter rolls differently. Figures from the UF Election Lab.",
  notup: "Senators serve six-year terms, so only about a third of seats are elected each time; the rest keep their senator. Most governors serve four years, so some states had no race this year.",
};

function showTerm(button) {
  const box = tip();
  box.innerHTML = `<div class="term">${TERMS[button.dataset.term]}</div>`;
  box.hidden = false;
  const b = button.getBoundingClientRect(), r = box.getBoundingClientRect();
  box.style.left = `${Math.max(8, Math.min(b.left, innerWidth - r.width - 8))}px`;
  box.style.top = `${b.bottom + 8 + r.height > innerHeight ? Math.max(8, b.top - r.height - 8) : b.bottom + 8}px`;
}

/* ------------------------------------------------------------------ what changed */

function drawChanges() {
  const flips = racesFor(VIEWS[view].office).filter((r) => r.flip);
  const unit = view === "governors" ? "governorship" : "seat";
  const to = { D: 0, R: 0, other: 0 };
  for (const r of flips) to[r.winner === "D" || r.winner === "R" ? r.winner : "other"]++;
  const n = flips.length;
  let text;
  if (!n) text = `No ${unit}s have changed party so far.`;
  else {
    const parts = [to.D && `${to.D === n && n > 1 ? "all" : to.D} to Democrats`,
      to.R && `${to.R === n && n > 1 ? "all" : to.R} to Republicans`,
      to.other && `${to.other} to other parties`].filter(Boolean);
    text = `<strong>${n} ${unit}${n > 1 ? "s" : ""} changed party so far:</strong> ${parts.join(", ")}.`;
  }
  document.getElementById("changes").innerHTML = text;
  const btn = document.getElementById("show-flips");
  btn.hidden = !n;
  btn.textContent = flipsOnly ? "Show all seats again" : "Show them on the map";
  btn.setAttribute("aria-pressed", String(flipsOnly));
}

function setFlipsOnly(on) {
  flipsOnly = on;
  drawMap();
  drawChanges();
}

/* ------------------------------------------------------------------ calls over time */

/** Small line chart of seats won per party, one point per update. Hidden until
 *  there are at least two updates to compare. */
function drawHistory() {
  const card = document.getElementById("history-card");
  const hist = DATA.results.history || [];
  card.hidden = hist.length < 2;
  if (card.hidden) return;
  const office = VIEWS[view].office;
  const t = tally(view);
  const pts = hist.map((h) => ({ time: Date.parse(h.t), D: h[office][0] + t.held.D, R: h[office][1] + t.held.R, u: h[office][2] }));
  const W = 360, H = 150, L = 34, Rm = 44, T = 10, B = 22;
  const t0 = pts[0].time, t1 = pts.at(-1).time;
  const lo = Math.min(...pts.map((p) => Math.min(p.D, p.R)), t.majority) - 5;
  const hi = Math.max(...pts.map((p) => Math.max(p.D, p.R)), t.majority) + 5;
  const X = (time) => L + ((time - t0) / (t1 - t0 || 1)) * (W - L - Rm);
  const Y = (v) => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);
  const line = (k) => pts.map((p, i) => `${i ? "L" : "M"}${X(p.time).toFixed(1)},${Y(p[k]).toFixed(1)}`).join("");
  const fmt = (ms) => new Date(ms).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric" });
  const last = pts.at(-1);
  document.getElementById("history-body").innerHTML =
    `<p class="lead">Seats each party had won on Wikipedia's results pages, hour by hour since election night. Wikipedia records calls a little after the Associated Press makes them.</p>
    <svg class="spark" viewBox="0 0 ${W} ${H}" role="img" aria-label="Democrats ${pts[0].D} to ${last.D}, Republicans ${pts[0].R} to ${last.R} between ${fmt(t0)} and ${fmt(t1)}">
      <line x1="${L}" x2="${W - Rm}" y1="${Y(t.majority)}" y2="${Y(t.majority)}" class="maj"/>
      <text x="${L - 4}" y="${Y(t.majority) + 4}" class="axis" text-anchor="end">${t.majority}</text>
      <path d="${line("D")}" class="ln dem-ln"/><path d="${line("R")}" class="ln rep-ln"/>
      <text x="${X(last.time) + 6}" y="${Y(last.D) + 4}" class="end dem">${last.D} D</text>
      <text x="${X(last.time) + 6}" y="${Y(last.R) + 4}" class="end rep">${last.R} R</text>
      <text x="${L}" y="${H - 4}" class="axis">${fmt(t0)}</text>
      <text x="${W - Rm}" y="${H - 4}" class="axis" text-anchor="end">${fmt(t1)}</text>
    </svg>`;
}

/* ------------------------------------------------------------------ zoom */

const reduceMotion = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
let zoomAnim = 0;

/** The seats (or state shapes) belonging to one state in the current drawing. */
function stateSeats(st) {
  return [...document.querySelectorAll("#map .seat")].filter((g) => seatState(g) === st);
}

/** The frame (SVG viewBox) that shows one state with a little of its surroundings. */
function frameFor(st) {
  const seats = stateSeats(st);
  if (!seats.length) return BASE_VB;
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const g of seats) {
    const b = g.getBBox();
    x0 = Math.min(x0, b.x); y0 = Math.min(y0, b.y);
    x1 = Math.max(x1, b.x + b.width); y1 = Math.max(y1, b.y + b.height);
  }
  const [, , W, H] = BASE_VB;
  // Never zoom closer than this share of the whole map, so neighbours stay in
  // view (a single Senate tile filling the screen would say nothing).
  const minShare = style !== "cartogram" ? 0.14 : view === "house" ? 0.22 : 0.45;
  const pad = style !== "cartogram" ? 1.18 : 1.3; // real shapes need less margin than hexagons
  let w = (x1 - x0) * pad, h = (y1 - y0) * pad;
  // Small states grow evenly to the minimum, keeping their own shape (growing only the
  // short side would pad a narrow state like Indiana out sideways).
  const share = Math.max(w / W, h / H);
  if (share < minShare) { w *= minShare / share; h *= minShare / share; }
  // A wide state keeps the map's wide proportions. A tall state (Indiana, California)
  // may make the frame taller, so it fills a phone screen instead of sitting in a wide
  // box: never taller than about 60% of the screen, and never on the hexagon cartogram.
  const svgW = document.getElementById("map").getBoundingClientRect().width || W;
  const tallest = style === "cartogram" ? W / H : Math.min(W / H, Math.max(0.7, svgW / (0.6 * innerHeight)));
  if (w / h > W / H) h = (w * H) / W;
  else if (w / h < tallest) w = h * tallest;
  w = Math.min(w, W); h = Math.min(h, H);
  // Centre on the state, but slide the frame back inside the map's edges.
  const [bx, by] = BASE_VB;
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  return [clamp((x0 + x1) / 2 - w / 2, bx, bx + W - w), clamp((y0 + y1) / 2 - h / 2, by, by + H - h), w, h];
}

function setViewBox(vb) {
  const svg = document.getElementById("map");
  svg.setAttribute("viewBox", vb.map((n) => n.toFixed(2)).join(" "));
  svg.style.setProperty("--z", (BASE_VB[2] / vb[2]).toFixed(3)); // labels use it to keep their size
  const w = svg.getBoundingClientRect().width || BASE_VB[2];
  svg.style.setProperty("--upx", (vb[2] / w).toFixed(4));
  svg.classList.toggle("zoomed", !!zoomState || vb[2] < BASE_VB[2] * 0.6);
  svg.classList.toggle("pannable", vb[2] < BASE_VB[2] * 0.98);
}

/** Glide the frame to `target` (instant for people who prefer less motion). */
function animateTo(target, done) {
  const from = document.getElementById("map").getAttribute("viewBox").split(/\s+/).map(Number);
  cancelAnimationFrame(zoomAnim);
  if (reduceMotion()) { setViewBox(target); done?.(); return; }
  const t0 = performance.now(), ms = 450;
  const ease = (t) => (t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2);
  const step = (now) => {
    const k = ease(Math.min(1, (now - t0) / ms));
    setViewBox(from.map((v, i) => v + (target[i] - v) * k));
    if (k < 1) zoomAnim = requestAnimationFrame(step); else done?.();
  };
  zoomAnim = requestAnimationFrame(step);
}

/** Zoom into one state: frame it and fade everything else. */
function zoomTo(st, done) {
  clearTimeout(settleTimer);
  zoomState = st;
  hideTip();
  applyFocus();
  document.getElementById("zoom-out").hidden = false;
  animateTo(frameFor(st), () => { finishZoom(); done?.(); });
}

function zoomOut() {
  if (!zoomState && !isZoomedIn()) return;
  clearTimeout(settleTimer); // a pending tidy-up from an earlier gesture must not re-show the button
  zoomState = null;
  hideTip();
  applyFocus();
  document.getElementById("zoom-out").hidden = true;
  document.getElementById("state-card").hidden = true;
  updateCountyNote();
  drawDistricts();
  animateTo(BASE_VB, finishZoom);
}

/** Once the frame has settled: county lines for the zoomed state, and smaller dots. */
function finishZoom() {
  const vb = document.getElementById("map").getAttribute("viewBox").split(/\s+/).map(Number);
  const layer = document.getElementById("county-layer");
  if (layer) {
    layer.replaceChildren();
    // Skip county lines while districts are filled in, to keep the map readable.
    const d = zoomState && !districtsFilled() && !countiesFilled() && DATA.geo.county_lines[zoomState];
    // Drawn twice ("casing"): a wide dark line, then a thin light one on top, so the
    // borders show over blue, red, grey and the plain background alike.
    // The Population style has a plain background, so a simple solid line is enough there.
    if (d) {
      if (style !== "dots") el("path", { class: "counties-casing", d, "aria-hidden": "true" }, layer);
      el("path", { class: "counties" + (style === "dots" ? " plain" : "") + (view === "house" ? " under-districts" : ""), d, "aria-hidden": "true" }, layer);
    }
  }
  drawDistricts();
  updateCountyNote();
  if (style === "dots") drawDots(BASE_VB[2] / vb[2]);
}

/** Every seat knows its state: districts and states by their id, counties by data-state. */
const seatState = (g) => g.dataset.state || g.dataset.id.slice(0, 2);

/** The Senate or governor race whose county results the zoomed map can show, or null. */
function countyRace() {
  if (!zoomState || view === "house" || style === "cartogram") return null;
  const key = `${VIEWS[view].office}-${zoomState}`;
  return DATA.results.counties && DATA.results.counties[key] ? key : null;
}

/** True while the Map style fills a zoomed state's counties with margins. */
function countiesFilled() {
  return style === "map" && !!countyRace();
}

/** Margin = Democratic minus Republican share of all votes, in points. */
const marginOf = ([d, r, t]) => (t ? ((d - r) / t) * 100 : 0);

/** Six-step color for a county margin: 20+ points, 5–20, under 5, each side. */
function marginFill(votes) {
  if (!votes || !votes[2]) return "var(--pending)";
  const m = marginOf(votes), a = Math.abs(m);
  if (a === 0) return "var(--mixed)";
  const side = m > 0 ? "dem" : "rep";
  return a >= 20 ? `var(--${side})` : a >= 5 ? `var(--${side}-2)` : `var(--${side}-3)`;
}

/** "D+12" / "R+3" / "Even". */
function marginLabel(votes) {
  const m = marginOf(votes);
  return Math.abs(m) < 0.05 ? "Even" : `${m > 0 ? "D" : "R"}+${Math.abs(m).toFixed(1)}`;
}

/** True while the Map style shows a zoomed state's districts filled with results. */
function districtsFilled() {
  return !!zoomState && view === "house" && style === "map" && !!DATA.geo.district_lines[zoomState];
}

/** House view, zoomed into a state, geographic styles: show its 2026 districts.
 *  Map style fills each district with its own result (clickable, like a seat);
 *  Population style draws the district borders over the dots. */
function drawDistricts() {
  const layer = document.getElementById("district-layer");
  if (!layer) return;
  layer.replaceChildren();
  const top = document.getElementById("outline-layer");
  top?.replaceChildren();
  drawLegend();
  if (!zoomState) return;
  const geo = DATA.geo, races = DATA.results.races;
  // Population style: the zoomed state's own outline, plus (House) its district borders,
  // in the same heavy cased line, on the top layer so county lines never cover them.
  // (The district file only has the borders between districts, so without the outline
  // the outer edge of the edge districts would be missing.)
  const heavy = (d) => {
    el("path", { class: "district-casing", d }, top);
    el("path", { class: "district-lines", d }, top);
  };
  if (style === "dots" && top) {
    const outline = geo.states.find((s) => s.state === zoomState);
    if (view === "house" && geo.district_lines[zoomState]) heavy(geo.district_lines[zoomState]);
    if (outline) heavy(outline.path);
  }
  if (view !== "house") { drawCounties(layer); return; }
  if (style === "dots") return;
  const keys = Object.keys(geo.district_paths).filter((k) => k.startsWith(zoomState + "-"));
  for (const id of keys) {
    const race = { key: `H-${id}`, ...races[`H-${id}`] };
    const item = { id, state: zoomState, race };
    const g = el("g", {
      class: "seat district" + (flipsOnly && !race.flip ? " dim" : ""),
      tabindex: "0", role: "button", "aria-label": describe(item).plain,
    }, layer);
    g.dataset.id = id;
    el("path", { class: "shape", d: geo.district_paths[id], fill: fillFor(race) }, g);
    if (race.flip) el("path", { class: "hatch", d: geo.district_paths[id], fill: "url(#flip-hatch)" }, g);
  }
}

/** Senate or governor tab, zoomed in, Map style: fill each county with its margin. */
function drawCounties(layer) {
  const key = countyRace();
  if (!key || style !== "map") return;
  const votes = DATA.results.counties[key];
  for (const [fips, v] of Object.entries(votes)) {
    const shape = DATA.county_shapes && DATA.county_shapes[fips];
    if (!shape) continue;
    const g = el("g", { class: "seat county", tabindex: "0", role: "button", "aria-label": describeCounty(fips, key).plain }, layer);
    g.dataset.id = fips;
    g.dataset.state = zoomState;
    el("path", { class: "shape", d: shape[1], fill: marginFill(v) }, g);
  }
}

/** Tooltip for one county: shares, margin and total votes. */
function describeCounty(fips, key) {
  const [d, r, t] = DATA.results.counties[key][fips];
  const name = DATA.county_shapes[fips][0];
  const kind = Number(fips.slice(2)) >= 500 ? " (city)" : zoomState === "LA" ? " Parish" : "";
  const title = `${name}${kind}, ${STATE_NAMES[zoomState]}`;
  const pct = (n) => (t ? ((n / t) * 100).toFixed(1) : "0") + "%";
  const label = marginLabel([d, r, t]);
  return {
    plain: `${title}: Democrat ${pct(d)}, Republican ${pct(r)}, margin ${label}, ${t.toLocaleString()} votes counted.`,
    html: `<h3>${esc(title)}</h3><span class="call"><span class="dem">D ${pct(d)}</span> · <span class="rep">R ${pct(r)}</span> · ${label}</span>` +
      `<div class="meta">${t.toLocaleString()} votes counted (unofficial)</div>`,
  };
}

/** Note shown with the zoomed House view about where the district lines come from. */
function districtNote() {
  if (!zoomState || view !== "house" || style === "cartogram") return "";
  if (DATA.geo.districts_not_current.includes(zoomState))
    return `<strong>${STATE_NAMES[zoomState]}'s 2026 district lines aren't available,</strong> because the state redrew its map after the Census Bureau's latest district file, so the state is shown as a whole.`;
  if (!DATA.geo.district_lines[zoomState]) return ""; // one at-large seat: the state is the district
  return style === "dots"
    ? "District borders from the Census Bureau (2026 lines). Dots keep the state's color: they're spread across each county, so which district a dot falls in isn't reliable."
    : "Each district is colored by its own result. District lines: Census Bureau, 2026.";
}

/** The "county results aren't available" note shows whenever county lines do. */
function updateCountyNote() {
  const show = !!zoomState && style !== "cartogram";
  const note = document.getElementById("county-note");
  note.hidden = !show;
  if (!show) return;
  const dn = districtNote();
  const key = countyRace();
  let counties;
  if (key) {
    const src = (DATA.results.county_sources[key] || []).find((l) => /Snapshot/.test(l)) || "";
    const when = (src.match(/read ([\d-]+ [\d:]+ UTC)/) || [])[1];
    counties = `<strong>County results are unofficial</strong> and change as counting continues: vote counts as listed on Wikipedia's race page, which copies them from state election offices${when ? ` (read ${when})` : ""}. ` +
      "Margin is the Democratic minus Republican share of all votes.";
  } else if (districtsFilled()) {
    counties = "";
  } else {
    counties = "County lines show borders only. <strong>How each county voted isn't available yet:</strong> states are still counting, and county results are published as each state finishes.";
  }
  note.innerHTML = [dn, counties].filter(Boolean).join("<br>");
}

/** Fade seats outside the zoomed state (none when zoomed out). */
function applyFocus() {
  const houseHexes = style === "cartogram" && view === "house";
  for (const g of document.querySelectorAll("#map .seat")) {
    g.classList.toggle("unfocused", !!zoomState && seatState(g) !== zoomState);
    if (houseHexes) g.setAttribute("tabindex", zoomState && seatState(g) === zoomState ? "0" : "-1");
  }
}

/** After the map is redrawn (new tab, style or filter), put the zoom back instantly. */
function restoreZoom() {
  document.getElementById("zoom-out").hidden = !zoomState;
  if (!zoomState) { document.getElementById("map").style.setProperty("--z", "1"); updateCountyNote(); return; }
  applyFocus();
  setViewBox(frameFor(zoomState));
  finishZoom();
}

/* ------------------------------------------------------------------ pan and zoom by hand */
// Drag (mouse, or one finger once zoomed in), pinch (two fingers or a trackpad),
// Ctrl/⌘ + scroll wheel, and the + / − buttons. A plain scroll wheel and a
// one-finger swipe at the country view still scroll the page, so the map never
// traps someone who is just scrolling past it.

const MAX_ZOOM = 24;          // closest view: 1/24 of the country's width
let lastDragEnd = -1e9;       // when the last drag or pinch ended (to ignore its click)
let settleTimer = 0;

const getVB = () => document.getElementById("map").getAttribute("viewBox").split(/\s+/).map(Number);
function isZoomedIn() { return getVB()[2] < BASE_VB[2] * 0.98; }

/** Keep a frame inside sensible limits: not closer than MAX_ZOOM, not wider than the
 *  country, and its centre over the map. Keeps the frame's proportions. */
function clampVB([x, y, w, h]) {
  const [bx, by, W, H] = BASE_VB;
  const aspect = w / h;
  w = Math.min(Math.max(w, W / MAX_ZOOM), W); h = w / aspect;
  if (h > H) { h = H; w = h * aspect; }
  const cx = Math.min(Math.max(x + w / 2, bx), bx + W), cy = Math.min(Math.max(y + h / 2, by), by + H);
  return [cx - w / 2, cy - h / 2, w, h];
}

/** The map point under a screen point. */
function mapPoint(clientX, clientY) {
  const r = document.getElementById("map").getBoundingClientRect(), [x, y, w, h] = getVB();
  return [x + ((clientX - r.left) / r.width) * w, y + ((clientY - r.top) / r.height) * h];
}

/** Zoom by `factor` (2 = twice as close) keeping the point under (clientX, clientY) still. */
function zoomAround(clientX, clientY, factor) {
  const [x, y, w, h] = getVB(), [u, v] = mapPoint(clientX, clientY);
  setViewBox(clampVB([u - (u - x) / factor, v - (v - y) / factor, w / factor, h / factor]));
}

/** Move the frame by a screen distance. */
function panBy(dxPx, dyPx) {
  const r = document.getElementById("map").getBoundingClientRect(), [x, y, w, h] = getVB();
  setViewBox(clampVB([x - (dxPx / r.width) * w, y - (dyPx / r.height) * h, w, h]));
}

/** After a gesture: redraw dots and county lines for the new scale, update the buttons. */
function settle() {
  clearTimeout(settleTimer);
  settleTimer = setTimeout(() => {
    finishZoom();
    document.getElementById("zoom-out").hidden = !(zoomState || isZoomedIn());
  }, 120);
}

/** Brief hint when someone scrolls over the map without Ctrl/⌘. */
let hintTimer = 0;
function wheelHint() {
  const el = document.getElementById("wheel-hint");
  el.hidden = false; clearTimeout(hintTimer);
  hintTimer = setTimeout(() => { el.hidden = true; }, 1600);
}

function wirePanZoom() {
  const svg = document.getElementById("map");

  // Mouse: drag to pan (once zoomed in); Ctrl/⌘ + wheel or trackpad pinch to zoom.
  let drag = null;
  svg.addEventListener("pointerdown", (e) => {
    if (e.pointerType !== "mouse" || e.button !== 0) return;
    drag = { x: e.clientX, y: e.clientY, moved: false, id: e.pointerId };
  });
  svg.addEventListener("pointermove", (e) => {
    if (!drag || e.pointerId !== drag.id) return;
    const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
    if (!drag.moved && Math.hypot(dx, dy) < 5) return;
    if (!isZoomedIn()) return;            // nothing to pan at the country view
    if (!drag.moved) { drag.moved = true; svg.setPointerCapture(e.pointerId); svg.classList.add("dragging"); hideTip(); }
    panBy(dx, dy); drag.x = e.clientX; drag.y = e.clientY;
  });
  const endDrag = () => {
    if (drag && drag.moved) { lastDragEnd = performance.now(); svg.classList.remove("dragging"); settle(); }
    drag = null;
  };
  svg.addEventListener("pointerup", endDrag);
  svg.addEventListener("pointercancel", endDrag);
  svg.addEventListener("wheel", (e) => {
    if (!(e.ctrlKey || e.metaKey)) { wheelHint(); return; } // plain wheel scrolls the page
    e.preventDefault();
    hideTip();
    zoomAround(e.clientX, e.clientY, Math.exp(-Math.max(-60, Math.min(60, e.deltaY)) * 0.01));
    settle();
  }, { passive: false });

  // Touch: two fingers pinch (and move); one finger pans once zoomed in.
  let touch = null;
  const centre = (t) => [(t[0].clientX + t[1].clientX) / 2, (t[0].clientY + t[1].clientY) / 2];
  const spread = (t) => Math.hypot(t[0].clientX - t[1].clientX, t[0].clientY - t[1].clientY);
  svg.addEventListener("touchstart", (e) => {
    if (e.touches.length === 2) {
      e.preventDefault();                 // our pinch, not the browser's page zoom
      touch = { pinch: true, c: centre(e.touches), d: spread(e.touches), moved: true };
      hideTip();
    } else if (e.touches.length === 1) {
      touch = { pinch: false, x: e.touches[0].clientX, y: e.touches[0].clientY, moved: false };
    }
  }, { passive: false });
  svg.addEventListener("touchmove", (e) => {
    if (!touch) return;
    if (touch.pinch && e.touches.length === 2) {
      e.preventDefault();
      const c = centre(e.touches), d = spread(e.touches);
      panBy(c[0] - touch.c[0], c[1] - touch.c[1]);
      zoomAround(c[0], c[1], d / touch.d);
      touch.c = c; touch.d = d;
    } else if (!touch.pinch && e.touches.length === 1 && isZoomedIn()) {
      const t = e.touches[0], dx = t.clientX - touch.x, dy = t.clientY - touch.y;
      if (!touch.moved && Math.hypot(dx, dy) < 6) return;
      e.preventDefault();                 // zoomed in: one finger moves the map, not the page
      if (!touch.moved) { touch.moved = true; hideTip(); }
      panBy(dx, dy); touch.x = t.clientX; touch.y = t.clientY;
    }
  }, { passive: false });
  svg.addEventListener("touchend", (e) => {
    if (touch && touch.moved) { lastDragEnd = performance.now(); settle(); }
    if (e.touches.length === 0) touch = null;
    else if (e.touches.length === 1) touch = { pinch: false, x: e.touches[0].clientX, y: e.touches[0].clientY, moved: true };
  });
  // Safari's own pinch-to-zoom-the-page gesture, while the fingers are on the map.
  svg.addEventListener("gesturestart", (e) => e.preventDefault());

  // + and − buttons (also the keyboard way to zoom).
  const step = (factor) => {
    const r = svg.getBoundingClientRect(), [x, y, w, h] = getVB();
    if (factor < 1 && w / factor >= BASE_VB[2] * 0.98) { zoomOut(); return; }
    const cx = r.left + r.width / 2, cy = r.top + r.height / 2, [u, v] = mapPoint(cx, cy);
    hideTip();
    animateTo(clampVB([u - (u - x) / factor, v - (v - y) / factor, w / factor, h / factor]), settle);
  };
  document.getElementById("zoom-in-btn").addEventListener("click", () => step(1.6));
  document.getElementById("zoom-out-btn").addEventListener("click", () => step(1 / 1.6));
}

/* ------------------------------------------------------------------ state card */

/** One state's results for all three offices, shown under the map. */
function showState(st, after) {
  const races = DATA.results.races;
  const card = document.getElementById("state-card");
  const line = (r, noRace) => {
    if (!r) return `<span class="muted">${noRace}</span>`;
    if (!r.called) return `<span class="muted">${r.status === "runoff" ? runoffText(r) : "Not yet called"}</span>`;
    return `<span class="${r.winner === "D" ? "dem" : r.winner === "R" ? "rep" : ""}"><strong>${esc(r.winner_name || "")}</strong> (${r.winner}) won</span>` +
      (r.flip ? ` <span class="pill n">changed party</span>` : "");
  };
  const g = races[`G-${st}`], s = races[`S-${st}`];
  const govHeld = DATA.results.context.governors.not_up[st];
  const house = Object.entries(races).filter(([k]) => k.startsWith(`H-${st}-`)).map(([k, r]) => ({ k, ...r }));
  const n = { D: 0, R: 0, u: 0 };
  for (const r of house) r.called ? (n[r.winner] = (n[r.winner] || 0) + 1) : n.u++;
  const districtRow = (r) => {
    const num = Number(r.k.slice(5));
    return `<li><span class="what">${num ? ordinal(num) : "At-large"}</span>${line(r)}</li>`;
  };
  card.innerHTML = `
    <div class="state-head"><h2>${STATE_NAMES[st]}</h2>
      <button type="button" class="close" id="state-close" aria-label="Close ${STATE_NAMES[st]} results">×</button></div>
    <ul class="rows">
      <li><span class="what">Governor</span>${line(g, `No race this year${govHeld ? ` · current governor: ${PARTY[govHeld]}` : ""}`)}</li>
      <li><span class="what">Senate</span>${line(s, "No race this year")}</li>
      <li><span class="what">House (${house.length} seat${house.length > 1 ? "s" : ""})</span>
        <span>${[n.D && `<span class="dem">${n.D} D</span>`, n.R && `<span class="rep">${n.R} R</span>`, n.u && `${n.u} not yet called`].filter(Boolean).join(" · ")}</span></li>
      ${turnoutLine(st)}
    </ul>
    ${house.length > 1 ? `<details class="more"><summary>Show all ${house.length} districts</summary><ul class="rows">${house.map(districtRow).join("")}</ul></details>` : ""}`;
  card.hidden = false;
  document.getElementById("state-close").addEventListener("click", zoomOut);
  // Zoom the map to this state, then run `after` (e.g. open a tooltip on the new spot).
  if (st !== zoomState) zoomTo(st, after);
  else after?.();
}

/* ------------------------------------------------------------------ search */

/** Every race and state, searchable by place or by winner's name. */
function buildSearchIndex() {
  const entries = [];
  for (const [key, r] of Object.entries(DATA.results.races)) {
    const v = { H: "house", S: "senate", G: "governors" }[r.office];
    const id = r.office === "H" ? key.slice(2) : r.state;
    const title = raceTitle({ id, state: r.state, race: r }, v) + (r.office === "H" ? " (House)" : "");
    entries.push({ label: title, view: v, id, state: r.state });
    if (r.winner_name) entries.push({ label: `${r.winner_name}, ${title}`, view: v, id, state: r.state });
  }
  for (const [st, name] of Object.entries(STATE_NAMES)) entries.push({ label: `${name}: all results`, view: null, id: st, state: st });
  document.getElementById("find-list").innerHTML = entries.map((e) => `<option value="${esc(e.label)}"></option>`).join("");
  return entries;
}

function findRace(text, entries) {
  const q = text.trim().toLowerCase().replace(/\s+/g, " ");
  if (!q) return null;
  return entries.find((e) => e.label.toLowerCase() === q) ||
    // Short codes like "WA-3" or "wa 03"
    (() => {
      const m = q.match(/^([a-z]{2})[\s-]?(\d{1,2})$/);
      if (!m) return null;
      const id = `${m[1].toUpperCase()}-${m[2].padStart(2, "0")}`;
      return entries.find((e) => e.view === "house" && e.id === id);
    })() ||
    entries.find((e) => e.label.toLowerCase().includes(q));
}

function goTo(entry) {
  const msg = document.getElementById("find-msg");
  if (!entry) { msg.textContent = "No match. Try a state name, a district like “WA-3”, or a candidate's last name."; return; }
  msg.textContent = "";
  if (entry.view && entry.view !== view) { view = entry.view; writeHash(); render(); }
  document.getElementById("map").scrollIntoView({ block: "center" });
  if (!entry.view) { showState(entry.state); return; }
  // In the map styles the House is drawn by state, so point at the state.
  const target = style === "cartogram" || view !== "house" ? entry.id : entry.state;
  showState(entry.state, () => {
    // A zoomed House map draws the districts themselves: point at the district.
    const seat = document.querySelector(`.seat.district[data-id="${entry.id}"]`) ||
      document.querySelector(`.seat[data-id="${target}"]`);
    if (seat) tipAtSeat(seat);
  });
}

function wireSearch() {
  const entries = buildSearchIndex();
  const input = document.getElementById("find");
  // Picking a suggestion fills the box with an exact label: go there at once.
  input.addEventListener("input", () => {
    const exact = entries.find((e) => e.label === input.value);
    if (exact) { goTo(exact); input.blur(); }
  });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); goTo(findRace(input.value, entries)); input.blur(); }
  });
}

/* ------------------------------------------------------------------ controls */

function render() {
  for (const b of document.querySelectorAll("[data-view]")) b.setAttribute("aria-pressed", String(b.dataset.view === view));
  for (const b of document.querySelectorAll("[data-style]")) b.setAttribute("aria-pressed", String(b.dataset.style === style));
  drawTally();
  drawChanges();
  drawMap();
  drawPanels();
  drawHistory();
  drawTurnout();
  drawTable();
  hideTip();
}

// Links look like #senate (cartogram) or #senate-map / #house-dots.
function readHash() {
  const [v, s] = location.hash.slice(1).split("-");
  if (VIEWS[v]) view = v;
  style = STYLES[s] ? s : "cartogram";
}

function writeHash() {
  history.replaceState(null, "", `#${view}${style === "cartogram" ? "" : `-${style}`}`);
}

async function main() {
  if (!document.documentElement.lang) document.documentElement.lang = "en";
  DATA = await loadData();
  readHash();
  document.querySelectorAll("[data-view]").forEach((b) =>
    b.addEventListener("click", () => { view = b.dataset.view; writeHash(); render(); }));
  document.querySelectorAll("[data-style]").forEach((b) =>
    b.addEventListener("click", () => { style = b.dataset.style; writeHash(); render(); }));
  document.getElementById("show-flips").addEventListener("click", () => setFlipsOnly(!flipsOnly));
  document.getElementById("zoom-out").addEventListener("click", zoomOut);
  wireSearch();
  addEventListener("hashchange", () => { readHash(); render(); });

  const when = new Date(DATA.results.updated);
  const whenText = when.toLocaleString(undefined, {
    month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZoneName: "short",
  });
  document.querySelectorAll("[data-updated]").forEach((el) => { el.textContent = whenText; });
  wireTooltip();
  wirePanZoom();
  drawFinalBanner();
  render();
}

main();
