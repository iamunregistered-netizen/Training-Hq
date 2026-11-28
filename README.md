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

## Plan page features
- Weekly plan scrolls sideways (day chips jump; today is highlighted); week ‹ › arrows; per-day **Copy…** and **Duplicate week**.
- `±` on an exercise row opens a quick editor for sets / reps / load; drag handles and ↑/↓ reorder.
- Day editor: ‹ / › (or swipe the bar) saves and switches day. Removing an exercise, saving a day, reordering, copying and duplicating a week all offer **Undo** in the toast.
- Edits to weeks 2+ go through `mutableDayPlan()`, which materialises the week so changes persist.

## Workout & progress tools (`public/tools.js`)
Loaded after `app.js`; it wraps `openWorkout`, `saveWorkout`, `closeModal`, `renderProgram`, `renderProgress` and `renderSettings` rather than editing them.
- **Logging:** last-time values with "Use these", floating rest timer (default rest, ±15 s, sound), screen wake lock, plate calculator, swap an exercise for today / in the plan.
- **Progress:** records (heaviest, est. 1RM, rep bests) with "New PR" on save, calendar heatmap + week streaks, volume by muscle group, bodyweight log.
- **Plan:** Deload copy of a week. Tool settings (bar, plates, default rest, wake lock, sound) are in Settings.
- Log dates use the device's local date (`localISODate()`), not UTC.

## Checks
    node tests/check-templates.mjs        # no dependencies; verifies HTML templates have balanced tags
    python3 tests/day-editor.e2e.py       # needs: pip install playwright && playwright install chromium
    python3 tests/training-tools.e2e.py   # tools.js features + local-date fix
                                          # set CHROME=/path/to/chrome to use an existing browser

Run both before deploying. The first would have caught the stray `</div>` that broke "Add exercise".

## Release note
When `public/` changes, bump `CACHE_NAME` in `public/service-worker.js`.
