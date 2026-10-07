'use strict';
const $=s=>document.querySelector(s),token=$('meta[name="api-token"]').content;
let report=null,csvText=null,runBusy=false,uploadBusy=false,uploadVersion=0;
const money=n=>new Intl.NumberFormat('en-US',{style:'currency',currency:'USD',maximumFractionDigits:2}).format(n);
const pct=n=>(n>=0?'+':'')+n.toFixed(2)+'%';
const date=s=>s.slice(0,10);
function error(message){$('#error').textContent=message;$('#error').hidden=!message}
async function request(path,body){const response=await fetch(path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-Scout-Token':token},body:JSON.stringify(body)});const value=await response.json();if(!response.ok)throw Error(value.error||'Request failed.');return value}
function cell(row,text,kind='td'){const c=document.createElement(kind);c.textContent=text;row.append(c);return c}
function list(target,items){target.replaceChildren();for(const text of items){const li=document.createElement('li');li.textContent=text;target.append(li)}}
function tone(el,value){el.classList.toggle('loss',value<0);el.classList.toggle('gain',value>=0)}
function chart(){const svg=$('#equity-chart'),ns='http://www.w3.org/2000/svg';svg.replaceChildren();const paths=[report.combined.curve,report.benchmark_curve];const all=paths.flat();if(!all.length)return;
 const values=all.map(p=>p.equity),low=Math.min(...values),high=Math.max(...values),pad=Math.max(1,(high-low)*.15),ymin=low-pad,ymax=high+pad;
 const times=all.map(p=>Date.parse(p.timestamp)),xmin=Math.min(...times),xmax=Math.max(...times);
 const x=p=>57+(Date.parse(p.timestamp)-xmin)/(xmax-xmin||1)*720,y=n=>244-(n-ymin)/(ymax-ymin)*214;
 const make=(tag,attrs,text)=>{const node=document.createElementNS(ns,tag);for(const[k,v]of Object.entries(attrs))node.setAttribute(k,String(v));if(text!==undefined)node.textContent=text;svg.append(node);return node};
 for(let k=0;k<5;k++){const value=ymin+(ymax-ymin)*k/4,py=y(value);make('line',{x1:57,x2:777,y1:py,y2:py,stroke:'#2c3e51','stroke-dasharray':'3 5'});make('text',{x:0,y:py+3,fill:'#7c94aa','font-size':9,'font-family':'monospace'},'$'+value.toFixed(0))}
 for(let i=1;i>=0;i--)make('path',{d:paths[i].map((p,k)=>(k?'L':'M')+x(p).toFixed(2)+','+y(p.equity).toFixed(2)).join(' '),fill:'none',stroke:i?'#bca0eb':'#8bd8b6','stroke-width':i?1.5:2.5});
 make('text',{x:57,y:269,fill:'#7c94aa','font-size':9,'font-family':'monospace'},date(report.split_at));make('text',{x:777,y:269,'text-anchor':'end',fill:'#7c94aa','font-size':9,'font-family':'monospace'},date(report.end));
}
function render(){const r=report,c=r.combined;
 $('#source-title').textContent=r.source==='synthetic_demo'?'INVENTED DEMO / NOT A PROFITABILITY CLAIM':'IMPORTED DATA / PROVENANCE NOT VERIFIED';
 $('#source-copy').textContent=r.source==='synthetic_demo'?'These assets and prices are fictional. Use them to check the workflow, then import real historical data.':'CSV loaded locally. Results depend on your timestamps, USD pricing, corporate-action adjustments and cost assumptions.';
 $('#data-period').textContent=date(r.start)+' → '+date(r.end);
 $('#net').textContent=money(c.net_profit);tone($('#net'),c.net_profit);$('#net-return').textContent=pct(c.net_return_pct)+' / estimated closeout equity '+money(c.final_equity);
 $('#drawdown').textContent=c.max_drawdown_pct.toFixed(2)+'%';$('#cost').textContent=money(c.fees_paid+c.slippage_cost+c.estimated_exit_cost);
 $('#risk').textContent=c.halted?'HALTED':'WITHIN LIMIT';$('#risk').classList.toggle('loss',c.halted);$('#risk-copy').textContent=c.halted?'Triggered '+date(c.halted_at)+'; exits wait for available bars.':'Entry caps active / '+(r.settings.max_drawdown*100).toFixed(0)+'% drawdown trigger';
 const comparisons=$('#comparison');comparisons.replaceChildren();for(const[key,label]of [['combined','Stocks + crypto'],['stocks_only','Stocks only'],['crypto_only','Crypto only'],['buy_and_hold','Buy & hold mix']]){const m=r.comparison[key],tr=document.createElement('tr');cell(tr,label);const ret=cell(tr,pct(m.net_return_pct));tone(ret,m.net_return_pct);cell(tr,m.max_drawdown_pct.toFixed(2)+'%');cell(tr,String(m.fill_count));comparisons.append(tr)}
 const candidates=$('#candidates');candidates.replaceChildren();for(const a of r.candidates){const tr=document.createElement('tr');if(a.selected)tr.classList.add('selected-row');const name=cell(tr,a.symbol+' / '+a.label);const tag=document.createElement('small');tag.textContent=a.asset_class.toUpperCase();name.append(tag);cell(tr,pct(a.training.net_return_pct));cell(tr,a.training.max_drawdown_pct.toFixed(2)+'%');cell(tr,pct(a.holdout_diagnostic.net_return_pct));cell(tr,a.selected?'TRAINING PICK':'Diagnostic');candidates.append(tr)}
 $('#selection-rule').textContent=r.selection_rule+' Holdout begins '+date(r.split_at)+'.';
 const selected=$('#selected');selected.replaceChildren();const labels={trend:'Trend',reversion:'Reversion',breakout:'Breakout',cash:'Cash'};for(const a of r.symbols){const row=document.createElement('div'),name=document.createElement('span'),small=document.createElement('small'),choice=document.createElement('strong');name.textContent=a.symbol;small.textContent=a.asset_class.toUpperCase()+' / '+a.bars+' BARS';name.append(small);choice.textContent=labels[a.selected_strategy];row.append(name,choice);selected.append(row)}
 const fills=$('#fills');fills.replaceChildren();if(!c.fills.length){const tr=document.createElement('tr'),td=cell(tr,'No fills. Staying in cash is a valid result.');td.colSpan=6;fills.append(tr)}for(const f of c.fills.slice(-300).reverse()){const tr=document.createElement('tr');cell(tr,date(f.timestamp));cell(tr,f.symbol);cell(tr,f.side.toUpperCase());cell(tr,f.quantity.toFixed(6));cell(tr,money(f.fill_price));cell(tr,money(f.fee));fills.append(tr)}
 $('#fill-caption').textContent='Showing latest '+Math.min(300,c.fills.length)+' of '+c.fills.length+' fills. Export JSON for full timestamps, assumptions, quantities and curves.';
 list($('#audit'),r.audit);list($('#limitations'),r.limitations);chart();$('#summarize').disabled=false;
}
function settings(){const value=id=>Number($('#'+id).value);return{capital:value('capital'),stock_weight:value('stock-weight')/100,crypto_weight:value('crypto-weight')/100,max_position:value('position-cap')/100,max_drawdown:value('drawdown-cap')/100,fees_bps:{stock:value('stock-fee'),crypto:value('crypto-fee')},slippage_bps:{stock:value('stock-slip'),crypto:value('crypto-slip')}}}
async function run(){if(runBusy||uploadBusy)return;runBusy=true;error('');$('#run-study').disabled=true;$('#reset-demo').disabled=true;$('#run-study').textContent='Testing…';try{const next=await request('/api/analyze',{settings:settings(),csv_text:csvText});report=next;$('#ai-notes').hidden=true;$('#ai-status').textContent='Optional. Review this report with an installed local model.';render()}catch(e){error(e.message+' Previous results are retained.')}finally{runBusy=false;$('#run-study').disabled=false;$('#reset-demo').disabled=false;$('#run-study').textContent='Run research'}}
$('#study-form').onsubmit=e=>{e.preventDefault();run()};
$('#csv').onchange=async()=>{const version=++uploadVersion;error('');const file=$('#csv').files[0];csvText=null;if(!file){uploadBusy=false;$('#run-study').disabled=runBusy;$('#reset-demo').disabled=runBusy;$('#file-state').textContent='No upload: deterministic invented demo.';return}if(file.size>1000000){uploadBusy=false;$('#run-study').disabled=runBusy;$('#reset-demo').disabled=runBusy;error('Use a CSV below 1 MB in this first version.');$('#csv').value='';$('#file-state').textContent='No upload: deterministic invented demo.';return}uploadBusy=true;$('#run-study').disabled=true;$('#reset-demo').disabled=true;try{const contents=await file.text();if(version!==uploadVersion)return;csvText=contents;$('#file-state').textContent=file.name+' loaded locally. Click Run research to test it.'}catch(e){if(version===uploadVersion)error('Could not read this CSV. Choose the file again.')}finally{if(version===uploadVersion){uploadBusy=false;$('#run-study').disabled=runBusy;$('#reset-demo').disabled=runBusy}}};
$('#reset-demo').onclick=()=>{uploadVersion++;uploadBusy=false;csvText=null;$('#csv').value='';$('#file-state').textContent='No upload: deterministic invented demo.';run()};
document.addEventListener('click',e=>{const b=e.target.closest('[data-view]');if(!b)return;if(b.dataset.view==='forward')refreshPaper();if(b.dataset.view==='board')refreshBoard();if(b.dataset.view==='safety')refreshSafety();document.querySelectorAll('.view').forEach(s=>s.hidden=s.id!==b.dataset.view);document.querySelectorAll('[data-view]').forEach(x=>{x.classList.toggle('active',x===b);x.setAttribute('aria-pressed',String(x===b))})});
$('#export-report').onclick=()=>{if(!report)return;const blob=new Blob([JSON.stringify(report,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download='Trading-Logic-Research-'+report.report_id+'.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000)};
$('#ai-form').onsubmit=async e=>{e.preventDefault();if(!report)return;const id=report.report_id;$('#summarize').disabled=true;$('#ai-status').textContent='Reading the report with your local model…';try{const result=await request('/api/summary',{model:$('#model').value,report_id:id});if(report.report_id!==result.report_id){$('#ai-status').textContent='Report changed; the older commentary was discarded.';return}$('#ai-summary').textContent=result.notes.summary;list($('#ai-risks'),result.notes.risks);list($('#ai-checks'),result.notes.next_checks);$('#ai-notes').hidden=false;$('#ai-status').textContent='Local model: '+result.notes.model+'. Commentary is unverified and has no execution authority.'}catch(err){$('#ai-status').textContent=err.message}finally{$('#summarize').disabled=false}};
$('#summarize').disabled=true;request('/api/report').then(r=>{report=r;render()}).catch(e=>error('Could not load the local research server. Run start-scout.bat and open http://127.0.0.1:8002. '+e.message));

$('#training-report').onchange=async()=>{
 const file=$('#training-report').files[0];if(!file)return;
 $('#training-results').hidden=true;
 try{
  if(file.size>10000000)throw Error('Use a training report below 10 MB.');
  const r=JSON.parse(await file.text()),finite=n=>typeof n==='number'&&Number.isFinite(n);
  if(!['0.2.0','0.3.0'].includes(r.version)||!Array.isArray(r.episodes)||r.episodes.length>2000||!Array.isArray(r.validation_candidates)||r.validation_candidates.length>5||!r.test||!r.split||!r.test_baselines||!finite(r.test.net_profit)||!finite(r.test.max_drawdown_pct)||!finite(r.selected_episode))throw Error('This is not a supported training report.json.');
  for(const row of r.episodes)if(!['episode','reward','net_return_pct','epsilon','states'].every(k=>finite(row[k])))throw Error('Invalid training episode data.');
  for(const c of r.validation_candidates)if(!c.metrics||!['net_return_pct','max_drawdown_pct','score'].every(k=>finite(c.metrics[k])))throw Error('Invalid validation metrics.');
  for(const m of Object.values(r.test_baselines))if(!['net_return_pct','max_drawdown_pct','fill_count'].every(k=>finite(m[k])))throw Error('Invalid baseline metrics.');
  const coverage=r.test.policy_coverage;if(!coverage||!finite(coverage.seen_decisions)||!finite(coverage.unseen_decisions)||!finite(r.test.net_return_pct)||!finite(r.test.fill_count))throw Error('Missing policy evaluation metrics.');
  $('#training-net').textContent=money(r.test.net_profit);tone($('#training-net'),r.test.net_profit);$('#training-dd').textContent=r.test.max_drawdown_pct.toFixed(2)+'%';$('#training-pick').textContent=r.selected_episode===0?'CASH':String(r.selected_episode);
  const count=coverage.seen_decisions+coverage.unseen_decisions;$('#training-unseen').textContent=count?(100*coverage.unseen_decisions/count).toFixed(0)+'%':'—';
  $('#training-context').textContent=(r.source==='synthetic_demo'?'INVENTED DEMO. No profitability evidence. ':'IMPORTED DATA. Provenance unverified. ')+'Frozen test starts '+String(r.split.validation_end_exclusive).slice(0,10)+'. Status: '+r.status+'.';
  const candidates=$('#training-candidates');candidates.replaceChildren();for(const c of r.validation_candidates){const row=document.createElement('tr');if(c.episode===r.selected_episode)row.classList.add('selected-row');cell(row,c.episode===0?'Cash':'Episode '+c.episode);cell(row,pct(c.metrics.net_return_pct));cell(row,c.metrics.max_drawdown_pct.toFixed(2)+'%');cell(row,c.metrics.score.toFixed(2));candidates.append(row)}
  const comparisons=$('#training-baselines');comparisons.replaceChildren();for(const[name,m]of [['Selected frozen policy',r.test],...Object.entries(r.test_baselines)]){const row=document.createElement('tr');cell(row,name);cell(row,pct(m.net_return_pct));cell(row,m.max_drawdown_pct.toFixed(2)+'%');cell(row,String(m.fill_count));comparisons.append(row)}
  const episodes=$('#training-episodes');episodes.replaceChildren();for(const e of r.episodes.slice(-50)){const row=document.createElement('tr');cell(row,String(e.episode));cell(row,e.reward.toFixed(5));cell(row,pct(e.net_return_pct));cell(row,(100*e.epsilon).toFixed(1)+'%');cell(row,String(e.states));episodes.append(row)}
  $('#training-results').hidden=false;$('#training-status').textContent=file.name+' loaded locally. No model was updated by opening this report.';
 }catch(e){$('#training-status').textContent=e.message}
};

let paperSnapshot=null,paperReadBusy=false,paperControlBusy=false,paperEpoch=0;
function renderPaper(r){
 paperSnapshot=r;
 if(r.configured===false){$('#paper-results').hidden=true;$('#paper-source').textContent='No account database at the configured path.';$('#paper-status').textContent='Start the worker first. Default monitor: runtime/demo.sqlite. For another account, restart app.py with --paper-db.';return}
 const s=r.state;$('#paper-results').hidden=false;
 $('#paper-source').textContent=(s.config.source==='robinhood_crypto_v2'?'ROBINHOOD QUOTE OBSERVATIONS / VIRTUAL MONEY':'INVENTED LIVE DEMO / NO MARKET DATA')+' · '+s.config.provider;
 $('#paper-equity').textContent=money(s.equity);$('#paper-profit').textContent=money(r.net_profit)+' vs initial virtual capital';tone($('#paper-profit'),r.net_profit);
 $('#paper-cash').textContent=money(s.cash);$('#paper-costs').textContent=money(s.fees)+' fees / '+money(s.slippage)+' extra slippage';$('#paper-dd').textContent=(s.max_drawdown*100).toFixed(2)+'%';
 $('#paper-risk').textContent=s.halted?'HALTED / entries blocked':s.paused?'PAUSED / positions retained':'Virtual risk limits active';
 $('#paper-health').textContent=s.health==='degraded'?'DEGRADED':!r.worker_active?'STOPPED':!r.receipt_fresh?'STALE':'OBSERVING';
 $('#paper-age').textContent=r.receipt_age_seconds===null?'No observations yet':Math.max(0,r.receipt_age_seconds).toFixed(0)+'s since receipt; not exchange freshness';
 $('#paper-toggle').textContent=s.paused?'Resume paper trading':'Pause paper trading';$('#paper-toggle').disabled=paperControlBusy;$('#paper-pending').textContent=s.pending.length+' pending virtual intent(s)';
 const positions=$('#paper-positions');positions.replaceChildren();for(const symbol of s.config.symbols){const tr=document.createElement('tr'),q=s.quotes[symbol];cell(tr,symbol);cell(tr,q?money(q.bid):'—');cell(tr,q?money(q.ask):'—');cell(tr,s.positions[symbol].toFixed(8));cell(tr,String(r.completed_candles[symbol]||0));positions.append(tr)}
 const fills=$('#paper-fills');fills.replaceChildren();for(const f of r.fills){const tr=document.createElement('tr');cell(tr,new Date(f.at*1000).toLocaleString());cell(tr,f.symbol);cell(tr,f.side.toUpperCase());cell(tr,f.quantity.toFixed(8));cell(tr,money(f.fill_price));cell(tr,money(f.fee));fills.append(tr)}
 if(!r.fills.length){const tr=document.createElement('tr'),td=cell(tr,'No virtual fills yet. Warmup, cash selection and pauses can all produce zero fills.');td.colSpan=6;fills.append(tr)}
 const events=$('#paper-events');events.replaceChildren();for(const e of r.events.slice(0,40)){const tr=document.createElement('tr');cell(tr,new Date(e.at*1000).toLocaleString());cell(tr,e.kind);cell(tr,e.error_type||e.reason||e.symbol||e.provider||'Saved in account journal');events.append(tr)}
 const decision=r.events.find(e=>e.kind==='decision');$('#paper-decision').textContent=decision?'Last decision: '+decision.proposal.reason:'Waiting for 30 completed sampled candles before proposals.';
 list($('#paper-limitations'),r.limitations);$('#paper-status').textContent='Virtual account retained across restarts. Automatically refreshes while this tab is open.';
}
async function refreshPaper(){if(paperReadBusy||paperControlBusy)return;paperReadBusy=true;const epoch=paperEpoch;try{const r=await request('/api/paper');if(epoch===paperEpoch)renderPaper(r)}catch(e){$('#paper-status').textContent=e.message+' Last displayed balances may be stale.'}finally{paperReadBusy=false}}
$('#paper-refresh').onclick=refreshPaper;
$('#paper-toggle').onclick=async()=>{if(!paperSnapshot||paperSnapshot.configured===false||paperControlBusy)return;paperControlBusy=true;paperEpoch++;$('#paper-toggle').disabled=true;try{const r=await request('/api/paper/control',{paused:!paperSnapshot.state.paused});renderPaper(r)}catch(e){$('#paper-status').textContent=e.message}finally{paperControlBusy=false;$('#paper-toggle').disabled=false}};
setInterval(()=>{if(!$('#forward').hidden&&!document.hidden)refreshPaper()},5000);

let boardBusy=false,boardReadBusy=false;
const boardOpen=new Map();
function renderBoard(value){
 const selected=$('#board-thread').value,select=$('#board-thread');select.replaceChildren();
 const fresh=document.createElement('option');fresh.value='';fresh.textContent='New discussion';select.append(fresh);
 for(const t of value.threads){const option=document.createElement('option');option.value=String(t.id);option.textContent='#'+t.id+' / '+t.title;select.append(option)}
 select.value=value.threads.some(t=>String(t.id)===selected)?selected:'';
 const roles=$('#board-roles');roles.replaceChildren();for(const name of Object.values(value.roles)){const badge=document.createElement('span');badge.textContent=name;roles.append(badge)}
 const target=$('#board-threads');target.replaceChildren();
 for(const t of value.threads){const thread=document.createElement('details');thread.classList.add('panel');thread.open=boardOpen.has(t.id)?boardOpen.get(t.id):t.id===value.threads[0].id;thread.ontoggle=()=>boardOpen.set(t.id,thread.open);
 const title=document.createElement('summary');title.textContent='#'+t.id+' / '+t.title+' / '+t.status;thread.append(title);if(t.context&&t.context.report_id){const context=document.createElement('p');context.classList.add('caption');context.textContent='Snapshot '+t.context.report_id+' / '+t.context.source+' / captured '+t.context.captured_at+'. Archived evidence; no execution authority.';thread.append(context)}
 for(const m of t.messages){const article=document.createElement('article');article.classList.add('board-message');
 const meta=document.createElement('small');meta.textContent=(value.roles[m.author]||m.author)+' · '+m.mode+' · '+new Date(m.created).toLocaleString()+(m.reply_to?' · replies to #'+m.reply_to:'')+' · #'+m.id;
 const text=document.createElement('p');text.textContent=m.content.summary||'';article.append(meta,text);
 for(const key of ['risks','next_checks'])if(Array.isArray(m.content[key])&&m.content[key].length){const label=document.createElement('strong');label.textContent=key==='risks'?'Concerns':'Next checks';const items=document.createElement('ul');list(items,m.content[key]);article.append(label,items)}
 thread.append(article)}target.append(thread)}
 if(!value.threads.length){const empty=document.createElement('p');empty.textContent='No discussions yet. Post a note or run a research meeting.';target.append(empty)}
}
async function refreshBoard(){if(boardReadBusy)return;boardReadBusy=true;try{renderBoard(await request('/api/board'))}catch(e){$('#board-status').textContent=e.message}finally{boardReadBusy=false}}
async function boardAction(review){if(boardBusy)return;boardBusy=true;$('#board-post').disabled=true;$('#board-review').disabled=true;
 try{const thread=$('#board-thread').value,body=review?{question:$('#board-text').value,model:$('#board-model').value}:{text:$('#board-text').value};if(thread)body.thread_id=Number(thread);
 const result=await request(review?'/api/board/review':'/api/board/post',body);await refreshBoard();$('#board-thread').value=String(result.thread_id);
 $('#board-status').textContent=review?'Meeting started. Messages appear as each role finishes; local inference can take several minutes.':'Your note was saved. Select this discussion when asking the researchers to review it.';
 }catch(e){$('#board-status').textContent=e.message}finally{boardBusy=false;$('#board-post').disabled=false;$('#board-review').disabled=false}}
$('#board-form').onsubmit=e=>{e.preventDefault();boardAction(false)};
$('#board-review').onclick=()=>boardAction(true);$('#board-refresh').onclick=refreshBoard;
setInterval(()=>{if(!$('#board').hidden&&!document.hidden)refreshBoard()},5000);

let safetyBusy=false,safetyReadBusy=false,safetyEpoch=0;
function renderSafety(value){
 const r=value.account,n=value.notifications,configured=r.configured!==false;
 for(const id of ['safety-kill','safety-ack','safety-resume'])$('#'+id).disabled=!configured||safetyBusy;
 const s=configured?r.state:null,latched=!!(s&&s.safety&&s.safety.latched);
 $('#safety-state').textContent=!configured?'NOT CONFIGURED':latched?'STOP LATCHED':s.halted?'DRAWDOWN HALT':s.paused?'PAUSED':'WITHIN LIMIT';
 $('#safety-reason').textContent=latched?s.safety.reason+' / '+new Date(s.safety.since*1000).toLocaleString():configured?'No safety latch. This is a virtual account.':'Start the configured forward worker.';
 $('#safety-worker').textContent=!configured?'—':r.worker_active?'ACTIVE':'STOPPED';
 $('#safety-age').textContent=configured&&r.receipt_age_seconds!==null?Math.max(0,r.receipt_age_seconds).toFixed(0)+'s since quote receipt':'No quote receipts';
 $('#safety-discord').textContent=!n.discord.required?'NOT CONFIGURED':n.discord.available?'CONNECTED':'UNAVAILABLE';
 $('#safety-pending').textContent=n.pending+' queued alert(s)';
 $('#safety-banner').hidden=!latched;$('#safety-banner').textContent=latched?'PAPER TRADING STOPPED: '+s.safety.reason+'. Review Safety & Alerts before acknowledging and resuming.':'';
 const rows=$('#safety-alerts');rows.replaceChildren();for(const a of n.alerts){const tr=document.createElement('tr');cell(tr,new Date(a.at*1000).toLocaleString());cell(tr,a.kind);cell(tr,a.message);cell(tr,a.delivered?'DELIVERED':'QUEUED / '+a.attempts+' attempt(s)'+(a.last_error?' / '+a.last_error:''));rows.append(tr)}
}
async function refreshSafety(){if(safetyReadBusy||safetyBusy)return;safetyReadBusy=true;const epoch=safetyEpoch;try{const value=await request('/api/safety');if(epoch===safetyEpoch)renderSafety(value)}catch(e){$('#safety-status').textContent=e.message+' Safety status may be stale.'}finally{safetyReadBusy=false}}
async function safetyAction(action){if(safetyBusy)return;safetyBusy=true;safetyEpoch++;for(const id of ['safety-kill','safety-ack','safety-resume'])$('#'+id).disabled=true;
 try{const value=await request('/api/safety/control',{action});safetyBusy=false;renderSafety(value);$('#safety-status').textContent=action==='acknowledge'?'Safety acknowledged. Paper trading remains paused; resume separately.':'Saved safety action: '+action+'. Open positions are retained.';await refreshPaper()}
 catch(e){$('#safety-status').textContent=e.message}
 finally{safetyBusy=false;await refreshSafety()}}
$('#safety-kill').onclick=()=>safetyAction('kill');$('#safety-ack').onclick=()=>safetyAction('acknowledge');$('#safety-resume').onclick=()=>safetyAction('resume');$('#safety-refresh').onclick=refreshSafety;
refreshSafety();setInterval(()=>{if(!document.hidden)refreshSafety()},5000);
