# -*- coding: utf-8 -*-
"""匹配度打分：0-100 分，并把每一项的得分拆开存起来，方便你知道它为什么高分/低分。

没有配置的维度按中性分（0.5）处理，不会因为没填就误杀岗位。
"""

import re

from . import normalize as N


def _overlap(job_min, job_max, exp_min, exp_max):
    """岗位薪资与期望薪资区间的契合度，0-1。"""
    if job_min is None or job_max is None:
        return None
    if not exp_min or not exp_max:
        return 0.5
    if job_max < exp_min:
        # 达不到期望，按缺口大小衰减
        gap = (exp_min - job_max) / max(exp_min, 1)
        return max(0.0, 1 - gap)
    if job_min >= exp_max:
        return 1.0
    overlap = min(job_max, exp_max) - max(job_min, exp_min)
    span = max(exp_max - exp_min, 1)
    return 0.6 + 0.4 * max(0.0, overlap) / span


def _title_score(title, targets):
    if not targets:
        return 0.5, '未配置目标岗位，按中性分计'
    t = (title or '').lower()
    for kw in targets:
        if str(kw).lower() in t:
            return 1.0, f'命中目标岗位「{kw}」'
    # 退而求其次：看有没有共同关键词
    title_chars = set(re.findall(r'[a-zA-Z\u4e00-\u9fa5]+', t))
    for kw in targets:
        kw_low = str(kw).lower()
        for tok in re.findall(r'[a-zA-Z\u4e00-\u9fa5]+', kw_low):
            if len(tok) >= 2 and tok in title_chars:
                return 0.6, f'部分匹配「{kw}」'
    return 0.1, '与目标岗位不匹配'


def _keyword_score(job, must, nice):
    if not must and not nice:
        return 0.5, '未配置关键词，按中性分计'
    text = ' '.join([
        job.get('title') or '', job.get('jd') or '',
        ' '.join(job.get('tags') or [])
    ]).lower()
    hits, misses = [], []
    base = 0.5
    if must:
        for kw in must:
            (hits if str(kw).lower() in text else misses).append(kw)
        ratio = len(hits) / max(len(must), 1)
        base = ratio
        if not hits:
            return 0.0, f'必备技能全部缺失：{", ".join(must)}'
    bonus = 0.0
    nice_hits = [k for k in (nice or []) if str(k).lower() in text]
    if nice:
        bonus = 0.3 * (len(nice_hits) / max(len(nice), 1))
    final = min(1.0, base + bonus)
    parts = []
    if must:
        parts.append(f'必备命中 {len(hits)}/{len(must)}')
    if nice_hits:
        parts.append(f'加分项命中 {", ".join(nice_hits)}')
    return final, ('；'.join(parts) or '无关键词命中')


def _experience_score(job_exp, user_exp):
    if not user_exp:
        return 0.5, '未配置你的经验，按中性分计'
    u, j = N.exp_rank(user_exp), N.exp_rank(job_exp)
    if j == N._EXP_RANK['经验不限']:
        return 1.0, '经验不限'
    if j <= u:
        return 1.0, f'经验要求（{job_exp}）未超出你的水平'
    diff = j - u
    return max(0.0, 1 - 0.3 * diff), f'经验要求（{job_exp}）高于你的水平，难度较大'


def _education_score(job_edu, user_edu):
    if not user_edu:
        return 0.5, '未配置学历，按中性分计'
    u, j = N.edu_rank(user_edu), N.edu_rank(job_edu)
    if j == 0:
        return 1.0, '学历不限'
    if j <= u:
        return 1.0, '学历达标'
    return 0.2, f'学历要求（{job_edu}）高于你'


def _location_score(city, district, cities, districts):
    if not cities:
        return 0.7, '未配置目标城市'
    cn = N.norm_city(city)
    if cn not in [N.norm_city(c) for c in cities]:
        return 0.0, f'城市（{city}）不在目标范围内'
    if districts and district:
        if any(d in district for d in districts):
            return 1.0, f'位于偏好区域（{district}）'
        return 0.75, f'城市符合，但 {district} 不在偏好区域'
    return 0.85, f'城市符合（{city}）'


def score_job(job, cfg):
    """给单个职位打分。返回 (总分 0-100, 明细 dict)。"""
    p = cfg.get('profile', {})
    w = cfg.get('weights', {})
    filters = cfg.get('filters', {})
    thr = cfg.get('thresholds', {})

    detail = {}

    lo, hi, months = job.get('salary_min'), job.get('salary_max'), job.get('salary_months') or 12
    s_sal = _overlap(lo, hi, p.get('expect_salary_min'), p.get('expect_salary_max'))
    if s_sal is None:
        s_sal = 0.4
        detail['salary'] = (0.4, '薪资面议，按偏低估计')
    else:
        # 高发薪月数折算成年薪优势，小幅加分
        if months and months > 12:
            s_sal = min(1.0, s_sal * (1 + 0.03 * (months - 12)))
        detail['salary'] = (s_sal, f'{lo}-{hi} 元/月 · {months}薪')

    detail['title'] = _title_score(job.get('title'), p.get('target_titles'))
    detail['keyword'] = _keyword_score(job, p.get('must_have_keywords'), p.get('nice_to_have_keywords'))
    detail['experience'] = _experience_score(job.get('experience'), p.get('experience'))
    detail['education'] = _education_score(job.get('education'), p.get('education'))
    detail['location'] = _location_score(job.get('city'), job.get('district'),
                                         p.get('cities'), p.get('preferred_districts'))
    fs = job.get('freshness_score') or 1
    detail['freshness'] = (fs / 3.0, ['较久以前', '两周内', '三天内', '最近一天内'][min(fs, 3)])
    ha = job.get('hr_active_score') or 0
    detail['hr_active'] = (ha / 3.0, ['HR 不活跃', 'HR 本周活跃', 'HR 今日活跃', 'HR 刚刚活跃'][min(ha, 3)])

    total_w = sum(w.get(k, 0) for k in detail)
    raw = sum(w.get(k, 0) * detail[k][0] for k in detail)
    score = round(raw / total_w * 100, 1) if total_w else 0.0

    # ---------- 排除项：直接判定，不看权重 ----------
    excl = []
    hay = ' '.join([job.get('company') or '', job.get('title') or '', job.get('jd') or ''])
    for kw in filters.get('exclude_keywords', []):
        if str(kw) in hay:
            excl.append(f'命中排除词「{kw}」')
    for c in filters.get('exclude_companies', []):
        if c and N.norm_company(c) and N.norm_company(c) in N.norm_company(job.get('company') or ''):
            excl.append(f'命中排除公司「{c}」')
    if excl:
        # 命中排除词基本等于不用看了，直接打到地板
        score = round(score * 0.15, 1)

    # ---------- 硬门槛 ----------
    # 城市通常是硬性的：光扣权重不行，异地岗位其他维度高分时照样能排到 70+，
    # 会浪费你一次投递。这里单独打折，不和排除项叠加。
    flags = list(excl)
    hard = cfg.get('hard_filters', {})
    if hard.get('location', True) and p.get('cities') and not excl:
        targets = [N.norm_city(c) for c in p['cities']]
        if N.norm_city(job.get('city')) not in targets:
            score = round(score * 0.35, 1)
            flags.append(f'城市不符：{job.get("city") or "未知"}（目标：{"、".join(p["cities"])}）')
    if hard.get('experience', True) and p.get('experience') and not excl:
        u = N.exp_rank(p['experience'])
        j = N.exp_rank(job.get('experience'))
        # '经验不限' 不算不符；其余只要岗位要求高于自己的年限，就是硬伤：
        # 年限差一年以上，HR 筛简历时基本过不了，光扣权重会被薪资高分盖过去。
        if j != N._EXP_RANK['经验不限'] and j > u:
            score = round(score * 0.5, 1)
            flags.append(f'经验门槛不符：要求 {job.get("experience") or "未知"}，你约 {p["experience"]}')
    if hard.get('education', False) and p.get('education') and not excl:
        if N.edu_rank(job.get('education')) > N.edu_rank(p['education']):
            score = round(score * 0.4, 1)
            flags.append(f'学历硬门槛不符：要求 {job.get("education")}')

    strong = thr.get('strong', 75)
    consider = thr.get('consider', 55)
    tier = 'strong' if score >= strong else ('consider' if score >= consider else 'weak')

    return score, {
        'score': score,
        'tier': tier,
        'flags': flags,
        'breakdown': {k: {'ratio': round(v[0], 3), 'weight': w.get(k, 0), 'note': v[1]}
                      for k, v in detail.items()},
    }


def score_all(jobs, cfg):
    for j in jobs:
        s, detail = score_job(j, cfg)
        j['score'] = s
        j['score_detail'] = detail
    jobs.sort(key=lambda x: (x.get('score') or 0, x.get('salary_max') or 0), reverse=True)
    return jobs
