from pathlib import Path
p=Path('public/app.js')
s=p.read_text()
# Add progressive ramp materialisation helper and call it for every week.
old="function materializeProgressionWeeks(){const p=active();p.weekPlans=p.weekPlans||{};const count=programWeekCount(p);for(let w=1;w<=count;w++){if(w===1)continue;const plan={};for(const day of ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday']){const base=p.days?.[day]||{type:'',description:'',items:[]};plan[day]={...structuredClone(base),items:(base.items||[]).map(it=>weeklyItem(it,day,w))};}p.weekPlans[String(w)]=plan;}p.weekCount=count;}"
new="function rampProgressionRule(week,p=active()){const w=Math.max(1,Number(week)||1);if((p?.progressionEngine||'off')==='builtin'){const factors=[1,1.025,1.05,.9,1.075,1.1,1.125,.95,1.15,1.175,1.2,.9];return {factor:factors[Math.min(w-1,11)]||1,add:0};}const engine=state.progressionEngines.find(e=>e.id===p?.progressionEngine);const rule=engine?.weeks?.[Math.min(w-1,(engine?.weeks?.length||1)-1)]||{};return {factor:Number(rule.loadChangeKg||0)!==0?1:Number(rule.intensity??100)/100,add:Number(rule.loadChangeKg)||0};}\nfunction applyRampProgression(item,week,p=active()){if(!item?.progressiveRamp||!Array.isArray(item.setScheme)||!item.setScheme.length)return item;const {factor,add}=rampProgressionRule(week,p);item.setScheme=item.setScheme.map(row=>({...row,loadKg:Number(row.loadKg)>0?roundWeight(Math.max(0,Number(row.loadKg)*factor+add)):0}));item.sets=item.setScheme.length;return item;}\nfunction materializeProgressionWeeks(){const p=active();p.weekPlans=p.weekPlans||{};const count=programWeekCount(p);for(let w=1;w<=count;w++){if(w===1)continue;const plan={};for(const day of ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday']){const base=p.days?.[day]||{type:'',description:'',items:[]};plan[day]={...structuredClone(base),items:(base.items||[]).map(it=>applyRampProgression(weeklyItem(it,day,w),w,p))};}p.weekPlans[String(w)]=plan;}p.weekCount=count;}"
assert old in s
s=s.replace(old,new)
# Replace day cards with horizontal day columns and per-exercise direct edit selection.
old="document.getElementById('programDays').innerHTML=['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'].map(d=>{let p=dayPlanForWeek(d,activeWeek())||{items:[]};return `<button class=\"card full\" style=\"display:block;text-align:left;margin-bottom:8px;color:var(--text)\" data-editday=\"${d}\"><div class=\"exercisehead\"><div><strong>${d}</strong><div class=\"muted small\">${esc(p.type||'No session type')} · ${(p.items||[]).length} exercises</div></div><span class=\"muted\">✎</span></div><div class=\"muted small\" style=\"margin-top:7px\">${(p.items||[]).slice(0,4).map(x=>esc(x.name)).join(' · ')}${p.items?.length>4?' …':''}</div></button>`}).join('');document.querySelectorAll('[data-editday]').forEach(b=>b.onclick=()=>openDayEditor(b.dataset.editday));"
new="document.getElementById('programDays').innerHTML=`<div class=\"program-day-strip\">${['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'].map(d=>{const plan=dayPlanForWeek(d,activeWeek())||{items:[]};return `<section class=\"card program-day-card\"><button type=\"button\" class=\"program-day-heading\" data-editday=\"${d}\"><strong>${d}</strong><span>${esc(plan.type||'No session type')} · ${(plan.items||[]).length} exercises</span><small>Edit day details</small></button><div class=\"program-day-exercises\">${(plan.items||[]).length?(plan.items||[]).map((it,i)=>`<button type=\"button\" class=\"program-exercise-link\" data-edit-exercise-day=\"${d}\" data-edit-exercise-index=\"${i}\"><span>${esc(it.name)}</span><small>${Number(it.sets)||1} × ${esc(it.reps||'—')}${Number(it.loadKg)>0?' · '+roundWeight(it.loadKg)+' kg':it.pct?' · '+it.pct+'%':''}</small></button>`).join(''):'<div class=\"muted small\">No exercises planned</div>'}<button type=\"button\" class=\"btn ghost full\" data-editday=\"${d}\">＋ Add / edit day</button></div></section>`}).join('')}</div>`;document.querySelectorAll('[data-editday]').forEach(b=>b.onclick=()=>openDayEditor(b.dataset.editday));document.querySelectorAll('[data-edit-exercise-day]').forEach(b=>b.onclick=()=>openDayEditor(b.dataset.editExerciseDay,Number(b.dataset.editExerciseIndex)));"
assert old in s
s=s.replace(old,new)
# Day editor supports a preselected exercise to expand.
s=s.replace('function openDayEditor(day){const editWeek=activeWeek();','function openDayEditor(day,selectedExerciseIndex=null){const editWeek=activeWeek();')
# after modal() and before add button event binding: add selected details open logic
needle="document.getElementById('addProgramItem').onclick=()=>{const container=document.getElementById('editItems');"
replacement="if(selectedExerciseIndex!==null){const selectedCard=document.querySelectorAll('#editItems .edititem')[selectedExerciseIndex];if(selectedCard){selectedCard.open=true;selectedCard.scrollIntoView({block:'nearest'});}}document.getElementById('addProgramItem').onclick=()=>{const container=document.getElementById('editItems');"
assert needle in s
s=s.replace(needle,replacement)
# Make each exercise editor an individually expandable item. Use details root while preserving .edititem selectors.
s=s.replace('return `<div class=\"edititem\" data-superset-group=\"${esc(it.supersetGroup||\'\')}\" style=\"border:1px solid var(--line);border-radius:12px;padding:10px;margin-bottom:8px\"><div style=\"display:flex;align-items:center;gap:8px;margin-bottom:10px\"><button type=\"button\" class=\"draghandle\" data-drag-handle aria-label=\"Drag to reorder exercise\" title=\"Drag to reorder\">⠿</button><span class=\"muted small\">Drag to reorder</span><button type=\"button\" class=\"btn\" data-create-superset style=\"padding:6px 9px;font-size:11px\">＋ Superset</button></div>', 'return `<details class=\"edititem\" data-superset-group=\"${esc(it.supersetGroup||\'\')}\" style=\"border:1px solid var(--line);border-radius:12px;padding:10px;margin-bottom:8px\"><summary class=\"edititem-summary\">${esc(it.name||\'New exercise\')} <span class=\"muted small\">· ${Number(it.sets)||1} sets</span></summary><div class=\"edititem-body\"><div style=\"display:flex;align-items:center;gap:8px;margin:10px 0\"><button type=\"button\" class=\"draghandle\" data-drag-handle aria-label=\"Drag to reorder exercise\" title=\"Drag to reorder\">⠿</button><span class=\"muted small\">Drag to reorder</span><button type=\"button\" class=\"btn\" data-create-superset style=\"padding:6px 9px;font-size:11px\">＋ Superset</button></div>')
s=s.replace('</button></div>`}\nfunction checklistKey', '</button></div></div></details>`}\nfunction checklistKey')
# Keep summary live as name changes, and don't auto-scroll all exercise cards.
needle="const editItems=document.getElementById('editItems');function refreshEditorSupersetStyles(){"
replacement="const editItems=document.getElementById('editItems');editItems.addEventListener('input',e=>{const card=e.target.closest('.edititem');if(!card)return;const name=card.querySelector('[data-k=name]')?.value.trim()||'New exercise';const sets=card.querySelector('[data-k=sets]')?.value||'1';const summary=card.querySelector('summary');if(summary)summary.innerHTML=esc(name)+' <span class=\"muted small\">· '+esc(sets)+' sets</span>';});function refreshEditorSupersetStyles(){"
assert needle in s
s=s.replace(needle,replacement)
# Remove the misleading LOAD badge from the exercise list; category is not an action.
s=s.replace("<span class=\"badge\">${isDone?'DONE':Number(it.loadKg)>0?'LOAD':it.pct?esc(prescribed(it).split(' · ')[0]):it.name.toLowerCase().includes('treadmill')?'CARDIO':'ACCESSORY'}</span>","<span class=\"badge\">${isDone?'DONE':it.name.toLowerCase().includes('treadmill')?'CARDIO':'PLANNED'}</span>")
# Explicitly remove any legacy inert button labelled Load if one is present in the logging modal.
needle="modal((exerciseIndex===null?'Log '+day+' workout':'Log '+activeWorkout.items[0]?.name),body,[{label:'Cancel',cls:'btn ghost',action:closeModal},{label:exerciseIndex===null?'Save session':'Save exercise',cls:'btn primary',action:saveWorkout}]);document.querySelectorAll('[data-addset]')"
replacement="modal((exerciseIndex===null?'Log '+day+' workout':'Log '+activeWorkout.items[0]?.name),body,[{label:'Cancel',cls:'btn ghost',action:closeModal},{label:exerciseIndex===null?'Save session':'Save exercise',cls:'btn primary',action:saveWorkout}]);document.querySelectorAll('#workoutExercises button').forEach(b=>{if(/^load$/i.test(b.textContent.trim()))b.remove()});document.querySelectorAll('[data-addset]')"
assert needle in s
s=s.replace(needle,replacement)
# Add collapsible settings/progress panels after page initialisation helpers are available.
insert="""
function compressDashboardPanels(){
 const wrap=(container,selector,labelFor)=>{if(!container)return;[...container.querySelectorAll(':scope > '+selector)].forEach((node,index)=>{if(node.parentElement?.classList.contains('compact-panel-body')||node.classList.contains('compact-panel'))return;const details=document.createElement('details');details.className='compact-panel';const summary=document.createElement('summary');summary.className='compact-panel-summary';summary.textContent=labelFor(node,index);const body=document.createElement('div');body.className='compact-panel-body';node.parentNode.insertBefore(details,node);details.append(summary,body);body.appendChild(node);});};
 const settings=document.getElementById('page-settings');wrap(settings,'.card',(node,i)=>node.querySelector('h3')?.textContent?.trim()||['Sync','Google Drive backup'][i]||'Settings');
 const progress=document.getElementById('page-progress');wrap(progress,'.card',(node,i)=>node.querySelector('h2')?.textContent?.trim()||(['Lift trend','Training consistency','Personal records'][i]||'Progress'));}
"""
marker="function renderSettings(){"
assert marker in s
s=s.replace(marker,insert+marker)
# invoke after page initial load before render
s=s.replace("render();\n", "render();\n",1) # noop
# find bottom render call
idx=s.rfind('render();')
if idx!=-1:s=s[:idx]+'compressDashboardPanels();'+s[idx:]
p.write_text(s)
