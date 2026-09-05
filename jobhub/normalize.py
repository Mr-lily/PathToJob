# -*- coding: utf-8 -*-
"""字段标准化：把各平台五花八门的写法统一成可计算的格式。

只依赖 Python 标准库。
"""

import re

# ---------------------------------------------------------------- 薪资解析

_UNIT_MAP = {
    'k': 1000, 'K': 1000, '千': 1000,
    'w': 10000, 'W': 10000, '万': 10000,
}

# 15-25K / 1.5-2万 / 8000-12000 / 8~12千 / 15k-25k
_RANGE_RE = re.compile(
    r'(\d+(?:\.\d+)?)\s*([kKwW千万]?)\s*(?:[-~—－至到]+)\s*(\d+(?:\.\d+)?)\s*([kKwW千万]?)'
)
_SINGLE_RE = re.compile(r'(\d+(?:\.\d+)?)\s*([kKwW千万])(?![a-zA-Z\u4e00-\u9fa5])')
_MONTHS_RE = re.compile(r'(\d+(?:\.\d+)?)\s*薪')
_DAY_RE = re.compile(r'(\d+(?:\.\d+)?)\s*[-~至到]?\s*(\d+(?:\.\d+)?)?\s*元?\s*/\s*(天|日|小时|时)')
_DAY_SINGLE_RE = re.compile(r'(\d+(?:\.\d+)?)\s*元\s*/\s*(天|日|小时|时)')

WORK_DAYS_PER_MONTH = 21.75
HOURS_PER_MONTH = 21.75 * 8


def _apply_unit(num: str, unit: str):
    """把 '15' + 'k' 变成 15000。裸数字按常见习惯推断。"""
    try:
        v = float(num)
    except (TypeError, ValueError):
        return None
    if unit in _UNIT_MAP:
        return int(round(v * _UNIT_MAP[unit]))
    # 没有单位：小于 1000 的裸数字一律按 K 处理（"15" == 15K，这是招聘界的默认写法）
    return int(round(v * 1000)) if v < 1000 else int(round(v))


def parse_salary(text):
    """把薪资字符串解析成 (月薪下限, 月薪上限, 发薪月数)。

    支持：15-25K / 1.5-2万·15薪 / 8000-12000元 / 8-12千 / 200-300元/天 / 面议
    返回 (None, None, None) 表示解析不出（面议、空白等）。
    """
    if text is None:
        return (None, None, None)
    t = str(text).strip()
    if not t or t in ('面议', '薪资面议', '保密', '-', '无'):
        return (None, None, None)
    t = t.replace(' ', '').replace('／', '/').replace('／', '/')

    months = 12
    m = _MONTHS_RE.search(t)
    if m:
        try:
            months = int(float(m.group(1)))
        except ValueError:
            months = 12
    if '年终' in t or '分红' in t:
        pass  # 无法量化，忽略

    # 日薪 / 时薪 优先判断，避免被当成极低的月薪
    m = _DAY_RE.search(t)
    if m:
        lo = float(m.group(1))
        hi = float(m.group(2)) if m.group(2) else lo
        if '小时' in m.group(3) or '时' == m.group(3):
            return (int(round(lo * HOURS_PER_MONTH)), int(round(hi * HOURS_PER_MONTH)), months)
        return (int(round(lo * WORK_DAYS_PER_MONTH)), int(round(hi * WORK_DAYS_PER_MONTH)), months)

    m = _RANGE_RE.search(t)
    if m:
        unit_lo = m.group(2)
        unit_hi = m.group(4) or unit_lo  # 右边没写单位就沿用左边的
        if unit_hi and not unit_lo:
            unit_lo = unit_hi  # 反过来也要兜住：'20-40万' 左边的 20 同样是「万」
        lo = _apply_unit(m.group(1), unit_lo)
        hi = _apply_unit(m.group(3), unit_hi)
        if lo is not None and hi is not None:
            if lo > hi:
                lo, hi = hi, lo
            # 明显是年薪（如 20-40万且带"年"字）
            if '年' in t and ('万' in t or 'W' in t.lower()) and hi >= 100000:
                lo, hi = int(lo / 12), int(hi / 12)
            return (lo, hi, months)

    m = _SINGLE_RE.search(t)
    if m:
        v = _apply_unit(m.group(1), m.group(2))
        if v is not None:
            return (v, v, months)

    # 纯数字兜底
    nums = re.findall(r'\d+(?:\.\d+)?', t)
    if len(nums) >= 2:
        lo = _apply_unit(nums[0], '')
        hi = _apply_unit(nums[1], '')
        if lo is not None and hi is not None:
            if lo > hi:
                lo, hi = hi, lo
            return (lo, hi, months)
    return (None, None, None)


# ---------------------------------------------------------------- 经验

_EXP_BUCKETS = ['在校/应届', '应届生', '1年以内', '1-3年', '3-5年', '5-10年', '10年以上', '经验不限']
_EXP_RANK = {b: i for i, b in enumerate(_EXP_BUCKETS)}


def parse_experience(text):
    """归一化经验要求，返回 _EXP_BUCKETS 之一。"""
    if not text:
        return '经验不限'
    t = str(text).strip()
    if '不限' in t or '无经验' in t or not t or t == '-':
        return '经验不限'
    if '应届' in t or '在校' in t or '实习' in t:
        return '在校/应届'

    # 区间写法必须优先处理：'5-10年' 里的 10 是上限，
    # 若先做 '10年' in t 的子串判断，会被误判成「要求 10 年以上」。
    nums = re.findall(r'(\d+)\s*[-~至到]\s*(\d+)', t)
    if nums:
        lo, hi = int(nums[0][0]), int(nums[0][1])
        if hi <= 1:
            return '1年以内'
        if hi <= 3:
            return '1-3年'
        if hi <= 5:
            return '3-5年'
        if hi <= 10:
            return '5-10年'
        return '10年以上'

    # 明确写「X 年以上」时，X 是下限而不是上限：
    # 「10年以上」属于最高档，不能按上限逻辑压成「5-10年」。
    above = re.search(r'(\d+)\s*年以上', t)
    if above:
        n = int(above.group(1))
        if n < 1:
            return '1年以内'
        if n < 3:
            return '1-3年'
        if n < 5:
            return '3-5年'
        if n < 10:
            return '5-10年'
        return '10年以上'

    single = re.search(r'(\d+)\s*年', t)
    if single:
        n = int(single.group(1))
        if n <= 1:
            return '1年以内'
        if n <= 3:
            return '1-3年'
        if n <= 5:
            return '3-5年'
        if n <= 10:
            return '5-10年'
        return '10年以上'
    if '十年' in t:
        return '10年以上'
    if '1年以下' in t or '1年以内' in t:
        return '1年以内'
    return '经验不限'


def exp_rank(text):
    return _EXP_RANK.get(parse_experience(text), _EXP_RANK['经验不限'])


# ---------------------------------------------------------------- 学历

_EDU_BUCKETS = ['学历不限', '初中及以下', '中专/中技', '高中', '大专', '本科', '硕士', '博士']
_EDU_RANK = {b: i for i, b in enumerate(_EDU_BUCKETS)}
_EDU_ALIAS = {
    '不限': '学历不限', '初中': '初中及以下', '中专': '中专/中技', '中技': '中专/中技',
    '职高': '高中', '高中': '高中', '大专': '大专', '专科': '大专',
    '本科': '本科', '学士': '本科', '研究生': '硕士', '硕士': '硕士',
    'MBA': '硕士', '博士': '博士', '博士及以上': '博士',
}


def parse_education(text):
    if not text:
        return '学历不限'
    t = str(text).strip()
    for k, v in _EDU_ALIAS.items():
        if k in t:
            return v
    return '学历不限'


def edu_rank(text):
    return _EDU_RANK.get(parse_education(text), 0)


# ---------------------------------------------------------------- 公司名 / 岗位名 归一化

_COMPANY_SUFFIX = re.compile(
    r'(股份有限公司|有限责任公司|有限公司|集团公司|集团|公司|'
    r'科技|技术|网络|信息|信息技术|软件|数据|智能|'
    r'（[^）]*）|\([^)]*\)|\s)+$'
)


def norm_company(name):
    """公司名归一化（轻度）：去括号、去空格、去尾部企业后缀。用于展示与索引。"""
    if not name:
        return ''
    s = str(name).strip()
    s = re.sub(r'\s+', '', s)
    s = re.sub(r'[（(].*?[)）]', '', s)
    s = _COMPANY_SUFFIX.sub('', s)
    return s.strip('·-—_ ')


# 城市前缀：'深圳市云枢科技' 和 '云枢科技（深圳）' 是同一家，前缀要抹掉
_CITY_PREFIX = re.compile(
    r'^(北京|上海|天津|重庆|广州|深圳|东莞|佛山|珠海|中山|惠州|汕头|江门|湛江|'
    r'杭州|南京|苏州|无锡|宁波|温州|嘉兴|常州|南通|徐州|'
    r'成都|武汉|西安|长沙|郑州|青岛|济南|合肥|福州|厦门|南昌|昆明|贵阳|南宁|太原|石家庄|'
    r'大连|沈阳|长春|哈尔滨|兰州|海口|三亚|扬州|镇江|绍兴|泉州|烟台|潍坊|洛阳|唐山|'
    r'香港|澳门|台湾)(市|省|地区)?'
)

# 通用行业词：这些词在不同平台上写法不一，去掉后剩下的才是品牌名
_GENERIC_TOKENS = [
    '股份有限公司', '有限责任公司', '有限公司', '集团有限公司', '集团公司',
    '信息技术', '电子商务', '文化传播', '资产管理', '系统集成', '互联网',
    '计算机', '供应链', '自动化', '通信', '软件', '科技', '技术', '网络',
    '信息', '数据', '智能', '数字', '电子', '实业', '贸易', '服务', '咨询',
    '管理', '发展', '文化', '传媒', '物流', '医疗', '健康', '教育', '投资',
    '资产', '资本', '产业', '建设', '工程', '机电', '系统', '股份', '集团', '控股',
    '有限', '责任', '公司',
]


def norm_company_core(name):
    """公司名归一化（激进）：再抹掉城市前缀和通用行业词，得到品牌核心词。

    '深圳市货拉拉科技有限公司' 和 '货拉拉（深圳）科技控股有限公司' 都会变成 '货拉拉'。
    跨平去重靠的就是这个。
    """
    if not name:
        return ''
    s = norm_company(name)
    if not s:
        return ''
    s = _CITY_PREFIX.sub('', s)
    changed = True
    while changed and s:
        changed = False
        for t in _GENERIC_TOKENS:
            if s != t and t in s:
                s = s.replace(t, '')
                changed = True
    s = s.strip('·-—_ ()（）')
    # 别把名字削没了，削没了就退回轻度归一化
    return s if len(s) >= 2 else norm_company(name)


def similar(a, b, threshold=0.75):
    """两个字符串的相似度，用于兜住 'Java 高级开发' vs '高级 Java 开发' 这类词序差异。"""
    from difflib import SequenceMatcher
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def norm_title(name):
    """岗位名归一化：去括号内容、去空格、去末尾的急招/高薪等营销词。"""
    if not name:
        return ''
    s = str(name).strip()
    s = re.sub(r'[（(].*?[)）]', '', s)
    s = re.sub(r'\s+', '', s)
    s = re.sub(r'(急招|急聘|高薪|诚聘|热招|直招|急|!|！)+$', '', s)
    return s


def norm_city(text):
    if not text:
        return ''
    s = str(text).strip()
    # "深圳-南山区" -> 取第一段
    s = re.split(r'[-·/、,，\s]', s)[0]
    s = re.sub(r'(市|地区)$', '', s)
    return s


def parse_hr_active(text):
    """HR 活跃度 -> 0-3 分。"""
    if not text:
        return 0
    t = str(text)
    if '刚刚' in t or '1分钟' in t or '半小时内' in t:
        return 3
    if '今日' in t or '今天' in t or '小时内' in t:
        return 2
    if '3日内' in t or '本周' in t or '近期' in t:
        return 1
    return 0


def salary_text(job):
    """统一的薪资展示文本：22-35K·15薪 / 4.4-6.5K / 面议。"""
    lo, hi = job.get('salary_min'), job.get('salary_max')
    if lo is None and hi is None:
        return job.get('salary_raw') or '面议'

    def f(v):
        if v is None:
            return '?'
        k = v / 1000
        # 只有非整 K 时才保留小数（4.4K），否则写成 "7-11K" 而不是 "7.0-11.0K"
        return f'{k:.1f}' if abs(k - round(k)) > 1e-6 else f'{round(k)}'

    s = f'{f(lo)}K' if lo == hi else f'{f(lo)}-{f(hi)}K'
    m = job.get('salary_months') or 12
    return f'{s}·{m}薪' if m != 12 else s


def parse_freshness(published_at, today=None):
    """发布时间新鲜度 -> 0-3 分。today 为 datetime.date。"""
    import datetime
    if today is None:
        today = datetime.date.today()
    if not published_at:
        return 1
    s = str(published_at)
    if '刚刚' in s or '今天' in s:
        return 3
    if '昨天' in s:
        return 2
    m = re.search(r'(\d+)\s*(天|日)前', s)
    if m:
        n = int(m.group(1))
        return 3 if n <= 1 else (2 if n <= 3 else (1 if n <= 14 else 0))
    m = re.search(r'(\d{4})[-/](\d{1,2})[-/](\d{1,2})', s)
    if m:
        try:
            d = datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            delta = (today - d).days
            if delta <= 1:
                return 3
            if delta <= 3:
                return 2
            if delta <= 14:
                return 1
            return 0
        except ValueError:
            return 1
    return 1


if __name__ == '__main__':
    cases = [
        '15-25K', '15-25K·15薪', '1.5-2万', '8000-12000元', '8-12千',
        '200-300元/天', '15k-25k·13薪', '面议', '20-40万/年', '20-30K·16薪',
    ]
    for c in cases:
        print(f'{c!r:20} -> {parse_salary(c)}')
