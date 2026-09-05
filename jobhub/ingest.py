# -*- coding: utf-8 -*-
"""导入层：把各平台导出/复制出来的数据吃进来。

支持三种来源：
  1. JSON  —— 最规范，字段见 README
  2. CSV   —— 中英文列名都能认（公司/company、岗位/title、薪资/salary ...）
  3. 纯文本 —— 直接从聊天窗口或备忘录里粘的一行一条，自动猜分隔符
"""

import csv
import json
import os
import re

ALIASES = {
    'platform':     ['平台', '来源', 'platform', 'source', '渠道'],
    'company':      ['公司', '公司名称', '公司名', '企业', '企业名', 'company', 'org'],
    'title':        ['岗位', '职位', '岗位名称', '职位名称', '招聘职位', 'title', 'job', 'position'],
    'salary_raw':   ['薪资', '薪水', '工资', '薪资范围', '薪酬', 'salary', 'pay'],
    'city':         ['城市', '工作城市', '地点', '工作地', 'city', 'location'],
    'district':     ['区域', '区', '商圈', '行政区', 'district', 'area'],
    'experience':   ['经验', '经验要求', '工作经验', 'experience', 'exp'],
    'education':    ['学历', '学历要求', 'education', 'degree'],
    'tags':         ['标签', '技能', '福利', '关键词', 'tags', 'skills'],
    'jd':           ['描述', '职位描述', '岗位描述', '职责', '任职要求', 'jd', 'description'],
    'hr_name':      ['hr', 'hr名称', '招聘者', '联系人', 'hr_name', 'recruiter'],
    'hr_active':    ['活跃', '活跃度', '最近活跃', 'hr_active', 'active'],
    'url':          ['链接', '详情', '详情链接', '岗位链接', 'url', 'link'],
    'published_at': ['发布时间', '发布', '更新日期', '发布日期', 'published_at', 'date', 'time'],
    'status':       ['状态', '投递状态', 'status', 'state'],
    'notes':        ['备注', '笔记', 'notes', 'note', 'comment'],
    'raw_id':       ['id', '编号', '职位id', 'raw_id'],
}

_LOOKUP = {}
for field, names in ALIASES.items():
    _LOOKUP[field] = field  # 规范字段名本身也要认，否则 JSON 里的 salary_raw 会被当成陌生列丢掉
    for n in names:
        _LOOKUP[n.strip().lower()] = field


def _map_key(k):
    if k is None:
        return None
    kk = str(k).strip().lower()
    if kk in _LOOKUP:
        return _LOOKUP[kk]
    # 模糊兜底：去掉常见修饰后再试
    kk2 = re.sub(r'[（(].*?[)）]', '', kk).strip()
    return _LOOKUP.get(kk2)


def _split_tags(v):
    if v is None:
        return []
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    s = str(v).strip()
    if not s:
        return []
    return [x.strip() for x in re.split(r'[,，、;；/|\s]{1,}', s) if x.strip()]


def normalize_item(raw, default_platform='other'):
    """把任意来源的一条记录映射成标准字段。"""
    item = {}
    for k, v in raw.items():
        f = _map_key(k)
        if not f:
            continue
        if v is None:
            continue
        if f == 'tags':
            item[f] = _split_tags(v)
        else:
            item[f] = str(v).strip()
    if 'platform' not in item or not item['platform']:
        item['platform'] = default_platform
    # 城市字段里常常写 "深圳-南山区"，拆一下
    if item.get('city') and not item.get('district'):
        parts = re.split(r'[-—·/、]', item['city'])
        if len(parts) >= 2:
            item['city'], item['district'] = parts[0].strip(), parts[1].strip()
    return item


def load_json(path):
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    if isinstance(data, dict):
        data = data.get('jobs') or data.get('data') or data.get('list') or []
    return [normalize_item(d) for d in data if isinstance(d, dict)]


def load_csv(path):
    with open(path, 'r', encoding='utf-8-sig', newline='') as f:
        rows = list(csv.DictReader(f))
    return [normalize_item(r) for r in rows]


def parse_text(text, default_platform='other'):
    """把纯文本表格粘进来。自动识别分隔符，第一行是表头就当表头用。"""
    lines = [l.rstrip() for l in text.strip().splitlines() if l.strip()]
    if not lines:
        return []

    def split_line(l):
        for sep in ('\t', '|', '｜', '，', ',', ';', '；'):
            if sep in l:
                return [c.strip() for c in l.split(sep)]
        return [c.strip() for c in re.split(r'\s{2,}', l)]

    rows = [split_line(l) for l in lines]
    width = max(len(r) for r in rows)
    if width < 2:
        return []

    header_mapped = [_map_key(c) for c in rows[0]]
    has_header = sum(1 for h in header_mapped if h) >= max(2, width // 2)

    out = []
    if has_header:
        for r in rows[1:]:
            if len(r) < 2:
                continue
            d = {}
            for i, h in enumerate(header_mapped):
                if h and i < len(r):
                    d[h] = r[i]
            out.append(normalize_item(d, default_platform))
    else:
        # 无表头，按最常见顺序猜：公司 岗位 薪资 城市
        guess = ['company', 'title', 'salary_raw', 'city', 'experience', 'education', 'url']
        for r in rows:
            d = {guess[i]: r[i] for i in range(min(len(r), len(guess)))}
            out.append(normalize_item(d, default_platform))
    return out


def load_any(path, default_platform='other'):
    ext = os.path.splitext(path)[1].lower()
    if ext == '.json':
        return load_json(path)
    if ext in ('.csv', '.tsv'):
        return load_csv(path)
    if ext in ('.txt', '.md'):
        with open(path, 'r', encoding='utf-8') as f:
            return parse_text(f.read(), default_platform)
    raise ValueError(f'不支持的文件类型：{ext}（支持 .json / .csv / .tsv / .txt）')
