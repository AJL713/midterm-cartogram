// Run in the browser on one of the three Wikipedia results pages (House,
// Senate or gubernatorial). Returns a text block: a summary line, then one
// snapshot line per race in the data/raw/*.txt format:
//   key|winner party (- = not called)|flip (1 = party gain)|winner|status|others|lean|held by before
// Same rules as scripts/scrape.py: a winner is the single bold name in the
// Candidates cell; "gain" in the Status cell marks a flip.
(() => {
  const AB = {Alabama:'AL',Alaska:'AK',Arizona:'AZ',Arkansas:'AR',California:'CA',Colorado:'CO',Connecticut:'CT',Delaware:'DE',Florida:'FL',Georgia:'GA',Hawaii:'HI',Idaho:'ID',Illinois:'IL',Indiana:'IN',Iowa:'IA',Kansas:'KS',Kentucky:'KY',Louisiana:'LA',Maine:'ME',Maryland:'MD',Massachusetts:'MA',Michigan:'MI',Minnesota:'MN',Mississippi:'MS',Missouri:'MO',Montana:'MT',Nebraska:'NE',Nevada:'NV','New Hampshire':'NH','New Jersey':'NJ','New Mexico':'NM','New York':'NY','North Carolina':'NC','North Dakota':'ND',Ohio:'OH',Oklahoma:'OK',Oregon:'OR',Pennsylvania:'PA','Rhode Island':'RI','South Carolina':'SC','South Dakota':'SD',Tennessee:'TN',Texas:'TX',Utah:'UT',Vermont:'VT',Virginia:'VA',Washington:'WA','West Virginia':'WV',Wisconsin:'WI',Wyoming:'WY'};
  const P = (t) => /Democratic|DFL|Farmer/.test(t) ? 'D' : /Republican/.test(t) ? 'R' : /Independent/.test(t) ? 'I' : /Libertarian/.test(t) ? 'L' : 'O';
  const clean = (s) => s.replace(/\[\w+\]/g, '').replace(/\s+/g, ' ').trim();
  const office = /House_of_Rep/.test(location.pathname) ? 'H' : /Senate/.test(location.pathname) ? 'S' : 'G';

  // The section heading a table sits under.
  const headingOf = (t) => {
    let e = t;
    for (let k = 0; k < 60 && e; k++) {
      e = e.previousElementSibling || e.parentElement;
      if (e && /mw-heading|^H[2-4]$/.test(e.className + ' ' + e.tagName)) return clean(e.innerText).replace(/edit$/, '').trim();
    }
    return '';
  };
  const tables = [...document.querySelectorAll('table.wikitable')].filter((t) => {
    const h = headingOf(t);
    if (office === 'H') return h in AB;                                  // one table per state
    if (office === 'S') return /^Elections leading to the next Congress|^Special elections during the preceding Congress/.test(h);
    return /Candidates/.test(t.rows[0]?.innerText) && t.rows.length > 30; // one big governors table
  });

  const out = [], seen = new Set(), skipped = [];
  for (const t of tables) {
    for (const r of [...t.rows]) {
      const c = [...r.cells];
      if (c.length < 3 || r.querySelector('th:only-child')) continue;
      const loc = clean(c[0].innerText);
      let key;
      if (office === 'H') {
        const m = loc.match(/^([A-Za-z ]+?) (\d+|at-large)$/i);
        if (!m || !AB[m[1]]) { if (c[0].tagName === 'TD') skipped.push(loc.slice(0, 30)); continue; }
        key = `H-${AB[m[1]]}-${/at-large/i.test(m[2]) ? '00' : m[2].padStart(2, '0')}`;
      } else {
        const st = AB[loc.replace(/\s*\(.*$/, '')];
        if (!st) continue;
        key = `${office}-${st}`;
      }
      if (seen.has(key)) continue;
      seen.add(key);
      const status = clean(c[c.length - 2].innerText);
      const cell = c[c.length - 1];
      const cands = [...cell.querySelectorAll('li')].map((li) => {
        const tx = clean(li.innerText).replace(/^[▌\s✓]+/, '');
        // Name = text before the first " (", party = whatever the parentheses say
        // (handles nested labels like "U.S. Taxpayers (Michigan)").
        const paren = tx.indexOf(' (');
        return { n: (paren > 0 ? tx.slice(0, paren) : tx).trim(), p: P(paren > 0 ? tx.slice(paren) : ''), w: !!li.querySelector('b') };
      }).filter((x) => x.n && !/:$/.test(x.n));        // drop labels like "General election:"
      const w = cands.filter((x) => x.w);
      const won = w.length === 1;
      const st = won ? 'called' : /Runoff:/.test(cell.innerText) ? 'runoff' : 'uncalled';
      const others = office === 'H' ? '' : cands.filter((x) => !(won && x === w[0])).map((x) => `${x.n}/${x.p}`).join(';');
      // Context columns: partisan lean (Cook PVI, e.g. "R+5") and the party that
      // held the seat before ("N" for a seat created by redistricting, "V" vacant).
      const txt = c.map((x) => clean(x.innerText));
      const pvi = txt.find((s) => /^(?:[DR]\+\d+|EVEN)$/.test(s)) || '';
      let held = '';
      for (let i = 1; i < c.length - 2; i++) {
        const s = txt[i];
        if (/new seat/i.test(s)) { held = 'N'; break; }
        if (/^Vacant/i.test(s)) { held = 'V'; break; }
        if (s.length < 40 && /^(Democratic|Republican|Independent|Libertarian|DFL)\b/.test(s)) { held = P(s); break; }
      }
      out.push([key, won ? w[0].p : '-', won && /\bgain\b/i.test(status) ? 1 : 0, won ? w[0].n : '', st, others, pvi, held].join('|'));
    }
  }
  const count = (p) => out.filter((l) => l.split('|')[1] === p).length;
  const edited = document.querySelector('#footer-info-lastmod')?.innerText.match(/(\d+ \w+ \d{4}), at (\d\d:\d\d)/);
  return `#SUMMARY office=${office} races=${out.length} D=${count('D')} R=${count('R')} uncalled=${count('-')} ` +
    `edited=${edited ? edited[1] + ' ' + edited[2] + ' UTC' : '?'} skipped=${JSON.stringify(skipped)}\n` + out.join('\n');
})()
