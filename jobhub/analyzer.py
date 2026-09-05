# -*- coding: utf-8 -*-
"""岗位深度分析生成器：调用 DeepSeek 为岗位生成贰贰风格的深度分析。

输出格式与看板 parts() 解析对齐：
  【岗位实际内容】...
  【岗位适配情况】...
  【公司经营状况+行业机会】...
  【面试攻略】...
  【总结判断】...

配置（config.json）：
  "llm": {
    "api_key": "sk-...",
    "base_url": "https://api.deepseek.com",
    "model": "deepseek-chat"
  }
"""
import json
import os
import urllib.request
import urllib.error

# 看板识别的段落标题（titleName() 会映射到展示名）
SECTIONS = [
    '岗位实际内容',
    '岗位适配情况',
    '公司经营状况+行业机会',
    '面试攻略',
    '总结判断',
    '适配指数',
]

def _system(cfg):
    """系统提示词：从 config profile 动态取求职者姓名/角色，不再写死。"""
    name = ((cfg.get('profile') or {}).get('name')) or '求职者'
    return (
        f'你是求职顾问「贰贰」，专门为求职者{name}做电商运营岗位的深度分析。'
        '你会结合他的真实简历、求职画像和岗位 JD，给出直接、有主见、中文的分析。'
        '不写套话，不堆形容词，每条都要落到具体事实。'
    )


def _profile_block(cfg):
    """从 config profile 动态生成【求职者画像】文本（目标/城市/薪资/经验/学历/动机）。"""
    p = cfg.get('profile') or {}
    name = p.get('name') or '求职者'
    cities = '、'.join(p.get('cities') or []) or '未指定'
    titles = '、'.join(p.get('target_titles') or []) or '未指定'
    sal_min = p.get('expect_salary_min')
    sal_max = p.get('expect_salary_max')
    def _k(v):
        return None if v is None else (f'{v//1000}K' if v % 1000 == 0 else str(v))
    smin, smax = _k(sal_min), _k(sal_max)
    sal = f"{smin}-{smax}" if (smin or smax) else '未指定'
    exp = p.get('experience') or '不限'
    edu = p.get('education') or '不限'
    mot = (p.get('motivation') or '').strip()
    lines = [
        '【求职者画像】',
        f'- 姓名：{name}',
        f'- 求职目标城市：{cities}；目标岗位：{titles}；期望薪资：{sal}',
        f'- 经验：{exp}；学历：{edu}',
    ]
    if mot:
        lines.append(f'- 求职动机：{mot}')
    return '\n'.join(lines)

_USER_TEMPLATE = """{profile}

【{name}完整简历】
{resume}

【岗位信息】
{job_json}

【规则基准分】
系统已按硬性维度对该岗位打了基准分（0-100）：{base_score}
各维度得分参考：
{base_breakdown}

【要求】
基于真实经历，分析这个岗位的适配度，并给出软性微调。

输出分5段，每段以「【】」开头占一行，正文用简洁中文（可用 - 列表、**加粗**）。**注意：【岗位适配情况】必须完整、详细地展开**——把{name}的工作经历逐条和岗位要求对照，写明匹配点+不匹配点+风险+结论，不要因为系统已算过基准分就略写这一整段。

【岗位实际内容】一句话总结岗位真实工作，再列2-4条核心职责
【岗位适配情况】完整详细：①匹配点（结合{name}的工作经历逐条说明）②不匹配点/硬伤（明说）③薪资与期望对比 ④竞争难度（结合岗位要求/薪资带宽/公司吸引力判断"好不好拿下"，写清理由） ⑤结论（值得投/观望/不投）
【公司经营状况+行业机会】这家公司/行业对{name}意味着什么，值不值得去
【面试攻略】针对这个岗位给3-5条具体面试准备建议（要结合他的实战操盘经历）
【总结判断】三行内结论：投/观望/不投 + 理由

最后额外输出两行（不要放在段落里，独立成行）：
【适配微调】给出一个整数（-5 到 +5），代表你基于**软性因素**（公司平台、成长空间、岗位真实性、是否契合他实战）对基准分的**小幅**调整：
- 正数（1~5）：软性加分（如公司平台大、岗位真实操盘空间大、成长快）
- 负数（-5~-1）：软性扣分（如公司是小中介/代运营、岗位是纯执行没成长、行业下滑、明显不匹配）
- 0：软性中性
注意：硬性维度（薪资/关键词/经验/学历/城市）系统已算进基准分，**你只调软性差异，幅度务必小**，不要大幅改写基准分。并在同一行用"理由：..."说明为什么这么调。

【求职难度】只输出一个 0-100 的整数（不要写理由，理由已写进上面的"岗位适配情况④竞争难度"）：
综合岗位要求（经验年限、学历门槛、行业要求）、薪资带宽（越高竞争越大）、公司吸引力（大厂/知名更难）、岗位热度。90+ 极难 / 70-89 难 / 40-69 中等 / 20-39 容易 / 19- 很容易。

要求：直接、有主见、不套话。全文不写"您好/祝您"等客套。"""


def _read_resume(root):
    p = os.path.join(root, 'data', 'resume.txt')
    try:
        with open(p, encoding='utf-8') as f:
            return f.read()
    except Exception:
        return ''


def _with_profile(cfg, profile):
    """返回一个用指定 profile 替换后的 cfg 副本（不影响原 cfg）。profile 为 None 则原样返回。"""
    if profile is None:
        return cfg
    import copy
    c = copy.deepcopy(cfg)
    c['profile'] = profile
    return c


def _slim_job(job):
    """只传白名单字段，避免塞无关数据。"""
    return {k: job.get(k) for k in
            ('company', 'title', 'salary_raw', 'city', 'district', 'experience',
             'education', 'jd', 'address', 'tags', 'hr_name') if job.get(k)}


def _call_llm(cfg, user_text, system=None):
    llm = cfg.get('llm') or {}
    api_key = llm.get('api_key') or ''
    base = (llm.get('base_url') or 'https://api.deepseek.com').rstrip('/')
    model = llm.get('model') or 'deepseek-chat'
    if not api_key:
        return None, '未配置 llm.api_key（config.json）'
    sys_prompt = system if system is not None else _system(cfg)
    payload = {
        'model': model,
        'messages': [
            {'role': 'system', 'content': sys_prompt},
            {'role': 'user', 'content': user_text},
        ],
        'temperature': 0.7,
        'max_tokens': 1800,
    }
    req = urllib.request.Request(
        base + '/chat/completions',
        data=json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + api_key},
        method='POST')
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            data = json.loads(r.read().decode('utf-8'))
        text = data['choices'][0]['message']['content'].strip()
        return text, None
    except urllib.error.HTTPError as e:
        return None, f'LLM HTTP {e.code}: {e.read().decode("utf-8", "ignore")[:300]}'
    except Exception as e:
        return None, f'LLM 调用失败: {e}'


def analyze(job, cfg, root, base_score=None, base_breakdown=None, profile=None, resume=None):
    """生成岗位深度分析。返回 (text, err)。text 为 None 表示失败。

    base_score / base_breakdown：规则基准分（0-100）及各维度明细，供 AI 参考作软性微调。
    profile / resume：多用户模式下覆盖该用户的画像与简历（None 则用 config + data/resume.txt）。
    """
    cfg = _with_profile(cfg, profile)
    resume = resume if resume is not None else _read_resume(root)
    name = ((cfg.get('profile') or {}).get('name')) or '求职者'
    bs = '' if base_score is None else str(base_score)
    bd = '' if not base_breakdown else str(base_breakdown)
    user = (_USER_TEMPLATE
            .replace('{profile}', _profile_block(cfg))
            .replace('{name}', name)
            .replace('{resume}', resume or '(无简历)')
            .replace('{job_json}', json.dumps(_slim_job(job), ensure_ascii=False, indent=2))
            .replace('{base_score}', bs or '(未提供)')
            .replace('{base_breakdown}', bd or '(未提供)'))
    return _call_llm(cfg, user, system=_system(cfg))


def parse_delta(text):
    """从分析文本里提取适配微调值（-5 ~ +5 整数）。提取不到返回 None。"""
    if not text:
        return None
    import re
    m = re.search(r'【适配微调】\s*([-+]?\d{1,2})', text)
    if m:
        v = int(m.group(1))
        return max(-5, min(5, v))
    # 兼容正文里"适配微调：+5"等写法
    m = re.search(r'适配微调\s*[:：]?\s*([-+]?\d{1,2})', text)
    if m:
        v = int(m.group(1))
        return max(-5, min(5, v))
    return None


def parse_difficulty(text):
    """从分析文本里提取求职难度（0-100 整数）。提取不到返回 None。"""
    if not text:
        return None
    import re
    m = re.search(r'【求职难度】\s*(\d{1,3})', text)
    if m:
        v = int(m.group(1))
        return max(0, min(100, v))
    m = re.search(r'求职难度\s*[:：]?\s*(\d{1,3})', text)
    if m:
        v = int(m.group(1))
        return max(0, min(100, v))
    # 兼容"数字 | 理由" 行首格式（评估难度的独立调用输出）
    m = re.search(r'(?:^|\n)\s*(\d{1,3})\s*[|｜]', text)
    if m:
        v = int(m.group(1))
        return max(0, min(100, v))
    return None


def parse_difficulty_reason(text):
    """从分析文本里提取求职难度的理由说明。提取不到返回空。"""
    if not text:
        return ''
    import re
    m = re.search(r'【求职难度】\s*\d{1,3}\s*[|｜]\s*(.+)', text, re.S)
    if m:
        return m.group(1).strip()
    # 兼容旧格式："45（理由：xxx）"
    m = re.search(r'【求职难度】\s*\d{1,3}\s*[（(]理由[：:]\s*(.+)', text, re.S)
    if m:
        return m.group(1).replace('）', '').replace(')', '').strip()
    # 兼容"求职难度：N 理由：xxx"
    m = re.search(r'求职难度\s*[:：]?\s*\d{1,3}\s*[理由：:\s]*([^\n【]+)', text, re.S)
    if m:
        return m.group(1).strip()
    return ''


_DIFF_PROMPT = """你是求职顾问「贰贰」。请只评估下面这个岗位对{name}的【求职难度/竞争程度】，不需要做长分析。

{profile}

岗位：
{job_json}

输出一行，格式：数字 | 完整理由
- 数字（0-100）：综合岗位要求(经验年限/学历/行业门槛)、薪资带宽(越高竞争越大)、公司吸引力(大厂/知名更难)、岗位热度，代表"好不好拿下"：90+ 极难 / 70-89 难 / 40-69 中等 / 20-39 容易 / 19- 很容易。
- 完整理由：写清楚为什么给这个分数，结合{name}背景与岗位差距，务必写完整到句号，不要中途断开。

例如：40 | 岗位要求"经验不限"，门槛低，薪资6-8K吸引力一般，竞争对手主要是应届生，你的经历背景明显优于平均水平，拿下概率较高，因此难度中等偏低。"""


def estimate_difficulty(job, cfg, root, profile=None, resume=None):
    """轻量调用：只让 AI 估算求职难度（0-100 + 理由），不生成深度分析。返回 (diff, err)。"""
    cfg = _with_profile(cfg, profile)
    resume = resume if resume is not None else _read_resume(root)
    name = ((cfg.get('profile') or {}).get('name')) or '求职者'
    user = (_DIFF_PROMPT
            .replace('{profile}', _profile_block(cfg))
            .replace('{name}', name)
            .replace('{resume}', resume or '(无简历)')
            .replace('{job_json}', json.dumps(_slim_job(job), ensure_ascii=False, indent=2)))
    text, err = _call_llm(cfg, user, system=_system(cfg))
    if err:
        return None, err
    return parse_difficulty(text), None


def parse_fit_score(text):
    """兼容旧版：从分析文本里提取适配指数（0-100）。新流程不再用，保留供回退。"""
    if not text:
        return None
    import re
    m = re.search(r'【适配指数】\s*(\d{1,3})', text)
    if m:
        v = int(m.group(1))
        return max(0, min(100, v))
    m = re.search(r'适配指数\s*[:：]\s*(\d{1,3})\s*(?:/100)?', text)
    if m:
        v = int(m.group(1))
        return max(0, min(100, v))
    return None


_DEEP_PROMPT = """你是求职顾问「贰贰」。BOSS {name}把下面这个岗位标记为【重点】，需要你对他做**深入专项分析**，帮他做决策。

【{name}简历】
{resume}

【岗位信息】
{job_json}

【已有的初筛分析（供参考，不必重复）】
{base_analysis}

【要求】
基于{name}的真实经历和这个岗位，输出三段深入分析，每段以「【】」开头占一行，正文用简洁中文（可用 - 列表、**加粗**）：
【一对一岗位深度拆解】把岗位JD逐条拆开，讲清每一条实际要做什么、做到什么程度才合格，以及{name}能不能做、差距在哪。要具体、能落地。
【公司尽调与考察】结合已知信息分析这家公司：规模/阶段/行业地位/风险（看公司名、行业、职位描述推断，不编造）。给出面试时值得问的几个关键问题。
【面试准备策略】针对这个岗位，给{name}一套可操作的备战方案：①如何把工作经历翻译成该岗语言 ②要补的知识盲区 ③1-2个可能被问到的棘手问题及应对思路 ④谈薪策略。

要求：直接、有主见、不套话，每段都要结合{name}真实经历，别空泛。"""


def deep_analyze(job, cfg, root, base_analysis='', profile=None, resume=None):
    """给重点岗位生成深入专项分析。返回 (text, err)。"""
    cfg = _with_profile(cfg, profile)
    resume = resume if resume is not None else _read_resume(root)
    name = ((cfg.get('profile') or {}).get('name')) or '求职者'
    user = (_DEEP_PROMPT
            .replace('{name}', name)
            .replace('{resume}', resume or '(无简历)')
            .replace('{job_json}', json.dumps(_slim_job(job), ensure_ascii=False, indent=2))
            .replace('{base_analysis}', (base_analysis or '')[:2000]))
    return _call_llm(cfg, user, system=_system(cfg))