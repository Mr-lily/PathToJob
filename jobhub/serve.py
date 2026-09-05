# -*- coding: utf-8 -*-
"""极轻量本地配置服务：让静态看板能改通勤起点 / 岗位终点地址。

用法：python run.py serve
  - 监听 http://127.0.0.1:8765
  - GET  /api/commute          -> 当前起点配置
  - POST /api/commute          {"origin":"...","origin_name":"..."}  写 config 并重算看板
  - POST /api/job/address      {"id":"...","address":"..."}          改岗位地址并重算看板

安全：仅绑定 127.0.0.1，不暴露到局域网。CORS 放开以支持 file:// 打开看板。
"""
import datetime
import json
import os
import sqlite3
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # job-hub/
CONFIG = os.path.join(ROOT, 'config.json')

# ---- 速率限制：/api/invite 每 IP 每分钟最多 5 次 ----
_invite_attempts = {}  # {ip: [(timestamp, ...)]}
_INVITE_RATE_LIMIT = 10   # 每分钟最多尝试次数（含正确+错误）
_INVITE_RATE_WINDOW = 60  # 窗口秒数

def _check_invite_rate(ip):
    """检查 IP 是否超过邀请码尝试频率。返回 True=允许，False=拒绝。"""
    import time
    now = time.time()
    # 清理过期记录
    _invite_attempts[ip] = [t for t in _invite_attempts.get(ip, []) if now - t < _INVITE_RATE_WINDOW]
    if len(_invite_attempts.get(ip, [])) >= _INVITE_RATE_LIMIT:
        return False
    _invite_attempts.setdefault(ip, []).append(now)
    return True

# ---- Sessions (serve.py 自建，不依赖 store.py) ----
_SESSION_TTL = 30 * 86400  # 30 days

def _ensure_sessions_table(conn):
    """确保 sessions 表结构正确；若旧表有 invite_code 列则重建。"""
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(sessions)").fetchall()]
        if 'username' not in cols:
            conn.execute("DROP TABLE IF EXISTS sessions")
            conn.execute("CREATE TABLE sessions (token TEXT PRIMARY KEY, username TEXT NOT NULL, created_at TEXT, expires_at REAL)")
            conn.commit()
            print('[session] sessions 表已重建为 username 模式')
    except Exception:
        conn.execute("CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, username TEXT NOT NULL, created_at TEXT, expires_at REAL)")
        conn.commit()

def _session_create(conn, username):
    """用用户名建 session，返回 token。调用方负责 commit。"""
    import secrets, time
    _ensure_sessions_table(conn)
    token = 'ses_' + secrets.token_hex(24)
    conn.execute('INSERT INTO sessions(token, username, created_at, expires_at) VALUES(?,?,?,?)',
                 (token, username, datetime.datetime.now().isoformat(timespec='seconds'), time.time() + _SESSION_TTL))
    return token

def _session_user(conn, token):
    """通过 session token 查对应的 username，返回 username 或 None。"""
    if not token:
        return None
    _ensure_sessions_table(conn)
    row = conn.execute('SELECT username, expires_at FROM sessions WHERE token=?', (token,)).fetchone()
    if not row:
        return None
    import time
    if row[1] and float(row[1]) < time.time():
        conn.execute('DELETE FROM sessions WHERE token=?', (token,))
        conn.commit()
        return None
    return row[0]

def _session_destroy(conn, token):
    _ensure_sessions_table(conn)
    conn.execute('DELETE FROM sessions WHERE token=?', (token,))
    conn.commit()


def _read_port():
    """读取监听端口：优先 config.json 的 serve_port，其次环境变量 PORT，默认 8765。"""
    try:
        with open(CONFIG, encoding='utf-8') as f:
            cfg = json.load(f)
        p = cfg.get('serve_port')
        if p:
            return int(p)
    except Exception:
        pass
    ep = os.environ.get('PORT')
    if ep:
        try:
            return int(ep)
        except ValueError:
            pass
    return 8765


def _read_config():
    with open(CONFIG, encoding='utf-8') as f:
        return json.load(f)


def _write_config(cfg):
    with open(CONFIG, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def _resume_python():
    """返回用于简历文件解析(需要 pypdf/python-docx)的解释器路径。
    优先：config runtime.venv_python → 项目内 .venv → 当前解释器。"""
    try:
        cfg = _read_config()
        vp = (cfg.get('runtime') or {}).get('venv_python') or ''
        if vp and os.path.exists(vp):
            return vp
    except Exception:
        pass
    for cand in (os.path.join(ROOT, '.venv', 'Scripts', 'python.exe'),
                 os.path.join(ROOT, '.venv', 'bin', 'python'),
                 os.path.join(ROOT, '.venv', 'Scripts', 'python')):
        if os.path.exists(cand):
            return cand
    return sys.executable


def _db_conn():
    from jobhub import store
    return store.connect(os.path.join(ROOT, 'data', 'jobs.db'))


def _rebuild_insight():
    """重算看板。返回 (ok, msg)。"""
    py = sys.executable
    try:
        r = subprocess.run([py, os.path.join(ROOT, 'run.py'), 'insight'],
                           capture_output=True, text=True, timeout=120,
                           cwd=ROOT)
        if r.returncode == 0:
            return True, '看板已重算'
        return False, (r.stderr or r.stdout or '重算失败')[:200]
    except Exception as e:
        return False, str(e)[:200]


def _rec_score(fit, commute_min, difficulty, cfg):
    """综合推荐指数 = 适配度*w_fit + 通勤*w_cm + 求职难度*w_diff (0-100)。

    通勤越近越高分：60min内按线性 100→0，无通勤信息按中性。
    难度：数值越大越难，推荐分越低（难度权重是反向的）。
    """
    w = cfg.get('rec_weight') or {'fit': 70, 'commute': 20, 'difficulty': 10}
    w_fit = w.get('fit', 70); w_cm = w.get('commute', 20); w_diff = w.get('difficulty', 10)
    total_w = w_fit + w_cm + w_diff or 1
    fit_s = (fit if fit is not None else 0) or 0
    if commute_min is None:
        cm_s = 50  # 无通勤信息中性
    else:
        cm_s = max(0, min(100, 100 - (commute_min / 60.0) * 100))
    diff_s = (difficulty if difficulty is not None else 50) or 50
    # 难度反向：越难推荐分越低 → 100 - difficulty
    diff_rev = max(0, min(100, 100 - diff_s))
    rec = (w_fit * fit_s + w_cm * cm_s + w_diff * diff_rev) / total_w
    return round(rec, 1)


def _analyze_job(jid):
    """给单个岗位生成深度分析，成功后重建看板。后台线程调用。"""
    try:
        import sys as _sys
        _sys.path.insert(0, ROOT)
        from jobhub import store, analyzer
        cfg = _read_config()
        conn = store.connect(os.path.join(ROOT, 'data', 'jobs.db'))
        row = conn.execute('SELECT * FROM jobs WHERE id=?', (jid,)).fetchone()
        if row is None:
            conn.close()
            return
        job = store.row_to_dict(row)
        if job.get('analysis'):
            conn.close()
            return  # 已有分析，不覆盖
        # 方案C：规则分做基准 + AI 软性微调
        # 1) 规则基准分（可解释：薪资/关键词/经验/学历/城市等）
        from jobhub import score as SC
        base_score, base_detail = SC.score_job(job, cfg)
        # 2) AI 分析（结合基准分，输出软性微调 -5~+5 + 求职难度）
        text, err = analyzer.analyze(job, cfg, ROOT, base_score=base_score,
                                     base_breakdown=base_detail.get('breakdown'),
                                     profile=cfg.get('profile'), resume='')
        if text and not err:
            delta = analyzer.parse_delta(text)
            diff = analyzer.parse_difficulty(text)
            fit = base_score if delta is None else int(max(0, min(100, base_score + delta)))
            # 存基准分(score) + 最终适配指数(fit_score) + 求职难度
            store.set_score(conn, jid, base_score, base_detail)
            store.set_analysis(conn, jid, text, fit_score=fit)
            if diff is not None:
                store.set_difficulty(conn, jid, diff)
            # 综合推荐指数：适配 + 通勤 + 难度
            cm_min = None
            cm = job.get('commute')
            if cm and isinstance(cm, dict) and cm.get('modes'):
                drv = cm['modes'].get('driving') or {}
                cm_min = drv.get('minutes')
            rec = _rec_score(fit, cm_min, diff, cfg)
            store.set_rec_score(conn, jid, rec)
            conn.close()
            _rebuild_insight()
        elif text:
            # 有分析但没微调值：存基准分
            fit = base_score
            store.set_score(conn, jid, base_score, base_detail)
            store.set_analysis(conn, jid, text, fit_score=fit)
            conn.close()
            _rebuild_insight()
        else:
            conn.close()
            print(f'[analyze] {jid} 分析失败: {err}', flush=True)
    except Exception as e:
        print(f'[analyze] {jid} 异常: {e}', flush=True)


def _deep_analyze_job(jid):
    """给重点岗位生成深入专项分析，成功后重建看板。后台线程调用。"""
    try:
        import sys as _sys
        _sys.path.insert(0, ROOT)
        from jobhub import store, analyzer
        cfg = _read_config()
        conn = store.connect(os.path.join(ROOT, 'data', 'jobs.db'))
        row = conn.execute('SELECT * FROM jobs WHERE id=?', (jid,)).fetchone()
        if row is None:
            conn.close()
            return
        job = store.row_to_dict(row)
        base_analysis = job.get('analysis') or ''
        text, err = analyzer.deep_analyze(job, cfg, ROOT, base_analysis=base_analysis,
                                          profile=cfg.get('profile'), resume='')
        if text:
            store.set_deep_analysis(conn, jid, text)
        else:
            print(f'[deep] {jid} 深入分析失败: {err}', flush=True)
        conn.close()
        _rebuild_insight()
    except Exception as e:
        print(f'[deep] {jid} 异常: {e}', flush=True)


def _cookie_attrs():
    """返回 Set-Cookie 通用安全属性。本地 HTTP 不加 Secure/SameSite=None（浏览器不允许），
    云端 HTTPS 自动带上。"""
    try:
        cfg = _read_config()
        port = int(cfg.get('serve_port') or 8765)
    except Exception:
        port = 8765
    # 本地端口(8765/8766)视为开发环境；其他端口或 HTTPS 视为生产
    is_local = port in (8765, 8766)
    attrs = 'Path=/; Max-Age={maxage}; HttpOnly; SameSite=Lax'
    if not is_local:
        attrs += '; Secure'
    return attrs


class Handler(BaseHTTPRequestHandler):
    def _cors(self):
        origin = self.headers.get('Origin') or '*'
        self.send_header('Access-Control-Allow-Origin', origin)
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, X-API-Token')
        self.send_header('Access-Control-Allow-Credentials', 'true')

    def _get_cookie(self, name):
        """从 Cookie 头读指定 cookie 值。"""
        raw = self.headers.get('Cookie') or ''
        for part in raw.split(';'):
            part = part.strip()
            if '=' in part:
                k, v = part.split('=', 1)
                if k.strip() == name:
                    return v.strip()
        return ''

    def _client_ip(self):
        """获取客户端 IP：优先 X-Forwarded-For（nginx 反代时），否则用 socket 地址。"""
        xff = self.headers.get('X-Forwarded-For') or ''
        if xff:
            return xff.split(',')[0].strip()
        return self.client_address[0] if self.client_address else ''

    def _redirect(self, url):
        self.send_response(302)
        self.send_header('Location', url)
        self.send_header('Content-Length', '0')
        self.end_headers()

    def _send_html_str(self, html_str):
        """直接返回一段 HTML 字符串。"""
        body = html_str.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _send(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def _send_html(self, path):
        """返回本地 HTML 文件（用于 http 访问看板，供高德 JS API 域名校验）。"""
        full = os.path.normpath(os.path.join(ROOT, 'data', path))
        if not full.startswith(os.path.normpath(os.path.join(ROOT, 'data'))):
            self._send(403, {'error': 'forbidden'})
            return
        if not os.path.isfile(full):
            self._send(404, {'error': 'no such file'})
            return
        with open(full, encoding='utf-8') as f:
            body = f.read().encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == '/login' or self.path == '/login.html':
            self._send_html('login.html')
            return
        if self.path == '/logout' or self.path == '/logout.html':
            tok = self._get_cookie('session_token')
            if tok:
                conn = _db_conn()
                _session_destroy(conn, tok)
                conn.close()
            self.send_response(302)
            self.send_header('Location', '/login')
            self.send_header('Set-Cookie', 'session_token=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax')
            self.send_header('Content-Length', '0')
            self.end_headers()
            return
        if self.path == '/' or self.path == '/index.html' or self.path == '/insight':
            conn = _db_conn()
            code = self._current_session(conn)
            conn.close()
            if code is None:
                self._redirect('/login')
                return
            try:
                self._serve_user_insight()
            except Exception as e:
                print(f'[insight] {e}', flush=True)
                self._send(500, {'error': '看板生成失败'})
            return
        # 扩展下载：打包 extension/bossdive 为 zip
        if self.path == '/api/extension/download':
            conn = _db_conn()
            code = self._current_session(conn)
            conn.close()
            if code is None:
                self._redirect('/login')
                return
            import zipfile, io
            ext_dir = os.path.join(ROOT, 'extension', 'bossdive')
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
                for root, dirs, files in os.walk(ext_dir):
                    for f in files:
                        fp = os.path.join(root, f)
                        arcname = os.path.relpath(fp, os.path.dirname(ext_dir))
                        zf.write(fp, arcname)
            data = buf.getvalue()
            self.send_response(200)
            self.send_header('Content-Type', 'application/zip')
            self.send_header('Content-Disposition', 'attachment; filename="bossdive-extension.zip"')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        # 开放 data/ 下静态文件（如 maptest.html）——需鉴权
        if self.path.startswith('/') and '.' in self.path and not self.path.startswith('/api/'):
            conn = _db_conn()
            code = self._current_session(conn)
            conn.close()
            if code is None:
                self._redirect('/login')
                return
            fn = self.path.lstrip('/')
            full = os.path.normpath(os.path.join(ROOT, 'data', fn))
            if full.startswith(os.path.normpath(os.path.join(ROOT, 'data'))) and os.path.isfile(full):
                ext = os.path.splitext(full)[1].lower()
                ctype = {'html': 'text/html; charset=utf-8', 'png': 'image/png',
                         'jpg': 'image/jpeg', 'js': 'text/javascript; charset=utf-8',
                         'css': 'text/css; charset=utf-8'}.get(ext.lstrip('.'), 'application/octet-stream')
                with open(full, encoding='utf-8', errors='replace') as f:
                    body = f.read().encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', ctype)
                self.send_header('Content-Length', str(len(body)))
                self._cors()
                self.end_headers()
                self.wfile.write(body)
                return
        if self.path.startswith('/api/'):
            from jobhub import store
            conn = _db_conn()
            try:
                if self.path.startswith('/api/me'):
                    ok, user = self._auth(conn)
                    if not ok:
                        return
                    is_master = (user == 'master')
                    self._send(200, {'ok': True, 'is_master': is_master, 'username': user if not is_master else None})
                    return
                if self.path.startswith('/api/jobs'):
                    ok, code = self._auth(conn)
                    if not ok:
                        return
                    from jobhub import normalize as _N
                    jobs = store.all_jobs(conn)  # no user_id filter
                    for j in jobs:
                        j['salary_text'] = _N.salary_text(j)
                    self._send(200, {'ok': True, 'jobs': jobs})
                    return
                if self.path.startswith('/api/commute'):
                    ok, code = self._auth(conn)
                    if not ok:
                        return
                    cfg = _read_config()
                    cc = cfg.get('commute') or {}
                    amap_key = cc.get('amap_key') or ''
                    self._send(200, {
                        'origin': cc.get('origin', ''),
                        'origin_name': cc.get('origin_name', ''),
                        'mode': cc.get('mode', 'driving'),
                        'city': cc.get('city', '杭州'),
                        'amap_key_set': bool(amap_key),
                    })
                    return
                if self.path.startswith('/api/resume'):
                    ok, code = self._auth(conn)
                    if not ok:
                        return
                    self._send(200, {'has': False, 'chars': 0, 'head': ''})
                    return
                if self.path.startswith('/api/settings/profile'):
                    ok, code = self._auth(conn)
                    if not ok:
                        return
                    self._send(200, {'ok': True, 'profile': {}})
                    return
                if self.path.startswith('/api/invite/list'):
                    tok = (self.headers.get('X-API-Token') or '').strip()
                    cfg = _read_config()
                    master = (cfg.get('api_token') or '').strip()
                    if not master or tok != master:
                        self._send(403, {'ok': False, 'error': '需要 master token'}); return
                    conn2 = _db_conn()
                    try:
                        conn2.execute('CREATE TABLE IF NOT EXISTS invite_codes (code TEXT PRIMARY KEY, created_at TEXT, created_by TEXT, used_by TEXT, used_at TEXT, note TEXT DEFAULT \'\')')
                        rows = conn2.execute('SELECT code, created_at, used_by, used_at, note FROM invite_codes ORDER BY created_at DESC').fetchall()
                        codes = [{'code': r[0], 'created_at': r[1], 'used': bool(r[2]), 'used_at': r[3], 'note': r[4]} for r in rows]
                    finally:
                        conn2.close()
                    self._send(200, {'ok': True, 'codes': codes})
                    return
                self._send(404, {'error': 'not found'})
            finally:
                conn.close()
            return

    def _current_session(self, conn):
        """解析当前 session：master token → 返回 'master'；cookie session_token → 查 DB 返回 username 或 None。"""
        token = (self.headers.get('X-API-Token') or '').strip()
        if not token:
            token = self._get_cookie('session_token')
        if not token:
            return None
        try:
            cfg = _read_config()
            master = (cfg.get('api_token') or '').strip()
        except Exception:
            master = ''
        if master and token == master:
            return 'master'
        return _session_user(conn, token)

    def _auth(self, conn):
        user = self._current_session(conn)
        if user is None:
            self._send(401, {'ok': False, 'error': '未授权：请先登录'})
            return False, None
        return True, user

    def _read_json(self):
        try:
            ln = int(self.headers.get('Content-Length') or 0)
            if ln > 1048576:  # 1MB 上限
                return {}
            return json.loads(self.rfile.read(ln).decode('utf-8')) if ln else {}
        except Exception:
            return {}

    def do_POST(self):
        # 公开端点：邀请码注册（邀请码+用户名+密码）
        if self.path.startswith('/api/invite') and not self.path.startswith('/api/invite/create') and not self.path.startswith('/api/invite/revoke') and not self.path.startswith('/api/invite/list'):
            # 速率限制
            if not _check_invite_rate(self._client_ip()):
                self._send(429, {'ok': False, 'error': '尝试过于频繁，请稍后再试'}); return
            body = self._read_json()
            code = (body.get('code') or '').strip()
            username = (body.get('username') or '').strip()
            password = (body.get('password') or '').strip()
            if not code:
                self._send(400, {'ok': False, 'error': '请输入邀请码'}); return
            if not username or len(username) < 2:
                self._send(400, {'ok': False, 'error': '用户名至少2个字符'}); return
            if not password or len(password) < 4:
                self._send(400, {'ok': False, 'error': '密码至少4位'}); return
            conn = _db_conn()
            try:
                conn.execute('CREATE TABLE IF NOT EXISTS invite_codes (code TEXT PRIMARY KEY, created_at TEXT, created_by TEXT, used_by TEXT, used_at TEXT, note TEXT DEFAULT \'\')')
                # 原子操作：SELECT + UPDATE 在同一事务中，防止竞态条件
                conn.execute('BEGIN IMMEDIATE')
                row = conn.execute('SELECT code, used_by FROM invite_codes WHERE code=?', (code,)).fetchone()
                if not row:
                    conn.execute('ROLLBACK')
                    self._send(400, {'ok': False, 'error': '邀请码不正确'}); return
                if row[1]:
                    conn.execute('ROLLBACK')
                    self._send(400, {'ok': False, 'error': '该邀请码已被使用'}); return
                # 检查用户名是否已存在
                existing = conn.execute('SELECT 1 FROM users WHERE username=?', (username,)).fetchone()
                if existing:
                    conn.execute('ROLLBACK')
                    self._send(400, {'ok': False, 'error': '用户名已存在'}); return
                # 注册用户
                from jobhub import store as _store
                pwd_hash = _store._hash_password(password)
                conn.execute('INSERT INTO users(username, password_hash, created_at) VALUES(?,?,?)',
                             (username, pwd_hash, datetime.datetime.now().isoformat(timespec='seconds')))
                # 标记邀请码已使用
                conn.execute('UPDATE invite_codes SET used_by=?, used_at=? WHERE code=?',
                             (username, datetime.datetime.now().isoformat(timespec='seconds'), code))
                # 创建 session
                token = _session_create(conn, username)
                conn.execute('COMMIT')
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                attrs = _cookie_attrs().format(maxage=_SESSION_TTL)
                self.send_header('Set-Cookie', f'session_token={token}; {attrs}')
                self._cors()
                out = json.dumps({'ok': True}, ensure_ascii=False).encode('utf-8')
                self.send_header('Content-Length', str(len(out)))
                self.end_headers()
                self.wfile.write(out)
            except Exception as e:
                try:
                    conn.execute('ROLLBACK')
                except Exception:
                    pass
                print(f'[invite] {e}', flush=True)
                self._send(500, {'ok': False, 'error': '注册失败'})
            finally:
                conn.close()
            return
        # 公开端点：用户名密码登录
        if self.path.startswith('/api/login'):
            if not _check_invite_rate(self._client_ip()):
                self._send(429, {'ok': False, 'error': '尝试过于频繁，请稍后再试'}); return
            body = self._read_json()
            username = (body.get('username') or '').strip()
            password = (body.get('password') or '').strip()
            if not username or not password:
                self._send(400, {'ok': False, 'error': '请输入用户名和密码'}); return
            conn = _db_conn()
            try:
                from jobhub import store as _store
                user = _store.verify_user(conn, username, password)
                if not user:
                    self._send(401, {'ok': False, 'error': '用户名或密码错误'}); return
                token = _session_create(conn, user)
                conn.commit()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                attrs = _cookie_attrs().format(maxage=_SESSION_TTL)
                self.send_header('Set-Cookie', f'session_token={token}; {attrs}')
                self._cors()
                out = json.dumps({'ok': True}, ensure_ascii=False).encode('utf-8')
                self.send_header('Content-Length', str(len(out)))
                self.end_headers()
                self.wfile.write(out)
            except Exception as e:
                print(f'[login] {e}', flush=True)
                self._send(500, {'ok': False, 'error': '登录失败'})
            finally:
                conn.close()
            return
        if self.path.startswith('/api/logout'):
            tok = self._get_cookie('session_token')
            if tok:
                conn = _db_conn()
                _session_destroy(conn, tok)
                conn.close()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Set-Cookie', 'session_token=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax')
            body = json.dumps({'ok': True})
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body.encode())
            return
        # 其余写操作需登录
        conn = _db_conn()
        ok, code = self._auth(conn)
        conn.close()
        if not ok:
            return
        # 简历文件上传：简化返回 400
        if self.path.startswith('/api/resume_file'):
            self._send(400, {'error': '简历功能暂未启用'}); return
        # BOSS 生成邀请码
        if self.path.startswith('/api/invite/create'):
            tok = (self.headers.get('X-API-Token') or '').strip()
            cfg = _read_config()
            master = (cfg.get('api_token') or '').strip()
            if not master or tok != master:
                self._send(403, {'ok': False, 'error': '需要 master token'}); return
            body = self._read_json()
            count = min(max(int(body.get('count') or 1), 1), 20)
            note = (body.get('note') or '').strip()
            import secrets as _s
            codes = []
            conn2 = _db_conn()
            try:
                conn2.execute('CREATE TABLE IF NOT EXISTS invite_codes (code TEXT PRIMARY KEY, created_at TEXT, created_by TEXT, used_by TEXT, used_at TEXT, note TEXT DEFAULT \'\')')
                for _ in range(count):
                    code = 'xt-' + _s.token_hex(4)
                    conn2.execute('INSERT INTO invite_codes(code, created_at, created_by, note) VALUES(?,?,?,?)',
                                 (code, datetime.datetime.now().isoformat(timespec='seconds'), 'boss', note))
                    codes.append(code)
                conn2.commit()
            finally:
                conn2.close()
            self._send(200, {'ok': True, 'codes': codes})
            return
        # BOSS 撤销邀请码
        if self.path.startswith('/api/invite/revoke'):
            tok = (self.headers.get('X-API-Token') or '').strip()
            cfg = _read_config()
            master = (cfg.get('api_token') or '').strip()
            if not master or tok != master:
                self._send(403, {'ok': False, 'error': '需要 master token'}); return
            body = self._read_json()
            code = (body.get('code') or '').strip()
            if not code:
                self._send(400, {'ok': False, 'error': '缺 code'}); return
            conn2 = _db_conn()
            try:
                conn2.execute('CREATE TABLE IF NOT EXISTS invite_codes (code TEXT PRIMARY KEY, created_at TEXT, created_by TEXT, used_by TEXT, used_at TEXT, note TEXT DEFAULT \'\')')
                conn2.execute("DELETE FROM invite_codes WHERE code=? AND (used_by IS NULL OR used_by='')", (code,))
                conn2.commit()
            finally:
                conn2.close()
            self._send(200, {'ok': True})
            return
        try:
            ln = int(self.headers.get('Content-Length') or 0)
            body = json.loads(self.rfile.read(ln).decode('utf-8')) if ln else {}
        except Exception:
            body = {}
        if self.path.startswith('/api/commute'):
            origin = (body.get('origin') or '').strip()
            if not origin:
                self._send(400, {'error': '起点不能为空'})
                return
            cfg = _read_config()
            cc = cfg.get('commute') or {}
            cc['origin'] = origin
            cc['origin_name'] = (body.get('origin_name') or origin).strip()
            cfg['commute'] = cc
            _write_config(cfg)
            ok, msg = _rebuild_insight()
            self._send(200 if ok else 500, {'ok': ok, 'msg': msg, 'origin': origin})
        elif self.path.startswith('/api/job/address'):
            jid = (body.get('id') or '').strip()
            addr = (body.get('address') or '').strip()
            if not jid or not addr:
                self._send(400, {'error': '缺少 id 或 address'})
                return
            conn = _db_conn()
            cur = conn.execute('SELECT COUNT(*) FROM jobs WHERE id=?', (jid,))
            if cur.fetchone()[0] == 0:
                conn.close()
                self._send(404, {'error': '岗位不存在'})
                return
            conn.execute('UPDATE jobs SET address=? WHERE id=?', (addr, jid))
            conn.commit()
            conn.close()
            ok, msg = _rebuild_insight()
            self._send(200 if ok else 500, {'ok': ok, 'msg': msg})
        elif self.path.startswith('/api/snapshot'):
            # 扩展抓到后把页面原始快照存档，供贰贰校准抓取规则
            try:
                snap_dir = os.path.join(ROOT, 'data', 'snapshots')
                os.makedirs(snap_dir, exist_ok=True)
                import time, hashlib
                fname = 'snap_' + time.strftime('%Y%m%d_%H%M%S') + '_' + hashlib.md5(
                    (body.get('url') or str(time.time())).encode()).hexdigest()[:6] + '.json'
                with open(os.path.join(snap_dir, fname), 'w', encoding='utf-8') as f:
                    json.dump(body, f, ensure_ascii=False, indent=1)
                self._send(200, {'ok': True, 'file': fname})
            except Exception as e:
                print(f'[snap] {e}', flush=True)
                self._send(500, {'ok': False, 'error': '快照保存失败'})
        elif self.path.startswith('/api/jobs'):
            # 扩展直接把解析好的岗位 POST 进来入库（全自动）
            item = {k: body.get(k) for k in
                    ('platform', 'company', 'title', 'salary_raw', 'city', 'district',
                     'experience', 'education', 'jd', 'address', 'url', 'tags', 'hr_name') if body.get(k) is not None}
            if not item.get('company') and not item.get('title'):
                self._send(400, {'error': '缺 company/title'})
                return
            try:
                import sys as _sys
                _sys.path.insert(0, ROOT)
                from jobhub import store
                conn = store.connect(os.path.join(ROOT, 'data', 'jobs.db'))
                res, jid = store.upsert(conn, item)
                conn.close()
                # 入库后自动生成深度分析（后台线程，不阻塞抓取响应）
                if res in ('new', 'merged') and not item.get('_skip_analyze'):
                    import threading
                    threading.Thread(target=_analyze_job, args=(jid,), daemon=True).start()
                self._send(200, {'ok': True, 'result': res, 'id': jid})
            except Exception as e:
                print(f'[jobs] {e}', flush=True)
                self._send(500, {'ok': False, 'error': '岗位入库失败'})
        elif self.path.startswith('/api/job/') and self.path.endswith('/analyze'):
            # 手动给岗位补深度分析：POST /api/job/{id}/analyze
            jid = self.path.split('/api/job/')[1].split('/analyze')[0].strip()
            if not jid:
                self._send(400, {'error': '缺 id'})
                return
            import threading
            threading.Thread(target=_analyze_job, args=(jid,), daemon=True).start()
            self._send(200, {'ok': True, 'msg': '分析任务已启动'})
        elif self.path.startswith('/api/job/') and (self.path.endswith('/key') or self.path.endswith('/unkey')):
            # 标记/取消重点岗位，标记时后台生成深入专项分析
            is_key = self.path.endswith('/key')
            jid = self.path.split('/api/job/')[1].rsplit('/', 1)[0].strip()
            if not jid:
                self._send(400, {'error': '缺 id'})
                return
            try:
                import sys as _sys
                _sys.path.insert(0, ROOT)
                from jobhub import store
                conn = store.connect(os.path.join(ROOT, 'data', 'jobs.db'))
                if not conn.execute('SELECT 1 FROM jobs WHERE id=?', (jid,)).fetchone():
                    conn.close()
                    self._send(404, {'error': '岗位不存在'})
                    return
                store.set_key(conn, jid, 1 if is_key else 0)
                conn.close()
                if is_key:
                    import threading
                    threading.Thread(target=_deep_analyze_job, args=(jid,), daemon=True).start()
                _rebuild_insight()
                self._send(200, {'ok': True, 'is_key': is_key})
            except Exception as e:
                print(f'[key] {e}', flush=True)
                self._send(500, {'ok': False, 'error': '操作失败'})
        elif self.path.startswith('/api/job/') and ('/delete' in self.path):
            # 删除岗位：POST /api/job/{id}/delete
            jid = self.path.split('/api/job/')[1].split('/delete')[0].strip()
            if not jid:
                self._send(400, {'error': '缺 id'})
                return
            try:
                conn = _db_conn()
                if not conn.execute('SELECT 1 FROM jobs WHERE id=?', (jid,)).fetchone():
                    conn.close()
                    self._send(404, {'error': '岗位不存在'})
                    return
                conn.execute('DELETE FROM jobs WHERE id=?', (jid,))
                conn.commit()
                conn.close()
                _rebuild_insight()
                self._send(200, {'ok': True})
            except Exception as e:
                print(f'[delete] {e}', flush=True)
                self._send(500, {'ok': False, 'error': '删除失败'})
        elif self.path.startswith('/api/job/'):
            # 编辑岗位：POST /api/job/{id}  body=要改的字段
            jid = self.path.split('/api/job/')[1].strip()
            if not jid:
                self._send(400, {'error': '缺 id'})
                return
            # 可编辑字段白名单（不碰 id/platforms/score 等系统字段）
            updatable = ('company', 'title', 'salary_raw', 'city', 'district', 'experience',
                         'education', 'jd', 'address', 'url', 'tags', 'hr_name', 'status', 'notes')
            sets = {k: body.get(k) for k in updatable if k in body}
            if not sets:
                self._send(400, {'error': '没有可更新字段'})
                return
            try:
                conn = _db_conn()
                cur = conn.execute('SELECT COUNT(*) FROM jobs WHERE id=?', (jid,))
                if cur.fetchone()[0] == 0:
                    conn.close()
                    self._send(404, {'error': '岗位不存在'})
                    return
                sets_sql = ', '.join(f'{k}=?' for k in sets)
                conn.execute(f'UPDATE jobs SET {sets_sql} WHERE id=?',
                             list(sets.values()) + [jid])
                conn.commit()
                conn.close()
                _rebuild_insight()
                self._send(200, {'ok': True})
            except Exception as e:
                print(f'[edit] {e}', flush=True)
                self._send(500, {'ok': False, 'error': '编辑失败'})
        elif self.path.startswith('/api/resume/delete'):
            self._send(200, {'ok': True})
            return
        elif self.path.startswith('/api/resume'):
            self._send(400, {'error': '简历功能暂未启用'})
            return
        else:
            self._send(404, {'error': 'not found'})

    def _serve_user_insight(self):
        from jobhub import store, insight, commute
        from jobhub import normalize as N
        conn = _db_conn()
        try:
            tok = self._get_cookie('session_token')
            username = _session_user(conn, tok) if tok else None
            if not username:
                username = '用户'
            jobs = store.all_jobs(conn)
            for j in jobs:
                j['salary_text'] = N.salary_text(j)
        finally:
            conn.close()
        cfg = _read_config()
        cm_meta = commute.load_from_config(cfg)
        out = os.path.join(ROOT, 'data', '_user_insight.html')
        api_token = (cfg.get('api_token') or '').strip()
        insight.build(jobs, cm_meta, out, api_token=api_token, username=username)
        self._send_html('_user_insight.html')

    def log_message(self, format, *args):
        # 记录请求日志到文件（排查自动删除等异常）
        try:
            msg = (format % args)
            if '/api/' in msg:
                with open(os.path.join(ROOT, 'data', 'requests.log'), 'a', encoding='utf-8') as f:
                    import time
                    f.write(time.strftime('%H:%M:%S') + ' ' + msg.strip() + '\n')
        except Exception:
            pass


def _lan_ip():
    """获取本机局域网 IP（用于手机访问看板）。失败返回 127.0.0.1。"""
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            # 不需要真的连，UDP 用于探测出口 IP
            s.connect(('8.8.8.8', 80))
            ip = s.getsockname()[0]
        finally:
            s.close()
        if ip and not ip.startswith('127.'):
            return ip
    except Exception:
        pass
    return '127.0.0.1'


def main():
    # 默认绑局域网内网 IP：同一 WiFi 的手机可访问看板，公网不可达（比 0.0.0.0 安全）
    host = '0.0.0.0'  # 监听所有网卡，配合打印内网 IP；若要更严格可改为具体内网 IP
    lan = _lan_ip()
    port = _read_port()
    # 绑定 0.0.0.0 让手机能连；内网 IP 仅用于展示访问地址
    srv = ThreadingHTTPServer((host, port), Handler)
    print(f'薪途 PathToJob 服务已启动：')
    print(f'  本机(电脑)访问：http://127.0.0.1:{port}')
    print(f'  手机(同WiFi)访问：http://{lan}:{port}')
    print('[!] 服务仅监听本机/局域网，公网不能访问。数据不会外传。保持此窗口开着。Ctrl+C 停止。')
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print('\n已停止')


if __name__ == '__main__':
    main()
