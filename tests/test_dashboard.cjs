// Verify saved training-report parsing/rendering without a browser or network.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const nodes=new Map();
function node(){return {textContent:'',hidden:false,content:'test-token',files:[],children:[],classList:{toggle(){},add(){}},append(...items){this.children.push(...items)},replaceChildren(){this.children=[]},setAttribute(){}}}
const document={querySelector(selector){if(!nodes.has(selector))nodes.set(selector,node());return nodes.get(selector)},querySelectorAll(){return []},createElement:node,createElementNS:node,addEventListener(){}};
const context={document,Intl,URL,Blob,setTimeout,setInterval:()=>0,fetch:()=>new Promise(()=>{})};
vm.createContext(context);vm.runInContext(fs.readFileSync('web/dashboard.js','utf8'),context);
const metrics={net_profit:-5,net_return_pct:-.5,max_drawdown_pct:1,fill_count:3,score:-2};
const report={version:'0.2.0',source:'synthetic_demo',selected_episode:0,status:'validation_selected_cash',
 split:{validation_end_exclusive:'2024-08-01T00:00:00Z'},
 test:{...metrics,policy_coverage:{seen_decisions:1,unseen_decisions:3}},
 test_baselines:{cash:{...metrics,net_return_pct:0}},
 validation_candidates:[{episode:0,metrics}],
 episodes:[{episode:1,reward:-.1,net_return_pct:-5,epsilon:.8,states:4}]};
async function importValue(value){document.querySelector('#training-report').files=[{name:'report.json',size:1000,text:async()=>JSON.stringify(value)}];await document.querySelector('#training-report').onchange()}
(async()=>{
 await importValue(report);
 assert.equal(document.querySelector('#training-results').hidden,false);
 assert.equal(document.querySelector('#training-pick').textContent,'CASH');
 assert.equal(document.querySelector('#training-unseen').textContent,'75%');
 assert.equal(document.querySelector('#training-candidates').children.length,1);
 assert.equal(document.querySelector('#training-baselines').children.length,2);
 assert.match(document.querySelector('#training-context').textContent,/INVENTED DEMO/);
 await importValue({...report,episodes:[{episode:1,reward:'invalid'}]});
 assert.equal(document.querySelector('#training-results').hidden,true);
 assert.match(document.querySelector('#training-status').textContent,/Invalid training episode/);
 const forward={configured:false};context.renderPaper(forward);
 assert.equal(document.querySelector('#paper-results').hidden,true);
 const account={state:{config:{source:'synthetic_live_demo',provider:'fixed:trend',symbols:['BTC-USD']},equity:1000,cash:1000,fees:0,slippage:0,max_drawdown:0,halted:false,paused:true,health:'observing',pending:[],quotes:{},positions:{'BTC-USD':0}},net_profit:0,worker_active:false,receipt_fresh:false,receipt_age_seconds:null,completed_candles:{},fills:[],events:[],limitations:['Virtual account only.']};
 context.renderPaper(account);
 assert.equal(document.querySelector('#paper-results').hidden,false);
 assert.equal(document.querySelector('#paper-health').textContent,'STOPPED');
 assert.equal(document.querySelector('#paper-toggle').textContent,'Resume paper trading');
 assert.match(document.querySelector('#paper-source').textContent,/INVENTED LIVE DEMO/);
 await importValue({version:'0.1.0'});
 assert.match(document.querySelector('#training-status').textContent,/not a supported/);
 console.log('Training and forward account UI checks passed.');
})().catch(e=>{console.error(e);process.exitCode=1});
