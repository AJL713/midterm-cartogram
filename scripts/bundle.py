"""Bundle the web page into one self-contained file: dist/index.html.

Why: browsers refuse to fetch() local JSON files when you open a page by
double-clicking it, so the dev version in web/ needs a local server. The
bundled file carries its data inside, so it opens anywhere and can be
published as a single page.

Run:  python scripts/bundle.py
      python scripts/bundle.py --site-url https://example.github.io/midterm-cartogram/
The second form is for public hosting: it adds the link-preview image, the page's
address and its canonical link, which need the site's full address. Make the image
first with  python scripts/preview.py  (it is written to dist/preview.png).

      python scripts/bundle.py --pages
builds everything for the public GitHub Pages site in docs/: dist/index.html as
usual, the preview image, and docs/index.html (a complete HTML document with the
public address, a tab icon and the preview tags). Commit docs/ to publish it.
"""

import argparse
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGES_URL = "https://ajl713.github.io/midterm-cartogram/"  # the public GitHub Pages address
# Tab icon for the public site: a small hexagon (the claude.ai version sets its own).
FAVICON = ('<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns=%27http://www.w3.org/2000/svg%27 viewBox=%270 0 32 32%27%3E'
           '%3Cpath d=%27M16 2l12 7v14l-12 7-12-7V9z%27 fill=%27%232c5cb0%27/%3E%3Cpath d=%27M16 2l12 7v14l-12 7z%27 fill=%27%23c03a36%27/%3E%3C/svg%3E">')


def county_shapes(county_results: dict) -> dict:
    """County outlines {fips: [name, svg path]}, only for states that have county
    results, so the page carries no county shapes until there is data to show."""
    if not county_results:
        return {}
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    import build_geo
    import counties

    wanted = {race.split("-")[1] for race in county_results}
    topo = json.loads(counties.county_source().read_text())
    arcs = build_geo.decode_arcs(topo)
    out = {}
    for g in topo["objects"]["counties"]["geometries"]:
        if counties.FIPS_STATE.get(g["id"][:2]) in wanted:
            shape = build_geo.to_shape(g, arcs)
            if shape is not None:
                out[g["id"]] = [g["properties"]["name"], build_geo.svg_path(shape.simplify(0.2))]
    return out


def site_tags(site_url: str) -> str:
    """Tags that need the public address: preview image, page address, canonical link."""
    if not site_url:
        return ""
    base = site_url.rstrip("/") + "/"
    return "\n".join([
        f'<meta property="og:url" content="{base}">',
        f'<meta property="og:image" content="{base}preview.png">',
        '<meta property="og:image:width" content="1200">',
        '<meta property="og:image:height" content="630">',
        '<meta property="og:image:alt" content="The seat tally and a hexagon map of the 2026 House results.">',
        f'<link rel="canonical" href="{base}">',
    ])


def main() -> None:
    ap = argparse.ArgumentParser(description="Bundle web/ and data/ into dist/index.html.")
    ap.add_argument("--site-url", default="", help="public address of the hosted page (adds link-preview tags)")
    ap.add_argument("--pages", action="store_true", help="also build the public GitHub Pages site in docs/")
    ap.add_argument("--experimental", action="store_true", help="mark the build as the experiment branch (banner; written to dist/experimental.html)")
    args = ap.parse_args()
    web, data = ROOT / "web", ROOT / "data"
    html = (web / "index.html").read_text()
    css = (web / "style.css").read_text()
    js = (web / "app.js").read_text()
    payload = {
        "hex": json.loads((data / "hex.json").read_text()),
        "tiles": json.loads((data / "tiles.json").read_text()),
        "results": json.loads((data / "results.json").read_text()),
        "geo": json.loads((data / "geo.json").read_text()),
    }
    payload["county_shapes"] = county_shapes(payload["results"].get("counties", {}))
    if args.experimental and (data / "layouts.json").exists():  # EXPERIMENT: layout switcher
        payload["layouts"] = json.loads((data / "layouts.json").read_text())
    data_js = "window.CARTO = " + json.dumps(payload, separators=(",", ":"), ensure_ascii=False) + ";"
    # "</" inside a script would end it early; escape it.
    data_js = data_js.replace("</", "<\\/")

    html = html.replace('<link rel="stylesheet" href="style.css">\n<!--INLINE_CSS-->', f"<style>\n{css}</style>")
    html = html.replace('<script src="app.js"></script>\n<!--INLINE_JS-->',
                        f"<script>{data_js}</script>\n<script>\n{js}</script>")
    assert "style.css" not in html and 'src="app.js"' not in html, "placeholders not replaced"

    if args.experimental:
        # The experiment branch's preview: a banner so it can't be mistaken for the real page.
        banner = ('<p class="unofficial" style="background:#fff3c4;color:#5a4300;border-radius:6px;padding:6px 10px">'
                  "Experimental version. The real page is at "
                  f'<a style="color:inherit" href="{PAGES_URL}">{PAGES_URL.replace("https://", "")}</a></p>')
        html = html.replace('<main class="wrap">', '<main class="wrap">' + banner, 1)
    out = ROOT / "dist" / ("experimental.html" if args.experimental else "index.html")
    out.parent.mkdir(exist_ok=True)
    out.write_text(html.replace("<!--SITE_TAGS-->", site_tags(args.site_url)))
    print(f"wrote {out} ({out.stat().st_size // 1024} KB)")
    if args.pages:
        build_pages(html)


def build_pages(html: str) -> None:
    """docs/: the public site. A full document (the claude.ai host adds these parts
    itself, a plain web host does not), plus the preview image it points to."""
    import preview  # scripts/preview.py: screenshots dist/index.html
    preview.main()
    docs = ROOT / "docs"
    docs.mkdir(exist_ok=True)
    body = html.replace("<!--SITE_TAGS-->", site_tags(PAGES_URL))
    body = body.replace('<meta charset="utf-8">', '<meta charset="utf-8">\n' + FAVICON, 1)  # charset stays first
    page = '<!doctype html>\n<html lang="en">\n' + body + "\n</html>\n"
    (docs / "index.html").write_text(page)
    shutil.copyfile(ROOT / "dist" / "preview.png", docs / "preview.png")
    (docs / ".nojekyll").write_text("")  # serve the files as they are (no Jekyll processing)
    print(f"wrote docs/index.html ({len(page) // 1024} KB) and docs/preview.png")


if __name__ == "__main__":
    main()
