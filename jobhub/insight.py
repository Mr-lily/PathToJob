# -*- coding: utf-8 -*-
"""岗位精读看板生成器 v3.

核心：汇总 + 贰贰深度分析 + 投递进度 + 通勤。弱化算法分。
每个岗位分节：①原始JD ②岗位硬信息 ③通勤(驾车/公交/步行+地图位)
④岗位实际内容 ⑤公司经营行业 ⑥岗位适配情况(可基于简历) ⑦面试攻略(+社媒链接位)
进度流水线手动更新。筛选/排序：进度/薪资/通勤。
"""
import json
import os
import hashlib
from datetime import datetime

from . import normalize as N
from . import commute as CM


def _esc(v):
    if v is None:
        return ''
    return (str(v).replace('&', '&amp;').replace('<', '&lt;')
            .replace('>', '&gt;').replace('"', '&quot;'))


def _slim(jobs):
    out = []
    for j in jobs:
        out.append({
            'id': j.get('id'),
            'company': j.get('company'),
            'title': j.get('title'),
            'city': j.get('city'),
            'district': j.get('district'),
            'address': j.get('address') or '',
            'salary_text': N.salary_text(j),
            'salary_max': j.get('salary_max'),
            'experience': j.get('experience'),
            'education': j.get('education'),
            'platforms': j.get('platforms') or [],
            'jd': j.get('jd'),
            'analysis': j.get('analysis'),
            'fit_score': j.get('fit_score'),
            'is_key': j.get('is_key') or 0,
            'difficulty': j.get('difficulty'),
            'deep_analysis': j.get('deep_analysis'),
            'rec_score': j.get('rec_score'),
            'commute': j.get('commute') or None,
            'url': j.get('url'),
            'status': j.get('status') or '未投递',
            'notes': j.get('notes'),
            'grabbed_at': j.get('created_at') or '',
            'created_at': j.get('created_at') or '',
        })
    return out


def _attach_commute(data, cm_meta):
    if not cm_meta.get('enabled') or not cm_meta.get('origin_loc'):
        return 0
    cc = cm_meta['commuter']
    n = 0
    for d in data:
        dest = (d.get('address') or '').strip()
        if not dest:
            continue
        res = cc.address_to_plan(cm_meta['origin_loc'], dest)
        if res and 'modes' in res:
            d['commute'] = res
            n += 1
    return n


TEMPLATE = r"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>薪途 PathToJob · 电商求职管理</title>
<style>
:root{--bg:#f5f6f8;--card:#fff;--bd:#e4e7ec;--bd2:#eef0f3;--tx:#1f2328;--tx2:#5b6470;--tx3:#8b949e;
--ac:#2563eb;--ac2:#1d4ed8;--ac-bg:#eff4ff;--ok:#16a34a;--okbg:#e9f7ef;--warn:#d97706;--warnbg:#fdf5e7;--gray:#f2f4f7;
--st-do:#94a3b8;--st-fav:#8b5cf6;--st-sub:#2563eb;--st-sel:#0ea5e9;--st-i1:#f59e0b;--st-i2:#d97706;--st-i3:#ea580c;
--st-off:#16a34a;--st-in:#15803d;--st-bad:#ef4444;}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--tx);font:14px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}
.wrap{max-width:1020px;margin:0 auto;padding:18px 16px 60px}
h1{font-size:23px;margin:0;font-weight:700;position:relative}
.sub{color:var(--tx3);font-size:13px;margin:4px 0 14px}
.tagline{background:linear-gradient(135deg,#eff4ff,#f5f0ff);border:1px solid #e4e0f5;border-radius:10px;
padding:9px 14px;color:var(--tx2);font-size:13px;margin-bottom:14px}
/* 简历栏 */
.resumebar{display:flex;align-items:center;gap:8px;background:#faf8ff;border:1px solid #e4def5;border-radius:10px;
  padding:7px 12px;font-size:12.5px;color:var(--tx2);margin-bottom:14px;flex-wrap:wrap}
.resumebar .rbl{font-weight:600;color:var(--tx)}
.resumebar #resume-st{flex:1;min-width:120px}
.resumebar .rbtn{padding:4px 12px;border:1px solid #b9a7e8;background:#fff;border-radius:6px;cursor:pointer;font-size:12px;color:#6d4fc2}
.resumebar .rbtn:hover{background:#f0ebff}
.resume-ok{color:#16a34a}.resume-none{color:var(--warn)}
/* 简历上传区 */
.resume-up{background:#f8f9fc;border:1px dashed #cdd5e0;border-radius:10px;padding:12px 14px}
.resume-up .ru-title{font-size:12.5px;font-weight:600;color:var(--tx);margin-bottom:8px}
.resume-up .ru-btn{padding:6px 14px;background:var(--ac);border:none;border-radius:6px;color:#fff;font-size:12.5px;cursor:pointer;margin-left:8px}
.resume-up .ru-btn:hover{opacity:.9}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(96px,1fr));gap:10px;margin-bottom:14px}
.stat{background:var(--card);border:1px solid var(--bd);border-radius:10px;padding:10px 13px;cursor:pointer;text-align:left;font-family:inherit;transition:.15s}
.stat:hover{border-color:var(--ac);box-shadow:0 2px 8px rgba(37,99,235,.08)}
.stat.on{border-color:var(--ac);background:var(--ac-bg);box-shadow:0 0 0 1px var(--ac) inset}
.stat.on .v{color:var(--ac)}
.stat .v{font-size:20px;font-weight:700;line-height:1.1}.stat .l{font-size:11px;color:var(--tx2);margin-top:2px}
.tools{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:14px}
input[type=text]{padding:8px 12px;border:1px solid var(--bd);border-radius:8px;font-size:13px;min-width:180px;outline:none}
input[type=text]:focus{border-color:var(--ac)}
select{padding:8px 10px;border:1px solid var(--bd);border-radius:8px;font-size:13px;background:#fff;color:var(--tx)}
.btn{padding:7px 13px;border:1px solid var(--bd);background:#fff;border-radius:8px;cursor:pointer;font-size:13px}
.btn:hover{background:var(--gray)}
.mut{color:var(--tx3);font-size:12px;margin-left:auto}
/* 多选批量 */
.cb{width:17px;height:17px;accent-color:var(--ac);cursor:pointer;flex:none}
.cb-col{display:flex;align-items:center;padding:14px 0 14px 16px;cursor:pointer}
.batchbar{display:none;gap:8px;align-items:center;background:var(--ac-bg);border:1px solid #cddcfb;
  border-radius:10px;padding:8px 12px;margin-bottom:12px;font-size:13px}
.batchbar.on{display:flex;flex-wrap:wrap}
.batchbar .bc{font-weight:700;color:var(--ac);margin-right:2px}
.batchbar select{padding:5px 8px;border:1px solid var(--bd);border-radius:6px;font-size:12.5px}
.batchbar .b-btn{padding:5px 12px;border:none;border-radius:6px;font-size:12.5px;cursor:pointer}
.b-done{background:var(--ac);color:#fff}.b-done:hover{opacity:.9}
.b-del{background:#fdecec;color:#c0392b}.b-del:hover{background:#fbd5d5}
.b-clear{background:#fff;border:1px solid var(--bd)!important;color:var(--tx2)}
.btn.batch-toggle{background:var(--ac-bg);color:var(--ac);border-color:#cddcfb}
.ftoggle{display:none;flex:0 0 auto}
.btn.batch-toggle.on{background:var(--ac);color:#fff;border-color:var(--ac)}
.job{background:var(--card);border:1px solid var(--bd);border-radius:13px;margin-bottom:15px;overflow:hidden}
.job-hd{display:flex;justify-content:space-between;align-items:flex-start;gap:10px;padding:13px 16px;
cursor:pointer;border-bottom:1px solid var(--bd2);flex-wrap:wrap}
.job-hd:hover{background:#fafbfc}
.job-hd h2{margin:0 0 2px;font-size:16.5px;font-weight:700}
.title-link{color:var(--tx);text-decoration:none;cursor:pointer}
.title-link:hover{color:var(--ac);text-decoration:underline}
.co{color:var(--ac2);font-size:13px;font-weight:600}
.meta{color:var(--tx3);font-size:12px;margin-top:3px}
.salary{font-weight:700;color:#c0392b;font-size:15.5px;white-space:nowrap;text-align:right}
.chev{color:var(--tx3);font-size:12px;text-align:right}
.badges{margin-top:6px}
/* 编辑/删除按钮 */
.job-ops{margin-top:6px;display:flex;gap:5px;justify-content:flex-end}
.op-btn{font-size:11.5px;padding:3px 9px;border-radius:6px;border:1px solid var(--bd);background:#fff;cursor:pointer;color:var(--tx2)}
.op-btn:hover{background:var(--ac-bg);color:var(--ac);border-color:var(--ac)}
.op-key{background:#fef9c3;border-color:#fde68a;color:#a16207}
.op-key:hover{background:#fef3c7;color:#92400e;border-color:#fbbf24}
.op-deep{background:#faf5ff;border-color:#f0abfc;color:#7c3aed;font-weight:600}
.op-deep:hover{background:#f3e8ff;color:#6d28d9;border-color:#d8b4fe}
.op-del:hover{background:#fdecec;color:#c0392b;border-color:#f5b8b8}
/* 编辑浮层 */
.edit-mask{position:fixed;inset:0;background:rgba(15,20,28,.5);z-index:200;display:none;align-items:flex-start;justify-content:center;padding:6vh 16px;overflow-y:auto}
.edit-mask.on{display:flex}
.edit-box{background:#fff;border-radius:14px;padding:22px 24px;width:100%;max-width:520px;box-shadow:0 10px 40px rgba(0,0,0,.25)}
.edit-box h3{margin:0 0 16px;font-size:17px}
.edit-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px 12px}
.edit-grid .full{grid-column:1/-1}
.edit-grid label{font-size:12px;color:var(--tx2);display:block;margin-bottom:3px}
.edit-grid input,.edit-grid select,.edit-grid textarea{width:100%;padding:7px 9px;border:1px solid var(--bd);border-radius:7px;font-size:13px;outline:none;background:#fff;color:var(--tx)}
.edit-grid input:focus,.edit-grid textarea:focus{border-color:var(--ac)}
.edit-grid textarea{min-height:70px;resize:vertical;font-family:inherit}
.edit-actions{display:flex;gap:8px;justify-content:flex-end;margin-top:16px}
.edit-actions button{padding:8px 18px;border-radius:8px;font-size:13px;cursor:pointer}
.ea-save{background:var(--ac);border:1px solid var(--ac);color:#fff}
.ea-save:hover{opacity:.9}
.ea-cancel{background:#fff;border:1px solid var(--bd);color:var(--tx2)}
.ea-del{background:#fdecec;border:1px solid #f5c6c6;color:#c0392b}
.ea-del:hover{background:#fbd5d5}
/* 深入分析侧边抽屉 */
.drawer-mask{position:fixed;inset:0;background:rgba(15,20,28,.45);z-index:300;display:none}
.drawer-mask.on{display:block}
.drawer{position:fixed;top:0;right:0;bottom:0;width:min(560px,92vw);background:#fff;z-index:301;
  box-shadow:-8px 0 30px rgba(0,0,0,.18);transform:translateX(100%);transition:transform .28s ease;
  display:flex;flex-direction:column}
.drawer.on{transform:translateX(0)}
.drawer-hd{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:15px 20px;
  background:linear-gradient(135deg,#7c3aed,#a855f7);color:#fff;flex:none}
.drawer-t{font-weight:800;font-size:16px}
.drawer-x{background:rgba(255,255,255,.18);border:none;color:#fff;width:28px;height:28px;border-radius:7px;
  cursor:pointer;font-size:15px;line-height:1}
.drawer-x:hover{background:rgba(255,255,255,.32)}
.drawer-bd{padding:16px 20px;overflow-y:auto;flex:1}
.drawer-job{margin-bottom:14px;padding-bottom:12px;border-bottom:1px dashed var(--bd2)}
.drawer-job h3{margin:0 0 4px;font-size:16px}
.drawer-job .co{color:var(--ac2);font-size:13px}
.drawer-job .meta{color:var(--tx3);font-size:12px;margin-top:4px}
.drawer-job .badges{margin-top:6px}
.drawer-panel{border:1px solid #f0abfc;border-radius:11px;overflow:hidden;margin:12px 0;background:#fff}
.drawer-panel .dp-h{padding:9px 14px;background:#faf5ff;font-weight:700;font-size:13.5px;color:#7c3aed;
  border-bottom:1px solid #f5d0fe}
.drawer-panel .dp-b{padding:10px 14px}
.badge{display:inline-block;padding:1px 7px;border-radius:20px;font-size:11px;margin-right:4px;background:var(--gray);color:var(--tx2)}
.badge.an{background:var(--okbg);color:var(--ok)}.badge.np{background:var(--warnbg);color:var(--warn)}
.badge.pf{background:var(--ac-bg);color:var(--ac)}
/* 进度条 */
.prog{margin:9px 0 0;max-width:420px}
.prog .track{display:flex;height:8px;border-radius:5px;overflow:hidden;background:var(--gray)}
.prog .seg-st{flex:1;margin:0 1px;background:transparent;border-radius:3px}
.prog .lab{font-size:11px;color:var(--tx2);margin-top:4px}
.prog .lab b{color:var(--tx)}
.pdot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:5px;vertical-align:0}
.job-bd{display:none;padding:4px 16px 14px}
.seg{margin:9px 0;border:1px solid var(--bd2);border-radius:10px;overflow:hidden;background:#fff}
.deep-seg{border:1.5px solid #f0abfc;background:linear-gradient(180deg,#faf5ff,#fff)}
.deep-seg .seg-h{background:#faf5ff;border-bottom:1px solid #f5d0fe}
.deep-seg .seg-h:hover{background:#f3e8ff}
.seg-h{display:flex;justify-content:space-between;align-items:center;gap:8px;padding:9px 14px;
cursor:pointer;font-weight:700;font-size:13.5px;user-select:none;background:#fafbfd}
.seg-h:hover{background:#f0f2f6}
.seg-bd{padding:10px 14px;border-top:1px solid var(--bd2);display:none}
.ic{display:inline-flex;width:18px;height:18px;border-radius:5px;align-items:center;justify-content:center;
font-size:11px;color:#fff;margin-right:7px;vertical-align:-2px;flex:none}
.kv{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:7px 18px;font-size:13px;padding:3px 0}
.kv .k{color:var(--tx3);font-size:11.5px}.kv .v{font-weight:600;word-break:break-all}
/* 通勤多方式 */
.cm{display:flex;gap:10px;flex-wrap:wrap;padding:4px 0}
.cm-mode{flex:1;min-width:110px;border:1px solid var(--bd2);border-radius:10px;padding:10px 12px;background:#fafbfd;text-align:center;cursor:pointer;transition:border-color .15s,background .15s,box-shadow .15s}
.cm-mode:hover{border-color:var(--ac);box-shadow:0 2px 6px rgba(37,99,235,.12)}
.cm-mode.cm-active{border-color:var(--ac);background:var(--ac-bg);box-shadow:0 0 0 2px rgba(37,99,235,.15)}
.cm-mode.cm-active[data-mode="transit"]{border-color:#16a34a;background:#e9f7ef;box-shadow:0 0 0 2px rgba(22,163,74,.18)}
.cm-mode.cm-active[data-mode="walking"]{border-color:#d97706;background:#fdf5e7;box-shadow:0 0 0 2px rgba(217,119,6,.18)}
.cm-plans{margin:8px 0 6px;display:flex;flex-direction:column;gap:5px}
.cm-plan{display:flex;align-items:center;gap:10px;padding:7px 10px;border:1px solid var(--bd2);border-radius:8px;
  background:#fafbfd;font-size:12.5px;cursor:pointer;color:var(--tx);transition:border-color .15s,background .15s}
.cm-plan.cm-active{border-color:var(--ac);background:var(--ac-bg);box-shadow:0 0 0 2px rgba(37,99,235,.14)}
.cm-plan:hover{background:#f0f6ff}
.cm-plan .cp-no{font-weight:700;color:var(--ac);min-width:48px}
.cm-plan .cp-tm,.cm-plan .cp-time{font-weight:700;color:var(--tx);font-size:13.5px;white-space:nowrap}
.cm-plan .cp-tm small,.cm-plan .cp-time small{font-size:10px;color:var(--tx3);font-weight:400;margin-left:1px}
.cm-plan .cp-desc{flex:1;min-width:0;font-size:12px;color:var(--tx2);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.cm-plan .cp-walk{color:var(--tx3);font-size:12px;white-space:nowrap}
.cm-mode .mt{font-size:12px;color:var(--tx2);margin-bottom:4px}
.cm-mode .mt b{font-size:14px;color:var(--tx)}
.cm-mode .big{font-size:19px;font-weight:700;color:var(--tx)}
.cm-mode .big small{font-size:11px;font-weight:400;color:var(--tx3)}
.cm-mode .km{font-size:11px;color:var(--tx3);margin-top:2px}
.cm-note{color:var(--warn);font-size:12px;margin-top:6px}
/* 通勤起点终点设置 */
.cm-cfg{margin:2px 0 10px;padding:8px 10px;background:#f0f6ff;border:1px solid #d3e3fd;border-radius:9px;font-size:12.5px}
.cm-cfg .row{display:flex;align-items:center;gap:6px;flex-wrap:wrap;margin:4px 0}
.cm-cfg input{flex:1;min-width:150px;padding:5px 8px;border:1px solid var(--bd);border-radius:6px;font-size:12.5px}
.cm-cfg .save{padding:5px 12px;border:none;background:var(--ac);color:#fff;border-radius:6px;cursor:pointer;font-size:12.5px}
.cm-cfg .save:hover{background:var(--ac2)}
.cm-cfg .st{font-size:11px;color:var(--tx3);margin-left:4px}
.cm-cfg .lbl{font-weight:600;color:var(--tx2);font-size:12px;flex:none}
/* 进度编辑 */
.st-sel{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-top:8px}
.st-sel select{padding:6px 8px;font-size:12.5px}
.analysis{font-size:13.5px;color:#333;line-height:1.75;white-space:pre-wrap}
.analysis ul{margin:3px 0;padding-left:20px}.analysis li{margin:3px 0}
.jd{white-space:pre-wrap;font-size:13px;color:#3a4150;background:#fafbfc;border-radius:7px;padding:11px 13px;
max-height:320px;overflow-y:auto;line-height:1.75;margin-top:2px}
.jd h3{font-size:13px;margin:0 0 6px;color:var(--tx2)}
.notes{white-space:pre-wrap;font-size:13px;background:#fffbe6;border:1px solid #f3e6b6;border-radius:7px;padding:10px}
.reflinks{margin-top:10px;padding-top:9px;border-top:1px dashed var(--bd2);display:flex;flex-wrap:wrap;gap:6px}
a.reflink{display:inline-block;padding:4px 11px;border:1px solid #d3d9e2;border-radius:16px;font-size:12px;
  color:var(--ac2);background:#fff;text-decoration:none}
a.reflink:hover{border-color:var(--ac);background:var(--ac-bg)}
.empty{padding:44px;text-align:center;color:var(--tx3)}
.foot{color:var(--tx3);font-size:12px;text-align:center;margin-top:24px}
a{color:var(--ac);text-decoration:none}a:hover{text-decoration:underline}
.mapbox{margin-top:10px;border:1px dashed var(--bd);border-radius:9px;padding:12px;color:var(--tx3);
font-size:12.5px;text-align:center;background:#fbfcfe}
/* ===== 手机端响应式 ===== */
@media(max-width:768px){
  body{padding:8px}
  .wrap{max-width:100%;padding:0}
  .tools{flex-wrap:wrap;gap:6px}
  .tools select,.tools input{flex:1 1 auto;min-width:44%}
  .ftoggle{display:inline-block;flex:0 0 auto}
  .tools.collapsed > *:not(#q):not(.ftoggle){display:none}
  .stats{grid-template-columns:repeat(2,1fr)}
  .job-hd{flex-direction:column}
  .job-hd h2{font-size:15px}
  .salary{text-align:left;margin-top:4px}
  .job-ops{flex-wrap:wrap}
  .badges{overflow-x:auto;white-space:nowrap;padding-bottom:2px}
  .kv{grid-template-columns:1fr 1fr}
  .drawer{width:100vw;max-width:100vw}
  .cm-mode{min-width:90px}
  .edit-box{max-width:96vw;margin:0 auto}
  .seg-h{font-size:13px}
}
@media(max-width:560px){
  .job-hd{flex-direction:column}
  .tools select,.tools input{min-width:100%}
  .reflinks a{font-size:11px}
}
/* 帮助弹窗 */
.help-mask{display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,.45);z-index:9999;
  align-items:center;justify-content:center;padding:20px}
.help-mask.on{display:flex}
.help-box{background:#fff;border-radius:16px;max-width:560px;width:100%;max-height:80vh;overflow-y:auto;
  padding:32px 28px;box-shadow:0 20px 60px rgba(0,0,0,.2);position:relative}
.help-box h2{margin:0 0 16px;font-size:20px;color:var(--tx)}
.help-box h3{margin:18px 0 8px;font-size:15px;color:var(--ac);border-bottom:1px solid var(--bd2);padding-bottom:5px}
.help-box p,.help-box li{font-size:13.5px;color:var(--tx2);line-height:1.8}
.help-box ul{padding-left:20px;margin:6px 0}
.help-box li{margin:4px 0}
.help-box code{background:#f0f2f5;padding:2px 6px;border-radius:4px;font-size:12.5px;color:var(--tx)}
.help-box .close{position:absolute;top:14px;right:16px;border:none;background:none;font-size:22px;
  cursor:pointer;color:var(--tx3);padding:4px 8px;border-radius:6px}
.help-box .close:hover{background:var(--gray);color:var(--tx)}
.help-box .step{display:flex;gap:10px;align-items:flex-start;margin:8px 0}
.help-box .step-n{flex:none;width:26px;height:26px;border-radius:50%;background:var(--ac);color:#fff;
  font-size:13px;font-weight:700;display:flex;align-items:center;justify-content:center}
.help-box .step-t{flex:1}
.help-box .step-t b{color:var(--tx)}
.dl-btn{display:inline-block;padding:6px 16px;background:var(--ac);color:#fff!important;text-decoration:none;
  border-radius:8px;font-size:13px;font-weight:600;cursor:pointer;transition:all .2s;text-decoration:none!important}
.dl-btn:hover{background:var(--ac2);transform:translateY(-1px);box-shadow:0 3px 10px rgba(37,99,235,.25)}
/* 安装图示 */
.guide-box{margin:8px 0 8px 36px;border:1px solid #e5e7eb;border-radius:10px;overflow:hidden;background:#fafbfc}
.guide-label{font-size:12px;font-weight:700;color:var(--ac);padding:6px 12px;background:#f0f7ff;border-bottom:1px solid #e0e7ff}
.guide-row{padding:10px 12px}
.guide-card{text-align:center}
.guide-browser{border:1px solid #d1d5db;border-radius:8px;overflow:hidden;background:#fff;display:inline-block}
.browser-bar{display:flex;align-items:center;gap:4px;padding:4px 6px;background:#e8e8e8;border-bottom:1px solid #d1d5db}
.browser-bar .win-btns{display:flex;gap:3px;margin-right:4px}
.browser-bar .win-btn{width:12px;height:12px;border-radius:2px;display:flex;align-items:center;justify-content:center;font-size:8px;line-height:1}
.wb-r{background:#e81123;color:#fff}.wb-m{background:#f5f5f5;color:#333;border:1px solid #ccc}.wb-x{background:#e81123;color:#fff}
.addr{font-size:9px;color:#333;background:#fff;padding:2px 6px;border-radius:3px;flex:1;text-align:left;border:1px solid #ccc;font-family:inherit}
.browser-body{padding:8px;min-height:60px}
.guide-caption{font-size:11.5px;color:#374151;margin-top:8px;line-height:1.6;text-align:left}
.guide-caption code{background:#f0f2f5;padding:1px 4px;border-radius:3px;font-size:11px}
.guide-caption b{color:#1d4ed8}
/* 首次使用提示横幅 */
.help-banner{display:flex;align-items:center;gap:12px;padding:12px 16px;margin-bottom:16px;
  background:linear-gradient(135deg,#eff4ff 0%,#f5f0ff 50%,#fef3f2 100%);
  border:1.5px solid #c7d2fe;border-radius:12px;cursor:pointer;transition:all .2s}
.help-banner:hover{border-color:#818cf8;box-shadow:0 4px 16px rgba(99,102,241,.15);transform:translateY(-1px)}
.hb-icon{font-size:28px;flex:none}
.hb-text{flex:1;min-width:0}
.hb-text b{display:block;font-size:14.5px;color:#1e1b4b;margin-bottom:2px}
.hb-text span{font-size:12.5px;color:#6b7280}
.hb-arrow{font-size:20px;color:#818cf8;font-weight:700;flex:none}
</style>
__AMAP_HEAD__
</head>
<body>
<div class="wrap">
<h1>🧭 薪途 PathToJob</h1><span class="user-badge" style="position:absolute;right:100px;top:18px;font-size:15px;color:#374151;display:flex;align-items:center;gap:6px"><span style="font-weight:600">👤 __USERNAME__</span><span style="font-size:13px;color:#9ca3af;background:#f3f4f6;padding:2px 8px;border-radius:4px">PTJ-__USER_ID__</span></span><button class="btn" onclick="doLogout()" style="color:#c0392b;position:absolute;right:16px;top:14px" title="退出登录">🚪 退出</button>
<div class="sub">生成于 __GEN__ · 岗位 __N__ · 已分析 __A__ · 已算通勤 __C__</div>
<div class="help-banner" id="help-banner" onclick="document.getElementById('help-mask').className='help-mask on'">
  <div class="hb-icon">📖</div>
  <div class="hb-text">
    <b>新用户必看：3 分钟学会用</b>
    <span>如何抓岗位 · 如何管理投递进度 · 如何看 AI 分析</span>
  </div>
  <div class="hb-arrow">→</div>
</div>
<div class="resumebar" id="resumebar">
  <span class="rbl">📄 我的简历：</span><span id="resume-st">加载中…</span>
  <button class="rbtn" onclick="openResume()">导入 / 更新</button>
  <button class="rbtn" id="resume-del" onclick="deleteResume()" style="display:none">删除</button>
</div>
<div class="stats" id="stats"></div>
<div class="tools" id="tools">
  <input type="text" id="q" placeholder="搜公司 / 岗位 / 分析…">
  <button class="btn ftoggle" id="ftoggle" onclick="toggleFilter()">筛选 ▾</button>
  <select id="f-pf"><option value="">全部平台</option><option value="boss">Boss直聘</option><option value="51job">前程无忧</option><option value="liepin">猎聘</option><option value="zhilian">智联招聘</option><option value="yupao">鱼泡直聘</option></select>
  <select id="f-an"><option value="">全部分析</option><option value="yes">已分析</option><option value="no">待分析</option></select>
  <select id="f-st"><option value="">全部进度</option></select>
  <select id="f-cm"><option value="">通勤不限</option><option value="fast">通勤&lt;60分钟</option><option value="slow">通勤≥60分钟</option></select>
  <select id="f-fit"><option value="">适配指数不限</option><option value="high">高（≥75）</option><option value="mid">中（60-74）</option><option value="low">低（&lt;60）</option><option value="none">待分析</option></select>
  <select id="sort"><option value="">按进度排序</option><option value="sal">按薪资高→低</option>
    <option value="cm">按通勤近→远</option><option value="new">按收录新→旧</option><option value="fit">按适配指数高→低</option><option value="rec">按推荐指数高→低</option></select>
  <button class="btn batch-toggle" id="batch-toggle" onclick="toggleBatch()">☑️ 批量选择</button>
  <button class="btn" id="reset">重置</button><span class="mut" id="cnt"></span>
</div>
<div class="batchbar" id="batchbar">
  <span>已选 <span class="bc">0</span> 个</span>
  <select id="batch-status"><option value="">改状态为…</option>
    <option value="已投递">已投递</option><option value="简历筛选中">简历筛选中</option>
    <option value="已约面试">已约面试</option><option value="一轮面试">一轮面试</option>
    <option value="二轮面试">二轮面试</option><option value="三轮终面">三轮终面</option>
    <option value="已发Offer">已发Offer</option><option value="已入职">已入职</option>
    <option value="不合适">不合适</option><option value="已婉拒">已婉拒</option><option value="已过期">已过期</option>
  </select>
  <button class="b-btn b-done" onclick="if(el('batch-status').value)batchSetStatus(el('batch-status').value)">✓ 应用状态</button>
  <button class="b-btn b-del" onclick="batchDelete()">🗑️ 批量删除</button>
  <button class="b-btn b-clear" onclick="selAll()">全选当前筛选</button>
  <button class="b-btn b-clear" onclick="selClear()">清除选择</button>
</div>
<div id="list"></div>
<div class="empty" id="none" style="display:none">没有匹配岗位</div>
<div class="foot">薪途 PathToJob · 数据仅存本机</div>
</div>

<div class="edit-mask" id="edit-mask" onclick="if(event.target===this)closeEdit()"><div class="edit-box" id="edit-box"></div></div>
<div class="edit-mask" id="resume-mask" onclick="if(event.target===this)closeResume()"><div class="edit-box" id="resume-box"></div></div>

<!-- 帮助弹窗 -->


<script>
// API 基础地址：跟随当前页面域名，兼容本机(127.0.0.1)/局域网/云端访问
const API = location.protocol+'//'+location.host;
const API_TOKEN = (function(){var m=document.cookie.match(/session_token=([^;]+)/);return m?m[1]:''})()||__API_TOKEN__||'';
// 包装 fetch：自动为所有请求加 X-API-Token（云端鉴权用）
const _origFetch = window.fetch.bind(window);
window.fetch = function(url, opts){
  opts = opts||{};
  const headers = new Headers(opts.headers||{});
  if(API_TOKEN) headers.set('X-API-Token', API_TOKEN);
  opts.headers = headers;
  return _origFetch(url, opts);
};
const DATA=__DATA__;
const esc=s=>(s==null?'':String(s)).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const el=id=>document.getElementById(id);
const escA=s=>esc(s).replace(/'/g,"&#39;");

/* 进度流水线定义：名称 -> (颜色) */
const FLOW=['未投递','已投递','简历筛选中','已约面试','一轮面试','二轮面试','三轮终面','已发Offer','已入职'];
const TERM={} ;['不合适','已婉拒','已过期'].forEach(s=>TERM[s]=1);
const STCOL={'未投递':'#94a3b8','已收藏':'#8b5cf6','已投递':'#2563eb','简历筛选中':'#0ea5e9','已约面试':'#f59e0b',
'一轮面试':'#f59e0b','二轮面试':'#d97706','三轮终面':'#ea580c','已发Offer':'#16a34a','已入职':'#15803d',
'不合适':'#ef4444','已婉拒':'#94a3b8','已过期':'#cbd5e1','已归档':'#94a3b8','待处理':'#94a3b8','已沟通':'#0ea5e9','面试中':'#f59e0b','已offer':'#16a34a'};
function normSt(s){ // 旧状态值归一为流水线
  const m={'待处理':'未投递','已沟通':'简历筛选中','面试中':'一轮面试','已offer':'已发Offer'};
  return (s&&m[s])?m[s]:(s||'未投递');
}
function stColor(s){return STCOL[s]||'#94a3b8'}
/* 平台中文名 + 品牌色 */
const PF_NAME={'boss':'Boss直聘','51job':'前程无忧','liepin':'猎聘','zhilian':'智联招聘','yupao':'鱼泡直聘','other':'其他'};
const PF_COLOR={'boss':'#2563eb','51job':'#ea580c','liepin':'#7c3aed','zhilian':'#0891b2','yupao':'#16a34a','other':'#64748b'};

function togJob(id){const b=el('bd-'+id),c=el('chv-'+id);const show=b.style.display!=='block';b.style.display=show?'block':'none';if(c)c.textContent=show?'▲':'▼';}
/* ===== 筛选栏收起/展开（手机端默认收起） ===== */
function toggleFilter(){
  const t=el('tools');
  const c=t.classList.toggle('collapsed');
  el('ftoggle').textContent=c?'筛选 ▾':'收起 ▴';
}
// 手机端默认收起筛选栏（宽度<=768 时初始化 collapsed）
if(window.innerWidth<=768){el('tools').classList.add('collapsed');}
/* ===== 多选批量 ===== */
let _batchMode=false;
const _sel=new Set();
function toggleBatch(){
  _batchMode=!_batchMode;
  _sel.clear();
  el('batch-toggle').classList.toggle('on',_batchMode);
  el('batchbar').classList.toggle('on',_batchMode);
  el('batchbar').querySelector('.bc').textContent='0';
  render();
}
function toggleSel(id,on){if(on)_sel.add(id);else _sel.delete(id);el('batchbar').querySelector('.bc').textContent=_sel.size;}
function selAll(){
  const vis=document.querySelectorAll('.job[data-id]');
  let n=0;
  vis.forEach(card=>{if(card.style.display!=='none'){const ck=card.querySelector('.cb');if(ck&&!ck.checked){ck.checked=true;_sel.add(card.dataset.id);n++;}}});
  el('batchbar').querySelector('.bc').textContent=_sel.size;
}
function selClear(){_sel.clear();render();}
function batchSetStatus(v){
  if(_sel.size===0){alert('请先勾选岗位');return;}
  const ids=[..._sel];
  let done=0,fail=0;
  ids.forEach((id,i)=>{
    fetch(API+'/api/job/'+id,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({status:v})})
      .then(r=>r.json()).then(d=>{d.ok?done++:fail++;if(i===ids.length-1){alert(`批量改状态完成：成功 ${done}，失败 ${fail}`);if(done){_sel.clear();location.reload();}}})
      .catch(()=>{fail++;if(i===ids.length-1)alert(`失败 ${fail} 条：连不上本地服务`);});
  });
}
function batchDelete(){
  if(_sel.size===0){alert('请先勾选岗位');return;}
  const ids=[..._sel];
  const names=ids.map(id=>{const j=DATA.find(x=>x.id===id);return j?(j.company+'｜'+j.title):id;});
  const listShow=names.slice(0,8).map(n=>'· '+n).join('\n')+(names.length>8?`\n…等共 ${names.length} 个`:'');
  if(!confirm(`确定删除以下 ${names.length} 个岗位？此操作不可撤销！\n\n${listShow}`))return;
  let done=0,fail=0;
  ids.forEach((id,i)=>{
    fetch(API+'/api/job/'+id+'/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'})
      .then(r=>r.json()).then(d=>{if(d&&d.ok)done++;else fail++;if(i===ids.length-1){alert(`批量删除：成功 ${done}，失败 ${fail}`);if(done){_sel.clear();location.reload();}}})
      .catch(()=>{fail++;if(i===ids.length-1)alert(`失败 ${fail} 条：连不上本地服务`);});
  });
}
function togSeg(id){const b=el(id),s=b.closest('.seg'),show=b.style.display!=='block';b.style.display=show?'block':'none';if(s){const c=s.querySelector('.chev');if(c)c.textContent=show?'▾':'▸';}
  if(show&&id.indexOf('cm-')===0){const jid=id.slice(3);const j=DATA.find(x=>x.id===jid);if(j&&j.commute)initAmapFor(jid,j.commute);}}
function evSt(e,id){e.stopPropagation();const v=e.target.value;fetchStatus(id,v);}

/* 状态写入：调本地服务 API 真正入库（进度修改需持久化） */
function fetchStatus(id,v){
  const j=DATA.find(x=>x.id===id); if(!j)return;
  const old=j.status; j.status=v;
  const job=document.querySelector('.job[data-id="'+id+'"]');
  if(job)refreshJob(id,job);
  toast(id,'保存中…');
  fetch(API+'/api/job/'+id,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({status:v})})
    .then(r=>r.json()).then(d=>{toast(id,d.ok?('✓ 状态已存：'+v):('✗ '+d.error));})
    .catch(()=>{j.status=old;toast(id,'✗ 本地服务未开，未入库');});
}
function toast(id,msg){const t=el('t'+id);if(t)t.textContent=msg;setTimeout(()=>{if(t)t.textContent=''},2600);}

function parts(a){if(!a)return[];const o=[];const re=/【([^】]+)】([\s\S]*?)(?=【|$)/g;let m;while((m=re.exec(a)))o.push({t:m[1].trim(),b:m[2].trim()});return o;}
function mi(s){return esc(s).replace(/\*\*(.+?)\*\*/g,'<b>$1</b>')}
function toHtml(b){let h='',inl=false;const re=/^([-•·*]|\d+[.、])\s+(.*)$/;for(const r of (b||'').split('\n')){const l=r.trim(),it=l.match(re);if(it){if(!inl){h+='<ul>';inl=true}h+='<li>'+mi(it[2])+'</li>'}else{if(inl){h+='</ul>';inl=false}if(l)h+='<p>'+mi(l)+'</p>'}}if(inl)h+='</ul>';return h}
const iconOf=t=>{if(/实际内容|干嘛|干什么/.test(t))return'🔍';if(/适配|优缺点|对你/.test(t))return'🧭';if(/面试/.test(t))return'💬';if(/公司|经营|行业/.test(t))return'🏢';if(/难度/.test(t))return'🎯';if(/总结|判断/.test(t))return'✅';return'📌'};
const colOf=t=>{if(/实际内容|干嘛|干什么/.test(t))return'#2563eb';if(/适配|优缺点|对你/.test(t))return'#7c3aed';if(/面试/.test(t))return'#16a34a';if(/公司|经营|行业/.test(t))return'#d97706';if(/难度/.test(t))return'#dc2626';return'#475569'};
/* 旧分析标题 → 新展示名（按 BOSS v3 要求） */
function titleName(t){
  if(/实际内容|干嘛|干什么/.test(t))return'岗位实际内容';
  if(/适配|优缺点|对你/.test(t))return'岗位适配情况';
  if(/公司|经营|行业/.test(t))return'公司经营状况+行业机会';
  if(/面试/.test(t))return'面试攻略';
  if(/总结|判断/.test(t))return'总结判断';
  return t;
}

/* 外部参考链接：跳转主流平台搜索（不爬取，平台反爬不允许） */
const REF_ENGINES=[
  {n:'小红书', f:kw=>'https://www.xiaohongshu.com/search_result?keyword='+encodeURIComponent(kw)+'&source=web_search_result_notes'},
  {n:'抖音',   f:kw=>'https://www.douyin.com/search/'+encodeURIComponent(kw)},
  {n:'知乎',   f:kw=>'https://www.zhihu.com/search?type=content&q='+encodeURIComponent(kw)},
  {n:'百度',   f:kw=>'https://www.baidu.com/s?wd='+encodeURIComponent(kw)},
];
function refLinks(kind, company, title){
  const kw = kind==='company'
    ? `${company} 公司 怎么样 评价 招聘`
    : `${title} ${company} 面试 经验 面经`;
  const btns=REF_ENGINES.map(r=>`<a class="reflink" target="_blank" rel="noopener" href="${r.f(kw)}">${r.n}搜「${esc((kind==='company'?company:title).slice(0,12))}」</a>`).join('');
  return `<div class="reflinks">${btns}</div>`;}

function seg(id,ic,title,body,defOpen){const isDeep=/深入专项/.test(title);
  return `<div class="seg${isDeep?' deep-seg':''}"><div class="seg-h" onclick="togSeg('${id}')">
<span><span class="ic" style="background:${isDeep?'#d97706':colOf(title)}">${ic}</span>${esc(title)}</span><span class="chev">${defOpen?'▾':'▸'}</span></div>
<div class="seg-bd" id="${id}" style="display:${defOpen?'block':'none'}">${body}</div></div>`}
function kvRow(k,v){return (v==null||v==='')?'':`<div><div class="k">${esc(k)}</div><div class="v">${esc(v)}</div></div>`}

const CM_LABEL={driving:'驾车',transit:'公交',walking:'步行'};
/* 通勤设置：起点(全局) / 终点(该岗位) */
const ORIGIN_NAME=__ORIGIN_NAME__;
const ORIGIN_RAW=__ORIGIN_RAW__;
function saveOrigin(btn,o,on){
  const inp=btn.parentElement.querySelector('input');
  const val=(inp.value||'').trim();
  if(!val){btn.nextElementSibling.textContent='请输入地址';return;}
  const st=btn.parentElement.querySelector('.st');
  st.textContent='保存中…';
  fetch(API+'/api/commute',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({origin:val,origin_name:o&&o.value?o.value.trim():''})})
    .then(r=>r.json()).then(d=>{st.textContent=d.ok?'已保存，正在重算…请稍后刷新页面':'失败:'+d.error;if(d.ok)setTimeout(()=>location.reload(),1200);})
    .catch(()=>{st.textContent='连不上本地服务，请先运行 python run.py serve'});}
function saveDest(btn){
  const row=btn.closest('.cm-cfg').querySelectorAll('input')[1];
  const jid=btn.dataset.jid,addr=(row.value||'').trim();
  const st=btn.parentElement.querySelector('.st');
  if(!addr){st.textContent='请输入地址';return;}
  st.textContent='保存中…';
  fetch(API+'/api/job/address',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({id:jid,address:addr})})
    .then(r=>r.json()).then(d=>{st.textContent=d.ok?'已保存并重算，请稍后刷新':'失败:'+d.error;if(d.ok)setTimeout(()=>location.reload(),1200);})
    .catch(()=>{st.textContent='连不上本地服务，请先运行 python run.py serve'});}
function cmCfg(jid,destAddr){
  return `<div class="cm-cfg">
    <div style="font-weight:700;font-size:12.5px;margin-bottom:2px">⚙ 通勤设置（需本地服务 python run.py serve）</div>
    <div class="row"><span class="lbl">起点</span><input placeholder="如：杭州市余杭区文一西路969号" value="">
      <button class="save" onclick="saveOrigin(this)">保存起点</button><span class="st"></span></div>
    <div class="row"><span class="lbl">终点</span><input placeholder="该岗位工作地址" value="${esc(destAddr||'')}">
      <button class="save" data-jid="${jid}" onclick="saveDest(this)">保存终点</button><span class="st"></span></div>
    <div class="st" style="color:var(--tx3)">当前起点：${esc(ORIGIN_NAME||ORIGIN_RAW||'(未设置)')}</div>
  </div>`;}
function routeSvg(c){
  const drv=c&&c.modes&&c.modes.driving, pl=drv&&drv.polyline;
  if(!pl||pl.length<2)return'<div class="mapbox">暂无路线数据（缺少精确地址）</div>';
  const W=660,H=300,pad=26;
  const lngs=pl.map(p=>p[0]),lats=pl.map(p=>p[1]);
  const mnL=Math.min(...lngs),mxL=Math.max(...lngs),mnT=Math.min(...lats),mxT=Math.max(...lats);
  const spanL=Math.max(mxL-mnL,0.004),spanT=Math.max(mxT-mnT,0.004);
  const scale=Math.min((W-2*pad)/spanL,(H-2*pad)/spanT);
  const offX=(W-spanL*scale)/2,offY=(H-spanT*scale)/2;
  const X=p=>offX+(p[0]-mnL)*scale, Y=p=>H-offY-(p[1]-mnT)*scale;
  const line=pl.map((p,i)=>(i?'L':'M')+X(p).toFixed(1)+' '+Y(p).toFixed(1)).join(' ');
  const s=X(pl[0]),t=Y(pl[0]),e=X(pl[pl.length-1]),et=Y(pl[pl.length-1]);
  return `<div class="mapbox" style="padding:0;overflow:hidden">
    <svg viewBox="0 0 ${W} ${H}" style="width:100%;height:auto;display:block;background:#eef3f9">
      <rect width="${W}" height="${H}" fill="#eef3f9"/>
      <path d="${line}" fill="none" stroke="#2563eb" stroke-width="3" stroke-linejoin="round" stroke-linecap="round"/>
      <circle cx="${s}" cy="${t}" r="7" fill="#ef4444" stroke="#fff" stroke-width="2"/>
      <circle cx="${e}" cy="${et}" r="7" fill="#16a34a" stroke="#fff" stroke-width="2"/>
      <text x="${Math.max(4,s-20)}" y="${Math.max(14,t-10)}" font-size="13" fill="#dc2626" font-weight="bold">起</text>
      <text x="${e+4}" y="${et+18}" font-size="13" fill="#15803d" font-weight="bold">终</text>
      <text x="10" y="${H-10}" font-size="12" fill="#5b6470">驾车 ${drv.minutes} 分钟 · 约 ${drv.distance} km（路线示意）</text>
    </svg></div>`;}
function cmBlock(c,jid){if(!c||!c.modes)return null;let m='';
  for(const k of ['driving','transit','walking']){
    const v=c.modes[k];
    if(!v)continue;
    m+=`<div class="cm-mode" data-jid="${jid}" data-mode="${k}" onclick="pickMode('${jid}','${k}')" title="点击查看${({driving:'驾车',transit:'公交',walking:'步行'})[k]}路线">
      <div class="mt">${CM_LABEL[k]||k}</div>
      <div class="big">${v.minutes}<small> 分钟</small></div><div class="km">约${v.distance}km${v.note?'（'+esc(v.note)+'）':''}</div></div>`;}
  const drv=c.modes.driving;
  const transitPlans=(c.modes.transit&&c.modes.transit.plans&&c.modes.transit.plans.length)
    ?'<div class="cm-plans" id="plans-'+jid+'">'+c.modes.transit.plans.map(p=>
      '<div class="cm-plan" data-jid="'+jid+'" data-pidx="'+p.idx+'" onclick="pickPlan(\''+jid+'\','+p.idx+')">'
      +'<span class="cp-no">方案'+(p.idx+1)+'</span>'
      +'<span class="cp-tm">'+p.minutes+'<small>分钟</small></span>'
      +'<span class="cp-desc">'+esc(p.desc||'')+'</span>'
      +'<span class="cp-walk">步行'+p.walk_km+'km</span>'
      +'</div>').join('')+'</div>'
    :'';
  const mapHtml=(AMAP_READY&&drv&&drv.polyline&&drv.polyline.length>1)
    ?`<div class="mapbox" style="padding:0;height:320px;overflow:hidden" id="amap-${jid}"><div class="cm-loading" style="padding:140px 0;text-align:center;color:var(--tx3)">地图加载中…</div></div>`
    :routeSvg(c);
  return cmCfg(jid,c.dest_address)+`<div class="cm">${m}</div>
    ${transitPlans}
    <div class="cm-note">终点：${esc(c.dest_address||'')}${drv?` · 驾车约${drv.minutes}分钟`:''} ${AMAP_READY?'<span style="color:var(--tx3);font-size:11px">点上方卡片切换驾车/公交/步行；点方案切具体路线</span>':''}</div>
    ${mapHtml}`;}

/* ============ 高德 JS API 真地图 ============ */
const AMAP_READY=__AMAP_READY__;
/* maps 脚本已在 <head> 静态加载（v2 官方推荐）。这里只等 AMap 就绪，轮询最多 10s。 */
function amapWait(cb){
  let t=0;
  const tryIt=()=>{
    if(window.AMap){cb&&cb();return;}
    t+=500;
    if(t>10000){console.warn('AMap 10s 未就绪');cb&&cb('timeout');return;}
    setTimeout(tryIt,500);
  };
  tryIt();
}
function renderRealMap(jid,c){
  const el=document.getElementById('amap-'+jid);
  if(!el)return;
  if(!window.AMap){el.innerHTML='<div class="cm-note" style="padding:8px">高德 SDK 未加载（检查 key/白名单/控制台报错）</div>';return;}
  const drv=c.modes.driving, pl=drv.polyline;
  el.innerHTML='';
  const map=new AMap.Map(el,{zoom:11,viewMode:'2D',resizeEnable:true});
  el._amap={map, polylines:[], markers:[], texts:[], modes:c.modes, cur:null};
  // 默认显示驾车
  selectMapMode(el,'driving');
  // fitView 兜底 + 容器 resize（折叠分节展开后尺寸才是真实的）
  map.on('complete',()=>{try{const i=el._amap;if(i&&i.polylines[0])map.setFitView([i.polylines[0]],false,[50,50,50,50]);}catch(e){}});
  setTimeout(()=>{try{map.resize();const i=el._amap;if(i&&i.polylines[0])map.setFitView([i.polylines[0]],false,[50,50,50,50]);}catch(e){}},350);
}
function clearMapOverlays(el){
  const s=el._amap; if(!s)return;
  try{s.map.clearMap();}catch(e){}
  s.polylines=[]; s.markers=[]; s.texts=[];
}
function selectMapMode(el,mode,planIdx){
  const s=el._amap; if(!s)return;
  clearMapOverlays(el);
  const m=s.modes[mode]; if(!m)return;
  s.cur=mode;
  const map=s.map;
  // 取 polyline：公交且给了方案号 → 用该方案的 polyline；否则默认 m.polyline（=方案0）
  let pl=m.polyline||[];
  if(mode==='transit' && m.plans && m.plans.length){
    const pi=Math.min(planIdx||0, m.plans.length-1);
    pl=(m.plans[pi]&&m.plans[pi].polyline&&m.plans[pi].polyline.length>1)?m.plans[pi].polyline:(m.polyline||[]);
    s.curPlan=pi;
  } else { s.curPlan=null; }
  // 公交时显示方案列表，其余隐藏
  const plansBox=document.getElementById('plans-'+el.id.replace(/^amap-/,''));
  if(plansBox)plansBox.style.display=(mode==='transit')?'flex':'none';
  // 方案高亮
  if(mode==='transit'&&plansBox){
    [...plansBox.querySelectorAll('.cm-plan')].forEach(b=>b.classList.toggle('cm-active',Number(b.dataset.pidx)===s.curPlan));
  }
  if(!pl||pl.length<2){
    // 该方式无路线坐标（如跨城公交/地铁）——显示提示卡片
    el.innerHTML+='<div style="position:absolute;left:50%;top:14px;transform:translateX(-50%);background:#fff;border:1px solid var(--bd);border-radius:8px;padding:8px 14px;font-size:13px;color:var(--tx2);box-shadow:0 2px 8px rgba(0,0,0,.1);z-index:10">'+({transit:'公交',walking:'步行'})[mode]+'方案耗时 '+m.minutes+' 分钟（'+(m.distance||'?')+'km）— 路线坐标未提供，请切换其他方式查看地图</div>';
    map.setCity && map.setCity('杭州');
    map.setZoom && map.setZoom(11);
    map.setCenter && map.setCenter([120.13,30.27]);
    const modes=['driving','transit','walking'];
    modes.forEach(mm=>{
        const btn=document.querySelector('.cm-mode[data-jid="'+el.id.replace(/^amap-/,'')+'"][data-mode="'+mm+'"]');
        if(btn) btn.classList.toggle('cm-active',mm===mode);
      });
    return;
  }
  const path=pl.map(p=>[p[0],p[1]]);
  const color=mode==='driving'?'#2563eb':(mode==='transit'?'#16a34a':'#d97706');
  const label={driving:'驾车',transit:'公交',walking:'步行'}[mode]||mode;
  // 每个覆盖物独立 try：一个失败不影响其余（v2 各组件容错不同）
  try{
    const poly=new AMap.Polyline({path,strokeColor:color,strokeWeight:6,strokeOpacity:.9,showDir:true,map});
    s.polylines.push(poly);
  }catch(e){}
  try{
    const icon=(c)=>new AMap.Icon({size:new AMap.Size(22,32),image:c,imageOffset:new AMap.Pixel(-11,-32)});
    s.markers.push(new AMap.Marker({position:[pl[0][0],pl[0][1]],icon:icon('https://webapi.amap.com/theme/v1.3/markers/n/mark_r.png'),map}));
    s.markers.push(new AMap.Marker({position:[pl[pl.length-1][0],pl[pl.length-1][1]],icon:icon('https://webapi.amap.com/theme/v1.3/markers/n/mark_b.png'),map}));
  }catch(e){}
  // 起终点文字：用 Marker+label（Text 在 v2 偶有兼容问题，弃用）
  // 中央耗时标签使用当前方案的耗时/距离（切方案时实时更新）
  const curP=(mode==='transit'&&s.curPlan!=null&&m.plans&&m.plans[s.curPlan])?m.plans[s.curPlan]:null;
  const showMin=curP?curP.minutes:m.minutes;
  const showDist=curP?curP.walk_km:m.distance;
  try{
    const mid=pl[Math.floor(pl.length/2)];
    s.markers.push(new AMap.Marker({position:[pl[0][0],pl[0][1]],label:{content:'起',direction:'top',offset:new AMap.Pixel(-6,-6),style:{color:'#fff',background:'#dc2626',border:'none',padding:'1px 5px','font-size':'11px'}},map}));
    s.markers.push(new AMap.Marker({position:[pl[pl.length-1][0],pl[pl.length-1][1]],label:{content:'终',direction:'top',offset:new AMap.Pixel(-6,-6),style:{color:'#fff',background:'#15803d',border:'none',padding:'1px 5px','font-size':'11px'}},map}));
    s.markers.push(new AMap.Marker({position:[mid[0],mid[1]],content:'<div style="background:'+color+';color:#fff;padding:3px 9px;border-radius:6px;font-size:12px;white-space:nowrap;box-shadow:0 2px 6px rgba(0,0,0,.25)">'+label+' '+showMin+'分钟 · '+showDist+'km</div>',offset:new AMap.Pixel(-10,-12),map}));
  }catch(e){}
  try{const p2=s.polylines[s.polylines.length-1];if(p2)map.setFitView([p2],false,[40,40,40,40]);}catch(e){}
  const modes=['driving','transit','walking'];
  modes.forEach(mm=>{
      const btn=document.querySelector('.cm-mode[data-jid="'+el.id.replace(/^amap-/,'')+'"][data-mode="'+mm+'"]');
      if(btn) btn.classList.toggle('cm-active',mm===mode);
    });
}
/* 点卡片切路线：地图没初始化就先展开分节+初始化，就绪后切换 */
function pickMode(jid,mode,planIdx){
  const el=document.getElementById('amap-'+jid);
  if(!el)return;
  const job=DATA.find(x=>x.id===jid);
  if(el._amap){selectMapMode(el,mode,planIdx);return;}
  const seg=el.closest('.seg-bd');
  if(seg&&seg.style.display!=='block'){const sh=seg.closest('.seg').querySelector('.seg-h');if(sh)sh.click();}
  const jc=job&&job.commute;
  if(jc)initAmapFor(jid,jc);
  let n=0;
  const wait=()=>{if(el._amap){selectMapMode(el,mode,planIdx);return;}n++;if(n<12)setTimeout(wait,400);};
  setTimeout(wait,600);
}
/* 点公交方案条目：切到公交 + 画该方案路线 */
function pickPlan(jid,idx){
  pickMode(jid,'transit',idx);
}
function initAmapFor(jid,c){
  if(!AMAP_READY)return;
  const el=document.getElementById('amap-'+jid);
  if(!el)return;
  if(el._amap)return;          // 已建成，无需再建
  if(el.dataset.busy)return;   // 正在初始化中，避免并发
  el.dataset.busy='1';
  amapWait((err)=>{
    if(err){el.innerHTML='<div class="cm-note" style="padding:8px">地图 SDK 加载超时，请检查网络/控制台</div>';delete el.dataset.busy;return;}
    try{renderRealMap(jid,c);}
    catch(e){el.innerHTML='<div class="cm-note" style="padding:8px">地图渲染失败：'+esc(e.message)+'</div>';}
    finally{delete el.dataset.busy;}
  });
}

function progBar(st){const ns=normSt(st);const idx=FLOW.indexOf(ns);const done=idx>=0?idx+1:0;
  const f=FLOW.slice(0,Math.max(0,done)).map((s,i)=>`<div class="seg-st" style="background:${stColor(s)}"></div>`).join('');
  const rest=FLOW.slice(Math.max(0,done)).map(()=>'<div class="seg-st"></div>').join('');
  const col=idx>=0?stColor(FLOW[idx]):stColor(ns);
  return `<div class="prog"><div class="track">${f}${rest}</div>
    <div class="lab"><span class="pdot" style="background:${col}"></span><b>${esc(ns)}</b>
    ${idx>=0?(FLOW.length-idx-1)+' 步待推进':''}</div></div>`;}

function stPicker(id,st){const opts=['未投递','已投递','简历筛选中','已约面试','一轮面试','二轮面试','三轮终面','已发Offer','已入职','不合适','已婉拒','已过期']
  .map(s=>`<option value="${s}" ${s===normSt(st)?'selected':''}>${s}</option>`).join('');
  return `<div class="st-sel">进度：<select onchange="evSt(event,'${id}')">${opts}</select></div>`;}

function jobCard(j){
  const id=j.id,hasA=!!j.analysis,st=normSt(j.status),col=stColor(st);
  const stb=`<span class="badge" style="background:${col}1a;color:${col};border:1px solid ${col}33">${esc(st)}</span>`;
  const anb=hasA?'<span class="badge an">✓已分析</span>':'<span class="badge np">待分析</span>';
  const fitb=(j.fit_score==null)?'':'<span class="badge fit" style="background:'+(j.fit_score>=75?'#16a34a':j.fit_score>=60?'#2563eb':'#dc2626')+'1a;color:'+(j.fit_score>=75?'#16a34a':j.fit_score>=60?'#2563eb':'#dc2626')+';border:1px solid '+(j.fit_score>=75?'#16a34a':j.fit_score>=60?'#2563eb':'#dc2626')+'40;font-weight:600">适配 '+j.fit_score+'</span>';
  // 综合推荐指数 = 适配70%+通勤20%+难度10%；所有岗位显示（颜色分档）
  const recb=(j.rec_score==null)?'':'<span class="badge rec" title="推荐指数=适配70%+通勤20%+求职难度反向10%" style="background:'+(j.rec_score>=85?'#0d9488':j.rec_score>=70?'#2563eb':'#64748b')+'1a;color:'+(j.rec_score>=85?'#0d9488':j.rec_score>=70?'#2563eb':'#64748b')+';border:1px solid '+(j.rec_score>=85?'#0d9488':j.rec_score>=70?'#2563eb':'#64748b')+'40;font-weight:700">🏆 推荐 '+j.rec_score+'</span>';
  // 求职难度（越低越好拿）
  const diffb=(j.difficulty==null)?'':'<span class="badge diff" title="求职难度：数值越大竞争越激烈/越难拿下" style="background:'+(j.difficulty>=70?'#dc2626':j.difficulty>=40?'#d97706':'#16a34a')+'1a;color:'+(j.difficulty>=70?'#dc2626':j.difficulty>=40?'#d97706':'#16a34a')+';border:1px solid '+(j.difficulty>=70?'#dc2626':j.difficulty>=40?'#d97706':'#16a34a')+'40;font-weight:600">难度 '+j.difficulty+'</span>';
  // 猎头/代招标识：公司名含人力资源/劳务/人才/咨询等，或分析文本提到"猎头/代招/推荐"
  const hhText=(j.company||'')+' '+(j.analysis||'');
  const hhRe=/(人力资源|人才服务|劳务派遣|劳务|企业管理咨询|创业服务|咨询有限公司|信息服务|信息技术.*服务|猎头|代招|代招聘|代为招聘|直招|推荐就业|人才中介)/;
  const isHh=hhRe.test(hhText);
  const hhb=isHh?'<span class="badge hh" style="background:#7c3aed1a;color:#7c3aed;border:1px solid #7c3aed40;font-weight:600" title="疑似猎头/代招岗位：页面上方公司可能非实际用人单位，请以正文/面试确认实际公司">🧭 猎头/代招</span>':'';
  // 重点岗位标记
  const keyb=j.is_key?'<span class="badge key" style="background:#fef9c3;color:#a16207;border:1px solid #fde68a;font-weight:700" title="已标记为重点，有深入专项分析">⭐ 重点</span>':'';
  const pfb=(j.platforms||[]).map(p=>{
    const pn=PF_NAME[p]||p, pc=PF_COLOR[p]||'#64748b';
    return `<span class="badge pf" style="background:${pc}1a;color:${pc};border:1px solid ${pc}40;font-weight:600">${esc(pn)}</span>`;
  }).join('');
  const meta=[j.city,j.district,j.experience,j.education].filter(Boolean).join(' · ');
  const sal=j.salary_text||'面议';
  const segs=[];
  // 1 JD(默认展开)
  segs.push(seg('jd-'+id,'📄','原始职位描述（JD）',`<div class="jd">${esc(j.jd||'(无 JD 文本)')}</div>`,true));
  // 2 通勤
  let cmHtml=null;
  if(j.commute&&j.commute.modes){cmHtml=cmBlock(j.commute,id);}
  else if(j.address){cmHtml=cmCfg(id,j.address)+'<div class="cm-note">⚠ 已记录地址，但未算出通勤。可能原因：① 地址不够精准（如只有大楼/路口）；② 通勤起点未设置；③ 高德 key 受限。请检查上方设置或按"地址原则"核对地址。</div>';}
  else {cmHtml=cmCfg(id,'')+'<div class="cm-note">⚠ 待确认地址：本平台未提供公司地址，需按"公司名搜索"确认后填入才能算通勤（务必别瞎编，确认不了就留空）。</div>';}
  segs.push(seg('cm-'+id,'🚗','通勤（多方式）',cmHtml,false));
  // 4 分析块，按给定顺序重排：实际内容→公司行业→适配→面试
  const order=[];const ps=parts(j.analysis);
  // 排除纯数据提取段落（适配指数/适配微调/求职难度），值已用徽章显示；理由已并入岗位适配情况。
  const psShow=ps.filter(x=>!/适配指数|适配微调|求职难度/.test(x.t));
  const prio=['实际内容','干嘛','干什么','公司','经营','行业','适配','优缺点','对你','面试','总结','判断'];
  for(const p of prio)for(const x of psShow)if(x.t.includes(p)&&!order.includes(x))order.push(x);
  for(const x of psShow)if(!order.includes(x))order.push(x);
  if(psShow.length){order.forEach((x,i)=>{const dn=titleName(x.t);
    let body;
    if(/难度/.test(x.t)){
      // 求职难度：body 里"40 | 理由..." → 只显示理由，分数已用徽章展示
      const m=x.b&&x.b.split(/[|｜]/);
      const reason=m&&m.length>1?m.slice(1).join('|').trim():(x.b||'').replace(/^\s*\d{1,3}\s*[（(]理由[：:][\s\S]*/,function(s){return s.replace(/^\s*\d{1,3}/,'');});
      body=`<div class="analysis">${toHtml(reason||x.b)}</div>`;
    } else {
      body=`<div class="analysis">${toHtml(x.b)}</div>`;
      if(/公司|经营|行业/.test(x.t))body+=refLinks('company',j.company,j.title);
      else if(/面试/.test(x.t))body+=refLinks('interview',j.company,j.title);
    }
    segs.push(seg('a'+id+'-'+i,iconOf(dn),dn,body,false));});}
  else{segs.push(`<div class="seg"><div class="seg-h"><span><span class="ic" style="background:#475569">📌</span>贰贰深度分析</span></div>
    <div class="seg-bd" style="display:block"><div class="analysis" style="color:var(--warn)">待贰贰补精读</div></div></div>`);}
  if(j.notes)segs.push(seg('n-'+id,'📝','我的备注',`<div class="notes">${esc(j.notes)}</div>`,false));
  const link=j.url?`<div class="seg"><div class="seg-h" style="cursor:default"><span>🔗 链接</span></div>
    <div class="seg-bd" style="display:block"><a href="${esc(j.url)}" target="_blank" rel="noopener">打开原始岗位 →</a></div></div>`:'';
  return `<div class="job" data-id="${id}" data-an="${hasA?'yes':'no'}" data-st="${esc(st)}"
    data-sal="${j.salary_max||0}" data-cm="${(j.commute&&j.commute.modes&&j.commute.modes.driving)?j.commute.modes.driving.minutes:9999}"
    data-ts="${esc(j.created_at||'')}">
    <div class="job-hd" onclick="togJob('${id}')">
      <label class="cb-col" style="display:${_batchMode?'flex':'none'}" onclick="event.stopPropagation()">
        <input type="checkbox" class="cb" ${_sel.has(id)?'checked':''} onchange="toggleSel('${id}',this.checked)">
      </label>
      <div style="flex:1;min-width:0"><h2>${j.url?('<a class="title-link" href="'+esc(j.url)+'" target="_blank" rel="noopener" title="点击打开原始岗位" onclick="event.stopPropagation()">'+esc(j.title||'')+'</a>'):esc(j.title||'')}</h2>
        <div class="co">${esc(j.company||'未知公司')}</div><div class="meta">${esc(meta)}</div>
        ${progBar(st)}${stPicker(id,st)}<div id="t${id}" class="mut" style="margin-top:2px"></div>
        <div class="badges">${stb}${recb}${fitb}${diffb}${keyb}${hhb}${anb}${pfb}</div></div>
      <div style="text-align:right"><div class="salary">${esc(sal)}</div><div class="chev" id="chv-${id}">▼</div>
        <div class="job-ops" onclick="event.stopPropagation()">
          ${j.is_key?'<button class="op-btn op-deep" title="打开深入专项分析" onclick="openDeep(\''+id+'\')">📊 深入分析</button>':''}
          <button class="op-btn ${j.is_key?'':'op-key'}" title="${j.is_key?'取消重点':'标记为重点并生成深入分析'}" onclick="setKey('${id}',${j.is_key?0:1})">${j.is_key?'★ 取消重点':'☆ 设为重点'}</button>
          <button class="op-btn" title="编辑岗位" onclick="openEdit('${id}')">✏️ 编辑</button>
          <button class="op-btn op-del" title="删除岗位" onclick="delJob('${id}')">🗑️ 删除</button>
        </div></div>
    </div>
    <div class="job-bd" id="bd-${id}">${segs.join('')}${link}</div></div>`;
}

function refreshJob(id,node){node.outerHTML=jobCard(DATA.find(x=>x.id===id));}

/* ===== 编辑/删除岗位 ===== */
let _editingId=null;
function openEdit(id){
  const j=DATA.find(x=>x.id===id); if(!j)return;
  _editingId=id;
  const stMap={'未投递':'未投递','已投递':'已投递','简历筛选中':'简历筛选中','已约面试':'已约面试','一轮面试':'一轮面试','二轮面试':'二轮面试','三轮终面':'三轮终面','已发Offer':'已发Offer','已入职':'已入职','不合适':'不合适','已婉拒':'已婉拒','已过期':'已过期'};
  const opts=['未投递','已投递','简历筛选中','已约面试','一轮面试','二轮面试','三轮终面','已发Offer','已入职','不合适','已婉拒','已过期']
    .map(s=>`<option value="${s}" ${s===normSt(j.status)?'selected':''}>${s}</option>`).join('');
  el('edit-box').innerHTML=`<h3>✏️ 编辑岗位</h3>
    <div class="edit-grid">
      <div><label>岗位名称</label><input id="ef-title" value="${esc(j.title||'')}"></div>
      <div><label>公司名称</label><input id="ef-company" value="${esc(j.company||'')}"></div>
      <div><label>薪资（如 8-12K·13薪）</label><input id="ef-salary" value="${esc(j.salary_text||'')}"></div>
      <div><label>城市</label><input id="ef-city" value="${esc(j.city||'')}"></div>
      <div><label>区域</label><input id="ef-district" value="${esc(j.district||'')}"></div>
      <div><label>状态</label><select id="ef-status">${opts}</select></div>
      <div><label>经验要求</label><input id="ef-exp" value="${esc(j.experience||'')}"></div>
      <div><label>学历要求</label><input id="ef-edu" value="${esc(j.education||'')}"></div>
      <div class="full"><label>工作地址</label><input id="ef-addr" value="${esc(j.address||'')}" placeholder="用于通勤计算，尽量精确"></div>
      <div class="full"><label>我的备注</label><textarea id="ef-notes">${esc(j.notes||'')}</textarea></div>
      <div class="full"><label>JD 描述</label><textarea id="ef-jd">${esc(j.jd||'')}</textarea></div>
    </div>
    <div class="edit-actions"><button class="ea-cancel" onclick="closeEdit()">取消</button>
      <button class="ea-save" onclick="saveEdit()">保存</button></div>`;
  el('edit-mask').classList.add('on');
}
function closeEdit(){el('edit-mask').classList.remove('on');_editingId=null;}
function saveEdit(){
  if(!_editingId)return;
  const body={
    title: el('ef-title').value.trim(),
    company: el('ef-company').value.trim(),
    salary_raw: el('ef-salary').value.trim(),
    city: el('ef-city').value.trim(),
    district: el('ef-district').value.trim(),
    status: el('ef-status').value,
    experience: el('ef-exp').value.trim(),
    education: el('ef-edu').value.trim(),
    address: el('ef-addr').value.trim(),
    notes: el('ef-notes').value.trim(),
    jd: el('ef-jd').value.trim()
  };
  const btn=document.querySelector('.ea-save');btn.textContent='保存中…';
  fetch(API+'/api/job/'+_editingId,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})
    .then(r=>r.json()).then(d=>{if(d.ok){btn.textContent='✓ 已保存';setTimeout(()=>location.reload(),500);}else{btn.textContent='失败:'+d.error;}})
    .catch(()=>{btn.textContent='连不上本地服务，请先启动 serve';});
}
function setKey(id,isKey){
  const j=DATA.find(x=>x.id===id); if(!j)return;
  const act=isKey?'标记为重点':'取消重点';
  if(isKey&&!confirm('将「'+(j.title||'')+'」标记为重点？\n将自动生成深入专项分析（一对一拆解/公司尽调/面试策略）。'))return;
  fetch(API+'/api/job/'+id+'/'+(isKey?'key':'unkey'),{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'})
    .then(r=>r.json()).then(d=>{if(d.ok){toast(id,isKey?'✓ 已设为重点，深入分析生成中…':'✓ 已取消重点');setTimeout(()=>location.reload(),isKey?1200:500);}else{alert(act+'失败:'+d.error);}})
    .catch(()=>{alert('连不上本地服务，请先启动 serve');});
}

function openDeep(id){
  const j=DATA.find(x=>x.id===id); if(!j)return;
  const deep=j.deep_analysis&&parts(j.deep_analysis).length
    ?parts(j.deep_analysis).map(x=>'<div class="drawer-panel"><div class="dp-h">'+iconOf(x.t)+' '+esc(x.t)+'</div><div class="dp-b analysis">'+toHtml(x.b)+'</div></div>').join('')
    :'<div class="analysis" style="color:var(--warn);padding:12px">深入分析生成中…稍后刷新查看。</div>';
  const cm=j.commute&&j.commute.modes?(j.commute.modes.driving?('驾车约'+j.commute.modes.driving.minutes+'分钟 · '+j.commute.modes.driving.distance+'km'):''):'未计算';
  const stb='<span class="badge" style="background:#eef0f4;color:#374151">'+esc(normSt(j.status))+'</span>';
  const fitb=(j.fit_score==null)?'':'<span class="badge" style="color:#16a34a">适配 '+j.fit_score+'</span>';
  const recb=(j.rec_score==null)?'':'<span class="badge" style="color:#0d9488;font-weight:700">推荐 '+j.rec_score+'</span>';
  const diffb=(j.difficulty==null)?'':'<span class="badge" style="color:#d97706">难度 '+j.difficulty+'</span>';
  el('drawer-bd').innerHTML=
    '<div class="drawer-job"><h3>'+esc(j.title||'')+'</h3><div class="co">'+esc(j.company||'未知公司')+'</div>'+
    '<div class="meta">'+esc(([j.city,j.district,j.experience,j.education].filter(Boolean).join(' · ')))+' · 通勤 '+esc(cm)+'</div>'+
    '<div class="badges">'+stb+recb+fitb+diffb+'</div></div>'+
    '<h4 style="margin:4px 0 8px;color:#7c3aed;font-size:14px">⭐ 深入专项分析</h4>'+deep;
  el('drawer-mask').classList.add('on');el('drawer').classList.add('on');
  document.body.style.overflow='hidden';
}
function closeDeep(){el('drawer-mask').classList.remove('on');el('drawer').classList.remove('on');document.body.style.overflow='';}
function delJob(id){
  const j=DATA.find(x=>x.id===id);
  if(!confirm('确定删除岗位「'+(j?j.title:'')+'」？\n（公司：'+(j?j.company:'')+'）\n此操作不可撤销。'))return;
  fetch(API+'/api/job/'+id+'/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'})
    .then(r=>r.json()).then(d=>{if(d.ok){location.reload();}else{alert('删除失败:'+d.error);}})
    .catch(()=>{alert('连不上本地服务，请先启动 serve（双击启动看板.bat）');});
}

/* ===== 简历导入 ===== */
function loadResumeStatus(){
  fetch(API+'/api/resume').then(r=>r.json()).then(d=>{
    const s=el('resume-st');
    if(d&&d.has){s.innerHTML='<span class="resume-ok">✓ 已导入</span>（'+d.chars+'字）<span class="mut" style="color:var(--tx3);font-size:11px">「'+esc(d.head)+'…」</span>';el('resume-del').style.display='inline-block';}
    else {s.innerHTML='<span class="resume-none">未导入</span> — 导入后贰贰分析「岗位适配情况」将结合你的简历';el('resume-del').style.display='none';}
  }).catch(()=>{el('resume-st').textContent='连不上本地服务（先启动 serve）';});
}
function openResume(){
  fetch(API+'/api/resume').then(r=>r.json()).then(d=>{
    const cur=d&&d.has?d.head+'…（已存 '+d.chars+' 字）':'尚未导入';
    el('resume-box').innerHTML=`<h3>📄 导入简历</h3>
      <div class="resume-up">
        <div class="ru-title">① 上传文件（支持 PDF / Word / 文本）</div>
        <input type="file" id="rf-file" accept=".pdf,.doc,.docx,.txt" style="font-size:13px">
        <button class="ru-btn" onclick="uploadResumeFile()">上传并解析</button>
        <div id="rf-feedback" style="font-size:12px;color:var(--tx3);margin-top:6px"></div>
      </div>
      <div class="cm-note" style="margin:12px 0 10px">② 或手动粘贴文本：保存后贰贰写「岗位适配情况」会结合简历做匹配分析。</div>
      <div class="edit-grid"><div class="full"><label>当前状态</label><input readonly value="${esc(cur)}" style="background:#f5f5f7"></div>
      <div class="full"><label>简历内容（可覆盖更新）</label><textarea id="rf-content" style="min-height:200px" placeholder="教育背景&#10;…&#10;&#10;工作经历&#10;…&#10;&#10;技能与项目&#10;…"></textarea></div></div>
      <div class="edit-actions"><button class="ea-cancel" onclick="closeResume()">取消</button>
      <button class="ea-save" onclick="saveResume()">保存文本简历</button>
      <button class="ea-del" onclick="deleteResume()">删除简历</button></div>`;
    el('resume-mask').classList.add('on');
  }).catch(()=>{alert('连不上本地服务');});
}
function uploadResumeFile(){
  const fi=el('rf-file');
  if(!fi.files||!fi.files[0]){el('rf-feedback').textContent='请先选择文件';return;}
  const f=fi.files[0];
  const ext=(f.name.split('.').pop()||'').toLowerCase();
  if(!['pdf','doc','docx','txt'].includes(ext)){el('rf-feedback').textContent='仅支持 pdf/doc/docx/txt';return;}
  const fb=el('rf-feedback');fb.textContent='上传解析中…';
  fetch(API+'/api/resume_file',{method:'POST',
    headers:{'Content-Type':'application/octet-stream','X-Resume-Ext':ext},body:f})
    .then(r=>r.json()).then(d=>{
      if(d.ok){fb.textContent='✓ 解析成功，已提取 '+d.chars+' 字。';setTimeout(()=>{closeResume();loadResumeStatus();},600);}
      else{fb.textContent='✗ '+d.error;}
    })
    .catch(()=>{fb.textContent='✗ 连不上本地服务（先启动 serve）';});
}
function closeResume(){el('resume-mask').classList.remove('on');}
function deleteResume(){
  if(!confirm('确定删除简历？删除后，岗位分析将不再结合你的简历。'))return;
  fetch(API+'/api/resume/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'})
    .then(r=>r.json()).then(d=>{if(d.ok){closeResume();loadResumeStatus();}else{alert('删除失败:'+(d.error||''));}})
    .catch(()=>alert('连不上本地服务'));
}
function saveResume(){
  const content=el('rf-content').value;
  const btn=document.querySelector('#resume-box .ea-save');btn.textContent='保存中…';
  fetch(API+'/api/resume',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({content})})
    .then(r=>r.json()).then(d=>{if(d.ok){btn.textContent='✓ 已保存';setTimeout(()=>{closeResume();loadResumeStatus();},400);}else{btn.textContent='失败:'+d.error;}})
    .catch(()=>{btn.textContent='连不上本地服务';});
}

function statBtnStat(){return {an:el('f-an').value,pf:el('f-pf').value,st:el('f-st').value,cm:el('f-cm').value,fit:el('f-fit').value};}
let _statActive=null; // 当前激活的统计筛选，null=无
function stats(){const t=DATA.length,a=DATA.filter(j=>j.analysis).length,c=DATA.filter(j=>j.commute).length;
  const dp=DATA.filter(j=>normSt(j.status)!=='未投递').length;
  const items=[['岗位','全部岗位',t,'all'],['已分析','仅看已分析',a,'analyzed'],['算通勤','仅看算出通勤',c,'commuted'],['已推进','已投递及之后',dp,'progressed']];
  el('stats').innerHTML=items.map(([l,title,v,k])=>
    `<button class="stat${_statActive===k?' on':''}" data-k="${k}" title="${title}" onclick="toggleStat('${k}')"><div class="v">${v}</div><div class="l">${l}</div></button>`).join('');}
function toggleStat(k){
  if(_statActive===k){_statActive=null;_cmOnlyComputed=false;
    el('f-an').value='';el('f-st').value='';el('f-cm').value='';el('f-pf').value='';el('f-fit').value='';
  }else{
    _statActive=k;_cmOnlyComputed=false;
    if(k==='analyzed')el('f-an').value='yes';
    else if(k==='commuted'){el('f-cm').value='';_cmOnlyComputed=true;}
    else if(k==='progressed'){el('f-st').value='';}
    else if(k==='all'){el('q').value='';el('f-pf').value='';el('f-an').value='';el('f-st').value='';el('f-cm').value='';el('f-fit').value='';}
  }
  _saveState();render();
}
let _cmOnlyComputed=false;
function filtered(){const q=el('q').value.trim().toLowerCase(),an=el('f-an').value,st=el('f-st').value,cm=el('f-cm').value,pf=el('f-pf').value,ft=el('f-fit').value;
  let l=DATA.filter(j=>{if(q){const hay=[j.company,j.title,j.address,j.jd,j.analysis].join(' ').toLowerCase();if(!hay.includes(q))return false}
    if(an==='yes'&&!j.analysis)return false;if(an==='no'&&j.analysis)return false;
    if(st&&normSt(j.status)!==st)return false;
    if(pf&&!(j.platforms||[]).includes(pf))return false;
    if(cm){const m=(j.commute&&j.commute.modes&&j.commute.modes.driving)?j.commute.modes.driving.minutes:9999;
      if(cm==='fast'&&!(m<60))return false;if(cm==='slow'&&m<60)return false;}
    if(ft){const f=j.fit_score;
      if(ft==='none'){if(f!=null)return false;}
      else if(f==null)return false;
      else if(ft==='high'&&!(f>=75))return false;
      else if(ft==='mid'&&!(f>=60&&f<75))return false;
      else if(ft==='low'&&!(f<60))return false;}
    // 统计卡筛选：已算通勤
    if(_cmOnlyComputed&&(!(j.commute&&j.commute.modes)))return false;
    // 统计卡筛选：已推进（已投递及之后的状态，且非终止态）
    if(_statActive==='progressed'&&(normSt(j.status)==='未投递'))return false;
    return true;});
  const sort=el('sort').value;
  if(sort==='sal')l.sort((a,b)=>(b.salary_max||0)-(a.salary_max||0));
  else if(sort==='cm')l.sort((a,b)=>(a.commute&&a.commute.modes&&a.commute.modes.driving?a.commute.modes.driving.minutes:9999)-(b.commute&&b.commute.modes&&b.commute.modes.driving?b.commute.modes.driving.minutes:9999));
  else if(sort==='new')l.sort((a,b)=>String(b.created_at||'').localeCompare(String(a.created_at||'')));
  else if(sort==='fit')l.sort((a,b)=>((b.fit_score==null?-1:b.fit_score))-((a.fit_score==null?-1:a.fit_score)));
  else if(sort==='rec')l.sort((a,b)=>((b.rec_score==null?-1:b.rec_score))-((a.rec_score==null?-1:a.rec_score)));
  else{const rk=s=>{const ns=normSt(s),i=FLOW.indexOf(ns);return TERM[ns]?99:(i<0?50:i)};l.sort((a,b)=>rk(a.status)-rk(b.status));}
  return l;}
function render(){const l=filtered();stats();el('cnt').textContent=`显示 ${l.length}/${DATA.length}`;
  el('none').style.display=l.length?'none':'block';el('list').innerHTML=l.map(jobCard).join('');}

/* 初始化 */
const FS_KEY='jobhub_filter_state';
function _saveState(){try{const s={q:el('q').value,pf:el('f-pf').value,an:el('f-an').value,st:el('f-st').value,cm:el('f-cm').value,fit:el('f-fit').value,sort:el('sort').value};localStorage.setItem(FS_KEY,JSON.stringify(s));}catch(e){}}
function _loadState(){try{const s=JSON.parse(localStorage.getItem(FS_KEY)||'{}');if(s.q!==undefined)el('q').value=s.q;if(s.pf)el('f-pf').value=s.pf;if(s.an)el('f-an').value=s.an;if(s.st)el('f-st').value=s.st;if(s.cm)el('f-cm').value=s.cm;if(s.fit)el('f-fit').value=s.fit;if(s.sort)el('sort').value=s.sort;}catch(e){}}
(function(){const seen=[];DATA.forEach(j=>{const s=normSt(j.status);if(!seen.includes(s))seen.push(s)});
  el('f-st').innerHTML='<option value="">全部进度</option>'+seen.map(s=>`<option value="${esc(s)}">${esc(s)}</option>`).join('');
  _loadState();
  el('q').addEventListener('input',()=>{_saveState();render();});el('f-pf').addEventListener('change',()=>{_saveState();render();});el('f-an').addEventListener('change',()=>{_saveState();render();});
  el('f-st').addEventListener('change',()=>{_saveState();render();});el('f-cm').addEventListener('change',()=>{_saveState();render();});el('f-fit').addEventListener('change',()=>{_saveState();render();});
  el('sort').addEventListener('change',()=>{_saveState();render();});
  el('reset').onclick=()=>{el('q').value='';el('f-pf').value='';el('f-an').value='';el('f-st').value='';el('f-cm').value='';el('f-fit').value='';el('sort').value='';_saveState();render();};
  render();loadResumeStatus();})();
function doLogout(){
  if(!confirm('确定退出登录？\n退出后岗位数据不会清除，刷新页面可重新登录。'))return;
  fetch(API+'/api/logout',{method:'POST',credentials:'include'}).then(()=>{window.location.reload();}).catch(()=>{window.location.reload();});
}
</script>
<div class="help-mask" id="help-mask" onclick="if(event.target===this)this.className='help-mask'">
<div class="help-box">
  <button class="close" onclick="document.getElementById('help-mask').className='help-mask'">&times;</button>
  <h2>薪途 PathToJob 使用指南</h2>

  <div style="background:#f0f7ff;border:1px solid #c7d2fe;border-radius:10px;padding:14px 16px;margin-bottom:18px;line-height:1.8">
    <div style="font-weight:700;font-size:14px;color:#1e1b4b;margin-bottom:6px">薪途是什么？</div>
    <div style="font-size:13px;color:#374151">
      找工作时，你需要在 Boss直聘、51job、猎聘等多个网站之间来回切换，很容易遗漏好机会。<br><br>
      <b>薪途帮你把这些岗位集中到一个页面管理</b>：在电脑上看到合适的岗位，点一下就能保存到这里。AI 还会帮你分析每个岗位是否适合你、面试该怎么准备。<br><br>
      <b>简单来说</b>：你在招聘网站上看岗位 → 点一下保存 → AI 帮你分析 → 你在这里管理投递进度。
    </div>
  </div>

  <div style="background:#f5f5f5;border:1px solid #e5e7eb;border-radius:8px;padding:10px 14px;margin-bottom:16px;font-size:12.5px;color:#374151;line-height:1.7">
    <b>📌 支持的网站</b>：Boss直聘、前程无忧（51job）、猎聘、智联招聘、鱼泡直聘，共 <b>5 个</b>。
  </div>

  <h3>⚠️ 重要提示</h3>
  <ul>
    <li><b>抓岗位只能用电脑</b>：需要在电脑的 Edge 或 Chrome 浏览器上安装一个小插件</li>
    <li><b>手机可以查看和管理</b>：用手机打开这个看板页面，能看岗位、改状态、加备注，但不能抓新岗位</li>
  </ul>

  <h3>🚀 3 步开始使用</h3>
  <div class="step"><div class="step-n">1</div><div class="step-t"><b>安装小插件（让浏览器能保存岗位）</b><br>
    <a href="/api/extension/download" class="dl-btn" onclick="event.stopPropagation()">⬇ 下载插件</a>
    &nbsp;下载后<b>解压</b>，得到一个 <code>bossdive</code> 文件夹。然后按下面的图示操作：</div></div>

  <!-- 步骤1-1：打开扩展管理页 -->
  <div class="guide-box">
    <div class="guide-label">① 打开扩展管理页</div>
    <div class="guide-row">
      <div class="guide-card">
        <div class="guide-browser">
          <div class="browser-bar">
            <div class="win-btns"><span class="win-btn wb-r">✕</span><span class="win-btn wb-m">☐</span><span class="win-btn wb-m">—</span></div>
            <span class="addr">edge://extensions</span>
          </div>
          <div class="browser-body">
            <svg width="200" height="100" viewBox="0 0 200 100"><rect width="200" height="100" rx="4" fill="#f8f9fa"/>
            <rect x="8" y="8" width="184" height="22" rx="3" fill="#e9ecef"/><text x="16" y="23" font-size="9" fill="#495057" font-family="Segoe UI,sans-serif">edge://extensions</text>
            <rect x="8" y="38" width="88" height="22" rx="3" fill="#0d6efd"/><text x="16" y="53" font-size="9" fill="#fff" font-family="Segoe UI,sans-serif">加载已解压的</text>
            <text x="8" y="78" font-size="8" fill="#dc3545" font-family="Segoe UI,sans-serif">👆 点这个蓝色按钮</text></svg>
          </div>
        </div>
        <div class="guide-caption">Edge 地址栏输入 <code>edge://extensions</code> 回车<br>（Chrome 输入 <code>chrome://extensions</code>）</div>
      </div>
    </div>
  </div>

  <!-- 步骤1-2：开启开发者模式 -->
  <div class="guide-box">
    <div class="guide-label">② 打开「开发者模式」开关</div>
    <div class="guide-row">
      <div class="guide-card">
        <div class="guide-browser">
          <div class="browser-bar">
            <div class="win-btns"><span class="win-btn wb-r">✕</span><span class="win-btn wb-m">☐</span><span class="win-btn wb-m">—</span></div>
            <span class="addr">扩展管理</span>
          </div>
          <div class="browser-body">
            <svg width="200" height="80" viewBox="0 0 200 80"><rect width="200" height="80" rx="4" fill="#f8f9fa"/>
            <rect x="8" y="8" width="184" height="64" rx="3" fill="#fff" stroke="#ccc"/>
            <text x="16" y="28" font-size="9" fill="#333" font-family="Segoe UI,sans-serif">扩展管理</text>
            <rect x="16" y="52" width="80" height="14" rx="7" fill="#198754"/>
            <circle cx="80" cy="59" r="5" fill="#fff"/>
            <text x="102" y="62" font-size="8" fill="#333" font-family="Segoe UI,sans-serif">开发者模式</text>
            <text x="16" y="42" font-size="8" fill="#dc3545" font-family="Segoe UI,sans-serif">👆 左下角这个开关要打开</text></svg>
          </div>
        </div>
        <div class="guide-caption">左下角找到「开发者模式」，确保开关是<b>绿色开启</b>状态</div>
      </div>
    </div>
  </div>

  <!-- 步骤1-3：加载文件夹 -->
  <div class="guide-box">
    <div class="guide-label">③ 点「加载已解压的扩展」→ 选择 bossdive 文件夹</div>
    <div class="guide-row">
      <div class="guide-card">
        <div class="guide-browser">
          <div class="browser-bar">
            <div class="win-btns"><span class="win-btn wb-r">✕</span><span class="win-btn wb-m">☐</span><span class="win-btn wb-m">—</span></div>
            <span class="addr">选择文件夹</span>
          </div>
          <div class="browser-body">
            <svg width="200" height="90" viewBox="0 0 200 90"><rect width="200" height="90" rx="4" fill="#f8f9fa"/>
            <rect x="8" y="8" width="184" height="74" rx="4" fill="#fff" stroke="#ccc"/>
            <text x="16" y="28" font-size="9" fill="#333" font-family="Segoe UI,sans-serif">📁 选择文件夹</text>
            <rect x="16" y="36" width="168" height="22" rx="3" fill="#e7f1ff" stroke="#0d6efd" stroke-dasharray="3"/>
            <text x="24" y="51" font-size="9" fill="#0d6efd" font-family="Segoe UI,sans-serif">📁 bossdive</text>
            <text x="8" y="82" font-size="8" fill="#dc3545" font-family="Segoe UI,sans-serif">👆 选中解压后的 bossdive 文件夹</text></svg>
          </div>
        </div>
        <div class="guide-caption">在弹出的窗口中，找到并选中解压后的 <code>bossdive</code> 文件夹</div>
      </div>
    </div>
  </div>

  <!-- 步骤1-4：效果预览 -->
  <div class="guide-box">
    <div class="guide-label">✅ 安装成功后效果</div>
    <div class="guide-row">
      <div class="guide-card">
        <div class="guide-browser">
          <div class="browser-bar">
            <div class="win-btns"><span class="win-btn wb-r">✕</span><span class="win-btn wb-m">☐</span><span class="win-btn wb-m">—</span></div>
            <span class="addr">www.zhipin.com/web/job/...</span>
          </div>
          <div class="browser-body" style="position:relative">
            <svg width="200" height="100" viewBox="0 0 200 100"><rect width="200" height="100" rx="4" fill="#f8f9fa"/>
            <rect x="8" y="8" width="120" height="12" rx="2" fill="#dee2e6"/><text x="14" y="17" font-size="7" fill="#6c757d" font-family="Segoe UI,sans-serif">岗位详情页内容...</text>
            <rect x="8" y="26" width="100" height="8" rx="2" fill="#e9ecef"/>
            <rect x="8" y="40" width="140" height="8" rx="2" fill="#e9ecef"/>
            <rect x="8" y="54" width="110" height="8" rx="2" fill="#e9ecef"/>
            </svg>
            <div style="position:absolute;right:14px;bottom:14px;background:#2563eb;color:#fff;padding:6px 14px;border-radius:20px;font-size:9px;font-weight:700;box-shadow:0 2px 8px rgba(0,0,0,.2);font-family:Segoe UI,sans-serif">+ 抓取岗位</div>
          </div>
        </div>
        <div class="guide-caption">打开招聘网站的岗位详情页，右下角会出现<b>蓝色「+ 抓取岗位」</b>悬浮按钮</div>
      </div>
    </div>
  </div>

  <div class="step"><div class="step-n">2</div><div class="step-t"><b>登录账号（只需操作一次）</b><br>点击浏览器右上角的拼图图标 🧩 → 点「Boss 岗位快抓」→ 输入你的用户名和密码 → 点登录。</div></div>
  <div class="step"><div class="step-n">3</div><div class="step-t"><b>开始保存岗位</b><br>打开以下任意一个招聘网站，找到你感兴趣的岗位：<br><br>
    <b>51job、猎聘、鱼泡</b>：点击岗位看到信息后就可以抓取<br>
    <b>Boss直聘、智联招聘</b>：必须点进<b>岗位详情页</b>才能抓到完整信息（往下拉看到「查看更多信息」）</div></div>

  <!-- Boss直聘图示 -->
  <div class="guide-box">
    <div class="guide-label">Boss直聘：点进岗位详情页</div>
    <div class="guide-row">
      <div class="guide-card">
        <div class="guide-browser">
          <div class="browser-bar">
            <div class="win-btns"><span class="win-btn wb-r">✕</span><span class="win-btn wb-m">☐</span><span class="win-btn wb-m">—</span></div>
            <span class="addr">www.zhipin.com/job_detail/...</span>
          </div>
          <div class="browser-body" style="padding:0">
            <svg width="320" height="140" viewBox="0 0 320 140" style="display:block">
              <rect width="320" height="140" fill="#fff"/>
              <!-- 左侧列表 -->
              <rect x="0" y="0" width="110" height="140" fill="#f8f9fa" stroke="#e5e7eb" stroke-width="0.5"/>
              <rect x="6" y="8" width="98" height="32" rx="4" fill="#fff" stroke="#00b8a9" stroke-width="1.5"/>
              <text x="12" y="22" font-size="7" fill="#00b8a9" font-weight="700" font-family="Microsoft YaHei,sans-serif">商家运营助理</text>
              <text x="12" y="32" font-size="7" fill="#f60" font-weight="700" font-family="Microsoft YaHei,sans-serif">5-6K</text>
              <text x="12" y="48" font-size="6" fill="#999" font-family="Microsoft YaHei,sans-serif">武汉佰钧成技术</text>
              <rect x="6" y="52" width="98" height="28" rx="4" fill="#fff" stroke="#e5e7eb" stroke-width="0.5"/>
              <text x="12" y="66" font-size="7" fill="#333" font-family="Microsoft YaHei,sans-serif">淘系运营专员</text>
              <text x="12" y="76" font-size="6" fill="#999" font-family="Microsoft YaHei,sans-serif">研和科技</text>
              <!-- 右侧详情 -->
              <rect x="110" y="0" width="210" height="140" fill="#fff"/>
              <text x="120" y="22" font-size="9" fill="#333" font-weight="700" font-family="Microsoft YaHei,sans-serif">商家运营助理 5-6K</text>
              <text x="120" y="36" font-size="7" fill="#999" font-family="Microsoft YaHei,sans-serif">杭州 · 1-3年 · 本科</text>
              <rect x="120" y="44" width="190" height="50" rx="3" fill="#fafafa" stroke="#eee" stroke-width="0.5"/>
              <text x="128" y="56" font-size="6" fill="#666" font-family="Microsoft YaHei,sans-serif">2、多国市场横向协作：对接欧洲、英联邦等区域</text>
              <text x="128" y="66" font-size="6" fill="#666" font-family="Microsoft YaHei,sans-serif">3、人群圈选与投放支持：协助完成push、edm等</text>
              <text x="128" y="76" font-size="6" fill="#666" font-family="Microsoft YaHei,sans-serif">数据与效果跟踪：配合团队进行活动效果统计</text>
              <text x="128" y="86" font-size="6" fill="#666" font-family="Microsoft YaHei,sans-serif">任职要求：1、本科及以上学历...</text>
              <!-- 工作地址 -->
              <text x="120" y="104" font-size="7" fill="#333" font-weight="700" font-family="Microsoft YaHei,sans-serif">工作地址</text>
              <text x="120" y="116" font-size="6" fill="#999" font-family="Microsoft YaHei,sans-serif">杭州余杭区菜鸟智谷产业园内</text>
              <!-- 查看更多信息 -->
              <rect x="170" y="124" width="80" height="12" rx="6" fill="#fff" stroke="#00b8a9" stroke-width="1"/>
              <text x="183" y="133" font-size="6" fill="#00b8a9" font-family="Microsoft YaHei,sans-serif">查看更多信息</text>
            </svg>
          </div>
        </div>
        <div class="guide-caption">
          <b>Boss直聘</b>：左侧点岗位 → 右侧出现详情 → 往下拉到底部看到<b>「查看更多信息」</b>→ 点蓝色「+ 抓取岗位」
        </div>
      </div>
    </div>
  </div>

  <!-- 智联招聘图示 -->
  <div class="guide-box">
    <div class="guide-label">智联招聘：点进岗位详情页</div>
    <div class="guide-row">
      <div class="guide-card">
        <div class="guide-browser">
          <div class="browser-bar">
            <div class="win-btns"><span class="win-btn wb-r">✕</span><span class="win-btn wb-m">☐</span><span class="win-btn wb-m">—</span></div>
            <span class="addr">www.zhaopin.com/job/...</span>
          </div>
          <div class="browser-body" style="padding:0">
            <svg width="320" height="140" viewBox="0 0 320 140" style="display:block">
              <rect width="320" height="140" fill="#fff"/>
              <!-- 顶部导航 -->
              <rect x="0" y="0" width="320" height="16" fill="#3e7cf1"/>
              <text x="8" y="11" font-size="6" fill="#fff" font-weight="700" font-family="Microsoft YaHei,sans-serif">智联招聘</text>
              <text x="50" y="11" font-size="5" fill="rgba(255,255,255,.8)" font-family="Microsoft YaHei,sans-serif">首页 职位 杭州站</text>
              <!-- 左侧列表 -->
              <rect x="0" y="16" width="120" height="124" fill="#f5f7fa" stroke="#e5e7eb" stroke-width="0.5"/>
              <rect x="6" y="24" width="108" height="32" rx="4" fill="#fff" stroke="#3e7cf1" stroke-width="1.5"/>
              <text x="12" y="36" font-size="7" fill="#333" font-weight="700" font-family="Microsoft YaHei,sans-serif">国内电商运营</text>
              <text x="12" y="46" font-size="6" fill="#3e7cf1" font-weight="700" font-family="Microsoft YaHei,sans-serif">8000-16000元·15薪</text>
              <text x="12" y="62" font-size="6" fill="#999" font-family="Microsoft YaHei,sans-serif">松下集团 · 杭州钱塘</text>
              <rect x="6" y="64" width="108" height="26" rx="4" fill="#fff" stroke="#e5e7eb" stroke-width="0.5"/>
              <text x="12" y="78" font-size="7" fill="#333" font-family="Microsoft YaHei,sans-serif">天猫运营（双休+六险一金）</text>
              <text x="12" y="88" font-size="6" fill="#999" font-family="Microsoft YaHei,sans-serif">河南食族人食品</text>
              <!-- 右侧详情 -->
              <rect x="120" y="16" width="200" height="124" fill="#fff"/>
              <text x="130" y="36" font-size="9" fill="#333" font-weight="700" font-family="Microsoft YaHei,sans-serif">国内电商运营</text>
              <text x="130" y="36" font-size="9" fill="#3e7cf1" font-weight="700" font-family="Microsoft YaHei,sans-serif"> </text>
              <text x="230" y="36" font-size="7" fill="#3e7cf1" font-family="Microsoft YaHei,sans-serif">8000-16000元·15薪</text>
              <text x="130" y="48" font-size="6" fill="#999" font-family="Microsoft YaHei,sans-serif">杭州钱塘区 · 1-3年 · 本科 · 招1人</text>
              <!-- 职位发布者 -->
              <rect x="130" y="54" width="180" height="24" rx="3" fill="#fafafa" stroke="#eee" stroke-width="0.5"/>
              <circle cx="142" cy="66" r="8" fill="#e0e7ff"/>
              <text x="154" y="64" font-size="6" fill="#333" font-weight="700" font-family="Microsoft YaHei,sans-serif">张女士</text>
              <text x="154" y="72" font-size="5" fill="#999" font-family="Microsoft YaHei,sans-serif">招聘方 · 松下集团</text>
              <!-- 工作地点 -->
              <text x="130" y="90" font-size="7" fill="#333" font-weight="700" font-family="Microsoft YaHei,sans-serif">工作地点</text>
              <rect x="130" y="94" width="180" height="20" rx="3" fill="#e8f4f0"/>
              <text x="138" y="107" font-size="6" fill="#666" font-family="Microsoft YaHei,sans-serif">钱塘区松下杭州工业园-南门HA栋</text>
              <!-- 查看更多信息 -->
              <rect x="180" y="120" width="80" height="12" rx="6" fill="#fff" stroke="#3e7cf1" stroke-width="1"/>
              <text x="191" y="129" font-size="6" fill="#3e7cf1" font-family="Microsoft YaHei,sans-serif">查看更多信息▸</text>
            </svg>
          </div>
        </div>
        <div class="guide-caption">
          <b>智联招聘</b>：左侧点岗位 → 右侧出现详情 → 往下拉到底部看到<b>「查看更多信息 ▸」</b>→ 点蓝色「+ 抓取岗位」
        </div>
      </div>
    </div>
  </div>

  <div style="margin:10px 0 10px 36px;padding:10px 14px;background:#fef3c7;border:1px solid #fde68a;border-radius:8px;font-size:12px;color:#92400e;line-height:1.7">
    <b>💡 关键点</b>：一定要看到岗位的<b>完整详情</b>（岗位职责、任职要求、工作地址等），再点「+ 抓取岗位」。如果只在列表页，抓到的信息不完整。
  </div>

  <div class="step"><div class="step-n">4</div><div class="step-t"><b>完成！</b><br>岗位自动保存到这个看板，AI 会帮你分析匹配度。你可以在这里搜索、筛选、跟踪投递进度。</div></div>
  <h3>📊 这个页面能做什么</h3>
  <ul>
    <li><b>搜索</b>：在顶部搜索框输入公司名或岗位名，快速找到目标</li>
    <li><b>筛选</b>：按平台、投递状态、通勤时间等条件过滤岗位</li>
    <li><b>AI 分析</b>：每个岗位都会自动分析，告诉你匹配度和面试建议</li>
    <li><b>投递跟踪</b>：点击岗位状态，标记「已投递」「面试中」「已入职」等</li>
    <li><b>通勤计算</b>：设置你的住址后，自动显示每个岗位的通勤时间</li>
  </ul>
  <h3>❓ 遇到问题？</h3>
  <ul>
    <li><b>点「抓取岗位」没反应？</b> → 你可能在岗位列表页，要<b>点进岗位详情页</b>才行。刷新页面后重试。</li>
    <li><b>登录后页面是空的？</b> → 按键盘上的 <b>Ctrl + F5</b> 强制刷新。</li>
    <li><b>想换账号？</b> → 点页面右上角的「退出」按钮。</li>
  </ul>
</div>
</div>
<div class="drawer-mask" id="drawer-mask" onclick="closeDeep()"></div>
<div class="drawer" id="drawer"><div class="drawer-hd"><span class="drawer-t">📊 深入专项分析</span><button class="drawer-x" onclick="closeDeep()">✕</button></div>
<div class="drawer-bd" id="drawer-bd"></div></div>
</body>
</html>

"""


def _calc_user_num(out_path, username):
    """根据注册顺序计算用户编号（boss=0，之后按注册时间递增）。"""
    import sqlite3
    try:
        db_path = os.path.join(os.path.dirname(os.path.dirname(out_path)), 'data', 'jobs.db')
        conn = sqlite3.connect(db_path)
        rows = conn.execute('SELECT username FROM users ORDER BY created_at ASC').fetchall()
        conn.close()
        for i, (u,) in enumerate(rows):
            if u == username:
                return str(i).zfill(4)
    except Exception:
        pass
    return '????'


def build(jobs, cm_meta, out_path, api_token='', username=''):
    """生成岗位精读看板 HTML。返回 (路径, data)。"""
    data = _slim(jobs)
    n_cm = _attach_commute(data, cm_meta)
    payload = json.dumps(data, ensure_ascii=False).replace('</', '<\\/')
    n_an = sum(1 for d in data if d.get('analysis'))
    user_id = _calc_user_num(out_path, username) if username else ''
    html = (TEMPLATE
            .replace('__DATA__', payload)
            .replace('__GEN__', datetime.now().strftime('%Y-%m-%d %H:%M'))
            .replace('__N__', str(len(data)))
            .replace('__A__', str(n_an))
            .replace('__C__', str(n_cm))
            .replace('__API_TOKEN__', json.dumps(api_token or '', ensure_ascii=False))
            .replace('__ORIGIN_NAME__', json.dumps(cm_meta.get('origin_name', '') or '', ensure_ascii=False))
            .replace('__ORIGIN_RAW__', json.dumps(cm_meta.get('origin_raw', '') or '', ensure_ascii=False))
            .replace('__AMAP_READY__', 'true' if cm_meta.get('amap_js_key') else 'false')
            .replace('__AMAP_KEY__', json.dumps(cm_meta.get('amap_js_key', '') or '', ensure_ascii=False))
            .replace('__AMAP_SEC__', json.dumps(cm_meta.get('amap_js_security', '') or '', ensure_ascii=False))
            .replace('__USERNAME__', json.dumps(username or '', ensure_ascii=False))
            .replace('__USER_ID__', json.dumps(user_id, ensure_ascii=False)))
    # <head> 静态注入高德 JS（v2 官方推荐写法：安全配置脚本在 maps 脚本前）
    if cm_meta.get('amap_js_key'):
        jkey = cm_meta['amap_js_key']
        jsec = cm_meta.get('amap_js_security', '') or ''
        head = ('<script>window._AMapSecurityConfig={securityJsCode:%s};</script>\n'
                '<script src="https://webapi.amap.com/maps?v=2.0&key=%s"></script>' % (json.dumps(jsec), jkey))
    else:
        head = ''
    html = html.replace('__AMAP_HEAD__', head)
    d = os.path.dirname(os.path.abspath(out_path))
    if d:
        os.makedirs(d, exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(html)
    return out_path, data
