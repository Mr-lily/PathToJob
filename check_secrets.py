# -*- coding: utf-8 -*-
"""隐私自检：扫描项目里可能泄漏的敏感信息。

用法：
  python check_secrets.py                 # 扫描整个项目
  python check_secrets.py <目录>          # 只扫某个目录/文件

检出：DeepSeek/OpenAI 风格 key、32位hex(高德key)、API token、IPv4 地址，
外加 gitignore 的 secrets_known.txt 里的"已知敏感值"精确匹配。

退出码：0 = 干净；1 = 发现可疑项。
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))

PATTERNS = [
    ('DeepSeek/OpenAI key', re.compile(r'\bsk-[A-Za-z0-9_\-]{10,}\b')),
    ('32位hex(高德key)', re.compile(r'\b[0-9a-fA-F]{32}\b')),
    ('API token(xintu-)', re.compile(r'\bxintu-[0-9a-fA-F]{6,}\b')),
    ('IPv4 地址', re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b')),
    ('疑似密码字段', re.compile(r'\b(?:password|passwd|pwd|secret)\s*[=:]\s*\S+', re.I)),
]

_IP = re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b')


def _is_private_ip(ip):
    """本地/私有/保留地址不算泄漏，跳过。"""
    if ip.startswith('127.') or ip.startswith('0.') or ip == '255.255.255.255':
        return True
    if ip.startswith('10.') or ip.startswith('192.168.') or ip.startswith('169.254.'):
        return True
    parts = ip.split('.')
    if parts[0] == '172':
        try:
            if 16 <= int(parts[1]) <= 31:
                return True
        except ValueError:
            pass
    return False

EXCLUDE_DIRS = {'data', '.venv', 'venv', '__pycache__', '.git', '.workbuddy',
                'node_modules', 'dist', 'build'}


def load_known():
    known = []
    p = os.path.join(ROOT, 'secrets_known.txt')
    if os.path.exists(p):
        for line in open(p, encoding='utf-8'):
            s = line.strip()
            if s and not s.startswith('#'):
                known.append(s)
    return known


def scan(target, known):
    hits = []
    if os.path.isfile(target):
        targets = [target]
    else:
        targets = []
        for root, dirs, files in os.walk(target):
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
            for fn in files:
                targets.append(os.path.join(root, fn))
    for fp in targets:
        if os.path.basename(fp) in ('secrets_known.txt',):
            continue
        try:
            content = open(fp, encoding='utf-8', errors='ignore').read()
        except Exception:
            continue
        rel = os.path.relpath(fp, ROOT)
        for label, rx in PATTERNS:
            for m in rx.finditer(content):
                if label == 'IPv4 地址' and _is_private_ip(m.group(0)):
                    continue
                hits.append((rel, label, m.group(0)))
        for k in known:
            if k in content:
                hits.append((rel, '已知敏感值', k))
    return hits


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else ROOT
    known = load_known()
    hits = scan(target, known)
    if not hits:
        print('未发现可疑信息（干净）。')
        return 0
    # 去重 + 汇总
    seen = {}
    for rel, label, val in hits:
        seen.setdefault((rel, label), []).append(val)
    print('发现 %d 处可疑信息，可能泄漏隐私：' % len(hits))
    for (rel, label), vals in sorted(seen.items()):
        print('  %s  [%s]  例: %s' % (rel, label, vals[0]))
    print('提示：若这些文件要公开/分享/推送，请先清洗，或确认已被 .gitignore 排除。')
    return 1


if __name__ == '__main__':
    sys.exit(main())
