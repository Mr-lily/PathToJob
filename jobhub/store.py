# -*- coding: utf-8 -*-
"""SQLite 存储层：建表、写入、跨平去重合并。

去重键 = 公司名(归一) + 岗位名(归一) + 城市(归一)
同一个岗位在 Boss、猎聘、51job 上重复出现时，会合并成一条，
platforms 字段记录它出现在哪些平台，避免你重复投递。
"""

import json
import os
import re
import sqlite3
import hashlib
import datetime

from . import normalize as N

# 尾部噪音锚点：JD 到这里就该截断（HR 信息/版权/安全提示/地图/公司介绍等）
_JD_TAIL = re.compile(r'(谭女士|先生\s*在线|在线\s*[·.∙]?\s*[A-Za-z\u4e00-\u9fa5]{1,10}\s*[·.∙]?\s*(HR|HRBP|招聘者|人事|猎头)|竞争力分析|个人综合排名|BOSS\s*安全|安全提示|举报|工作地址|工作地点|地图完整地址|点击查看地图|©|ICP备|ICP证|京ICP|沪ICP|版权|公司信息|公司介绍|团队介绍|相似职位|工商信息|温馨提示|立即投递|正在招聘|发布于|快速申请|其他信息|行业要求|公司规模|公司行业|公司性质|薪资范围|职位亮点|我们提供)')


def clean_jd(jd):
    """清洗原始 JD：去掉尾部噪音（HR/版权/安全提示/地图/公司介绍）、开头标签云、悬空序号，保留「岗位职责/任职要求」小标题。"""
    if not jd:
        return jd
    s = (jd or '').replace('\u3000', ' ').strip()
    tail_m = _JD_TAIL.search(s)
    if tail_m:
        s = s[:tail_m.start()]
    # 去掉锚点前的中文/康德部首序号（如"一、岗位职责"→"岗位职责"），保留职责/任职标题本身
    s = re.sub(r'[一二三四五六七八九十\u2f00-\u2fdf]、\s*(?=(?:岗位职责|职位描述|工作职责|岗位描述|任职要求|岗位要求|任职资格|职位要求))', '', s)
    # 去掉悬空序号（中文/康熙部首序号+顿号），但别动紧跟数字条目的序号
    s = re.sub(r'[一二三四五六七八九十\u2f00-\u2fdf]、', '', s)
    # 规范小标题：给"岗位职责/任职要求"等加换行标题（标题前也保证有换行分隔），去掉多余冒号
    s = re.sub(r'(岗位职责|职位描述|工作职责|岗位描述|任职要求|岗位要求|任职资格|职位要求)\s*[:：]\s*', r'\n\1：\n', s)
    # 去掉开头的技能标签云（标签是连续短词、无标点，直到第一个数字条目/标题）
    s = re.sub(r'^(?:[\u4e00-\u9fa5A-Za-z/]+\s*){1,6}?(?=(?:岗位职责|任职要求|\d+[、.]))', '', s)
    s = re.sub(r'[ \t]{2,}', ' ', s)
    s = re.sub(r'\n{2,}', '\n', s)
    # 若整段只有数字条目块且无"岗位职责/任职要求"标题，按块补标题
    s = _ensure_jd_titles(s)
    s = s.strip(' \n')
    # 排版：把长段按句号分条，增强可读性
    s = _format_jd(s)
    return s or jd


def _format_jd(s):
    """把 JD 正文排版成易读的多行：标题行保留，数字条目逐条成行，长段落按句号分条。"""
    if not s:
        return s
    out = []
    for raw in s.split('\n'):
        seg = raw.strip()
        if not seg:
            continue
        # 标题行（岗位职责/任职要求等）原样保留
        if re.match(r'^(岗位职责|职位描述|工作职责|岗位描述|任职要求|岗位要求|任职资格|职位要求)', seg):
            out.append(seg)
            continue
        # 数字编号条目：逐条成行（每条以 数字+、 开头的片段）
        if re.match(r'^\s*\d+[、.]', seg):
            # 把一条条"1、xx 2、xx 3、xx"切成单条
            parts = re.findall(r'\d+[、.][^0-9]*?(?=\s*\d+[、.]|$)', seg)
            for p in parts:
                p = p.strip()
                if p:
                    out.append(p)
            continue
        # 长段落（无编号）：按句号拆成短句
        parts = [x.strip() for x in re.split(r'(?<=[。；])', seg) if x.strip()]
        if parts:
            out.append(parts[0])
            out.extend('　' + p for p in parts[1:])
        else:
            out.append(seg)
    return '\n'.join(out)


def _ensure_jd_titles(s):
    """若 JD 是纯数字条目（"1、xx 2、xx" 分多块），第一块补"岗位职责"，其余块补"任职要求"。"""
    if not s:
        return s
    lines = [l.strip() for l in s.split('\n') if l.strip()]
    if not lines:
        return s
    has_title = any(re.search(r'岗位职责|职位描述|工作职责|任职要求|岗位要求', l) for l in lines)
    if has_title:
        return s
    # 数字条目行：以 数字+顿号/点 开头的整行（一行可含多条，如"1、a；2、b"）
    item_rows = [l for l in lines if re.match(r'^\s*\d+[、.]', l) or re.search(r'^\s*\d+[、.]', l)]
    if len(item_rows) < 2:
        return s  # 不足两块，不猜
    # 分块：每行一个候选块；若同一行含多个数字序号则视为一块
    out = []
    label_idx = 0
    for l in lines:
        if re.match(r'^\s*\d+[、.]', l) or re.match(r'^\s*(?:\d+[、.]|[一二三四五六七八九十]),', l):
            pass
    # 简单起见：按"行"分块，第一行=职责，后续=任职要求
    if re.search(r'\d+[、.]', lines[0]):
        out.append('岗位职责：\n' + '\n'.join(lines[:1]).strip())
    rest = lines[1:]
    if rest:
        out.append('任职要求：\n' + '\n'.join(rest).strip())
    return '\n\n'.join(out) if len(out) >= 2 else s

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    username        TEXT PRIMARY KEY,
    password_hash   TEXT NOT NULL,
    created_at      TEXT
);
CREATE TABLE IF NOT EXISTS invite_codes (
    code            TEXT PRIMARY KEY,
    created_at      TEXT,
    created_by      TEXT,
    used_by         TEXT,
    used_at         TEXT,
    note            TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS jobs (
    id              TEXT PRIMARY KEY,
    user_id         TEXT,
    dedupe_key      TEXT NOT NULL,
    platforms       TEXT DEFAULT '[]',
    company         TEXT,
    company_norm    TEXT,
    company_core    TEXT,
    title           TEXT,
    title_norm      TEXT,
    city            TEXT,
    district        TEXT,
    salary_raw      TEXT,
    salary_min      INTEGER,
    salary_max      INTEGER,
    salary_months   INTEGER,
    experience      TEXT,
    education       TEXT,
    tags            TEXT DEFAULT '[]',
    jd              TEXT,
    hr_name         TEXT,
    hr_active       TEXT,
    hr_active_score INTEGER DEFAULT 0,
    url             TEXT,
    published_at    TEXT,
    freshness_score INTEGER DEFAULT 1,
    status          TEXT DEFAULT '未投递',
    applied_at      TEXT,
    notes           TEXT,
    score           REAL,
    score_detail    TEXT DEFAULT '{}',
    analysis        TEXT,
    address         TEXT,
    fit_score       INTEGER,
    is_key          INTEGER DEFAULT 0,
    difficulty      INTEGER,
    deep_analysis   TEXT,
    rec_score       REAL,
    created_at      TEXT,
    updated_at      TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_dedupe ON jobs(dedupe_key);
CREATE INDEX IF NOT EXISTS idx_jobs_core ON jobs(company_core);
CREATE INDEX IF NOT EXISTS idx_jobs_city ON jobs(city);
CREATE INDEX IF NOT EXISTS idx_jobs_score ON jobs(score);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
"""

STATUS_ORDER = {
    # —— 投递进度阶梯（从早到晚）——
    '未投递': 0,
    '已收藏': 1,
    '已投递': 2,
    '简历筛选中': 3,
    '已约面试': 4,
    '一轮面试': 5,
    '二轮面试': 6,
    '三轮终面': 7,
    '已发Offer': 8,
    '已入职': 9,
    # —— 终止态 ——
    '不合适': 10,
    '已婉拒': 11,
    '已过期': 12,
    '已归档': 13,
    # —— 兼容旧值 ——
    '待处理': 0,
    '已沟通': 3,
    '面试中': 5,
    '已offer': 8,
}

# 合并时的取值优先级：索引越大越优先保留
_STATUS_RANK = {k: i for i, k in enumerate(STATUS_ORDER)}


def _now():
    return datetime.datetime.now().isoformat(timespec='seconds')


def connect(db_path):
    d = os.path.dirname(os.path.abspath(db_path))
    if d:
        os.makedirs(d, exist_ok=True)
    # 自动备份：库存在且非空时保留每小时一份快照（上限48份≈2天，防滥用）
    try:
        if os.path.exists(db_path) and os.path.getsize(db_path) > 4096:
            bk_dir = os.path.join(d, 'backups')
            os.makedirs(bk_dir, exist_ok=True)
            import glob
            from datetime import datetime
            # 按小时命名：jobs_YYYYMMDDHH.db，同一小时内不重复备份
            hour = datetime.now().strftime('%Y%m%d%H')
            hour_bk = os.path.join(bk_dir, 'jobs_' + hour + '.db')
            if not os.path.exists(hour_bk):
                import shutil
                shutil.copy2(db_path, hour_bk)
            # 只保留最近 48 份
            bks = sorted(glob.glob(os.path.join(bk_dir, 'jobs_*.db')))
            if len(bks) > 48:
                for old in bks[:len(bks) - 48]:
                    try:
                        os.remove(old)
                    except OSError:
                        pass
    except Exception:
        pass  # 备份失败不阻塞主流程
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    # 兼容迁移：旧库缺列时补上（IF NOT EXISTS 无法加列）
    try:
        cols = [r[1] for r in conn.execute('PRAGMA table_info(jobs)').fetchall()]
        for name, decl in (('analysis', 'TEXT'), ('address', 'TEXT'), ('fit_score', 'INTEGER'),
                           ('is_key', 'INTEGER DEFAULT 0'), ('difficulty', 'INTEGER'),
                           ('deep_analysis', 'TEXT'), ('rec_score', 'REAL'),
                           ('user_id', 'TEXT')):
            if name not in cols:
                conn.execute(f'ALTER TABLE jobs ADD COLUMN {name} {decl}')
        conn.commit()
    except Exception:
        pass
    return conn


def dedupe_key(company, title, city):
    raw = f'{N.norm_company_core(company)}|{N.norm_title(title)}|{N.norm_city(city)}'
    return hashlib.sha1(raw.encode('utf-8')).hexdigest()[:16]


def looks_same(a, b, title_threshold=0.75, company_threshold=0.75):
    """判断两条记录是不是同一个岗位（跨平台重复）。

    标题用模糊匹配兜住词序差异，公司名用核心词比较 + 包含关系判断。
    """
    if (a.get('city') or '') != (b.get('city') or ''):
        return False
    tr = N.similar(a.get('title_norm') or '', b.get('title_norm') or '')
    if tr < title_threshold:
        return False
    ca, cb = a.get('company_core') or '', b.get('company_core') or ''
    if ca and cb:
        if ca == cb or ca in cb or cb in ca:
            return True
        return N.similar(ca, cb) >= company_threshold
    # 公司名解析不出来时，就要求岗位名几乎一致
    return tr >= 0.9


def _merge_platforms(old_json, plat):
    """合并平台来源列表。

    未标注来源（'other'）时不要覆盖已有的真实来源，
    否则把导出的 CSV 再导回来会给每条记录都多加一个 other。
    """
    plats = json.loads(old_json or '[]')
    if plat in plats:
        return plats
    if plat == 'other' and plats:
        return plats
    plats.append(plat)
    return plats


def _merge_into(conn, existing, row, platform):
    """把 row 合并进已存在的记录 existing。"""
    e = dict(existing)
    plats = _merge_platforms(e['platforms'], platform)
    merged = {}
    for k, v in row.items():
        if k in ('id', 'dedupe_key'):
            continue
        if k == 'platforms':
            if plats != json.loads(e['platforms'] or '[]'):
                merged[k] = json.dumps(plats, ensure_ascii=False)
        elif k == 'status':
            nv = (v if _STATUS_RANK.get(v, 0) > _STATUS_RANK.get(e.get('status'), 0)
                  else e.get('status'))
            if nv != e.get(k):
                merged[k] = nv
        else:
            nv = _fill(e.get(k), v)
            if nv != e.get(k):
                merged[k] = nv
    if not merged:
        return e['id'], False
    merged['updated_at'] = _now()
    sets = ', '.join(f'{k} = ?' for k in merged)
    conn.execute(f'UPDATE jobs SET {sets} WHERE id = ?',
                 list(merged.values()) + [e['id']])
    conn.commit()
    return e['id'], True


def job_id(platform, raw_id, company, title, url, user_id=None):
    basis = raw_id or url or f'{company}|{title}'
    if user_id:
        basis = f'{user_id}::{basis}'
    return hashlib.sha1(f'{platform}::{basis}'.encode('utf-8')).hexdigest()[:20]


def row_to_dict(row):
    if row is None:
        return None
    d = dict(row)
    for f in ('platforms', 'tags', 'score_detail'):
        if d.get(f):
            try:
                d[f] = json.loads(d[f])
            except (json.JSONDecodeError, TypeError):
                d[f] = [] if f != 'score_detail' else {}
        else:
            d[f] = [] if f != 'score_detail' else {}
    return d


def _fill(old, new):
    """旧值为空就用新值补上；都有值时保留旧值（先到先得，避免被脏数据覆盖）。"""
    return old if (old not in (None, '', 0, '[]', '{}')) else new


def upsert(conn, item, recompute_salary=True, user_id=None):
    """写入或合并一条职位。

    返回 ('new'|'merged'|'dupe', job_id)：
      new    —— 新岗位，已入库
      merged —— 识别出是已入库的同一岗位，且补充/更新了字段
      dupe   —— 识别出是同一岗位，但没带来任何新信息（纯重复）

    user_id 用于多用户隔离：同一岗位在不同用户名下各自独立，不跨用户合并。
    """
    platform = (item.get('platform') or 'other').strip()
    company = (item.get('company') or '').strip()
    title = (item.get('title') or '').strip()
    city = (item.get('city') or '').strip()

    if recompute_salary and item.get('salary_raw'):
        lo, hi, months = N.parse_salary(item['salary_raw'])
    else:
        lo = item.get('salary_min')
        hi = item.get('salary_max')
        months = item.get('salary_months') or 12

    if item.get('salary_min') is not None and not recompute_salary:
        lo, hi = item.get('salary_min'), item.get('salary_max')

    row = {
        'id': job_id(platform, item.get('raw_id'), company, title, item.get('url'), user_id),
        'user_id': user_id,
        'dedupe_key': dedupe_key(company, title, city),
        'platforms': json.dumps([platform], ensure_ascii=False),
        'company': company,
        'company_norm': N.norm_company(company),
        'company_core': N.norm_company_core(company),
        'title': title,
        'title_norm': N.norm_title(title),
        'city': N.norm_city(city),
        'district': (item.get('district') or '').strip(),
        'salary_raw': item.get('salary_raw') or '',
        'salary_min': lo,
        'salary_max': hi,
        'salary_months': months,
        'experience': N.parse_experience(item.get('experience')),
        'education': N.parse_education(item.get('education')),
        'tags': json.dumps(item.get('tags') or [], ensure_ascii=False),
        'jd': clean_jd(item.get('jd') or ''),
        'address': (item.get('address') or '').strip(),
        'hr_name': (item.get('hr_name') or '').strip(),
        'hr_active': (item.get('hr_active') or '').strip(),
        'hr_active_score': N.parse_hr_active(item.get('hr_active')),
        'url': (item.get('url') or '').strip(),
        'published_at': (item.get('published_at') or '').strip(),
        'freshness_score': N.parse_freshness(item.get('published_at')),
        'status': (item.get('status') or '未投递').strip(),
        'applied_at': (item.get('applied_at') or '').strip(),
        'notes': (item.get('notes') or '').strip(),
    }

    cur = conn.execute('SELECT * FROM jobs WHERE id = ?', (row['id'],))
    existing = cur.fetchone()

    if existing is None:
        # 同岗不同平台 -> 按 dedupe_key 合并（仅限同一用户）
        if user_id:
            cur = conn.execute('SELECT * FROM jobs WHERE dedupe_key = ? AND user_id = ?',
                               (row['dedupe_key'], user_id))
        else:
            cur = conn.execute('SELECT * FROM jobs WHERE dedupe_key = ?', (row['dedupe_key'],))
        twin = cur.fetchone()
        if twin is not None:
            jid, changed = _merge_into(conn, twin, row, platform)
            return ('merged' if changed else 'dupe', jid)

        # 精确键没命中，再做一次模糊匹配，兜住各平台写法差异（仅限同一用户）
        if user_id:
            cur = conn.execute('SELECT * FROM jobs WHERE city = ? AND user_id = ?',
                               (row['city'], user_id))
        else:
            cur = conn.execute('SELECT * FROM jobs WHERE city = ?', (row['city'],))
        for cand in cur.fetchall():
            if looks_same(dict(cand), row):
                jid, changed = _merge_into(conn, cand, row, platform)
                return ('merged' if changed else 'dupe', jid)

        row['created_at'] = _now()
        row['updated_at'] = _now()
        cols = ', '.join(row.keys())
        ph = ', '.join('?' * len(row))
        conn.execute(f'INSERT INTO jobs ({cols}) VALUES ({ph})', list(row.values()))
        conn.commit()
        return ('new', row['id'])

    # 完全同一条，只做字段补全
    e = dict(existing)
    updates = {}
    for k, v in row.items():
        if k in ('id', 'dedupe_key'):
            continue
        if k == 'platforms':
            np = _merge_platforms(e['platforms'], platform)
            if np != json.loads(e['platforms'] or '[]'):
                updates[k] = json.dumps(np, ensure_ascii=False)
        elif k == 'status':
            updates[k] = (v if _STATUS_RANK.get(v, 0) > _STATUS_RANK.get(e.get('status'), 0)
                          else e.get('status'))
        else:
            nv = _fill(e.get(k), v)
            if nv != e.get(k):
                updates[k] = nv
    if updates:
        updates['updated_at'] = _now()
        sets = ', '.join(f'{k} = ?' for k in updates)
        conn.execute(f'UPDATE jobs SET {sets} WHERE id = ?',
                     list(updates.values()) + [row['id']])
        conn.commit()
    return ('merged' if updates else 'dupe', row['id'])


def all_jobs(conn, user_id=None):
    if user_id:
        cur = conn.execute('SELECT * FROM jobs WHERE user_id = ?', (user_id,))
    else:
        cur = conn.execute('SELECT * FROM jobs')
    return [row_to_dict(r) for r in cur.fetchall()]


def set_key(conn, job_id, is_key):
    """标记/取消重点岗位。is_key: 1 重点, 0 普通。"""
    conn.execute('UPDATE jobs SET is_key = ?, updated_at = ? WHERE id = ?',
                 (1 if is_key else 0, _now(), job_id))
    conn.commit()
    return conn.total_changes


def set_difficulty(conn, job_id, difficulty):
    """写入求职难度（0-100，数值越大越难）。"""
    conn.execute('UPDATE jobs SET difficulty = ? WHERE id = ?',
                 (int(difficulty), job_id))
    conn.commit()
    return conn.total_changes


def set_deep_analysis(conn, job_id, deep_analysis):
    """写入深入专项分析文本。"""
    conn.execute('UPDATE jobs SET deep_analysis = ?, updated_at = ? WHERE id = ?',
                 (deep_analysis, _now(), job_id))
    conn.commit()
    return conn.total_changes


def set_rec_score(conn, job_id, rec_score):
    """写入综合推荐指数（0-100）。"""
    conn.execute('UPDATE jobs SET rec_score = ?, updated_at = ? WHERE id = ?',
                 (rec_score, _now(), job_id))
    conn.commit()
    return conn.total_changes


def set_score(conn, job_id, score, detail):
    """写入规则基准分（0-100）及明细。"""
    import json as _j
    conn.execute('UPDATE jobs SET score = ?, score_detail = ?, updated_at = ? WHERE id = ?',
                 (score, _j.dumps(detail, ensure_ascii=False), _now(), job_id))
    conn.commit()
    return conn.total_changes


def set_analysis(conn, job_id, analysis, fit_score=None):
    """写入/更新岗位深度分析文本，可选附带适配指数（0-100）。"""
    if fit_score is None:
        conn.execute('UPDATE jobs SET analysis = ?, updated_at = ? WHERE id = ?',
                     (analysis, _now(), job_id))
    else:
        conn.execute('UPDATE jobs SET analysis = ?, fit_score = ?, updated_at = ? WHERE id = ?',
                     (analysis, int(fit_score), _now(), job_id))
    conn.commit()
    return conn.total_changes


def set_status(conn, job_id, status, notes=None):
    if status not in STATUS_ORDER:
        raise ValueError(f'未知状态 {status}，可选：{list(STATUS_ORDER)}')
    now = _now()
    if notes is None:
        conn.execute('UPDATE jobs SET status = ?, updated_at = ? WHERE id = ?',
                     (status, now, job_id))
    else:
        conn.execute('UPDATE jobs SET status = ?, notes = ?, updated_at = ? WHERE id = ?',
                     (status, notes, now, job_id))
    if status in ('已投递',) :
        conn.execute('UPDATE jobs SET applied_at = ? WHERE id = ? AND (applied_at IS NULL OR applied_at = "")',
                     (datetime.date.today().isoformat(), job_id))
    conn.commit()
    return conn.total_changes


def find(conn, keyword=None, status=None, min_score=None, platform=None, limit=50, user_id=None):
    sql = 'SELECT * FROM jobs WHERE 1=1'
    args = []
    if user_id:
        sql += ' AND user_id = ?'
        args.append(user_id)
    if keyword:
        sql += ' AND (company LIKE ? OR title LIKE ? OR jd LIKE ?)'
        args += [f'%{keyword}%'] * 3
    if status:
        sql += ' AND status = ?'
        args.append(status)
    if min_score is not None:
        sql += ' AND score >= ?'
        args.append(min_score)
    if platform:
        sql += ' AND platforms LIKE ?'
        args.append(f'%{platform}%')
    sql += ' ORDER BY COALESCE(score, 0) DESC, COALESCE(salary_max, 0) DESC LIMIT ?'
    args.append(limit)
    return [row_to_dict(r) for r in conn.execute(sql, args).fetchall()]


def get_user_settings(conn, user_id):
    """返回该用户的 {profile, commute, resume}，缺省用空值。"""
    row = conn.execute('SELECT * FROM user_settings WHERE user_id = ?', (user_id,)).fetchone()
    if row is None:
        return {'user_id': user_id, 'profile': {}, 'commute': {}, 'resume': ''}
    d = dict(row)
    for k in ('profile', 'commute'):
        try:
            d[k] = json.loads(d[k] or '{}')
        except Exception:
            d[k] = {}
    return d


def save_user_settings(conn, user_id, profile=None, commute=None, resume=None):
    """按需更新该用户的 profile/commute/resume（传 None 表示不改）。"""
    cur = conn.execute('SELECT profile, commute, resume FROM user_settings WHERE user_id = ?',
                       (user_id,)).fetchone()
    if cur is None:
        p = json.dumps(profile if profile is not None else {}, ensure_ascii=False)
        c = json.dumps(commute if commute is not None else {}, ensure_ascii=False)
        r = resume if resume is not None else ''
        conn.execute('INSERT INTO user_settings(user_id, profile, commute, resume, updated_at) '
                     'VALUES(?,?,?,?,?)', (user_id, p, c, r, _now()))
    else:
        sets, vals = [], []
        if profile is not None:
            sets.append('profile = ?'); vals.append(json.dumps(profile, ensure_ascii=False))
        if commute is not None:
            sets.append('commute = ?'); vals.append(json.dumps(commute, ensure_ascii=False))
        if resume is not None:
            sets.append('resume = ?'); vals.append(resume)
        if sets:
            sets.append('updated_at = ?'); vals.append(_now())
            conn.execute(f'UPDATE user_settings SET {", ".join(sets)} WHERE user_id = ?',
                         vals + [user_id])
    conn.commit()


def ensure_user(conn, user_id, username=None):
    """确保用户存在；不存在则创建（返回该用户行 dict）。"""
    row = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    if row is None:
        import hashlib as _h, time as _t
        h = _h.sha256((username or user_id).encode('utf-8')).hexdigest()
        conn.execute('INSERT INTO users(id, username, password_hash, created_at) '
                     'VALUES(?,?,?,?)', (user_id, username or user_id, h, _now()))
        conn.commit()
        row = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    return dict(row)


# ---- 简单账户系统 ----

def _hash_password(password, salt=None):
    """密码哈希：PBKDF2-SHA256，返回 'salt:hash' 格式。"""
    import secrets as _s
    if salt is None:
        salt = _s.token_hex(16)
    h = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), 100000)
    return f'{salt}:{h.hex()}'


def _verify_password(password, stored_hash):
    """验证密码。stored_hash 格式 'salt:hash'。"""
    if ':' not in stored_hash:
        return False
    salt, _ = stored_hash.split(':', 1)
    return _hash_password(password, salt) == stored_hash


def register_user(conn, username, password):
    """注册用户。返回 (ok, error_msg)。"""
    username = username.strip()
    if not username or len(username) < 2:
        return False, '用户名至少2个字符'
    if not password or len(password) < 4:
        return False, '密码至少4位'
    existing = conn.execute('SELECT 1 FROM users WHERE username=?', (username,)).fetchone()
    if existing:
        return False, '用户名已存在'
    pwd_hash = _hash_password(password)
    conn.execute('INSERT INTO users(username, password_hash, created_at) VALUES(?,?,?)',
                 (username, pwd_hash, _now()))
    conn.commit()
    return True, ''


def verify_user(conn, username, password):
    """登录验证。返回 username 或 None。"""
    row = conn.execute('SELECT username, password_hash FROM users WHERE username=?',
                       (username.strip(),)).fetchone()
    if not row:
        return None
    if _verify_password(password, row[1]):
        return row[0]
    return None
