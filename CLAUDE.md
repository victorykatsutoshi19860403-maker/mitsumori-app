# CLAUDE.md

Guidance for Claude Code (and other AI assistants) working in this repository.

## Project overview

`mitsumori-app` is a single-page web app for 株式会社エヌプライム that generates
initial-cost estimate PDFs (見積書) for real-estate leasing.

Flow:

1. Agent uploads a マイソク (property flyer) PDF.
2. Gemini 2.5 Flash extracts the initial-cost line items as JSON.
3. The user edits items / rent / occupancy date / notes in the browser.
4. The server renders a branded A4 PDF (or a ZIP of PDFs when multiple
   properties are detected in one upload).

All user-facing text is Japanese. Keep it that way unless the user asks
otherwise.

## Tech stack

- Python 3.12, Flask 3
- `google-genai` (model `gemini-2.5-flash`, PDF sent inline as base64)
- `reportlab` with the built-in Japanese CID fonts `HeiseiKakuGo-W5`
  (gothic, primary) and `HeiseiMin-W3` (mincho, kept registered but not
  currently used — the UI was unified to gothic in commit `25ba35d`).
- `gunicorn` (`gthread`, 1 worker × 4 threads, timeout 300s) — see
  `Procfile`. Single worker is intentional because of Gemini request cost
  and memory footprint on Render's free tier.
- Deploy target: Render. `PORT` is injected by Render.

Dependencies are pinned in `requirements.txt`; do not loosen the pins
without reason.

## Repository layout

```
mitsumori-app/
├── app.py            # Flask app: Gemini call, PDF render, embedded HTML/CSS/JS
├── requirements.txt
├── Procfile
├── README.md         # User-facing (Japanese)
└── CLAUDE.md         # This file
```

Everything lives in `app.py`. There is no separate `templates/`, `static/`,
or JS bundle — the entire single-page UI is a raw-string Python constant
(`INDEX_HTML`) rendered with `render_template_string`. Keep this structure
unless the user asks to split it.

## app.py map

Approximate line ranges (will drift — grep first if you need the exact
location):

| Concern | Where |
|---|---|
| Company constants, colors, fonts, `APP_VERSION` | ~L30–L63 |
| Flask app + 20 MB upload cap | ~L65–L67 |
| `extract_items_from_pdf` — Gemini prompt + JSON normalization | ~L72–L187 |
| `_coerce_amount` / `_amount_to_int` — number-or-string amount helpers | ~L190–L225 |
| `_wrap_text`, `_fmt_yen` — PDF text helpers | ~L230–L267 |
| `generate_estimate_pdf` — reportlab layout | ~L270–L509 |
| `INDEX_HTML` — HTML, CSS, and client JS as one string | ~L515–L1437 |
| Routes: `/`, `/favicon.ico`, `/healthz`, `/api/extract`, `/api/generate_pdf`, `/api/generate_zip` | ~L1440–L1549 |
| `app.run` for local dev | L1551–L1552 |

## HTTP routes

- `GET  /` — serves `INDEX_HTML`. Response is sent with
  `Cache-Control: no-store…` so deploys are picked up without a hard
  reload (see commit `442f64b`). `APP_VERSION` is rendered into the page
  for cache-verification.
- `GET  /favicon.ico` — returns an inline 1×1 PNG to silence browser 404
  noise.
- `GET  /healthz` — returns `ok`; used by Render health checks.
- `POST /api/extract` — `multipart/form-data` with `file=<pdf>`. Validates
  size, non-empty, and `%PDF` signature. Returns the normalized
  `{"properties":[…]}` shape.
- `POST /api/generate_pdf` — JSON body for one property; returns a single
  PDF attachment.
- `POST /api/generate_zip` — JSON body `{"properties":[…]}`; returns a ZIP
  of one PDF per property. File names are `見積書_{NN}_{property}.pdf`
  with Windows-unsafe chars replaced.

## Data shape contracts

The normalizer in `extract_items_from_pdf` accepts three Gemini output
shapes (`{"properties":[…]}`, a bare list, or a single dict) and always
returns `{"properties":[…]}`. Downstream code relies on this — preserve
it.

Per-property dict used by both front-end and `generate_estimate_pdf`:

```json
{
  "property_name": "...",
  "address": "...",
  "occupancy_date": "YYYY-MM-DD",      // optional; added by the UI
  "items": [ {"name": "...", "amount": <int | str>} ],
  "total": <int>,
  "notes": "..."                        // optional; added by the UI
}
```

`REQUIRED_ITEMS` (家賃, 管理費, 敷金, 礼金, 仲介手数料, 保証会社料, 火災保険料,
鍵交換費用) are always present. If Gemini omits them they are back-filled
with `amount=0`.

### Amount polymorphism — important

An item's `amount` is deliberately either an **int** (yen) or a **string**
like `"別途"`, `"応相談"`, `"要相談"`, `"未定"` (commit `ad5d69b`).

- `_coerce_amount` normalizes incoming values: numeric strings with
  `,¥￥円` get parsed; non-numeric strings pass through verbatim.
- `_amount_to_int` is the **totals-only** helper: strings become `0` so
  they are excluded from the sum.
- `_fmt_yen` prints `¥X,XXX` for numbers and the raw string otherwise.

If you add code that touches `amount`, decide explicitly whether you need
the display value (`_fmt_yen`), the numeric-or-zero value (`_amount_to_int`),
or the raw polymorphic value, and use the right helper.

## PDF rendering notes

- Page size is A4. Margins are 20 mm. Fonts are registered once at module
  import.
- Header / total bars are navy (`#1a2a3a`) with gold (`#c9a961`)
  accents. The whole document is rendered in `FONT_GOTHIC`
  (`HeiseiKakuGo-W5`) — commits `676ede0` and `25ba35d` unified the
  typography. Do not reintroduce mincho for new content unless asked.
- Long item lists paginate at `y_cur < 50 * mm`; a simplified header row
  is repeated on continuation pages.
- The 備考 (notes) block flows into a new page when under ~22 mm remain
  (commit `987ce4f`). Only the text clipping path is allowed to show
  `…以下省略`; do not silently drop notes.

## Front-end behavior (embedded JS)

The editor is plain vanilla JS (no framework). State lives in the module
scope:

- `properties` — array of per-property form state.
- `currentIdx` — active tab.
- `saveCurrentForm()` ↔ `renderCurrentProperty()` synchronize the DOM
  and `properties[currentIdx]`.
- `buildPayloadFromProperty` composes the server payload from
  `monthly_rent` / `monthly_mgmt` / `occupancy_date`, then appends
  `other_items`.

### Prorated rent rule

See `calcBreakdown` (and the mirror in `buildPayloadFromProperty`):

- If `occupancy_date.getDate() === 1` → one row each for
  `家賃（M月分）` / `管理費（M月分）` only (commit `8848ff6`).
- Otherwise → `日割り N日分` for the current month **plus** the next
  month's full `家賃` / `管理費` row.

The same logic exists in two places (display + payload build). If you
change the rule, change both and keep them in sync.

### Amount input

The `.amount` input is `type="text"` (with `inputmode="numeric"`) so a
user can type `別途` / `応相談`. `parseAmount` returns
`{num, text, raw}` — pick the right field at the call site.

## Conventions

- **File boundary:** keep everything in `app.py`. Don't add a
  `templates/` directory or a JS bundler without an explicit request.
- **No new top-level files** unless asked. The repo intentionally ships
  only `app.py` + `requirements.txt` + `Procfile` + `README.md`.
- **Comments:** Japanese is the norm in this codebase. Keep existing
  Japanese comments; match the tone of surrounding comments rather than
  rewriting them in English.
- **Commit messages:** follow the existing style — conventional-commit
  prefix in English (`feat:`, `fix:`, `style:`, `refactor:`, `docs:`)
  followed by a Japanese summary. See recent history:
  - `feat: 備考欄を追加 (入力→見積書PDFに印字)`
  - `fix: 1日入居の場合は当月分のみ (日割り・翌月分なし)`
  - `style: 全テキストをゴシック体に統一 (明朝体を廃止)`
- **APP_VERSION:** bump the date in `APP_VERSION` when shipping a
  user-visible change — it is printed on the upload screen and is the
  fastest way to verify a deploy landed.
- **Cache headers on `/`:** do not remove the no-store headers; the site
  was broken on mobile Safari before they were added (commit `442f64b`).

## Environment variables

| Var | Purpose |
|---|---|
| `GEMINI_API_KEY` | Required. Google AI Studio key used by `extract_items_from_pdf`. |
| `PORT` | Injected by Render. `app.run` falls back to 5000 locally. |

`GEMINI_API_KEY` is read fresh on every request, so rotating it on Render
does not need a restart.

## Local development

```bash
cd mitsumori-app
python -m venv venv
# Windows
venv\Scripts\activate
# Unix
source venv/bin/activate

pip install -r requirements.txt
export GEMINI_API_KEY=xxxx
python app.py            # http://localhost:5000, debug=True
```

There are no tests, no linter config, and no CI in this repo. "Done"
means: (a) `python app.py` starts without error, (b) the upload→edit→PDF
flow works end-to-end for a single-property PDF, and (c) a multi-property
PDF produces the ZIP flow. If you can't run a real Gemini call, stub the
call or say so explicitly — don't claim the flow works.

## Git workflow for Claude Code sessions

- Default development branch for Claude sessions is the branch named in
  the session instructions (e.g. `claude/add-claude-documentation-*`).
  `main` is the release branch; do not push directly to it.
- Always `git push -u origin <branch>`. Retry transient network errors
  with exponential backoff (2s/4s/8s/16s), up to 4 attempts.
- Do **not** open a pull request unless the user explicitly asks for
  one.

## Things to avoid

- Splitting `INDEX_HTML` into a template file — the single-file layout
  is intentional and keeps Render deploys trivial.
- Coercing `amount` to `int` globally. Several code paths depend on the
  polymorphic int-or-string contract described above.
- Silently truncating notes or items. The existing code only prints
  `…以下省略` when the draw cursor runs out of room on a continuation
  page; preserve that visibility.
- Reintroducing mincho (`HeiseiMin-W3`) in generated PDFs. It is kept
  registered for forward-compatibility only.
- Skipping the `%PDF` signature check in `/api/extract` — it blocks
  trivial misuse from the browser file picker.
