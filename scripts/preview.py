"""Make the link-preview image (dist/preview.png, 1200 x 630) from the built page.

    python scripts/preview.py            # after scripts/bundle.py

Messaging apps and social sites show this image when someone shares the link
(it is referenced by the og:image tag, which bundle.py adds when it is given the
site's public address with --site-url). It is a screenshot of the real page,
House cartogram with the seat tally, so it always matches the current results.
"""

from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "dist" / "index.html"
OUT = ROOT / "dist" / "preview.png"

# Keep the title, the tally and the map; hide everything a preview has no room for.
TRIM = """
  .lede, .unofficial, .final-banner, .controls, .tick, .map-hint, .legend, .zoom-out,
  .summary, .state-card, .panels, .background, details, footer { display: none !important; }
  body { padding: 28px 44px !important; }
  .wrap { gap: 14px !important; max-width: none !important; }
  figure { padding: 6px !important; width: 690px !important; margin: 0 auto !important; }
"""


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1200, "height": 630}, device_scale_factor=1, color_scheme="light")
        page.goto(PAGE.as_uri() + "#house")
        page.add_style_tag(content=TRIM)
        page.wait_for_timeout(500)
        page.screenshot(path=str(OUT), clip={"x": 0, "y": 0, "width": 1200, "height": 630})
        browser.close()
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
