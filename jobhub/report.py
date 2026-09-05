# -*- coding: utf-8 -*-
"""生成单文件 HTML 看板。不依赖任何 CDN，断网也能打开。"""

import json
import os
from datetime import datetime

from . import normalize as N

TIER_LABEL = {'strong': '强烈推荐', 'consider': '可以考虑', 'weak': '不太匹配'}


def _esc(v):
    if v is None:
        return ''
    return (str(v).replace('&', '&amp;').replace('<', '&lt;')
            .replace('>', '&gt;').replace('"', '&quot;'))


def _slim(jobs):
    """只把看板用得到的字段塞进 HTML，避免文件过大。"""
    out = []
    for j in jobs:
        out.append({
            'id': j.get('id'),
            'company': j.get('company'),
            'title': j.get('title'),
            'city': j.get('city'),
            'district': j.get('district'),
            'salary_raw': j.get('salary_raw'),
            'salary_text': N.salary_text(j),
            'salary_min': j.get('salary_min'),
            'salary_max': j.get('salary_max'),
            'salary_months': j.get('salary_months'),
            'experience': j.get('experience'),
            'education': j.get('education'),
            'platforms': j.get('platforms') or [],
            'tags': j.get('tags') or [],
            'jd': j.get('jd'),
            'hr_name': j.get('hr_name'),
            'hr_active': j.get('hr_active'),
            'url': j.get('url'),
            'published_at': j.get('published_at'),
            'status': j.get('status'),
            'notes': j.get('notes'),
            'score': j.get('score'),
            'detail': j.get('score_detail') or {},
        })
    return out


TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>求职汇总看板</title>
<style>
  :root{
    --bg:#f6f7f9; --card:#fff; --bd:#e4e7ec; --bd2:#eef0f3;
    --tx:#1f2328; --tx2:#5b6470; --tx3:#8b949e;
    --ac:#2563eb; --ac-bg:#eff4ff;
    --strong:#16a34a; --consider:#d97706; --weak:#98a2b3;
    --ok-bg:#e9f7ef; --warn-bg:#fdf5e7; --gray-bg:#f2f4f7;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--tx);
    font:14px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}
  .wrap{max-width:1280px;margin:0 auto;padding:24px 20px 64px}
  h1{font-size:22px;margin:0 0 4px}
  .sub{color:var(--tx3);font-size:13px;margin-bottom:20px}
  .kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:20px}
  .kpi{background:var(--card);border:1px solid var(--bd);border-radius:10px;padding:14px 16px}
  .kpi .v{font-size:24px;font-weight:650;letter-spacing:-.5px}
  .kpi .l{font-size:12px;color:var(--tx2);margin-top:2px}
  .card{background:var(--card);border:1px solid var(--bd);border-radius:10px;padding:16px;margin-bottom:16px}
  .card h2{font-size:14px;margin:0 0 14px;font-weight:600;color:var(--tx)}
  .charts{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:16px;margin-bottom:16px}
  .bar{display:flex;align-items:center;gap:8px;margin-bottom:7px;font-size:12px}
  .bar .nm{width:88px;flex:none;color:var(--tx2);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .bar .tr{flex:1;background:var(--gray-bg);border-radius:4px;height:16px;overflow:hidden}
  .bar .fl{height:100%;background:var(--ac);border-radius:4px}
  .bar .ct{width:34px;flex:none;text-align:right;color:var(--tx3);font-variant-numeric:tabular-nums}
  .hist{display:flex;align-items:flex-end;gap:4px;height:110px;padding-top:6px}
  .hist .col{flex:1;display:flex;flex-direction:column;justify-content:flex-end;align-items:center;gap:4px}
  .hist .b{width:100%;background:var(--ac);border-radius:3px 3px 0 0;min-height:2px}
  .hist .lb{font-size:10px;color:var(--tx3);white-space:nowrap}
  .hist .vv{font-size:10px;color:var(--tx2);font-variant-numeric:tabular-nums}
  .tools{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:14px}
  input[type=text],select,input[type=number]{padding:7px 10px;border:1px solid var(--bd);border-radius:7px;
    font-size:13px;background:#fff;color:var(--tx);outline:none}
  input[type=text]:focus,select:focus{border-color:var(--ac)}
  input[type=text]{min-width:200px}
  .btn{padding:7px 13px;border:1px solid var(--bd);background:#fff;border-radius:7px;
    cursor:pointer;font-size:13px;color:var(--tx)}
  .btn:hover{background:var(--gray-bg)}
  .btn.pri{background:var(--ac);border-color:var(--ac);color:#fff}
  .btn.pri:hover{opacity:.9}
  table{width:100%;border-collapse:collapse;font-size:13px}
  th{text-align:left;padding:9px 10px;border-bottom:1px solid var(--bd);color:var(--tx2);
    font-weight:600;font-size:12px;cursor:pointer;user-select:none;white-space:nowrap}
  th:hover{color:var(--ac)}
  th.as::after{content:' ↓';color:var(--ac)}
  th.de::after{content:' ↑';color:var(--ac)}
  td{padding:10px;border-bottom:1px solid var(--bd2);vertical-align:top}
  tbody tr{cursor:pointer}
  tbody tr:hover{background:#fafbfc}
  .co{font-weight:600}
  .ti{color:var(--tx2);font-size:12px;margin-top:2px}
  .sc{display:inline-block;min-width:42px;text-align:center;padding:2px 8px;border-radius:20px;
    font-weight:650;font-size:12px;font-variant-numeric:tabular-nums}
  .t-strong{background:var(--ok-bg);color:var(--strong)}
  .t-consider{background:var(--warn-bg);color:var(--consider)}
  .t-weak{background:var(--gray-bg);color:var(--weak)}
  .pill{display:inline-block;padding:1px 7px;border-radius:5px;background:var(--gray-bg);
    color:var(--tx2);font-size:11px;margin:1px 3px 1px 0}
  .pill.pf{background:var(--ac-bg);color:var(--ac)}
  .money{font-variant-numeric:tabular-nums;white-space:nowrap;font-weight:600}
  .mut{color:var(--tx3);font-size:12px}
  .empty{padding:44px;text-align:center;color:var(--tx3)}
  /* 抽屉 */
  .mask{position:fixed;inset:0;background:rgba(15,20,28,.42);display:none;z-index:40}
  .mask.on{display:block}
  .draw{position:fixed;top:0;right:0;bottom:0;width:min(560px,94vw);background:#fff;z-index:41;
    transform:translateX(100%);transition:transform .22s ease;overflow-y:auto;
    box-shadow:-6px 0 28px rgba(15,20,28,.12)}
  .draw.on{transform:none}
  .draw .hd{position:sticky;top:0;background:#fff;padding:16px 20px;border-bottom:1px solid var(--bd);
    display:flex;justify-content:space-between;align-items:flex-start;gap:12px;z-index:1}
  .draw .hd h3{margin:0;font-size:17px}
  .draw .bd{padding:16px 20px 40px}
  .x{border:none;background:var(--gray-bg);width:28px;height:28px;border-radius:7px;
    cursor:pointer;font-size:16px;color:var(--tx2);flex:none;line-height:1}
  .x:hover{background:#e6e9ee}
  .sec{margin-bottom:18px}
  .sec h4{margin:0 0 9px;font-size:12px;color:var(--tx2);font-weight:600;
    text-transform:uppercase;letter-spacing:.4px}
  .kv{display:flex;flex-wrap:wrap;gap:6px 20px;font-size:13px}
  .kv div{min-width:44%}
  .kv span{color:var(--tx3)}
  .brk{margin-bottom:8px;font-size:12px}
  .brk .r{display:flex;align-items:center;gap:8px}
  .brk .n{width:64px;flex:none;color:var(--tx2)}
  .brk .t{flex:1;background:var(--gray-bg);height:7px;border-radius:4px;overflow:hidden}
  .brk .f{height:100%;background:var(--ac);border-radius:4px}
  .brk .w{width:36px;flex:none;text-align:right;color:var(--tx3);font-variant-numeric:tabular-nums}
  .brk .nt{color:var(--tx3);margin-left:72px;font-size:11px}
  .jd{white-space:pre-wrap;font-size:13px;color:var(--tx2);background:#fafbfc;
    border:1px solid var(--bd2);border-radius:8px;padding:12px;max-height:300px;overflow-y:auto}
  .flag{background:#fdecec;color:#c0392b;padding:7px 11px;border-radius:7px;
    font-size:12px;margin-bottom:8px;border:1px solid #f7d4d4}
  a{color:var(--ac);text-decoration:none}
  a:hover{text-decoration:underline}
  .foot{color:var(--tx3);font-size:12px;text-align:center;margin-top:26px}
</style>
</head>
<body>
<div class="wrap">
  <h1>求职汇总看板</h1>
  <div class="sub">生成于 __GEN__ · 共 __N__ 个去重后的岗位 · 数据仅保存在本地</div>

  <div class="kpis" id="kpis"></div>

  <div class="charts">
    <div class="card"><h2>匹配度分档</h2><div id="c-tier"></div></div>
    <div class="card"><h2>薪资分布（月薪 / 元）</h2><div class="hist" id="c-sal"></div></div>
    <div class="card"><h2>平台来源</h2><div id="c-pf"></div></div>
    <div class="card"><h2>城市分布</h2><div id="c-city"></div></div>
    <div class="card"><h2>投递进度</h2><div id="c-st"></div></div>
    <div class="card"><h2>经验要求</h2><div id="c-exp"></div></div>
  </div>

  <div class="card">
    <h2>岗位清单</h2>
    <div class="tools">
      <input type="text" id="q" placeholder="搜索公司 / 岗位 / 描述…">
      <select id="f-pf"><option value="">全部平台</option></select>
      <select id="f-st"><option value="">全部状态</option></select>
      <select id="f-ct"><option value="">全部城市</option></select>
      <select id="f-tr">
        <option value="">全部分档</option>
        <option value="strong">强烈推荐</option>
        <option value="consider">可以考虑</option>
        <option value="weak">不太匹配</option>
      </select>
      <input type="number" id="f-ms" placeholder="最低分" style="width:96px">
      <button class="btn" id="reset">重置</button>
      <button class="btn pri" id="exp">导出当前结果 CSV</button>
      <span class="mut" id="cnt"></span>
    </div>
    <div style="overflow-x:auto">
      <table id="tb">
        <thead><tr>
          <th data-k="score">匹配度</th>
          <th data-k="title">岗位</th>
          <th data-k="salary_max">薪资</th>
          <th data-k="city">城市</th>
          <th data-k="experience">经验</th>
          <th data-k="education">学历</th>
          <th data-k="_pf">平台</th>
          <th data-k="hr_active">HR</th>
          <th data-k="status">状态</th>
        </tr></thead>
        <tbody></tbody>
      </table>
    </div>
    <div class="empty" id="none" style="display:none">没有符合条件的岗位</div>
  </div>

  <div class="foot">job-hub · 数据全部保存在本机 SQLite，不会上传到任何地方</div>
</div>

<div class="mask" id="mask"></div>
<div class="draw" id="draw">
  <div class="hd">
    <div><h3 id="d-title"></h3><div class="mut" id="d-sub"></div></div>
    <button class="x" id="d-x">×</button>
  </div>
  <div class="bd" id="d-bd"></div>
</div>

<script>
const DATA = __DATA__;
const TIER = {strong:'强烈推荐', consider:'可以考虑', weak:'不太匹配'};
const THR = __THR__;
let sortK='score', sortDir=-1;

const esc = s => (s==null?'':String(s)).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const tierOf = s => s>=THR.strong?'strong':(s>=THR.consider?'consider':'weak');
const mid = j => (j.salary_min==null&&j.salary_max==null)?null:((j.salary_min||0)+(j.salary_max||0))/2;

function uniq(a){return [...new Set(a.filter(x=>x))].sort();}
function fillSel(id, arr){
  const el=document.getElementById(id), cur=el.value;
  el.innerHTML='<option value="">'+(id==='f-st'?'全部状态':id==='f-pf'?'全部平台':'全部城市')+'</option>'
    +arr.map(v=>`<option value="${esc(v)}">${esc(v)}</option>`).join('');
  el.value=[...el.options].some(o=>o.value===cur)?cur:'';
}

/* ---------- KPI ---------- */
function renderKpis(list){
  const sal=list.map(mid).filter(x=>x!=null);
  const med=sal.length?sal.sort((a,b)=>a-b)[Math.floor(sal.length/2)]:null;
  const st=s=>list.filter(j=>j.status===s).length;
  const applied=list.filter(j=>['已投递','已沟通','面试中','已offer'].includes(j.status)).length;
  const replied=list.filter(j=>['已沟通','面试中','已offer'].includes(j.status)).length;
  const items=[
    ['去重后岗位', list.length],
    ['强烈推荐', list.filter(j=>tierOf(j.score??0)==='strong').length],
    ['薪资中位数', med?Math.round(med/1000)+'K':'—'],
    ['已投递', applied],
    ['有回应', replied],
    ['回应率', applied?Math.round(replied/applied*100)+'%':'—'],
  ];
  document.getElementById('kpis').innerHTML=items.map(([l,v])=>
    `<div class="kpi"><div class="v">${v}</div><div class="l">${l}</div></div>`).join('');
}

/* ---------- 图表 ---------- */
function bars(el, pairs){
  const max=Math.max(1,...pairs.map(p=>p[1]));
  document.getElementById(el).innerHTML = pairs.length
    ? pairs.map(([n,v])=>`<div class="bar"><div class="nm" title="${esc(n)}">${esc(n)}</div>
        <div class="tr"><div class="fl" style="width:${v/max*100}%"></div></div>
        <div class="ct">${v}</div></div>`).join('')
    : '<div class="mut">暂无数据</div>';
}
function hist(el, vals){
  if(!vals.length){document.getElementById(el).innerHTML='<div class="mut">暂无薪资数据</div>';return;}
  const step=5000, max=Math.max(...vals), n=Math.ceil(max/step);
  const buckets=Array(n).fill(0);
  vals.forEach(v=>{buckets[Math.min(n-1,Math.floor(v/step))]++});
  const mx=Math.max(...buckets);
  document.getElementById(el).innerHTML=buckets.map((c,i)=>
    `<div class="col"><div class="vv">${c||''}</div>
     <div class="b" style="height:${c/mx*74}px"></div>
     <div class="lb">${i*5}-${(i+1)*5}K</div></div>`).join('');
}
function renderCharts(list){
  const t=n=>list.filter(j=>tierOf(j.score??0)===n).length;
  bars('c-tier',[['强烈推荐',t('strong')],['可以考虑',t('consider')],['不太匹配',t('weak')]]);
  hist('c-sal',list.map(mid).filter(x=>x!=null));
  const pf={};list.forEach(j=>(j.platforms||['other']).forEach(p=>pf[p]=(pf[p]||0)+1));
  bars('c-pf',Object.entries(pf).sort((a,b)=>b[1]-a[1]));
  const ct={};list.forEach(j=>{if(j.city)ct[j.city]=(ct[j.city]||0)+1});
  bars('c-city',Object.entries(ct).sort((a,b)=>b[1]-a[1]).slice(0,10));
  bars('c-st',['待处理','已收藏','已投递','已沟通','面试中','已offer','不合适','已归档']
    .map(s=>[s,list.filter(j=>j.status===s).length]).filter(x=>x[1]));
  const ex={};list.forEach(j=>{if(j.experience)ex[j.experience]=(ex[j.experience]||0)+1});
  bars('c-exp',Object.entries(ex).sort((a,b)=>b[1]-a[1]));
}

/* ---------- 表格 ---------- */
function filtered(){
  const q=document.getElementById('q').value.trim().toLowerCase();
  const pf=document.getElementById('f-pf').value;
  const st=document.getElementById('f-st').value;
  const ct=document.getElementById('f-ct').value;
  const tr=document.getElementById('f-tr').value;
  const ms=parseFloat(document.getElementById('f-ms').value);
  return DATA.filter(j=>{
    if(q){const hay=[j.company,j.title,j.jd,(j.tags||[]).join(' ')].join(' ').toLowerCase();
      if(!hay.includes(q))return false;}
    if(pf&&!(j.platforms||[]).includes(pf))return false;
    if(st&&j.status!==st)return false;
    if(ct&&j.city!==ct)return false;
    if(tr&&tierOf(j.score??0)!==tr)return false;
    if(!isNaN(ms)&&(j.score??0)<ms)return false;
    return true;
  });
}
function val(j,k){
  if(k==='_pf')return (j.platforms||[]).join(',');
  return j[k];
}
function render(){
  const list=filtered().sort((a,b)=>{
    const x=val(a,sortK),y=val(b,sortK);
    if(x==null)return 1; if(y==null)return -1;
    return (x>y?1:x<y?-1:0)*sortDir;
  });
  renderKpis(list); renderCharts(list);
  document.getElementById('cnt').textContent=`显示 ${list.length} / ${DATA.length} 条`;
  document.getElementById('none').style.display=list.length?'none':'block';
  document.querySelector('#tb tbody').innerHTML=list.map(j=>{
    const tr=tierOf(j.score??0);
    return `<tr data-id="${esc(j.id)}">
      <td><span class="sc t-${tr}">${j.score??'—'}</span></td>
      <td><div class="co">${esc(j.title)}</div>
          <div class="ti">${esc(j.company)}</div></td>
      <td class="money">${esc(j.salary_text)}</td>
      <td>${esc(j.city||'')}${j.district?'<div class="ti">'+esc(j.district)+'</div>':''}</td>
      <td class="mut">${esc(j.experience||'')}</td>
      <td class="mut">${esc(j.education||'')}</td>
      <td>${(j.platforms||[]).map(p=>`<span class="pill pf">${esc(p)}</span>`).join('')}</td>
      <td class="mut">${esc(j.hr_active||'')}</td>
      <td>${esc(j.status||'')}</td></tr>`;
  }).join('');
  document.querySelectorAll('#tb th').forEach(th=>{
    th.className = th.dataset.k===sortK ? (sortDir<0?'as':'de') : '';
  });
}

/* ---------- 抽屉 ---------- */
function open(id){
  const j=DATA.find(x=>x.id===id); if(!j)return;
  const d=j.detail||{}, bd=d.breakdown||{};
  document.getElementById('d-title').textContent=j.title||'';
  document.getElementById('d-sub').textContent=[j.company,j.city,j.district].filter(Boolean).join(' · ');
  let h='';
  if((d.flags||[]).length) h+=`<div class="flag">⚠ ${d.flags.map(esc).join('；')}</div>`;
  h+=`<div class="sec"><h4>基本信息</h4><div class="kv">
    <div><span>薪资</span> ${esc(j.salary_text)}</div>
    <div><span>经验</span> ${esc(j.experience||'—')}</div>
    <div><span>学历</span> ${esc(j.education||'—')}</div>
    <div><span>状态</span> ${esc(j.status||'—')}</div>
    <div><span>发布</span> ${esc(j.published_at||'—')}</div>
    <div><span>HR</span> ${esc([j.hr_name,j.hr_active].filter(Boolean).join(' · ')||'—')}</div>
    <div><span>平台</span> ${(j.platforms||[]).map(esc).join('、')||'—'}</div>
  </div></div>`;
  if((j.tags||[]).length)
    h+=`<div class="sec"><h4>标签</h4>${j.tags.map(t=>`<span class="pill">${esc(t)}</span>`).join('')}</div>`;
  if(Object.keys(bd).length){
    h+=`<div class="sec"><h4>匹配度拆解（总分 ${j.score}）</h4>`+
      Object.entries(bd).map(([k,v])=>`<div class="brk">
        <div class="r"><div class="n">${esc(k)}</div>
        <div class="t"><div class="f" style="width:${Math.round(v.ratio*100)}%"></div></div>
        <div class="w">${v.weight}分</div></div>
        <div class="nt">${esc(v.note)}</div></div>`).join('')+'</div>';
  }
  if(j.jd) h+=`<div class="sec"><h4>职位描述</h4><div class="jd">${esc(j.jd)}</div></div>`;
  if(j.notes) h+=`<div class="sec"><h4>我的备注</h4><div class="jd">${esc(j.notes)}</div></div>`;
  if(j.url) h+=`<div class="sec"><a href="${esc(j.url)}" target="_blank" rel="noopener">打开原始岗位链接 →</a></div>`;
  document.getElementById('d-bd').innerHTML=h;
  document.getElementById('draw').classList.add('on');
  document.getElementById('mask').classList.add('on');
}
function close(){
  document.getElementById('draw').classList.remove('on');
  document.getElementById('mask').classList.remove('on');
}

/* ---------- 导出 ---------- */
function csv(){
  const list=filtered();
  const cols=['score','tier','company','title','salary_text','city','district','experience',
    'education','status','platforms','hr_active','published_at','url'];
  const rows=[cols.join(',')].concat(list.map(j=>cols.map(c=>{
    let v = c==='tier'?TIER[tierOf(j.score??0)]
          : c==='platforms'?(j.platforms||[]).join(' ')
          : j[c];
    v = v==null?'':String(v);
    return /[",\n]/.test(v)?'"'+v.replace(/"/g,'""')+'"':v;
  }).join(',')));
  const blob=new Blob(['\ufeff'+rows.join('\n')],{type:'text/csv;charset=utf-8'});
  const a=document.createElement('a');
  a.href=URL.createObjectURL(blob);
  a.download='jobs_'+new Date().toISOString().slice(0,10)+'.csv';
  a.click();
}

/* ---------- 绑定 ---------- */
document.querySelectorAll('.tools input,.tools select').forEach(el=>el.addEventListener('input',render));
document.getElementById('reset').onclick=()=>{
  ['q','f-ms'].forEach(i=>document.getElementById(i).value='');
  ['f-pf','f-st','f-ct','f-tr'].forEach(i=>document.getElementById(i).value='');
  render();
};
document.getElementById('exp').onclick=csv;
document.getElementById('d-x').onclick=close;
document.getElementById('mask').onclick=close;
document.addEventListener('keydown',e=>{if(e.key==='Escape')close()});
document.querySelector('#tb tbody').addEventListener('click',e=>{
  const tr=e.target.closest('tr'); if(tr)open(tr.dataset.id);
});
document.querySelectorAll('#tb th').forEach(th=>th.onclick=()=>{
  if(sortK===th.dataset.k) sortDir*=-1;
  else{sortK=th.dataset.k; sortDir = sortK==='score'?-1:1;}
  render();
});

fillSel('f-pf',uniq(DATA.flatMap(j=>j.platforms||[])));
fillSel('f-st',uniq(DATA.map(j=>j.status)));
fillSel('f-ct',uniq(DATA.map(j=>j.city)));
render();
</script>
</body>
</html>
"""


def build(jobs, cfg, out_path):
    data = _slim(jobs)
    thr = cfg.get('thresholds', {'strong': 75, 'consider': 55})
    payload = json.dumps(data, ensure_ascii=False).replace('</', '<\\/')

    html = (TEMPLATE
            .replace('__DATA__', payload)
            .replace('__THR__', json.dumps(thr))
            .replace('__GEN__', datetime.now().strftime('%Y-%m-%d %H:%M'))
            .replace('__N__', str(len(data))))

    d = os.path.dirname(os.path.abspath(out_path))
    if d:
        os.makedirs(d, exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(html)
    return out_path
