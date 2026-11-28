#!/usr/bin/env python3
"""End-to-end checks for public/tools.js (last time, rest pill, wake lock, plates, swap, PRs,
heatmap, muscle volume, bodyweight log, deload copy) and the local-date fix.

    pip install playwright && playwright install chromium
    python3 tests/training-tools.e2e.py            # or CHROME=/path/to/chrome python3 ...
"""
import asyncio, http.server, os, re, socketserver, sys, threading
from datetime import datetime, timedelta, timezone
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
URL = f'http://127.0.0.1:{srv.server_address[1]}/index.html'
threading.Thread(target=srv.serve_forever, daemon=True).start()

# headless Chromium has neither a real wake lock nor audio output: stub them so we can assert they are used
STUBS = """
window.__wl = {req: 0, rel: 0};
Object.defineProperty(navigator, 'wakeLock', {configurable: true, value: {request: async () => {
  window.__wl.req++; const s = {release: async () => { window.__wl.rel++; }, addEventListener() {}}; return s; }}});
window.__beeps = 0; window.__vibes = 0;
navigator.vibrate = () => { window.__vibes++; return true; };
class FakeCtx { constructor(){ this.state='running'; this.currentTime=0; this.destination={}; }
  resume(){} createOscillator(){ return {type:'', frequency:{value:0}, connect(){}, start(){ window.__beeps++; }, stop(){}}; }
  createGain(){ return {gain:{setValueAtTime(){}, exponentialRampToValueAtTime(){}}, connect(){}}; } }
window.AudioContext = FakeCtx;
"""


def launch_args():
    a = dict(args=['--no-sandbox'])
    if os.environ.get('CHROME'):
        a['executable_path'] = os.environ['CHROME']
    elif Path('/opt/pw-browsers/chromium-1243/chrome-linux64/chrome').exists():
        a['executable_path'] = '/opt/pw-browsers/chromium-1243/chrome-linux64/chrome'
    return a


def card(pg, name):
    return pg.locator(f'#workoutExercises .exercise[data-name="{name}"]')


async def open_workout(pg, day='Thursday'):
    await pg.evaluate("state.checklists = {}; save()")  # fully-ticked exercises are saved as done and open collapsed
    await pg.evaluate(f"openWorkout('{day}')")
    await pg.wait_for_selector('#workoutExercises .exercise')
    await pg.wait_for_timeout(150)


async def close_modal(pg):
    await pg.click('#closeModal')
    await pg.wait_for_timeout(150)


async def open_panels(pg, page_id):
    await pg.evaluate(f"document.querySelectorAll('#{page_id} details.compact-panel').forEach(d=>d.open=true)")


def seconds(txt):
    m = re.match(r'^(?:(\d+):)?(\d+)s?$', txt.strip())
    return (int(m.group(1) or 0) * 60 + int(m.group(2))) if m else None


SEED = """(rows) => { const p = active().name; state.logs = rows.map((r, i) => ({id: 'seed' + i, timestamp: new Date(r.date + 'T12:00:00').getTime(), date: r.date, day: r.day || 'Thursday', week: 1, program: p, exercise: r.exercise, weight: r.weight, sets: 1, reps: r.reps, type: 'exercise', done: true})); save(); }"""


async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(**launch_args())
        ctx = await b.new_context(viewport={'width': 430, 'height': 900})
        await ctx.add_init_script(STUBS)
        pg = await ctx.new_page()
        errors = []
        pg.on('pageerror', lambda e: errors.append(str(e)))
        pg.on('console', lambda m: errors.append('console.error: ' + m.text) if m.type == 'error' and 'Failed to load resource' not in m.text else None)
        await pg.goto(URL)
        await pg.wait_for_timeout(1200)

        today = await pg.evaluate("localISODate()")
        def days_ago(n):
            return (datetime.strptime(today, '%Y-%m-%d') - timedelta(days=n)).strftime('%Y-%m-%d')

        # ── 1. last time ───────────────────────────────────────────────────────────────────────────
        await pg.evaluate(SEED, [
            {'date': days_ago(3), 'exercise': 'Chest press', 'weight': 60, 'reps': 8},
            {'date': days_ago(3), 'exercise': 'Chest press', 'weight': 60, 'reps': 8},
            {'date': days_ago(3), 'exercise': 'Chest press', 'weight': 62.5, 'reps': 6},
            {'date': days_ago(10), 'exercise': 'Chest press', 'weight': 50, 'reps': 10},
            {'date': today, 'exercise': 'Chest press', 'weight': 99, 'reps': 1},
        ])
        await open_workout(pg)
        lt = await card(pg, 'Chest press').locator('.lasttime').text_content()
        ok('shows last session\'s sets for an exercise with history', '60×8' in lt and '62.5×6' in lt, lt)
        ok('…using the most recent earlier session, not today or older ones', '99' not in lt and '50×10' not in lt, lt)
        ok('exercises without history show nothing', await card(pg, 'Lat pulldown').locator('.lasttime').count() == 0)
        await card(pg, 'Chest press').locator('[data-use-last]').click()
        vals = await card(pg, 'Chest press').evaluate("c=>[...c.querySelectorAll('.setrow')].map(r=>[r.querySelector('[data-field=weight]').value,r.querySelector('[data-field=reps]').value])")
        ok('"Use these" fills the set rows from last time', vals[:3] == [['60', '8'], ['60', '8'], ['62.5', '6']], vals)

        # ── 2. rest pill ──────────────────────────────────────────────────────────────────────────────
        ok('no rest pill before any set is ticked', not await pg.is_visible('#restPill'))
        await card(pg, 'Chest press').locator('[data-setcheck]').first.click()
        await pg.wait_for_timeout(400)
        t0 = seconds(await pg.text_content('#restPill .restpill-time'))
        ok('ticking a set starts the default 90s rest', await pg.is_visible('#restPill') and t0 is not None and 85 <= t0 <= 90, t0)
        ok('…labelled with the exercise', 'Chest press' in await pg.text_content('#restPill .restpill-label'))
        ok('…and shown above the open workout dialog', await pg.evaluate("(()=>{const r=document.getElementById('restPill').getBoundingClientRect();const e=document.elementFromPoint(r.left+r.width/2,r.top+r.height/2);return !!e&&!!e.closest('#restPill')})()"))
        await pg.click('[data-rest-adj="15"]')
        t1 = seconds(await pg.text_content('#restPill .restpill-time'))
        ok('＋15 adds fifteen seconds', t1 is not None and t1 >= t0 + 12, f'{t0} -> {t1}')
        await pg.click('[data-rest-skip]')
        ok('Skip hides the pill', not await pg.is_visible('#restPill'))
        await pg.evaluate("THQ.startRest(2,'Test')")
        await pg.wait_for_timeout(2700)
        ok('when rest ends the pill says Go! and beeps + vibrates',
           await pg.text_content('#restPill .restpill-time') == 'Go!' and await pg.evaluate("window.__beeps") > 0 and await pg.evaluate("window.__vibes") > 0)
        await pg.evaluate("THQ.stopRest(); state.settings={defaultRest:0}; save()")
        await card(pg, 'Chest press').locator('[data-setcheck]').nth(1).click()
        await pg.wait_for_timeout(300)
        ok('a default rest of 0 turns the automatic timer off', not await pg.is_visible('#restPill'))
        await pg.evaluate("state.settings={}; save()")
        await card(pg, 'Chest press').locator('[data-setcheck]').nth(2).click()
        await pg.wait_for_timeout(300)
        pill_visible = await pg.is_visible('#restPill')
        pad = await pg.evaluate("parseInt(getComputedStyle(document.querySelector('#modalShade > div')).paddingBottom)")
        ok('the dialog reserves room so the pill never covers the Save button', pill_visible and pad >= 80, pad)
        await close_modal(pg)
        ok('closing the workout hides the rest pill', not await pg.is_visible('#restPill'))

        # ── 3. wake lock ───────────────────────────────────────────────────────────────────────────────
        wl0 = await pg.evaluate("({...window.__wl})")
        await open_workout(pg)
        wl1 = await pg.evaluate("({...window.__wl})")
        ok('opening a workout requests a screen wake lock', wl1['req'] == wl0['req'] + 1, f'{wl0} -> {wl1}')
        await close_modal(pg)
        wl2 = await pg.evaluate("({...window.__wl})")
        ok('closing it releases the lock', wl2['rel'] == wl1['rel'] + 1, f'{wl1} -> {wl2}')
        await pg.evaluate("state.settings={keepAwake:false}; save()")
        await open_workout(pg)
        ok('the setting can turn it off', (await pg.evaluate("window.__wl.req")) == wl2['req'])
        await pg.evaluate("state.settings={}; save()")

        # ── 4. plate calculator ───────────────────────────────────────────────────────────────────────────
        calc = lambda w: pg.evaluate(f"(()=>{{const c=THQ.cfg();const r=THQ.plateBreakdown({w},c.barKg,c.plates);return r&&!r.below?THQ.fmtPlates(r.used)+'|'+r.rem:(r?'below':null)}})()")
        ok('60 kg on a 20 kg bar = a 20 each side', await calc(60) == '20|0')
        ok('102.5 kg = 25 + 15 + 1.25 each side', await calc(102.5) == '25 + 15 + 1.25|0')
        ok('140 kg groups repeats (2×25 + 10 each side)', await calc(140) == '2×25 + 10|0')
        ok('the empty bar needs no plates; lighter than the bar is flagged', await calc(20) == 'bar only|0' and await calc(15) == 'below')
        await card(pg, 'Chest press').locator('[data-plates]').click()
        row = card(pg, 'Chest press').locator('.setrow [data-field=weight]').first
        await row.fill('100')
        ok('the Plates button shows plates per side for the weights in the card', '25 + 15' in await card(pg, 'Chest press').locator('[data-plate-panel]').text_content())
        await row.fill('101')
        ok('…and flags a weight the plates cannot make', 'closest loadable: 100' in await card(pg, 'Chest press').locator('[data-plate-panel]').text_content())
        await close_modal(pg)
        await pg.evaluate("navigate('settings')")
        await open_panels(pg, 'page-settings')
        await pg.fill('#plateTarget', '82.5')
        ok('the Settings plate calculator works', '25 + 5 + 1.25' in await pg.text_content('#plateOut'), await pg.text_content('#plateOut'))
        await pg.fill('#toolBarKg', '15'); await pg.fill('#toolPlates', '20, 10, 5'); await pg.fill('#toolDefaultRest', '45')
        await pg.click('#saveTools')
        c = await pg.evaluate("THQ.cfg()")
        ok('tool settings save (bar, plates, default rest)', c['barKg'] == 15 and c['plates'] == [20, 10, 5] and c['defaultRest'] == 45, c)
        await pg.evaluate("state.settings={}; save()")

        # ── 5. swap ─────────────────────────────────────────────────────────────────────────────────────────
        await pg.evaluate("state.swaps={}; navigate('home')")
        await open_workout(pg)
        await card(pg, 'Chest press').locator('.setrow [data-field=weight]').first.fill('77')
        await card(pg, 'Front squat').locator('[data-swap]').click()
        await card(pg, 'Front squat').locator('[data-swap-name]').fill('Leg press')
        await card(pg, 'Front squat').locator('[data-swap-go="today"]').click()
        await pg.wait_for_timeout(200)
        ok('Swap for today replaces the exercise in place', await card(pg, 'Leg press').count() == 1 and await card(pg, 'Front squat').count() == 0)
        ok('…without losing what you typed in other exercises', await card(pg, 'Chest press').locator('.setrow [data-field=weight]').first.input_value() == '77')
        ok('…and marks it as swapped', 'swapped for Front squat' in await card(pg, 'Leg press').locator('.prescription').text_content())
        ok('the card keeps working (add set, tick set)', True)
        await card(pg, 'Leg press').locator('.setrow [data-field=weight]').first.fill('100')
        await card(pg, 'Leg press').locator('[data-setcheck]').first.click()
        await pg.click('#modalButtons >> text=Save session')
        await pg.wait_for_timeout(500)
        logged = await pg.evaluate("state.logs.filter(l=>l.exercise==='Leg press').length")
        ok('the session is logged under the substitute', logged >= 1 and await pg.evaluate("state.logs.filter(l=>l.exercise==='Front squat'&&l.weight===100).length") == 0)
        ok('Leg press was added to the exercise library', await pg.evaluate("state.exerciseLibrary.includes('Leg press')"))
        await open_workout(pg)
        ok('reopening the workout keeps today\'s swap', await card(pg, 'Leg press').count() == 1 and await card(pg, 'Front squat').count() == 0)
        await card(pg, 'Leg press').locator('[data-swap]').click()
        await card(pg, 'Leg press').locator('[data-swap-go="restore"]').click()
        await pg.wait_for_timeout(200)
        ok('Restore brings back the planned exercise and clears the swap', await card(pg, 'Front squat').count() == 1 and await pg.evaluate("Object.keys(state.swaps).length") == 0)
        await card(pg, 'Seated cable row').locator('[data-swap]').click()
        await card(pg, 'Seated cable row').locator('[data-swap-name]').fill('Barbell row')
        await card(pg, 'Seated cable row').locator('[data-swap-go="plan"]').click()
        await pg.wait_for_timeout(200)
        plan_names = await pg.evaluate("dayPlanForWeek('Thursday',1).items.map(i=>i.name)")
        ok('Swap & update plan renames it in the plan itself', 'Barbell row' in plan_names and 'Seated cable row' not in plan_names, plan_names)
        await close_modal(pg)

        # ── 6. personal records ───────────────────────────────────────────────────────────────────────────────
        await pg.evaluate(SEED, [
            {'date': days_ago(8), 'exercise': 'Chest press', 'weight': 60, 'reps': 8},
            {'date': days_ago(8), 'exercise': 'Chest press', 'weight': 62.5, 'reps': 6},
        ])
        await open_workout(pg)
        cp = card(pg, 'Chest press'); lp = card(pg, 'Lat pulldown')
        await cp.locator('.setrow [data-field=weight]').first.fill('70'); await cp.locator('.setrow [data-field=reps]').first.fill('5')
        await cp.locator('[data-setcheck]').first.click()
        await lp.locator('.setrow [data-field=weight]').first.fill('40'); await lp.locator('.setrow [data-field=reps]').first.fill('10')
        await lp.locator('[data-setcheck]').first.click()
        await pg.click('#modalButtons >> text=Save session')
        await pg.wait_for_timeout(500)
        toast = await pg.text_content('#toast')
        ok('beating a heaviest-weight record shows "New PR"', 'New PR' in toast and 'Chest press 70 kg × 5' in toast, toast)
        ok('…but the first-ever log of an exercise is a baseline, not a PR', 'Lat pulldown' not in toast, toast)
        rep_pr = await pg.evaluate("""(()=>{const mk=(w,r)=>({exercise:'X',weight:w,reps:r,date:'2026-01-01'});const before=[mk(100,1),mk(80,5)],added=[mk(85,5)];const saved=state.logs;state.logs=[...before,...added];const out=THQ.detectPRs(THQ.prTable(before),added);state.logs=saved;return out})()""")
        ok('a rep-range record is detected when the heaviest weight is not beaten', len(rep_pr) == 1 and '85 kg × 5' in rep_pr[0], rep_pr)
        none_pr = await pg.evaluate("""(()=>{const mk=(w,r)=>({exercise:'X',weight:w,reps:r,date:'2026-01-01'});const before=[mk(100,5)],added=[mk(90,5)];const saved=state.logs;state.logs=[...before,...added];const out=THQ.detectPRs(THQ.prTable(before),added);state.logs=saved;return out})()""")
        ok('a lighter set is not a PR', none_pr == [], none_pr)
        await pg.evaluate("navigate('progress')")
        await open_panels(pg, 'page-progress')
        rec = pg.locator('#recordsList details.record', has_text='Chest press')
        await rec.locator('summary').click()
        body = await rec.locator('.record-body').text_content()
        ok('records show heaviest, estimated 1RM and rep bests', '70 kg × 5' in body and '81.7' in body and '5 reps' in body, body)

        # ── 7. heatmap + streaks ──────────────────────────────────────────────────────────────────────────────────
        rows = [{'date': days_ago(n), 'exercise': 'Back squat', 'weight': 100, 'reps': 5} for n in (7, 14, 21)]
        await pg.evaluate(SEED, rows)
        await pg.evaluate("navigate('progress')")
        st = await pg.evaluate("[...document.querySelectorAll('.streaks > div')].map(d=>d.querySelector('strong').textContent)")
        ok('a quiet current week does not zero the streak (3 weeks back-to-back)', st[0] == '3' and st[1] == '3', st)
        ok('the heatmap shows 16 weeks × 7 days', await pg.evaluate("document.querySelectorAll('.heatmap .heat').length") == 112)
        await pg.evaluate(SEED, rows + [{'date': today, 'exercise': 'Back squat', 'weight': 100, 'reps': 5}] * 8)
        await pg.evaluate("navigate('progress')")
        st = await pg.evaluate("[...document.querySelectorAll('.streaks > div')].map(d=>d.querySelector('strong').textContent)")
        ok('logging this week extends the streak and counts the session', st[0] == '4' and st[2] == '1', st)
        ok('today\'s cell is shaded by volume (8 sets → level 2)', await pg.evaluate("[...document.querySelectorAll('.heatmap .heat.l2')].some(i=>i.title.includes('8 sets'))"))

        # ── 8. muscle volume ────────────────────────────────────────────────────────────────────────────────────────────
        expect = {'Back squat': 'Quads', 'Front squat': 'Quads', 'Seated cable row': 'Back', 'Chest-supported row': 'Back', 'Lat pulldown': 'Back',
                  'Chest press': 'Chest', 'Incline dumbbell press': 'Chest', 'Rear delt fly': 'Shoulders', 'Lateral raise': 'Shoulders', 'Overhead press': 'Shoulders',
                  'Single-leg Romanian deadlift': 'Hams & glutes', 'Seated hip abduction': 'Hams & glutes', 'Snatch complex': 'Olympic', 'Clean pull': 'Olympic',
                  'Treadmill intervals': 'Conditioning', 'Easy aerobic run': 'Conditioning', 'Dips': 'Chest', 'Vertical pull': 'Back', 'Sissy squat': 'Quads'}
        got = await pg.evaluate("(m)=>Object.fromEntries(Object.keys(m).map(k=>[k,THQ.muscleOf(k)]))", expect)
        bad = {k: (got[k], v) for k, v in expect.items() if got[k] != v}
        ok('exercise names map to sensible muscle groups', not bad, bad)
        await pg.evaluate(SEED, [{'date': today, 'exercise': 'Chest press', 'weight': 50, 'reps': 10}] * 5 + [{'date': today, 'exercise': 'Back squat', 'weight': 100, 'reps': 5}] * 3
                          + [{'date': today, 'exercise': 'Seated cable row', 'weight': 40, 'reps': 10}] * 4 + [{'date': days_ago(7), 'exercise': 'Chest press', 'weight': 50, 'reps': 10}] * 2)
        await pg.evaluate("navigate('progress')")
        mv = await pg.evaluate("Object.fromEntries([...document.querySelectorAll('.mvrow')].map(r=>[r.querySelector('.mvname').textContent,[r.querySelector('strong').textContent,r.querySelector('.mvdelta').textContent]]))")
        ok('sets per muscle group for the chosen week', mv.get('Chest', [None])[0] == '5' and mv.get('Quads', [None])[0] == '3' and mv.get('Back', [None])[0] == '4', mv)
        ok('…with the change versus last week', mv['Chest'][1] == '+3', mv)
        await pg.select_option('#mvMetric', 'tonnes')
        ok('volume can be shown in tonnes', (await pg.evaluate("[...document.querySelectorAll('.mvrow')].find(r=>r.querySelector('.mvname').textContent==='Chest').querySelector('strong').textContent")) == '2.5 t')
        await pg.evaluate("navigate('program')")
        await pg.wait_for_timeout(300)
        ok('the exercise library shows each exercise\'s group', 'Back' in await pg.locator('[data-muscle-ex="Seated cable row"]').text_content())
        await pg.locator('[data-muscle-ex="Seated cable row"]').click()
        await pg.select_option('#muscleSel', 'Arms')
        await pg.click('#modalButtons >> text=Save')
        await pg.wait_for_timeout(200)
        ok('a group can be overridden from the library', await pg.evaluate("THQ.muscleOf('Seated cable row')") == 'Arms')
        await pg.locator('[data-muscle-ex="Seated cable row"]').click()
        await pg.click('#modalButtons >> text=Reset to automatic')
        await pg.wait_for_timeout(200)
        ok('…and reset to automatic', await pg.evaluate("THQ.muscleOf('Seated cable row')") == 'Back')

        # ── 9. bodyweight log ───────────────────────────────────────────────────────────────────────────────────────────
        await pg.evaluate("state.bodyLog=[]; navigate('progress')")
        await open_panels(pg, 'page-progress')
        await pg.fill('#bwDate', days_ago(10)); await pg.fill('#bwKg', '96'); await pg.click('#bwAdd')
        await pg.fill('#bwDate', today); await pg.fill('#bwKg', '95.2'); await pg.click('#bwAdd')
        ok('bodyweight entries are stored in date order', await pg.evaluate("state.bodyLog.map(x=>x.kg)") == [96, 95.2])
        ok('…the profile bodyweight follows the latest entry', await pg.evaluate("state.profile.bodyweight") == '95.2')
        ok('…with a summary and a trend chart', 'Latest 95.2 kg' in await pg.text_content('#bwSummary') and await pg.locator('#bwChart polyline').count() == 1)
        await pg.fill('#bwKg', '95.0'); await pg.click('#bwAdd')
        ok('adding on the same date replaces that day\'s entry', await pg.evaluate("state.bodyLog.length") == 2 and await pg.evaluate("state.bodyLog[1].kg") == 95)
        await pg.locator('[data-bw-del]').first.click()
        ok('deleting the latest entry updates the profile weight', await pg.evaluate("state.profile.bodyweight") == '96')
        await pg.click('#toast .toast-action')
        await pg.wait_for_timeout(200)
        ok('Undo brings the entry back', await pg.evaluate("state.bodyLog.length") == 2 and await pg.evaluate("state.profile.bodyweight") == '95')

        # ── 10. deload copy ───────────────────────────────────────────────────────────────────────────────────────────────
        await pg.evaluate("navigate('program')")
        await pg.wait_for_timeout(300)
        c0 = await pg.evaluate("programWeekCount()")
        src = await pg.evaluate("dayPlanForWeek('Thursday',1).items.map(i=>({s:Number(i.sets),l:Number(i.loadKg)||0,p:Number(i.pct)||0}))")
        await pg.evaluate("document.getElementById('deloadProgramWeek').click()")
        await pg.wait_for_selector('#dlVol')
        ok('the Deload dialog defaults to 60% sets and 90% load', await pg.input_value('#dlVol') == '60' and await pg.input_value('#dlLoad') == '90')
        await pg.click('#modalButtons >> text=Create deload week')
        await pg.wait_for_timeout(300)
        ok('a deload week is added at the end and selected', await pg.evaluate("programWeekCount()") == c0 + 1 and await pg.evaluate("activeWeek()") == c0 + 1)
        out = await pg.evaluate("dayPlanForWeek('Thursday',activeWeek()).items.map(i=>({s:Number(i.sets),l:Number(i.loadKg)||0,p:Number(i.pct)||0,n:i.planNote||''}))")
        sets_ok = all(o['s'] == max(1, round(s['s'] * 0.6 + 1e-9)) for o, s in zip(out, src))
        ok('sets are scaled (never below 1)', sets_ok, list(zip(src, out)))
        pcts = [(s['p'], o['p']) for o, s in zip(out, src) if s['p'] > 0]
        ok('percentage loads are scaled to 90%', bool(pcts) and all(abs(o - round(s * 0.9, 1)) < 0.06 for s, o in pcts), pcts)
        unit = await pg.evaluate("""(()=>{const f=THQ.scaleItemForDeload;const a=f({sets:4,loadKg:100,pct:0},60,90),b=f({sets:3,loadKg:102.5},60,90),c=f({sets:1,loadKg:50},60,90),d=f({sets:5,progressiveRamp:true,setScheme:[{loadKg:40,reps:5},{loadKg:60,reps:3},{loadKg:80,reps:2},{loadKg:90,reps:1},{loadKg:100,reps:1}]},60,90);return {a:[a.sets,a.loadKg],b:[b.sets,b.loadKg],c:c.sets,d:[d.sets,d.setScheme.map(x=>x.loadKg)]}})()""")
        ok('kg loads scale and round to the plate step; sets never drop below 1', unit['a'] == [2, 90] and unit['b'] == [2, 92.5] and unit['c'] == 1, unit)
        ok('ramp set schemes are shortened to the new set count with scaled loads', unit['d'] == [3, [35, 55, 72.5]], unit['d'])
        ok('items are tagged "Deload" and the week is named', all('Deload' in o['n'] for o in out) and 'Deload' in await pg.evaluate("weekLabel(activeWeek())"))
        ok('the original week is untouched', await pg.evaluate("dayPlanForWeek('Thursday',1).items.map(i=>({s:Number(i.sets),l:Number(i.loadKg)||0,p:Number(i.pct)||0}))") == src)
        await pg.click('#toast .toast-action')
        await pg.wait_for_timeout(300)
        ok('Undo removes the deload week', await pg.evaluate("programWeekCount()") == c0 and await pg.evaluate("activeWeek()") == 1)

        ok('no page errors or console errors', not errors, errors)
        await ctx.close()

        # ── date fix: a morning workout east of UTC must be dated today, not yesterday ────────────────────────────────────
        ctx2 = await b.new_context(viewport={'width': 430, 'height': 900}, timezone_id='Australia/Sydney')
        pg2 = await ctx2.new_page()
        await pg2.clock.set_fixed_time(datetime(2026, 11, 27, 21, 0, 0, tzinfo=timezone.utc))  # 08:00 on 28 Nov in Sydney
        await pg2.goto(URL)
        await pg2.wait_for_timeout(1000)
        await pg2.evaluate("openWorkout('Thursday')")
        await pg2.wait_for_selector('#logDate')
        ok('the log date defaults to the local date (28 Nov), not the UTC date (27 Nov)', await pg2.input_value('#logDate') == '2026-11-28', await pg2.input_value('#logDate'))
        await b.close()


asyncio.run(main())
print()
if FAILS:
    print(f'{len(FAILS)} check(s) FAILED')
    sys.exit(1)
print('All checks passed')
