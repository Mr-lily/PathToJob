# -*- coding: utf-8 -*-
"""薪途 PathToJob 引导助手

在新电脑上跑通整个工具：检测 Python → 补依赖 → 配 API Key → 启动看板。
同时兼容"已配好的机器"直接一键启动。

用法（任选其一）：
  python bootstrap.py            # 交互菜单
  python bootstrap.py check      # 只做环境检查报告
  python bootstrap.py setup      # 一次性引导（依赖 + 配置 + 启动）
  python bootstrap.py serve      # 直接启动看板（缺依赖/配置时引导补齐）
  python bootstrap.py stop       # 停止后台服务
"""
import json
import os
import subprocess
import sys
import time
import webbrowser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # job-hub/
CONFIG = os.path.join(ROOT, 'config.json')
DATA = os.path.join(ROOT, 'data')
RUN_PY = os.path.join(ROOT, 'run.py')
VENV_DIR = os.path.join(ROOT, '.venv')
EXT_DIR = os.path.join(ROOT, 'extension', 'bossdive')
RESUME = os.path.join(DATA, 'resume.txt')
DB = os.path.join(DATA, 'jobs.db')

def _read_cfg():
    with open(CONFIG, encoding='utf-8') as f:
        return json.load(f)


def _write_cfg(cfg):
    with open(CONFIG, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def _port():
    try:
        p = _read_cfg().get('serve_port')
        if p:
            return int(p)
    except Exception:
        pass
    return 8765


def _resume_python():
    """简历解析用的解释器：config runtime.venv_python → 项目 .venv → 当前解释器。"""
    try:
        vp = (_read_cfg().get('runtime') or {}).get('venv_python') or ''
        if vp and os.path.exists(vp):
            return vp
    except Exception:
        pass
    for c in (os.path.join(VENV_DIR, 'Scripts', 'python.exe'),
              os.path.join(VENV_DIR, 'bin', 'python'),
              os.path.join(VENV_DIR, 'Scripts', 'python')):
        if os.path.exists(c):
            return c
    return sys.executable


def _import_ok():
    try:
        import pypdf  # noqa
        import docx  # noqa
        return True
    except Exception:
        return False


def check_deps():
    """返回 (ok, 描述)。检查简历解析依赖 pypdf / python-docx 是否可用。"""
    py = _resume_python()
    if py == sys.executable:
        return _import_ok(), ('当前解释器' if _import_ok() else '当前解释器缺 pypdf/python-docx')
    try:
        r = subprocess.run([py, '-c', 'import pypdf,docx'], capture_output=True, text=True)
        if r.returncode == 0:
            return True, os.path.basename(py)
    except Exception:
        pass
    return False, os.path.basename(py) + ' 缺 pypdf/python-docx'


def ensure_deps(interactive=True):
    """确保简历解析依赖可用。优先装到当前解释器，失败则创建项目 .venv 装。"""
    ok, detail = check_deps()
    if ok:
        print('  [依赖] 简历解析 OK（%s）' % detail)
        return True
    print('  [依赖] 缺少 pypdf / python-docx（用于 PDF/Word 简历解析）')
    # 1) 尝试直接装到当前解释器
    try:
        r = subprocess.run([sys.executable, '-m', 'pip', 'install', '--quiet',
                            'pypdf', 'python-docx'], capture_output=True, text=True)
        if r.returncode == 0 and _import_ok():
            print('  [依赖] 已装到当前解释器。')
            return True
    except Exception:
        pass
    # 2) 创建项目 .venv
    if not interactive:
        print('  [依赖] 自动安装失败，请运行：python bootstrap.py setup')
        return False
    if not os.path.exists(VENV_DIR):
        print('  [依赖] 正在创建项目虚拟环境 .venv ...')
        r = subprocess.run([sys.executable, '-m', 'venv', VENV_DIR],
                           capture_output=True, text=True)
        if r.returncode != 0:
            print('  [依赖] .venv 创建失败：%s' % (r.stderr or r.stdout or '').strip()[:200])
            return False
    vpy = _resume_python()
    print('  [依赖] 正在向 .venv 安装 pypdf / python-docx ...')
    r = subprocess.run([vpy, '-m', 'pip', 'install', '--quiet', 'pypdf', 'python-docx'],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print('  [依赖] 安装失败：%s' % (r.stderr or r.stdout or '').strip()[:200])
        return False
    cfg = _read_cfg()
    cfg.setdefault('runtime', {})['venv_python'] = vpy
    _write_cfg(cfg)
    print('  [依赖] 就绪，已写入 config runtime.venv_python = %s' % vpy)
    return True


def check_config():
    """返回缺失/待填的配置项列表 [(key, 说明), ...]。"""
    cfg = _read_cfg()
    issues = []
    llm = cfg.get('llm') or {}
    cm = cfg.get('commute') or {}
    if not llm.get('api_key'):
        issues.append(('llm.api_key', 'DeepSeek API key 未配置，岗位深度分析/难度/推荐指数无法生成'))
    if not cm.get('amap_key'):
        issues.append(('commute.amap_key', '高德 Web服务 key 未配置，通勤计算失效'))
    if not cm.get('amap_js_key'):
        issues.append(('commute.amap_js_key', '高德 Web(JS API) key 未配置，地图显示失败'))
    if not cm.get('origin'):
        issues.append(('commute.origin', '通勤起点未设置'))
    if not cfg.get('api_token'):
        issues.append(('api_token', '未设置 API 令牌（本地使用可留空，云端需要）'))
    return issues


def prompt_config():
    """交互式补齐缺失配置。缺失项为空时只提示，不强制。"""
    cfg = _read_cfg()
    issues = check_config()
    if not issues:
        print('  [配置] 完整，无需填写。')
        return
    print('  [配置] 以下项缺失，直接回车可跳过：')
    for key, desc in issues:
        print('      - %s：%s' % (key, desc))

    def ask(label, key, section=None):
        cur = ''
        if section:
            cur = (cfg.get(section) or {}).get(key) or ''
        else:
            cur = cfg.get(key) or ''
        v = input('      %s [%s]：' % (label, cur or '未设置')).strip()
        if v:
            if section:
                cfg.setdefault(section, {})[key] = v
            else:
                cfg[key] = v

    ask('DeepSeek API key', 'api_key', 'llm')
    ask('高德 Web服务 key', 'amap_key', 'commute')
    ask('高德 Web(JS API) key', 'amap_js_key', 'commute')
    ask('通勤起点(如 杭州市西湖区xx路)', 'origin', 'commute')
    ask('API 令牌(本地可留空)', 'api_token')
    _write_cfg(cfg)
    print('  [配置] 已保存。')


def check_extension():
    return (os.path.isdir(EXT_DIR)
            and os.path.exists(os.path.join(EXT_DIR, 'manifest.json')))


def _healthy():
    import socket
    try:
        s = socket.create_connection(('127.0.0.1', _port()), timeout=2)
        s.close()
        return True
    except Exception:
        return False


def _serve_pids():
    """查找占用服务端口、处于 LISTENING 的 python 进程 PID（仅 Windows）。"""
    pids = set()
    if os.name != 'nt':
        return pids
    try:
        out = subprocess.check_output('netstat -ano', shell=True, text=True,
                                      stderr=subprocess.STDOUT)
        port = _port()
        for line in out.splitlines():
            if ':%d' % port in line and 'LISTENING' in line:
                parts = line.split()
                if parts:
                    pids.add(parts[-1])
    except Exception:
        pass
    return pids


def start_serve():
    """后台启动 serve（隐藏窗口，不依赖控制台），等待就绪后返回。"""
    url = 'http://127.0.0.1:%d/' % _port()
    if _healthy():
        print('  [服务] 已在运行：%s' % url)
        return True
    for pid in _serve_pids():
        try:
            subprocess.run(['taskkill', '/PID', pid, '/F'], capture_output=True)
        except Exception:
            pass
    print('  [服务] 正在启动 ...')
    try:
        if os.name == 'nt':
            # 用 start /min 开一个最小化的持久控制台窗口（比 DETACHED 更稳，不依赖 job 对象）
            cmd = 'start "jobhub-serve" /min "%s" "%s" serve' % (sys.executable, RUN_PY)
            subprocess.Popen(cmd, shell=True, cwd=ROOT)
        else:
            subprocess.Popen([sys.executable, RUN_PY, 'serve'], cwd=ROOT, start_new_session=True)
    except Exception as e:
        print('  [服务] 启动失败：%s' % e)
        return False
    for _ in range(40):
        time.sleep(1)
        if _healthy():
            print('  [服务] 就绪：%s' % url)
            return True
    print('  [服务] 启动超时，请手动运行：python run.py serve')
    return False


def stop_serve():
    pids = _serve_pids()
    if not pids:
        print('  [服务] 未在运行。')
        return
    for pid in pids:
        try:
            subprocess.run(['taskkill', '/PID', pid, '/F'], capture_output=True)
            print('  [服务] 已停止 PID %s' % pid)
        except Exception as e:
            print('  [服务] 停止失败：%s' % e)


def open_browser():
    webbrowser.open('http://127.0.0.1:%d/' % _port())


def check_report():
    print('== 薪途 PathToJob 环境检查 ==')
    print('  项目根目录 : %s' % ROOT)
    print('  Python     : %s' % sys.executable)
    print('  版本       : %s.%s.%s' % sys.version_info[:3])
    ok, detail = check_deps()
    print('  简历解析   : %s（%s）' % ('OK' if ok else '缺失', detail))
    issues = check_config()
    if issues:
        print('  配置       : %d 项缺失/待填' % len(issues))
        for key, desc in issues:
            print('      - %s：%s' % (key, desc))
    else:
        print('  配置       : 完整')
    print('  浏览器扩展 : %s' % ('已就绪' if check_extension() else '未找到（需在浏览器加载 extension/bossdive）'))
    print('  数据库     : %s' % ('存在' if os.path.exists(DB) else '空库（可在看板抓取/导入）'))
    print('  简历文件   : %s' % ('存在' if os.path.exists(RESUME) else '无（可在看板顶部上传）'))
    print('  服务端口   : %d' % _port())


def cmd_setup():
    check_report()
    print()
    if not ensure_deps(interactive=True):
        print('依赖未就绪，仅影响 PDF/Word 简历解析，其余功能可用。')
    prompt_config()
    print()
    start_serve()
    open_browser()


def cmd_serve():
    check_report()
    print()
    if not ensure_deps(interactive=True):
        print('依赖未就绪，仅影响 PDF/Word 简历解析，其余功能可用。')
    if check_config():
        prompt_config()
    print()
    start_serve()
    open_browser()


def menu():
    print('=== 薪途 PathToJob 引导助手 ===')
    while True:
        print()
        print('  [1] 环境检查')
        print('  [2] 安装依赖（pypdf / python-docx）')
        print('  [3] 配置 API Key / 通勤起点')
        print('  [4] 启动看板（服务 + 浏览器）')
        print('  [5] 停止服务')
        print('  [0] 退出')
        ch = input('  请选择：').strip()
        if ch == '1':
            check_report()
        elif ch == '2':
            ensure_deps(interactive=True)
        elif ch == '3':
            prompt_config()
        elif ch == '4':
            if not ensure_deps(interactive=True):
                print('依赖未就绪，仅影响 PDF/Word 简历解析。')
            if check_config():
                prompt_config()
            if start_serve():
                open_browser()
        elif ch == '5':
            stop_serve()
        elif ch == '0':
            print('  再见！')
            break
        else:
            print('  无效选择。')


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'menu'
    if cmd == 'check':
        check_report()
    elif cmd == 'setup':
        cmd_setup()
    elif cmd == 'serve':
        cmd_serve()
    elif cmd == 'stop':
        stop_serve()
    elif cmd == 'menu':
        menu()
    else:
        print('未知命令：%s' % cmd)
        print('用法：bootstrap.py [check|setup|serve|stop|menu]')


if __name__ == '__main__':
    main()
