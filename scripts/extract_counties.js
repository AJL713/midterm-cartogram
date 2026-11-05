// County results for Senate and governor races, read from Wikipedia race pages.
//
// Paste this whole file into a browser tab on any en.wikipedia.org page. It
// starts a background job and returns at once; read the result afterwards with
//   window.__countyJob.done ? window.__countyJob.output : `working: ${window.__countyJob.finished}/${window.__countyJob.total}`
//
// The job fetches each race page (4 at a time, through Wikipedia's own API, so
// no page navigation is needed) and, for every page that has a county table,
// adds a block to the output:
//   =====S-TX|<page title>|revision <id>|rows=<n> D=<sum> R=<sum> total=<sum>
//   county name|Democratic votes|Republican votes|total votes
// Pages without a county table yet are listed on one "#NONE" line.
//
// Table rules:
//  * The first table whose header starts with "County" (or "Parish" /
//    "Locality") and has a "Margin" column, inside the "General election"
//    section (or the page's main "Results" section). Primary and runoff tables
//    are never used.
//  * Each candidate column holds "# | %"; votes are summed by party (so two
//    Republicans count together). The last column is the total.
//  * Only vote counts are copied; shares and margins are worked out later.
(() => {
  const RACES = {
    "G-AK": "2026_Alaska_gubernatorial_election", "G-AL": "2026_Alabama_gubernatorial_election",
    "G-AR": "2026_Arkansas_gubernatorial_election", "G-AZ": "2026_Arizona_gubernatorial_election",
    "G-CA": "2026_California_gubernatorial_election", "G-CO": "2026_Colorado_gubernatorial_election",
    "G-CT": "2026_Connecticut_gubernatorial_election", "G-FL": "2026_Florida_gubernatorial_election",
    "G-GA": "2026_Georgia_gubernatorial_election", "G-HI": "2026_Hawaii_gubernatorial_election",
    "G-IA": "2026_Iowa_gubernatorial_election", "G-ID": "2026_Idaho_gubernatorial_election",
    "G-IL": "2026_Illinois_gubernatorial_election", "G-KS": "2026_Kansas_gubernatorial_election",
    "G-MA": "2026_Massachusetts_gubernatorial_election", "G-MD": "2026_Maryland_gubernatorial_election",
    "G-ME": "2026_Maine_gubernatorial_election", "G-MI": "2026_Michigan_gubernatorial_election",
    "G-MN": "2026_Minnesota_gubernatorial_election", "G-NE": "2026_Nebraska_gubernatorial_election",
    "G-NH": "2026_New_Hampshire_gubernatorial_election", "G-NM": "2026_New_Mexico_gubernatorial_election",
    "G-NV": "2026_Nevada_gubernatorial_election", "G-NY": "2026_New_York_gubernatorial_election",
    "G-OH": "2026_Ohio_gubernatorial_election", "G-OK": "2026_Oklahoma_gubernatorial_election",
    "G-OR": "2026_Oregon_gubernatorial_election", "G-PA": "2026_Pennsylvania_gubernatorial_election",
    "G-RI": "2026_Rhode_Island_gubernatorial_election", "G-SC": "2026_South_Carolina_gubernatorial_election",
    "G-SD": "2026_South_Dakota_gubernatorial_election", "G-TN": "2026_Tennessee_gubernatorial_election",
    "G-TX": "2026_Texas_gubernatorial_election", "G-VT": "2026_Vermont_gubernatorial_election",
    "G-WI": "2026_Wisconsin_gubernatorial_election", "G-WY": "2026_Wyoming_gubernatorial_election",
    "S-AK": "2026_United_States_Senate_election_in_Alaska", "S-AL": "2026_United_States_Senate_election_in_Alabama",
    "S-AR": "2026_United_States_Senate_election_in_Arkansas", "S-CO": "2026_United_States_Senate_election_in_Colorado",
    "S-DE": "2026_United_States_Senate_election_in_Delaware", "S-FL": "2026_United_States_Senate_special_election_in_Florida",
    "S-GA": "2026_United_States_Senate_election_in_Georgia", "S-IA": "2026_United_States_Senate_election_in_Iowa",
    "S-ID": "2026_United_States_Senate_election_in_Idaho", "S-IL": "2026_United_States_Senate_election_in_Illinois",
    "S-KS": "2026_United_States_Senate_election_in_Kansas", "S-KY": "2026_United_States_Senate_election_in_Kentucky",
    "S-LA": "2026_United_States_Senate_election_in_Louisiana", "S-MA": "2026_United_States_Senate_election_in_Massachusetts",
    "S-ME": "2026_United_States_Senate_election_in_Maine", "S-MI": "2026_United_States_Senate_election_in_Michigan",
    "S-MN": "2026_United_States_Senate_election_in_Minnesota", "S-MS": "2026_United_States_Senate_election_in_Mississippi",
    "S-MT": "2026_United_States_Senate_election_in_Montana", "S-NC": "2026_United_States_Senate_election_in_North_Carolina",
    "S-NE": "2026_United_States_Senate_election_in_Nebraska", "S-NH": "2026_United_States_Senate_election_in_New_Hampshire",
    "S-NJ": "2026_United_States_Senate_election_in_New_Jersey", "S-NM": "2026_United_States_Senate_election_in_New_Mexico",
    "S-OH": "2026_United_States_Senate_special_election_in_Ohio", "S-OK": "2026_United_States_Senate_election_in_Oklahoma",
    "S-OR": "2026_United_States_Senate_election_in_Oregon", "S-RI": "2026_United_States_Senate_election_in_Rhode_Island",
    "S-SC": "2026_United_States_Senate_election_in_South_Carolina", "S-SD": "2026_United_States_Senate_election_in_South_Dakota",
    "S-TN": "2026_United_States_Senate_election_in_Tennessee", "S-TX": "2026_United_States_Senate_election_in_Texas",
    "S-VA": "2026_United_States_Senate_election_in_Virginia", "S-WV": "2026_United_States_Senate_election_in_West_Virginia",
    "S-WY": "2026_United_States_Senate_election_in_Wyoming",
  };

  const clean = (s) => (s || "").replace(/\[\w+\]/g, "").replace(/\s+/g, " ").trim();
  // Vote counts and totals are never negative: keep the digits only ("15,022" -> 15022).
  const num = (s) => Number(clean(s).replace(/\D/g, "")) || 0;
  const party = (t) => /Democratic|DFL/.test(t) ? "D" : /Republican/.test(t) ? "R" : "O";

  /** The section headings above each table, e.g. "General election > Results > By county". */
  const sectionOf = (doc) => {
    const where = new Map();
    let h2 = "", h3 = "", h4 = "";
    const walk = doc.createTreeWalker(doc.body, NodeFilter.SHOW_ELEMENT);
    for (let n = walk.nextNode(); n; n = walk.nextNode()) {
      if (n.tagName === "H2") { h2 = clean(n.textContent); h3 = h4 = ""; }
      else if (n.tagName === "H3") { h3 = clean(n.textContent); h4 = ""; }
      else if (n.tagName === "H4") h4 = clean(n.textContent);
      else if (n.tagName === "TABLE") where.set(n, [h2, h3, h4].join(" > "));
    }
    return where;
  };

  /** One page's November county table as lines "county|D|R|total", or null if it has none. */
  const extract = (doc) => {
    const where = sectionOf(doc);
    const table = [...doc.querySelectorAll("table.wikitable")].find((t) => {
      const head = t.rows[0] ? [...t.rows[0].cells].map((c) => clean(c.textContent)) : [];
      // Virginia says "Locality" (counties and independent cities), Louisiana "Parish".
      if (!/^(County|Parish|Locality)/i.test(head[0] || "") || !head.some((h) => /^Margin/i.test(h))) return false;
      // Only the November election: never a primary or a runoff table (California's
      // page shows its June primary by county long before the November one).
      const path = where.get(t) || "";
      return !/primary|runoff/i.test(path) && /general election|^results/i.test(path);
    });
    if (!table) return null;
    const head = [...table.rows[0].cells].map((c) => clean(c.textContent));
    const marginAt = head.findIndex((h) => /^Margin/i.test(h));
    const cands = head.slice(1, marginAt).map((h) => party(h));
    const rows = [];
    for (const r of [...table.rows].slice(1)) {
      const c = [...r.cells].map((x) => clean(x.textContent));
      if (!c[0] || c[0] === "#" || /^Totals?$/i.test(c[0])) continue;
      if (c.length !== 1 + cands.length * 2 + 2 + 1) continue; // county, 2 per candidate, margin #/%, total
      let D = 0, R = 0;
      cands.forEach((p, i) => { const v = num(c[1 + 2 * i]); if (p === "D") D += v; else if (p === "R") R += v; });
      rows.push([c[0], D, R, num(c[c.length - 1])].join("|"));
    }
    return rows;
  };

  const job = (window.__countyJob = { done: false, finished: 0, total: Object.keys(RACES).length, output: "" });
  (async () => {
    const blocks = [], none = [], errors = [];
    const entries = Object.entries(RACES);
    for (let i = 0; i < entries.length; i += 4) {
      await Promise.all(entries.slice(i, i + 4).map(async ([key, title]) => {
        try {
          const url = `/w/api.php?action=parse&page=${title}&prop=text|revid&formatversion=2&format=json`;
          const j = await (await fetch(url)).json();
          if (j.error) { errors.push(`${key}:${j.error.code}`); return; }
          const rows = extract(new DOMParser().parseFromString(j.parse.text, "text/html"));
          if (rows && rows.length) {
            // A check line, so a saved copy can be verified: row count and vote sums.
            const sum = (i) => rows.reduce((a, l) => a + Number(l.split("|")[i]), 0);
            blocks.push(`=====${key}|${title}|revision ${j.parse.revid}|rows=${rows.length} D=${sum(1)} R=${sum(2)} total=${sum(3)}\n${rows.join("\n")}`);
          }
          else none.push(key);
        } catch (e) {
          errors.push(`${key}:${e.message}`);
        } finally {
          job.finished++;
        }
      }));
    }
    job.output = `#NONE ${none.sort().join(" ")}\n#ERRORS ${errors.join(" ")}\n` + blocks.sort().join("\n");
    job.done = true;
  })();
  return `started: ${job.total} race pages`;
})()
