// Turnout of eligible voters, read from the UF Election Lab turnout page.
//
// Run in a browser tab on
//   https://election.lab.ufl.edu/2026-general-election-turnout/   (or the 2022 page)
// It returns one line per state (and "US" for the whole country):
//   state|turnout rate %|total ballots counted|voting-eligible population
// The first line is "#UPDATED <the page's own 'last updated' text, or blank>".
//
// Only the table whose header starts "State" and mentions "Voting-Eligible
// Population Turnout Rate" is read, so the page's map labels are ignored.
(() => {
  const NAMES = {
    "United States": "US", Alabama: "AL", Alaska: "AK", Arizona: "AZ", Arkansas: "AR", California: "CA",
    Colorado: "CO", Connecticut: "CT", Delaware: "DE", "District of Columbia": "DC", Florida: "FL",
    Georgia: "GA", Hawaii: "HI", Idaho: "ID", Illinois: "IL", Indiana: "IN", Iowa: "IA", Kansas: "KS",
    Kentucky: "KY", Louisiana: "LA", Maine: "ME", Maryland: "MD", Massachusetts: "MA", Michigan: "MI",
    Minnesota: "MN", Mississippi: "MS", Missouri: "MO", Montana: "MT", Nebraska: "NE", Nevada: "NV",
    "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY",
    "North Carolina": "NC", "North Dakota": "ND", Ohio: "OH", Oklahoma: "OK", Oregon: "OR",
    Pennsylvania: "PA", "Rhode Island": "RI", "South Carolina": "SC", "South Dakota": "SD",
    Tennessee: "TN", Texas: "TX", Utah: "UT", Vermont: "VT", Virginia: "VA", Washington: "WA",
    "West Virginia": "WV", Wisconsin: "WI", Wyoming: "WY",
  };
  const clean = (s) => (s || "").replace(/\s+/g, " ").trim();
  const num = (s) => Number(clean(s).replace(/[^\d.]/g, ""));
  const table = [...document.querySelectorAll("table")].find((t) => {
    const head = t.rows[0] ? clean(t.rows[0].textContent) : "";
    return /^State/.test(head) && /Turnout Rate/i.test(head);
  });
  if (!table) return "#NO TABLE";
  const out = [];
  for (const r of [...table.rows].slice(1)) {
    const c = [...r.cells].map((x) => clean(x.textContent));
    const st = NAMES[c[0]];
    if (st) out.push([st, num(c[1]), num(c[2]), num(c[3])].join("|"));
  }
  const updated = clean((document.body.innerText.match(/(Last updated [^\n]*|These estimates are [^\n.]*)/) || [""])[0]);
  return `#UPDATED ${updated}\n#ROWS ${out.length}\n` + out.join("\n");
})()
