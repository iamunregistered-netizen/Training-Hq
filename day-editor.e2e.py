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

        # 0. horizontal weekly strip -------------------------------------------------------------------
        STRIP = "document.querySelector('.program-day-strip')"
        lay = await pg.evaluate(f"(()=>{{const s={STRIP},cs=getComputedStyle(s),cards=[...s.querySelectorAll('.program-day-card')];return {{ox:cs.overflowX,scrolls:s.scrollWidth>s.clientWidth+50,tops:new Set(cards.map(c=>Math.round(c.getBoundingClientRect().top))).size,n:cards.length}}}})()")
        ok('weekly plan is a horizontally scrolling strip of 7 day cards in one row', lay['ox'] == 'auto' and lay['scrolls'] and lay['tops'] == 1 and lay['n'] == 7, lay)
        today = await pg.evaluate("dayName(new Date())")
        edge = f"(()=>{{const s={STRIP};return Math.round(s.querySelector('[data-day-card=\"'+DAY+'\"]').getBoundingClientRect().left-s.getBoundingClientRect().left)}})()"
        ok('opens scrolled to today\'s card', abs(await pg.evaluate(edge.replace('DAY', repr(today)))) <= 6)
        ok('today\'s chip is active and marked', await pg.evaluate(f"(()=>{{const b=document.querySelector('[data-jump-day=\"{today}\"]');return b.classList.contains('active')&&b.classList.contains('today')}})()"))
        ok('today\'s card is highlighted', await pg.evaluate(f"document.querySelector('[data-day-card=\"{today}\"]').classList.contains('today')"))
        target = 'Friday' if today != 'Friday' else 'Monday'
        await pg.click(f'[data-jump-day="{target}"]')
        await pg.wait_for_function(f"Math.abs({edge.replace('DAY', repr(target))})<=6", timeout=4000)
        ok(f'tapping the {target[:3]} chip scrolls that day to the left edge', True)
        ok('…and that chip becomes active', await pg.evaluate(f"document.querySelector('[data-jump-day=\"{target}\"]').classList.contains('active')"))
        await pg.evaluate(f"(()=>{{const s={STRIP};const c=s.querySelector('[data-day-card=\"Tuesday\"]');s.scrollTo({{left:s.scrollLeft+c.getBoundingClientRect().left-s.getBoundingClientRect().left,behavior:'instant'}})}})()")
        await pg.wait_for_timeout(250)
        ok('swiping to another day updates the active chip', await pg.evaluate("document.querySelector('[data-jump-day=\"Tuesday\"]').classList.contains('active')"))
        # keeps its place when an edit re-renders the page
        await pg.click('[data-jump-day="Wednesday"]')
        await pg.wait_for_function(f"Math.abs({edge.replace('DAY', repr('Wednesday'))})<=6", timeout=4000)
        await pg.locator('.program-day-card[data-day-card="Wednesday"] [data-move-exercise][data-dir="1"]').first.click()
        await pg.wait_for_timeout(300)
        ok('re-render after a reorder keeps the same day in view', abs(await pg.evaluate(edge.replace('DAY', repr('Wednesday')))) <= 6)
        await pg.locator('.program-day-card[data-day-card="Wednesday"] [data-move-exercise][data-dir="-1"]').nth(1).click()
        await pg.wait_for_timeout(300)
        # keeps its place when leaving and returning to the Plan page
        await pg.click('[data-page=progress]'); await pg.wait_for_timeout(300)
        await pg.click('[data-page=program]'); await pg.wait_for_timeout(400)
        ok('returning to the Plan page restores the day you were on', abs(await pg.evaluate(edge.replace('DAY', repr('Wednesday')))) <= 6)

        # wide screens: the last days cannot reach the left edge, but a chosen chip must stay active
        await pg.set_viewport_size({'width': 1280, 'height': 900})
        await pg.wait_for_timeout(200)
        await pg.click('[data-jump-day="Sunday"]')
        await pg.wait_for_timeout(900)
        ok('on a wide screen, tapping Sun keeps Sun active (no drift to an earlier day)', await pg.evaluate("document.querySelector('[data-jump-day=\"Sunday\"]').classList.contains('active')"))
        await pg.set_viewport_size({'width': 430, 'height': 900})
        await pg.wait_for_timeout(200)

        counts = await pg.eval_on_selector_all('.program-day-card', 'cs=>cs.map(c=>c.querySelectorAll(".program-exercise-row").length)')
        idx = counts.index(max(counts))
        n = counts[idx]
        day = await pg.locator('button.btn.ghost.full[data-editday]').nth(idx).get_attribute('data-editday')
        orig = await plan_names(pg, day)
        print(f'\nUsing {day}: {n} exercises\n')

        # 1. structure ---------------------------------------------------------------------------
        await open_editor(pg, idx)
        kids = await pg.evaluate("[...document.querySelectorAll('#modalBody > *')].map(e=>e.tagName+'#'+e.id)")
        ok('modal body holds only day switcher, meta, list, add button, datalist', kids == ['DIV#dayNav', 'DIV#dayMeta', 'DIV#editItems', 'BUTTON#addProgramItem', 'DATALIST#exerciseOptions'], kids)
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
        await pg.evaluate("window.scrollBy(0,-320)")  # scrollIntoView parks the handle under the fixed top nav
        await pg.wait_for_timeout(600)  # let the strip's scroll-snap animation settle before measuring
        hb = await handle.bounding_box()
        lb = await rows.nth(count - 1).bounding_box()
        await pg.mouse.move(hb['x'] + hb['width'] / 2, hb['y'] + hb['height'] / 2)
        await pg.mouse.down()
        await pg.mouse.move(hb['x'] + hb['width'] / 2, lb['y'] + lb['height'] - 1, steps=12)
        await pg.mouse.up()
        await pg.wait_for_timeout(200)
        reordered = await plan_names(pg, day)
        ok('dragging a row on the program page moves it and saves the new order', reordered == saved2[1:] + saved2[:1], f'before={saved2} after={reordered}')
        ui_names = await day_card.locator('.program-exercise-link span').all_text_contents()
        ok('…and the page re-renders in that order', ui_names == reordered, ui_names)

        # 11. week bar ------------------------------------------------------------------------------------
        await pg.evaluate("window.scrollTo(0,0)")
        wb = await pg.evaluate(r'''({label:document.querySelector('.weekbar-label strong').textContent,prevDisabled:document.querySelector('[data-week-step="-1"]').disabled})''')
        ok('week bar shows the current week and disables ‹ on week 1', wb['label'] == 'Week 1' and wb['prevDisabled'], wb)
        await pg.click('[data-week-step="1"]')
        await pg.wait_for_timeout(250)
        ok('› moves to the next week (and the week selector follows)', await pg.evaluate("activeWeek()==2&&document.querySelector('.weekbar-label strong').textContent==='Week 2'&&document.getElementById('programWeekSelect').value==='2'"))

        # 12. reordering on a later (derived) week used to be silently lost ----------------------------------
        w2 = await pg.evaluate("dayPlanForWeek('Monday',2).items.map(i=>i.name)")
        await pg.locator('.program-day-card[data-day-card="Monday"] [data-move-exercise][data-dir="1"]').first.click()
        await pg.wait_for_timeout(250)
        w2b = await pg.evaluate("dayPlanForWeek('Monday',2).items.map(i=>i.name)")
        ok('↓ on week 2 actually reorders (previously a silent no-op)', w2b[0] == w2[1] and w2b[1] == w2[0], f'{w2} -> {w2b}')
        await pg.click('#toast .toast-action')
        await pg.wait_for_timeout(250)
        ok('Undo restores the previous order', await pg.evaluate("dayPlanForWeek('Monday',2).items.map(i=>i.name)") == w2)

        # 13. quick edit (still on week 2) ---------------------------------------------------------------------
        qi = await pg.evaluate("dayPlanForWeek('Monday',2).items.findIndex(i=>!i.progressiveRamp&&!(i.setScheme||[]).length)")
        b4 = await pg.evaluate(f"(()=>{{const i=dayPlanForWeek('Monday',2).items[{qi}];return {{sets:i.sets,load:Number(i.loadKg)||0,pct:Number(i.pct)||0,inc:Number(i.loadIncrementKg)||0}}}})()")
        row = pg.locator('.program-day-card[data-day-card="Monday"] .program-exercise-row').nth(qi)
        await row.locator('[data-quick-toggle]').click()
        await pg.wait_for_timeout(200)
        ok('± opens an inline quick-edit panel under the row', await pg.locator('.program-quick').count() == 1)
        await pg.locator('.program-quick [data-qe="sets"][data-dir="1"]').click()
        await pg.wait_for_timeout(150)
        cur = await pg.evaluate(f"dayPlanForWeek('Monday',2).items[{qi}].sets")
        meta = await row.locator('.program-exercise-link small').text_content()
        ok('sets ＋ saves immediately and the row summary updates', cur == b4['sets'] + 1 and meta.startswith(f"{cur} ×"), f'{cur} / {meta}')
        ok('…without closing the panel', await pg.locator('.program-quick').count() == 1)
        await pg.fill('.program-quick [data-qe-reps]', '5')
        await pg.press('.program-quick [data-qe-reps]', 'Tab')
        await pg.wait_for_timeout(150)
        ok('editing reps saves and updates the summary', await pg.evaluate(f"dayPlanForWeek('Monday',2).items[{qi}].reps") == '5' and '× 5' in await row.locator('.program-exercise-link small').text_content())
        await pg.locator('.program-quick [data-qe="load"][data-dir="1"]').click()
        await pg.wait_for_timeout(150)
        step = b4['inc'] if b4['inc'] > 0 else 2.5
        got = await pg.evaluate(f"(()=>{{const i=dayPlanForWeek('Monday',2).items[{qi}];return i.pct>0&&!(i.loadKg>0)?i.pct:i.loadKg}})()")
        want = (b4['pct'] + 2.5) if (b4['pct'] > 0 and b4['load'] == 0) else (b4['load'] + step)
        ok('load ＋ steps by the exercise\'s increment', abs(got - want) < 0.01, f'{got} vs {want}')
        await row.locator('[data-quick-toggle]').click()
        await pg.wait_for_timeout(200)
        ok('tapping ± again closes the panel', await pg.locator('.program-quick').count() == 0)
        await pg.click('[data-week-step="-1"]')
        await pg.wait_for_timeout(250)

        # 14. copy day ----------------------------------------------------------------------------------------
        thu = await plan_names(pg, 'Thursday'); sun0 = await plan_names(pg, 'Sunday'); sat0 = await plan_names(pg, 'Saturday')
        await pg.click('[data-copyday="Thursday"]')
        await pg.check('.copy-day input[value="Sunday"]')
        await pg.click('#modalButtons >> text=Copy')
        await pg.wait_for_timeout(250)
        ok('Copy… (replace) makes Sunday match Thursday', await plan_names(pg, 'Sunday') == thu)
        await pg.click('#toast .toast-action')
        await pg.wait_for_timeout(250)
        ok('…and Undo restores Sunday', await plan_names(pg, 'Sunday') == sun0)
        await pg.click('[data-copyday="Thursday"]')
        await pg.check('.copy-day input[value="Saturday"]')
        await pg.select_option('#copyMode', 'append')
        await pg.click('#modalButtons >> text=Copy')
        await pg.wait_for_timeout(250)
        ok('Copy… (add after) appends to Saturday', await plan_names(pg, 'Saturday') == sat0 + thu)
        await pg.click('#toast .toast-action')
        await pg.wait_for_timeout(250)
        ok('…and Undo restores Saturday', await plan_names(pg, 'Saturday') == sat0)

        # 15. duplicate week -----------------------------------------------------------------------------------
        c0 = await pg.evaluate("programWeekCount()")
        mon1 = await plan_names(pg, 'Monday')
        await pg.evaluate("document.getElementById('duplicateProgramWeek').click()")
        await pg.wait_for_timeout(300)
        ok('Duplicate week adds a copy at the end and switches to it', await pg.evaluate("programWeekCount()") == c0 + 1 and await pg.evaluate("activeWeek()") == c0 + 1)
        ok('…named "(copy)" with the same exercises', '(copy)' in await pg.text_content('.weekbar-label strong') and await pg.evaluate("dayPlanForWeek('Monday',activeWeek()).items.map(i=>i.name)") == mon1)
        await pg.click('#toast .toast-action')
        await pg.wait_for_timeout(300)
        ok('Undo removes the duplicate and returns to the original week', await pg.evaluate("programWeekCount()") == c0 and await pg.evaluate("activeWeek()") == 1)

        # 16. rest days are slim ----------------------------------------------------------------------------------
        await pg.evaluate("window.__sun=snapshotDay('Sunday',1);const p=mutableDayPlan('Sunday',1);p.items=[];p.type='';renderProgram()")
        await pg.wait_for_timeout(300)
        rest = await pg.evaluate(r'''(()=>{const c=document.querySelector('[data-day-card="Sunday"]');return {cls:c.classList.contains('rest'),w:Math.round(c.getBoundingClientRect().width),copy:!!c.querySelector('[data-copyday]'),txt:c.querySelector('.program-day-heading span').textContent,chip:document.querySelector('[data-jump-day="Sunday"]').classList.contains('rest')}})()''')
        ok('an empty day renders as a slim "Rest day" card', rest['cls'] and rest['w'] < 260 and not rest['copy'] and rest['txt'] == 'Rest day' and rest['chip'], rest)
        await pg.evaluate("setDayPlan('Sunday',1,window.__sun);save();renderProgram()")
        await pg.wait_for_timeout(200)

        # 17. editor: undo remove / undo save, toast above the modal ----------------------------------------------
        await pg.evaluate("window.scrollTo(0,0)")
        await open_editor(pg, idx)
        names0 = await pg.evaluate(NAMES)
        for pos in (0, 2):
            await pg.evaluate(f"document.querySelectorAll('#editItems > .edititem')[{pos}].open=true")
            await pg.locator('#editItems > .edititem').nth(pos).locator('[data-remove-item]').click()
            await pg.wait_for_timeout(150)
            if pos == 0:
                ok('toast (with Undo) shows above the open editor', await pg.evaluate("(()=>{const t=document.getElementById('toast').getBoundingClientRect();const e=document.elementFromPoint(t.left+t.width/2,t.top+t.height/2);return !!e&&!!e.closest('#toast')})()"))
            await pg.click('#toast .toast-action')
            await pg.wait_for_timeout(150)
            ok(f'Undo puts a removed card back in position {pos}', await pg.evaluate(NAMES) == names0, await pg.evaluate(NAMES))
        ok('editor bookkeeping stays consistent after undo (save would not abort)', await pg.evaluate("document.querySelectorAll('#modalBody .edititem').length") == len(names0))
        await pg.evaluate("document.querySelector('#editItems > .edititem').open=true")
        await pg.locator('#editItems > .edititem').first.locator('[data-remove-item]').click()
        await pg.click('#modalButtons >> text=Save day')
        await pg.wait_for_timeout(250)
        ok('saving after a removal drops it…', await plan_names(pg, day) == names0[1:])
        await pg.click('#toast .toast-action')
        await pg.wait_for_timeout(250)
        ok('…and "Undo" on the save toast restores the day', await plan_names(pg, day) == names0)

        # 18. day switcher in the editor -------------------------------------------------------------------------------
        await open_editor(pg, idx)
        label = lambda: pg.evaluate("document.querySelector('#modalShade [role=dialog]').getAttribute('aria-label')")
        orig_desc = await pg.evaluate("document.getElementById('edDesc').value")
        await pg.fill('#edDesc', 'nav test')
        nxt = {'Thursday': 'Friday'}.get(day, None) or await pg.evaluate(f"PLAN_DAYS[(PLAN_DAYS.indexOf('{day}')+1)%7]")
        await pg.click('[data-daynav="1"]')
        await pg.wait_for_timeout(300)
        ok(f'› switches the editor to {nxt}', await label() == f'Edit {nxt}', await label())
        ok('…after saving the day you were editing', await pg.evaluate(f"dayPlanForWeek('{day}',1).description") == 'nav test')
        ok(f'…and {nxt}\'s exercises are loaded', await pg.evaluate(NAMES) == await plan_names(pg, nxt))
        await pg.click('#toast .toast-action')
        await pg.wait_for_timeout(250)
        ok('Undo on that toast restores the previous description', await pg.evaluate(f"dayPlanForWeek('{day}',1).description") == orig_desc)
        bar = await pg.locator('#dayNav .muted').bounding_box()
        cx, cy = bar['x'] + bar['width'] / 2, bar['y'] + bar['height'] / 2
        await pg.mouse.move(cx, cy); await pg.mouse.down(); await pg.mouse.move(cx - 120, cy, steps=6); await pg.mouse.up()
        await pg.wait_for_timeout(300)
        after_next = await pg.evaluate(f"PLAN_DAYS[(PLAN_DAYS.indexOf('{nxt}')+1)%7]")
        ok('swiping left on the bar goes to the next day', await label() == f'Edit {after_next}', await label())
        bar = await pg.locator('#dayNav .muted').bounding_box()
        cx, cy = bar['x'] + bar['width'] / 2, bar['y'] + bar['height'] / 2
        await pg.mouse.move(cx, cy); await pg.mouse.down(); await pg.mouse.move(cx + 120, cy, steps=6); await pg.mouse.up()
        await pg.wait_for_timeout(300)
        ok('swiping right goes back', await label() == f'Edit {nxt}', await label())
        await close_editor(pg)

        ok('no page errors or console errors', not errors, errors)
        await b.close()


asyncio.run(main())
print()
if FAILS:
    print(f'{len(FAILS)} check(s) FAILED')
    sys.exit(1)
print('All checks passed')
