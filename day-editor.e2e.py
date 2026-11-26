#!/usr/bin/env python3
"""End-to-end checks for the planning page / day editor.

    pip install playwright && playwright install chromium
    python3 tests/day-editor.e2e.py            # or CHROME=/path/to/chrome python3 ...

Serves ./public on a random local port, drives the real app in headless Chromium and
exits non-zero if any check fails.
"""
import asyncio, functools, http.server, os, socketserver, sys, threading
from pathlib import Path
from playwright.async_api import async_playwright

PUBLIC = Path(__file__).resolve().parent.parent / 'public'
FAILS = []


def ok(label, cond, extra=''):
    print(('PASS  ' if cond else 'FAIL  ') + label + (f'   [{extra}]' if extra and not cond else ''))
    if not cond:
        FAILS.append(label)


class Quiet(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(PUBLIC), **k)

    def log_message(self, *a):
        pass


socketserver.TCPServer.allow_reuse_address = True
srv = socketserver.TCPServer(('127.0.0.1', 0), Quiet)
PORT = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()

UIDS = "[...document.querySelectorAll('#editItems > .edititem')].map(c=>c.dataset.uid)"
NAMES = "[...document.querySelectorAll('#editItems > .edititem [data-k=name]')].map(e=>e.value)"
DIALOG = "document.querySelector('#modalShade > div')"


async def plan_names(pg, day):
    return await pg.evaluate(f"dayPlanForWeek('{day}',activeWeek()).items.map(i=>i.name)")


async def open_editor(pg, idx):
    await pg.locator('button.btn.ghost.full[data-editday]').nth(idx).click()
    await pg.wait_for_selector('#editItems')
    await pg.wait_for_timeout(150)


async def close_editor(pg):
    await pg.click('#closeModal')
    await pg.wait_for_timeout(100)


async def main():
    async with async_playwright() as p:
        launch = dict(args=['--no-sandbox'])
        if os.environ.get('CHROME'):
            launch['executable_path'] = os.environ['CHROME']
        elif Path('/opt/pw-browsers/chromium-1243/chrome-linux64/chrome').exists():
            launch['executable_path'] = '/opt/pw-browsers/chromium-1243/chrome-linux64/chrome'
        b = await p.chromium.launch(**launch)
        pg = await b.new_page(viewport={'width': 430, 'height': 900})
        errors = []
        pg.on('pageerror', lambda e: errors.append(str(e)))
        # Network failures (offline CI, no sync Worker behind the static server) are not app bugs; real JS errors are.
        pg.on('console', lambda m: errors.append('console.error: ' + m.text) if m.type == 'error' and 'Failed to load resource' not in m.text else None)

        await pg.goto(f'http://127.0.0.1:{PORT}/index.html')
        await pg.wait_for_timeout(1200)
        await pg.click('[data-page=program]')
        await pg.wait_for_timeout(300)

        counts = await pg.eval_on_selector_all('.program-day-card', 'cs=>cs.map(c=>c.querySelectorAll(".program-exercise-row").length)')
        idx = counts.index(max(counts))
        n = counts[idx]
        day = await pg.locator('button.btn.ghost.full[data-editday]').nth(idx).get_attribute('data-editday')
        orig = await plan_names(pg, day)
        print(f'\nUsing {day}: {n} exercises\n')

        # 1. structure ---------------------------------------------------------------------------
        await open_editor(pg, idx)
        kids = await pg.evaluate("[...document.querySelectorAll('#modalBody > *')].map(e=>e.tagName+'#'+e.id)")
        ok('modal body holds only meta, list, add button, datalist', kids == ['DIV#dayMeta', 'DIV#editItems', 'BUTTON#addProgramItem', 'DATALIST#exerciseOptions'], kids)
        ok('every exercise is inside #editItems', len(await pg.evaluate(UIDS)) == n)
        ok('exactly one #exerciseOptions datalist', await pg.evaluate("document.querySelectorAll('#exerciseOptions').length") == 1)
        ok('each card has a drag handle in its summary', await pg.evaluate("[...document.querySelectorAll('#editItems > .edititem')].every(c=>c.querySelector('summary [data-drag-handle]'))"))

        # 2. add exercise ------------------------------------------------------------------------
        await pg.click('#addProgramItem')
        await pg.wait_for_timeout(300)
        uids = await pg.evaluate(UIDS)
        new_uid = uids[-1]
        ok('Add exercise appends one entry at the bottom', len(uids) == n + 1)
        ok('new entry has a blank name and shows "New exercise" in its summary',
           await pg.evaluate("(()=>{const c=document.querySelector('#editItems > .edititem:last-child');return c.querySelector('[data-k=name]').value===''&&c.querySelector('[data-summary-text]').textContent.startsWith('New exercise')})()"))
        ok('new entry is open and its name field is focused',
           await pg.evaluate("(()=>{const c=document.querySelector('#editItems > .edititem:last-child');return c.open&&document.activeElement===c.querySelector('[data-k=name]')})()"))

        # 3. up / down buttons and keyboard --------------------------------------------------------
        card = pg.locator(f'#editItems > [data-uid="{new_uid}"]')
        await card.locator('[data-move-item="-1"]').click()
        ok('↑ button moves the entry up one place', (await pg.evaluate(UIDS)).index(new_uid) == n - 1)
        await card.locator('[data-move-item="1"]').click()
        ok('↓ button moves the entry back down', (await pg.evaluate(UIDS)).index(new_uid) == n)
        await card.locator('[data-drag-handle]').focus()
        await pg.keyboard.press('ArrowUp')
        ok('ArrowUp on the handle moves the entry up', (await pg.evaluate(UIDS)).index(new_uid) == n - 1)

        # 4. drag from the summary handle of a collapsed card -------------------------------------
        await pg.evaluate(f"{DIALOG}.scrollTop=0")
        before = await pg.evaluate(UIDS)
        open_before = await pg.evaluate("[...document.querySelectorAll('#editItems > .edititem')].map(c=>c.open)")
        cards = pg.locator('#editItems > .edititem')
        h0 = await cards.nth(0).locator('[data-drag-handle]').bounding_box()
        x, y = h0['x'] + h0['width'] / 2, h0['y'] + h0['height'] / 2
        await pg.mouse.move(x, y)
        await pg.mouse.down()
        await pg.mouse.move(x, y + 6, steps=2)
        mid = await pg.evaluate("({active:document.querySelector('#editItems').classList.contains('drag-active'),anyOpen:[...document.querySelectorAll('#editItems > .edititem')].some(c=>c.open)})")
        ok('cards collapse while dragging', mid['active'] and not mid['anyOpen'], mid)
        r3 = await cards.nth(3).bounding_box()
        await pg.mouse.move(x, r3['y'] + r3['height'] / 2 - 2, steps=10)
        await pg.mouse.up()
        await pg.wait_for_timeout(100)
        after = await pg.evaluate(UIDS)
        moved_to = after.index(before[0])
        ok('dragging a collapsed card by its summary handle reorders it', moved_to >= 2, f'index {moved_to}')
        ok('other cards keep their relative order', [u for u in after if u != before[0]] == [u for u in before if u != before[0]])
        open_after = await pg.evaluate("Object.fromEntries([...document.querySelectorAll('#editItems > .edititem')].map(c=>[c.dataset.uid,c.open]))")
        ok('open/closed state is restored after the drag', all(open_after[u] == o for u, o in zip(before, open_before)))
        ok('drag state is cleared', not await pg.evaluate("document.querySelector('#editItems').classList.contains('drag-active')"))

        # 5. auto-scroll near the dialog edges ------------------------------------------------------
        await pg.evaluate(f"{DIALOG}.scrollTop={DIALOG}.scrollHeight")
        await pg.wait_for_timeout(100)
        order = await pg.evaluate(UIDS)
        last_uid = order[-1]
        hb = await pg.locator(f'#editItems > [data-uid="{last_uid}"] [data-drag-handle]').bounding_box()
        dlg = await pg.evaluate(f"(()=>{{const r={DIALOG}.getBoundingClientRect();return {{top:r.top,bottom:r.bottom}}}})()")
        start_scroll = await pg.evaluate(f"{DIALOG}.scrollTop")
        await pg.mouse.move(hb['x'] + hb['width'] / 2, hb['y'] + hb['height'] / 2)
        await pg.mouse.down()
        await pg.mouse.move(hb['x'] + hb['width'] / 2, dlg['top'] + 10, steps=8)
        for _ in range(30):
            await pg.wait_for_timeout(100)
            if await pg.evaluate(f"{DIALOG}.scrollTop") < start_scroll - 100:
                break
        scrolled_up = await pg.evaluate(f"{DIALOG}.scrollTop")
        await pg.mouse.up()
        ok('holding a drag at the top edge auto-scrolls up', scrolled_up < start_scroll - 100, f'{start_scroll} -> {scrolled_up}')
        ok('…and the dragged card moved to the top of the list', (await pg.evaluate(UIDS)).index(last_uid) == 0)

        await pg.evaluate(f"{DIALOG}.scrollTop=0")
        await pg.wait_for_timeout(100)
        first_uid = (await pg.evaluate(UIDS))[0]
        hb = await pg.locator(f'#editItems > [data-uid="{first_uid}"] [data-drag-handle]').bounding_box()
        await pg.mouse.move(hb['x'] + hb['width'] / 2, hb['y'] + hb['height'] / 2)
        await pg.mouse.down()
        await pg.mouse.move(hb['x'] + hb['width'] / 2, dlg['bottom'] - 10, steps=8)
        for _ in range(40):
            await pg.wait_for_timeout(100)
            if await pg.evaluate(f"{DIALOG}.scrollTop") > 100:
                break
        scrolled_down = await pg.evaluate(f"{DIALOG}.scrollTop")
        for _ in range(40):
            if (await pg.evaluate(UIDS)).index(first_uid) == n:
                break
            await pg.wait_for_timeout(100)
        await pg.mouse.up()
        ok('holding a drag at the bottom edge auto-scrolls down', scrolled_down > 100, f'scrollTop {scrolled_down}')
        ok('…and the dragged card reached the bottom of the list', (await pg.evaluate(UIDS)).index(first_uid) == n)

        # 6. save persists order; named entry saved ---------------------------------------------------
        blank_uid = await pg.evaluate("(()=>{const c=[...document.querySelectorAll('#editItems > .edititem')].find(c=>c.querySelector('[data-k=name]').value==='');return c&&c.dataset.uid})()")
        await pg.evaluate(f"document.querySelector('#editItems > [data-uid=\"{blank_uid}\"]').open=true")
        await pg.locator(f'#editItems > [data-uid="{blank_uid}"] [data-k=name]').fill('Test lift')
        expected = await pg.evaluate(NAMES)
        await pg.click('#modalButtons >> text=Save day')
        await pg.wait_for_timeout(200)
        saved = await plan_names(pg, day)
        ok('Save day stores every exercise in the on-screen order', saved == expected and len(saved) == n + 1, f'{saved} vs {expected}')
        ok('modal closed after save', await pg.evaluate("document.getElementById('modalRoot').innerHTML===''"))

        # 7. unnamed entries are skipped, with a message ------------------------------------------------
        await open_editor(pg, idx)
        await pg.click('#addProgramItem')
        await pg.click('#modalButtons >> text=Save day')
        await pg.wait_for_timeout(150)
        toast = await pg.text_content('#toast')
        ok('unnamed new entry is not saved', await plan_names(pg, day) == saved)
        ok('…and the toast says it was skipped', 'skipped' in (toast or ''), toast)

        # 8. integrity guard: a card outside the list aborts the save ---------------------------------------
        await open_editor(pg, idx)
        await pg.evaluate("document.querySelector('#modalBody').appendChild(document.querySelector('#editItems > .edititem:nth-child(2)'))")
        await pg.click('#modalButtons >> text=Save day')
        await pg.wait_for_timeout(150)
        toast = await pg.text_content('#toast')
        ok('save aborts instead of silently dropping exercises', 'nothing was saved' in (toast or '') and await plan_names(pg, day) == saved, toast)
        ok('editor stays open so nothing is lost', await pg.query_selector('#editItems') is not None)
        await close_editor(pg)

        # 9. remove --------------------------------------------------------------------------------------
        await open_editor(pg, idx)
        await pg.evaluate("document.querySelector('#editItems > .edititem').open=true")
        await pg.locator('#editItems > .edititem').first.locator('[data-remove-item]').click()
        ok('Remove exercise takes the card out of the list', len(await pg.evaluate(UIDS)) == n)
        await pg.click('#modalButtons >> text=Save day')
        await pg.wait_for_timeout(150)
        saved2 = await plan_names(pg, day)
        ok('removal is persisted and the rest are kept in order', saved2 == saved[1:], saved2)

        # 10. drag reorder on the program page ---------------------------------------------------------------
        day_card = pg.locator(f'.program-day-card:has(.program-day-heading[data-editday="{day}"])')
        rows = day_card.locator('.program-exercise-row')
        count = await rows.count()
        ok('program page shows a drag handle on every exercise row', await day_card.locator('[data-prog-drag]').count() == count)
        handle = rows.nth(0).locator('[data-prog-drag]')
        await handle.scroll_into_view_if_needed()
        hb = await handle.bounding_box()
        lb = await rows.nth(count - 1).bounding_box()
        await pg.mouse.move(hb['x'] + hb['width'] / 2, hb['y'] + hb['height'] / 2)
        await pg.mouse.down()
        await pg.mouse.move(hb['x'] + hb['width'] / 2, lb['y'] + lb['height'] - 1, steps=12)
        await pg.mouse.up()
        await pg.wait_for_timeout(200)
        reordered = await plan_names(pg, day)
        ok('dragging a row on the program page moves it and saves the new order', reordered == saved2[1:] + saved2[:1], reordered)
        ui_names = await day_card.locator('.program-exercise-link span').all_text_contents()
        ok('…and the page re-renders in that order', ui_names == reordered, ui_names)

        ok('no page errors or console errors', not errors, errors)
        await b.close()


asyncio.run(main())
print()
if FAILS:
    print(f'{len(FAILS)} check(s) FAILED')
    sys.exit(1)
print('All checks passed')
