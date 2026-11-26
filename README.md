# Training HQ

Offline-first training planner, deployed on Cloudflare Workers (`wrangler.jsonc`).

## Layout
- `public/` — the served app. **This is the only copy of the front-end; edit here.**
  - `index.html` — markup only
  - `styles.css` — all styles (previously three inline `<style>` blocks)
  - `app.js` — app logic, `sync.js` — backup/sync, `service-worker.js` — offline cache
- `src/index.js` — Worker API for sync (D1: see `schema.sql`, `SETUP-SYNC.txt`)
- `tests/` — checks (below)
- `archive/` — retired patch scripts and stale copies; not deployed

## Checks
    node tests/check-templates.mjs        # no dependencies; verifies HTML templates have balanced tags
    python3 tests/day-editor.e2e.py       # needs: pip install playwright && playwright install chromium
                                          # set CHROME=/path/to/chrome to use an existing browser

Run both before deploying. The first would have caught the stray `</div>` that broke "Add exercise".

## Release note
When `public/` changes, bump `CACHE_NAME` in `public/service-worker.js`.
