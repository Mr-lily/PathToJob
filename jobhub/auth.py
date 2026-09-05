# -*- coding: utf-8 -*-
"""多用户鉴权：密码哈希、登录令牌、注册/登录/校验。"""
import datetime
import hashlib
import hmac
import secrets
import time


def _now():
    return datetime.datetime.now().isoformat(timespec='seconds')


def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), 100_000)
    return f'{salt}${dk.hex()}'


def verify_password(password, stored):
    try:
        salt, hexpart = stored.split('$', 1)
        dk = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), 100_000)
        return hmac.compare_digest(dk.hex(), hexpart)
    except Exception:
        return False


def create_user(conn, username, password):
    """创建用户，返回 (user_id, error)。"""
    username = (username or '').strip()
    if not username or not password:
        return None, '用户名和密码不能为空'
    if len(password) < 6:
        return None, '密码至少 6 位'
    row = conn.execute('SELECT id FROM users WHERE username = ?', (username,)).fetchone()
    if row:
        return None, '用户名已存在'
    uid = 'u_' + secrets.token_hex(8)
    conn.execute('INSERT INTO users(id, username, password_hash, created_at) VALUES(?,?,?,?)',
                 (uid, username, hash_password(password), _now()))
    conn.commit()
    return uid, None


def create_session(conn, user_id, ttl_days=30):
    """创建登录会话，返回 token。"""
    token = 'tok_' + secrets.token_hex(24)
    exp = time.time() + ttl_days * 86400
    conn.execute('INSERT INTO sessions(token, user_id, created_at, expires_at) VALUES(?,?,?,?)',
                 (token, user_id, _now(), exp))
    conn.commit()
    return token


def authenticate(conn, username, password):
    """校验用户名密码，成功返回 (user_id, token)，失败返回 (None, error)。"""
    row = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
    if not row or not verify_password(password, row['password_hash']):
        return None, '用户名或密码错误'
    return row['id'], create_session(conn, row['id'])


def user_by_token(conn, token):
    """根据 token 返回 user_id；无效/过期返回 None。"""
    if not token:
        return None
    row = conn.execute('SELECT user_id, expires_at FROM sessions WHERE token = ?', (token,)).fetchone()
    if not row:
        return None
    if row['expires_at'] and float(row['expires_at']) < time.time():
        return None
    return row['user_id']


def logout(conn, token):
    conn.execute('DELETE FROM sessions WHERE token = ?', (token,))
    conn.commit()
