import {heading} from '../components/common/header.js';import {table} from '../components/common/table.js';import {status} from '../components/common/status.js';import {esc,fmt} from '../utils/format.js';import {store} from '../stores/business.js';
const pct=v=>(v*100).toLocaleString('zh-CN',{maximumFractionDigits:1})+'%';
const blank='—';
function createForm(c,d){
 const approved=d.runs.filter(r=>r.approved);
 if(!approved.length)return '<p class="empty">暂无已复核报告。请先在「核算与复核」完成报告复核，再回来试算两档人手。</p>';
 const runId=approved.some(r=>r.id===store.simRun)?store.simRun:approved[0].id;
 const run=approved.find(r=>r.id===runId);
 const prios=Object.keys(run.snapshot.policy.sla_minutes);
 return `<form id="sim-form" class="inline-form"><label>试算名称<input name="name" value="${esc(c.title.slice(0,2))}排班试算" required></label><label>已复核报告<select id="sim-run" name="run_id">${approved.map(r=>`<option value="${r.id}" ${r.id===runId?'selected':''}>${esc(r.name)}</option>`).join('')}</select></label>${prios.map(p=>`<label>${esc(p)}·单均办理分钟<input name="handle_${esc(p)}" type="number" min="1" max="100000" step="any" value="30" required></label>`).join('')}<label>一档名称<input name="tier1_name" value="值守档" required></label><label>一档人数<input name="tier1_staff" type="number" min="1" max="500" value="2" required></label><label>二档名称<input name="tier2_name" value="加强档" required></label><label>二档人数<input name="tier2_staff" type="number" min="1" max="500" value="3" required></label><button>发起两档试算</button></form>`;
}
function compareBlock(pub){
 const[a,b]=pub;
 const map=t=>Object.fromEntries(t.result.rows.map(r=>[r['优先级'],r]));
 const ra=map(a),rb=map(b);
 const prios=[...new Set([...Object.keys(ra),...Object.keys(rb)])];
 const g=(m,k)=>m?m[k]:blank;
 const timeout=prios.map(p=>({'优先级':p,[a.label+'超时数']:g(ra[p],'超时数'),[a.label+'超时率']:ra[p]?pct(ra[p]['超时率']):blank,[b.label+'超时数']:g(rb[p],'超时数'),[b.label+'超时率']:rb[p]?pct(rb[p]['超时率']):blank}));
 timeout.push({'优先级':'合计',[a.label+'超时数']:a.result.summary['超时数'],[a.label+'超时率']:pct(a.result.summary['超时率']),[b.label+'超时数']:b.result.summary['超时数'],[b.label+'超时率']:pct(b.result.summary['超时率'])});
 const waits=prios.map(p=>({'优先级':p,[a.label+'平均等待']:g(ra[p],'平均等待营业分钟'),[a.label+'最大等待']:g(ra[p],'最大等待营业分钟'),[b.label+'平均等待']:g(rb[p],'平均等待营业分钟'),[b.label+'最大等待']:g(rb[p],'最大等待营业分钟')}));
 waits.push({'优先级':'全部',[a.label+'平均等待']:a.result.summary['平均等待营业分钟'],[a.label+'最大等待']:a.result.summary['最大等待营业分钟'],[b.label+'平均等待']:b.result.summary['平均等待营业分钟'],[b.label+'最大等待']:b.result.summary['最大等待营业分钟']});
 const metrics=t=>`<div class="metrics">${[['人手',t.result.summary['人手']+' 人'],['样本数',t.result.summary['样本数']],['平均等待营业分钟',fmt(t.result.summary['平均等待营业分钟'])],['最大等待营业分钟',fmt(t.result.summary['最大等待营业分钟'])],['超时率',pct(t.result.summary['超时率'])],['收尾营业分钟',fmt(t.result.summary['收尾营业分钟'])]].map(([k,v])=>`<div><small>${esc(k)}</small><strong>${esc(String(v))}</strong></div>`).join('')}</div>`;
 return `<h2>超时对比</h2>${table(timeout)}<h2>等待明细（营业分钟）</h2>${table(waits)}<h3>${esc(a.label)}</h3>${metrics(a)}<h3>${esc(b.label)}</h3>${metrics(b)}<p class="method">${esc(a.result.method)}</p><p class="warning">${a.result.warnings.map(esc).join('；')}</p>`;
}
function rerunForm(sim){
 const p=sim.params;
 return `<details><summary>调整参数并重算（并发重算安全：仅当新一代两档都完成才替换对比，旧试算晚到不覆盖）</summary><form id="rerun-form" data-id="${sim.id}"><div class="form-grid">${Object.entries(p.handle_minutes).map(([k,v])=>`<label>${esc(k)}·单均办理分钟<input name="handle_${esc(k)}" type="number" min="1" max="100000" step="any" value="${v}" required></label>`).join('')}${p.tiers.map((t,i)=>`<label>${i===0?'一':'二'}档名称<input name="tier${i+1}_name" value="${esc(t.name)}" required></label><label>${i===0?'一':'二'}档人数<input name="tier${i+1}_staff" type="number" min="1" max="500" value="${t.staff}" required></label>`).join('')}</div><button>重算第${sim.generation+1}代试算</button></form></details>`;
}
function detail(c,d,sim){
 if(!sim)return '<p class="empty">选择左侧试算，查看两档人手对比。</p>';
 const run=d.runs.find(r=>r.id===sim.run_id);
 const total=run?run.snapshot.sources.length:0;
 const tiers=sim.tiers.map(t=>`<div class="tier-card"><div class="report-top"><h3>${esc(t.label)} · ${t.staff}人</h3>${status(t.status)}</div><p>到单进度 ${t.progress}/${total} · 积压 ${t.backlog} · 在办 ${t.inflight}</p>${t.error?`<p class="error">${esc(t.error)}</p>`:''}</div>`).join('');
 const pub=sim.published_tiers;
 const compare=pub.length===2?compareBlock(pub):'<p class="empty">尚无已发布结果。同一次试算的两档都完成后，超时对比与等待明细才整体更新；任一档失败则保留旧版。</p>';
 return `<section class="report"><div class="report-top"><h2>${esc(sim.name)}</h2>${status(sim.status)}</div><p>引用报告 #${sim.run_id} · 第${sim.generation}代试算${sim.published?` · 已发布第${sim.published}代`:' · 尚未发布'} · 办理耗时 ${Object.entries(sim.params.handle_minutes).map(([k,v])=>esc(k)+' '+v+'分').join(' / ')}</p>${sim.error?`<p class="error">${esc(sim.error)}</p>`:''}<div class="tier-grid">${tiers}</div>${compare}${rerunForm(sim)}</section>`;
}
export function sims(c,d,selected){
 const sim=d.sims.find(s=>s.id===selected)||d.sims[0];
 return heading('STAFFING TRIAL / 05','排班两档人手试算','引用已复核报告的冻结到单与日历，按优先级设定办理耗时，对比两档人手的超时与等待。')+createForm(c,d)+`<div class="run-layout"><aside class="run-list">${d.sims.map(s=>`<button class="select-sim" data-id="${s.id}">${esc(s.name)} ${status(s.status)}</button>`).join('')}</aside><div>${detail(c,d,sim)}</div></div>`;
}
