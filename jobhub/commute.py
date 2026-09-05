# -*- coding: utf-8 -*-
"""通勤计算（高德 Web 服务 API）。

对每个岗位：起点(config.commute.origin) → 终点(岗位 address)，
算 驾车/公交/步行 三种方式的耗时（骑行个人 key 默认不可用，预留不启用）。
key 只在本机脚本使用，不内嵌进 HTML。
"""

import json
import os
import urllib.parse
import urllib.request

GEO_URL = 'https://restapi.amap.com/v3/geocode/geo'
MODES = {
    'driving': {'label': '驾车', 'url': 'https://restapi.amap.com/v3/direction/driving'},
    'transit': {'label': '公交', 'url': 'https://restapi.amap.com/v3/direction/transit/integrated', 'need_city': True},
    'walking': {'label': '步行', 'url': 'https://restapi.amap.com/v3/direction/walking'},
}


def _http_get(url, timeout=15):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 job-hub'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8'))


class Commute:
    def __init__(self, key, city=''):
        self.key = key or ''
        self.city = city or '杭州'

    @property
    def enabled(self):
        return bool(self.key)

    def geocode(self, address):
        if not address:
            return None
        url = (GEO_URL + '?key=' + self.key + '&address=' + urllib.parse.quote(address))
        try:
            d = _http_get(url)
            if d.get('status') == '1' and d.get('geocodes'):
                return d['geocodes'][0]['location']
        except Exception:
            pass
        return None

    def _plan(self, mode, origin_loc, dest_loc):
        """对给定坐标算单种方式的 (分钟, 距离m)。返回 dict 或 None。"""
        spec = MODES.get(mode)
        if not spec:
            return None
        try:
            url = spec['url'] + '?key=' + self.key \
                + '&origin=' + urllib.parse.quote(origin_loc) \
                + '&destination=' + urllib.parse.quote(dest_loc)
            if spec.get('need_city'):
                url += '&city=' + urllib.parse.quote(self.city)
            else:
                url += '&strategy=10'
            d = _http_get(url)
            if d.get('status') != '1':
                return None
            if mode == 'transit':
                tr = d.get('route', {}).get('transits') or []
                if not tr:
                    return None
                out = {
                    'minutes': round(int(tr[0].get('duration', 0)) / 60.0),
                    'distance': round(int(tr[0].get('walking_distance', 0)) / 1000.0, 1),
                    'note': '含步行',
                }

                def plan_geo(tx):
                    """从单个 transit 方案提取 {desc, polyline, minutes, walk_km}。"""
                    pmins = round(int(tx.get('duration', 0)) / 60.0)
                    pwk = round(int(tx.get('walking_distance', 0)) / 1000.0, 1)
                    desc_parts = []   # 交通工具段描述
                    pts = []          # 完整路线坐标
                    for seg in (tx.get('segments') or []):
                        wk = seg.get('walking')
                        if isinstance(wk, dict):
                            for stp in (wk.get('steps') or []):
                                for pair in (stp.get('polyline') or '').split(';'):
                                    if ',' in pair:
                                        lng, lat = pair.split(',', 1)
                                        pts.append([round(float(lng), 6), round(float(lat), 6)])
                        blines = []
                        b = seg.get('bus') or {}
                        if isinstance(b, dict) and isinstance(b.get('buslines'), list):
                            blines = b['buslines']
                        if blines:
                            # 同一段多条 buslines = 可替换线路（三选一），polyline 只取第一条（高德主方案）
                            main = blines[0]
                            nm = (main.get('name') or '公交').split('(')[0]
                            ds = (main.get('arrival_stop') or {}).get('name', '')
                            # 描述：多条并列则 "A/B/C路→站"，提示可选
                            if len(blines) > 1:
                                alts = [x.get('name', '').split('(')[0] for x in blines]
                                nm = '/'.join(alts)
                            desc_parts.append(f'{nm}' + (f'→{ds}' if ds else ''))
                            for pair in (main.get('polyline') or '').split(';'):
                                if ',' in pair:
                                    lng, lat = pair.split(',', 1)
                                    pts.append([round(float(lng), 6), round(float(lat), 6)])
                        rw = seg.get('railway')
                        if isinstance(rw, dict):
                            rn = rw.get('name', '')
                            if rn:
                                ds = (rw.get('arrival_stop') or {}).get('name', '')
                                desc_parts.append(rn + (f'→{ds}' if ds else ''))
                    # 去重相邻点 + 抽稀
                    dedup = []
                    for p in pts:
                        if not dedup or dedup[-1] != p:
                            dedup.append(p)
                    pts = dedup
                    if len(pts) > 100:
                        step = max(1, len(pts)//100)
                        pts = [pts[i] for i in range(0, len(pts), step)]
                    return {
                        'idx': None,
                        'minutes': pmins,
                        'walk_km': pwk,
                        'desc': ' → '.join(desc_parts) or f'方案',
                        'polyline': pts if len(pts) >= 2 else [],
                    }

                plans = []
                for ti, tx in enumerate(tr[:3]):
                    g = plan_geo(tx)
                    g['idx'] = ti
                    plans.append(g)
                out['plans'] = plans
                # 顶层 polyline 取方案0（兼容：前端默认画第一条）
                if plans:
                    out['polyline'] = plans[0]['polyline']
                return out
            path = (d.get('route', {}).get('paths') or [None])[0]
            if not path:
                return None
            out = {
                'minutes': round(int(path.get('duration', 0)) / 60.0),
                'distance': round(int(path.get('distance', 0)) / 1000.0, 1),
            }
            # 驾车/步行均取 steps polyline 抽稀
            if mode in ('driving', 'walking'):
                pts = []
                for st in path.get('steps', []):
                    for pair in (st.get('polyline') or '').split(';'):
                        if ',' in pair:
                            lng, lat = pair.split(',', 1)
                            pts.append([round(float(lng), 6), round(float(lat), 6)])
                if len(pts) > 80: step = max(1, len(pts)//80); pts = [pts[i] for i in range(0,len(pts),step)]
                if len(pts) >= 2: out['polyline'] = pts
            return out
        except Exception:
            return None

    def plan_all(self, origin_loc, dest_loc, dest_address):
        """对终点坐标算全部支持方式。返回 {'dest_address':.., 'modes':{..}} 或 None。"""
        if not (self.enabled and origin_loc and dest_loc):
            return None
        out = {'dest_address': dest_address, 'modes': {}}
        for mode in MODES:
            r = self._plan(mode, origin_loc, dest_loc)
            if r:
                out['modes'][mode] = r
        if not out['modes']:
            return None
        # 驾车距离作为参考公里数
        drv = out['modes'].get('driving')
        if drv:
            out['km'] = drv['distance']
        return out

    def address_to_plan(self, origin_loc, dest_address):
        """终点是地址字符串。先 geocode 拿坐标再算多方式。"""
        if not self.enabled or not origin_loc or not dest_address:
            return None
        dest_loc = self.geocode(dest_address)
        if not dest_loc:
            return {'error': 'geocode_fail', 'dest_address': dest_address}
        res = self.plan_all(origin_loc, dest_loc, dest_address)
        if not res:
            return {'error': 'plan_fail', 'dest_address': dest_address}
        return res


def load_from_config(cfg):
    """从 config.commute 构造对象 + 预解析起点。"""
    cc = cfg.get('commute', {}) or {}
    city = cc.get('city', '杭州')
    c = Commute(cc.get('amap_key', ''), city)
    meta = {
        'enabled': c.enabled,
        'origin_raw': cc.get('origin', ''),
        'origin_name': cc.get('origin_name', ''),
        'origin_loc': None,
        'geocode_ok': False,
        'origin_city': city,
        'amap_js_key': cc.get('amap_js_key', '') or '',
        'amap_js_security': cc.get('amap_js_security', '') or '',
    }
    if c.enabled and cc.get('origin'):
        loc = c.geocode(cc['origin'])
        if loc:
            meta['origin_loc'] = loc
            meta['geocode_ok'] = True
    meta['commuter'] = c
    return meta
