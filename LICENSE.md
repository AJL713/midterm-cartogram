# Licenses

This project mixes its own code with data from several sources. Each part keeps
its own license.

## Code: MIT License

Applies to everything in `scripts/`, `web/` and `tests/`.

Copyright (c) 2026 Alberto

Permission is hereby granted, free of charge, to any person obtaining a copy of
this software and associated documentation files (the "Software"), to deal in the
Software without restriction, including without limitation the rights to use,
copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the
Software, and to permit persons to whom the Software is furnished to do so,
subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS
FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR
COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN
AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION
WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

## Data

| Files | Source | License |
| --- | --- | --- |
| `data/raw/*.txt`, `data/county_raw/*.txt`, the race fields of `data/results.json` (calls, winners, candidates, previous holder, party gain) | Wikipedia's 2026 House, Senate and governor results pages and race pages | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/). If you reuse these files, credit Wikipedia and share them under the same license. |
| Lean figures (`pvi`) in the same files | The Cook Partisan Voting Index, as listed in those Wikipedia tables | Taken from Wikipedia (CC BY-SA 4.0); the index itself is published by the Cook Political Report. |
| `data/turnout_raw/*.txt`, the `turnout` part of `data/results.json` | UF Election Lab, Michael McDonald, University of Florida | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Credit: "Turnout rates: UF Election Lab (Michael McDonald)". |
| State and county outlines in `data/geo.json` | US Census Bureau boundary files, via [us-atlas](https://github.com/topojson/us-atlas) 3.0.1 | Census data is a US government work (public domain); us-atlas is ISC-licensed. |
| District outlines in `data/geo.json` | US Census Bureau, 120th Congressional Districts (TIGERweb) | Public domain (US government work). |
| Population behind the dots | 2020 Census state totals; county shares from Census estimates via [plotly/datasets](https://github.com/plotly/datasets) | Census data is public domain; the plotly/datasets repository is MIT-licensed. |
| Runoff dates in `data/context.json` | The state's official election site (named next to each date) | Public government information. |

The published page credits these sources in its "Sources and notes" section.
