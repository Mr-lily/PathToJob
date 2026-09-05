# -*- coding: utf-8 -*-
#!/usr/bin/env python3
"""job-hub 命令行入口。

常用流程：
    python run.py demo                     # 载入示例数据，看看效果
    python run.py import 岗位.csv           # 导入一个文件
    python run.py paste                    # 直接粘贴文本（输完后 Ctrl-Z 回车 / Linux 下 Ctrl-D）
    python run.py refresh                  # 按 config.json 重新打分并刷新看板
    python run.py list --top 20            # 命令行里看排名
    python run.py set <id前缀> 已投递       # 更新投递状态
    python run.py export                   # 导出 CSV
"""

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from jobhub import store, score as SC, ingest, report, insight, commute, normalize as N  # noqa: E402

CONFIG_PATH = os.path.join(ROOT, 'config.json')
# 去重保序（STATUS_ORDER 里含旧值别名，如 待处理/未投递 rank 相同）
STATUS_CHOICES = list(dict.fromkeys(store.STATUS_ORDER))


def load_cfg():
    if not os.path.exists(CONFIG_PATH):
        print(f'找不到配置文件：{CONFIG_PATH}')
        sys.exit(1)
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def db_path(cfg):
    p = cfg.get('runtime', {}).get('db_path', 'data/jobs.db')
    return p if os.path.isabs(p) else os.path.join(ROOT, p)


def out_path(cfg, key, default):
    p = cfg.get('runtime', {}).get(key, default)
    return p if os.path.isabs(p) else os.path.join(ROOT, p)


def refresh(cfg, verbose=True):
    """重新打分 + 回写数据库 + 刷新看板。"""
    conn = store.connect(db_path(cfg))
    jobs = store.all_jobs(conn)
    if not jobs:
        if verbose:
            print('库里还没有数据，先 import 或 paste 一点进来。')
        conn.close()
        return []
    SC.score_all(jobs, cfg)
    conn.executemany(
        'UPDATE jobs SET score = ?, score_detail = ?, updated_at = updated_at WHERE id = ?',
        [(j['score'], json.dumps(j['score_detail'], ensure_ascii=False), j['id']) for j in jobs]
    )
    conn.commit()
    conn.close()
    return jobs


def cmd_import(args, cfg):
    conn = store.connect(db_path(cfg))
    try:
        items = ingest.load_any(args.file, default_platform=args.platform)
    except FileNotFoundError:
        print(f'文件不存在：{args.file}')
        sys.exit(1)
    except ValueError as e:
        print(str(e))
        sys.exit(1)

    n_new = n_merged = n_dupe = 0
    for it in items:
        if not it.get('company') and not it.get('title'):
            continue
        res, _ = store.upsert(conn, it)
        if res == 'new':
            n_new += 1
        elif res == 'merged':
            n_merged += 1
        else:
            n_dupe += 1
    conn.close()

    print(f'导入完成：新增 {n_new} · 更新 {n_merged} · 重复 {n_dupe} · 共读取 {len(items)} 条')
    if n_merged or n_dupe:
        print(f'  （{n_merged + n_dupe} 条在库里已有同一岗位，已合并来源，没产生新记录）')
    if not args.no_refresh:
        jobs = refresh(cfg, verbose=False)
        if jobs:
            p = report.build(jobs, cfg, out_path(cfg, 'report_path', 'data/dashboard.html'))
            print(f'看板已刷新：{p}')


def cmd_paste(args, cfg):
    print('把数据粘进来（支持 Tab / | / 逗号 / 制表符分隔，第一行可写表头）。')
    print('Windows 下输完按 Ctrl-Z 再回车；macOS/Linux 按 Ctrl-D：')
    lines = []
    try:
        for line in sys.stdin:
            lines.append(line)
    except KeyboardInterrupt:
        pass
    text = ''.join(lines)
    if not text.strip():
        print('没有读到内容。')
        return
    items = ingest.parse_text(text, default_platform=args.platform)
    if not items:
        print('没能解析出有效行，检查下分隔符是否在用。')
        return
    conn = store.connect(db_path(cfg))
    n = sum(1 for it in items if store.upsert(conn, it)[0] in ('new', 'merged'))
    conn.close()
    print(f'导入完成：{len(items)} 条记录，其中 {n} 条有变化')
    if not args.no_refresh:
        jobs = refresh(cfg, verbose=False)
        if jobs:
            p = report.build(jobs, cfg, out_path(cfg, 'report_path', 'data/dashboard.html'))
            print(f'看板已刷新：{p}')


def cmd_refresh(args, cfg):
    jobs = refresh(cfg)
    if not jobs:
        return
    p = report.build(jobs, cfg, out_path(cfg, 'report_path', 'data/dashboard.html'))
    strong = sum(1 for j in jobs if j['score_detail']['tier'] == 'strong')
    print(f'已重新打分：{len(jobs)} 个岗位，其中 {strong} 个强烈推荐')
    print(f'看板：{p}')


def cmd_list(args, cfg):
    jobs = refresh(cfg, verbose=False)
    if not jobs:
        print('库里还没有数据。')
        return
    conn = store.connect(db_path(cfg))
    rows = store.find(conn, keyword=args.keyword, status=args.status,
                      min_score=args.min_score, platform=args.platform, limit=args.top)
    conn.close()
    if not rows:
        print('没有匹配的岗位。')
        return
    print(f'\n{"分数":>6}  {"岗位":<22} {"公司":<20} {"薪资":<14} {"城市":<8} {"状态":<8} ID')
    print('-' * 104)
    for j in rows:
        s = N.salary_text(j)
        print(f'{j.get("score") or 0:>6}  {(j.get("title") or "")[:21]:<22} '
              f'{(j.get("company") or "")[:19]:<20} {s:<14} '
              f'{(j.get("city") or "")[:7]:<8} {(j.get("status") or "")[:7]:<8} {j["id"]}')
    print()


def cmd_set(args, cfg):
    conn = store.connect(db_path(cfg))
    jid = args.id
    if len(jid) < 20:
        row = conn.execute('SELECT id, title, company FROM jobs WHERE id LIKE ?',
                           (jid + '%',)).fetchone()
        if not row:
            print(f'找不到以 {jid} 开头的岗位 ID。用 `python run.py list` 看完整 ID。')
            sys.exit(1)
        jid = row['id']
    store.set_status(conn, jid, args.status, notes=args.notes)
    conn.close()
    print(f'已更新：{jid} -> {args.status}')
    jobs = refresh(cfg, verbose=False)
    if jobs:
        report.build(jobs, cfg, out_path(cfg, 'report_path', 'data/dashboard.html'))


def cmd_export(args, cfg):
    import csv as _csv
    jobs = refresh(cfg, verbose=False)
    if not jobs:
        print('没有数据可导出。')
        return
    path = args.out or out_path(cfg, 'export_path', 'data/jobs.csv')
    cols = ['score', 'company', 'title', 'salary_min', 'salary_max', 'salary_months',
            'city', 'district', 'experience', 'education', 'status', 'platforms',
            'hr_name', 'hr_active', 'published_at', 'url', 'notes']
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, 'w', encoding='utf-8-sig', newline='') as f:
        w = _csv.writer(f)
        w.writerow(cols)
        for j in jobs:
            row = []
            for c in cols:
                v = j.get(c)
                if c == 'platforms':
                    v = ' '.join(v or [])
                row.append('' if v is None else v)
            w.writerow(row)
    print(f'已导出 {len(jobs)} 条 -> {path}')


def cmd_demo(args, cfg):
    sample = os.path.join(ROOT, 'samples', 'sample_jobs.json')
    if not os.path.exists(sample):
        print(f'示例数据不存在：{sample}')
        sys.exit(1)
    args.file = sample
    args.platform = 'other'
    args.no_refresh = False
    cmd_import(args, cfg)


def cmd_stats(args, cfg):
    jobs = refresh(cfg, verbose=False)
    if not jobs:
        print('库里还没有数据。')
        return
    sals = [j['salary_max'] for j in jobs if j.get('salary_max')]
    tiers = {}
    for j in jobs:
        t = j['score_detail']['tier']
        tiers[t] = tiers.get(t, 0) + 1
    st = {}
    for j in jobs:
        st[j.get('status')] = st.get(j.get('status'), 0) + 1
    print(f'\n去重后岗位：{len(jobs)}')
    print(f'分档：强烈推荐 {tiers.get("strong",0)} · 可以考虑 {tiers.get("consider",0)} · '
          f'不太匹配 {tiers.get("weak",0)}')
    if sals:
        sals.sort()
        print(f'薪资上限中位数：{sals[len(sals)//2] // 1000}K')
    print('状态分布：' + ' · '.join(f'{k} {v}' for k, v in sorted(st.items())))
    print()


def _commute_min_of(jid):
    """从已生成的 insight.html DATA 里读取某岗位的驾车通勤分钟数（避免重复调高德）。"""
    import json as _json
    import re as _re
    from jobhub import serve as sv
    ipath = out_path(load_cfg(), 'dashboard_insight', 'data/insight.html')
    try:
        html = open(ipath, encoding='utf-8').read()
        m = _re.search(r'const DATA=(\[.*?\]);', html, _re.S)
        if m:
            for d in _json.loads(m.group(1)):
                if d.get('id') == jid:
                    cm = d.get('commute') or {}
                    return ((cm.get('modes') or {}).get('driving') or {}).get('minutes')
    except Exception:
        pass
    return None


def cmd_analyze(args, cfg):
    """批量给缺分析的岗位生成深度分析（调 DeepSeek）。"""
    from jobhub import analyzer, score as SC
    conn = store.connect(db_path(cfg))
    jobs = store.all_jobs(conn)
    todo = [j for j in jobs if not j.get('analysis')]
    if not todo:
        print('所有岗位都已有分析，无需处理。')
        conn.close()
        return
    ok_n = fail_n = 0
    for j in todo:
        jid = j['id']
        print(f'分析中: {j.get("company", "")} | {j.get("title", "")} ...', end=' ', flush=True)
        base_score, base_detail = SC.score_job(j, cfg)
        text, err = analyzer.analyze(j, cfg, os.path.dirname(os.path.abspath(__file__)),
                                     base_score=base_score, base_breakdown=base_detail.get('breakdown'))
        if text:
            delta = analyzer.parse_delta(text)
            diff = analyzer.parse_difficulty(text)
            fit = base_score if delta is None else max(0, min(100, base_score + delta))
            store.set_score(conn, jid, base_score, base_detail)
            store.set_analysis(conn, jid, text, fit_score=fit)
            if diff is not None:
                store.set_difficulty(conn, jid, diff)
                from jobhub import serve as sv
                cm_min = _commute_min_of(jid)
                rec = sv._rec_score(fit, cm_min, diff, cfg)
                store.set_rec_score(conn, jid, rec)
                ok_n += 1
                print(f'OK  基准={base_score} 微调={delta} → 适配={fit} 难度={diff} 推荐={rec}')
            else:
                ok_n += 1
                print(f'OK  基准={base_score} 微调={delta} → 适配={fit}（无难度分）')
        else:
            fail_n += 1
            print(f'失败: {err}')
    conn.close()
    print(f'完成：成功 {ok_n}，失败 {fail_n}。')
    if ok_n:
        cmd_insight(args, cfg)


def cmd_recalc(args, cfg):
    """按当前 rec_weight 权重，用已有 fit_score/difficulty/通勤 重算推荐指数（不调 AI）。"""
    import json as _json
    from jobhub import serve as sv
    conn = store.connect(db_path(cfg))
    jobs = store.all_jobs(conn)
    # 从已生成的 insight.html 里读每个岗位的通勤分钟数（避免重复调高德）
    cm_map = {}
    ipath = out_path(cfg, 'dashboard_insight', 'data/insight.html')
    try:
        html = open(ipath, encoding='utf-8').read()
        m = __import__('re').search(r'const DATA=(\[.*?\]);', html, __import__('re').S)
        if m:
            for d in _json.loads(m.group(1)):
                cm = d.get('commute') or {}
                drv = (cm.get('modes') or {}).get('driving') or {}
                cm_map[d.get('id')] = drv.get('minutes')
    except Exception:
        pass
    n = 0
    for j in jobs:
        if j.get('fit_score') is None:
            continue
        diff = j.get('difficulty')
        cm_min = cm_map.get(j['id'])
        rec = sv._rec_score(j.get('fit_score'), cm_min, diff, cfg)
        store.set_rec_score(conn, j['id'], rec)
        n += 1
    conn.close()
    print(f'已按新权重重算推荐指数：{n} 条。')
    if n:
        cmd_insight(args, cfg)


def cmd_scorediff(args, cfg):
    """给缺求职难度的岗位补估难度，并计算综合推荐指数（适配+通勤+难度）。"""
    from jobhub import analyzer
    from jobhub import serve as sv
    conn = store.connect(db_path(cfg))
    jobs = store.all_jobs(conn)
    todo = [j for j in jobs if j.get('difficulty') is None]
    if not todo:
        print('所有岗位都已估算求职难度，无需处理。')
        conn.close()
        return
    ok_n = fail_n = 0
    for j in todo:
        jid = j['id']
        print(f'估难度: {j.get("company", "")} | {j.get("title", "")} ...', end=' ', flush=True)
        diff, err = analyzer.estimate_difficulty(j, cfg, os.path.dirname(os.path.abspath(__file__)))
        if diff is not None:
            store.set_difficulty(conn, jid, diff)
            # 算推荐指数
            fit = j.get('fit_score')
            cm_min = None
            cm = j.get('commute')
            if cm and isinstance(cm, dict) and cm.get('modes'):
                drv = cm['modes'].get('driving') or {}
                cm_min = drv.get('minutes')
            rec = sv._rec_score(fit, cm_min, diff, cfg)
            store.set_rec_score(conn, jid, rec)
            ok_n += 1
            print(f'OK 难度={diff} 推荐={rec}')
        else:
            fail_n += 1
            print(f'失败: {err}')
    conn.close()
    print(f'完成：成功 {ok_n}，失败 {fail_n}。')
    if ok_n:
        cmd_insight(args, cfg)


def cmd_insight(args, cfg):
    """生成「岗位精读看板」——以汇总+贰贰深度分析为核心，弱化分数排序。"""
    conn = store.connect(db_path(cfg))
    jobs = store.all_jobs(conn)
    conn.close()
    if not jobs:
        # 空库也要重建看板，覆盖旧 HTML 里的僵尸岗位（否则删除后页面永远不同步）
        print('库里没有数据，正在生成空看板覆盖旧页面...')
        jobs = []
    n_an = sum(1 for j in jobs if j.get('analysis'))
    path = out_path(cfg, 'dashboard_insight', 'data/insight.html')
    cm_meta = commute.load_from_config(cfg)
    out, data = insight.build(jobs, cm_meta, path, api_token=(cfg.get('api_token') or ''))
    n_cm = sum(1 for d in data if d.get('commute'))
    print(f'岗位精读看板已生成：{out}')
    print(f'共 {len(data)} 个岗位，其中 {n_an} 个已有贰贰深度分析，{n_cm} 个算出通勤。')
    if n_an < len(data):
        print('其余岗位待贰贰逐个补分析。')


def cmd_serve(args, cfg):
    """启动本地配置服务（供看板网页改通勤起点/岗位地址）。"""
    from jobhub import serve as sv
    sv.main()


def main():
    p = argparse.ArgumentParser(
        prog='job-hub', description='本地求职汇总工具（纯标准库，数据不出本机）')
    sub = p.add_subparsers(dest='cmd', required=True)

    sp = sub.add_parser('import', help='从 .json / .csv / .tsv / .txt 导入')
    sp.add_argument('file')
    sp.add_argument('--platform', default='other', help='未标注平台时的默认来源名')
    sp.add_argument('--no-refresh', action='store_true', help='只入库，不重新打分')
    sp.set_defaults(func=cmd_import)

    sp = sub.add_parser('paste', help='从标准输入粘贴文本导入')
    sp.add_argument('--platform', default='other')
    sp.add_argument('--no-refresh', action='store_true')
    sp.set_defaults(func=cmd_paste)

    sp = sub.add_parser('refresh', help='按 config.json 重新打分并刷新看板')
    sp.set_defaults(func=cmd_refresh)

    sp = sub.add_parser('list', help='命令行列出岗位')
    sp.add_argument('--top', type=int, default=20)
    sp.add_argument('--keyword')
    sp.add_argument('--status', choices=STATUS_CHOICES)
    sp.add_argument('--platform')
    sp.add_argument('--min-score', type=float)
    sp.set_defaults(func=cmd_list)

    sp = sub.add_parser('set', help='更新投递状态')
    sp.add_argument('id', help='岗位 ID，或 ID 的前几位')
    sp.add_argument('status', choices=STATUS_CHOICES)
    sp.add_argument('--notes')
    sp.set_defaults(func=cmd_set)

    sp = sub.add_parser('export', help='导出 CSV')
    sp.add_argument('--out')
    sp.set_defaults(func=cmd_export)

    sp = sub.add_parser('demo', help='载入示例数据')
    sp.set_defaults(func=cmd_demo)

    sp = sub.add_parser('stats', help='看汇总统计')
    sp.set_defaults(func=cmd_stats)

    sp = sub.add_parser('insight', help='生成「岗位精读看板」（汇总+贰贰深度分析）')
    sp.set_defaults(func=cmd_insight)

    sp = sub.add_parser('analyze', help='批量给缺分析的岗位生成深度分析（调 DeepSeek）')
    sp.set_defaults(func=cmd_analyze)

    sp = sub.add_parser('scorediff', help='给缺求职难度的岗位补估难度并计算综合推荐指数')
    sp.set_defaults(func=cmd_scorediff)

    sp = sub.add_parser('recalc', help='按当前权重用已有数据重算推荐指数（不调AI）')
    sp.set_defaults(func=cmd_recalc)

    sp = sub.add_parser('serve', help='启动本地配置服务（网页改通勤起点/岗位地址）')
    sp.set_defaults(func=cmd_serve)

    args = p.parse_args()
    cfg = load_cfg()
    args.func(args, cfg)


if __name__ == '__main__':
    main()
