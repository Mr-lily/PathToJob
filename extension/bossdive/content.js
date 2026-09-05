// Boss岗位快抓 - content script
// 跑在 zhipin.com。注入一个可拖动的悬浮按钮「+ 抓取岗位」。
// 你在 Boss 点开某个岗位后，点一下悬浮按钮，才把当前右侧详情抓下来
// 存 chrome.storage——全程手动触发，绝不自动收你不想要的岗位。
//
// 抓取策略：不硬编码易变的 class 名，而是"按中文标签 + 文本结构"定位，
// 这样平台改版（A/B、class 改名）也不容易全废。抓不到某字段时会记录
// 到 selfDiag，方便校准。

(function () {
  'use strict';
  if (window.__bossGrabLoaded) return; // 防重复注入
  window.__bossGrabLoaded = true;

  var STORE_KEY = 'bossGrab_records';
  var CFG_KEY = 'bossGrab_config';
  var SESSION_KEY = 'bossGrab_session'; // {token, username}
  var TOAST_ID = 'bossGrab_toast';
  var SERVER_BASE = 'https://pathtojob.icu:8765';

  // 加载配置和登录状态
  var _grabSession = null;
  function loadGrabCfg(cb) {
    try {
      var api = (typeof chrome !== 'undefined' && chrome.storage && chrome.storage.local) || null;
      if (api) {
        api.get(SESSION_KEY, function (obj) {
          _grabSession = (obj && obj[SESSION_KEY]) || null;
          cb();
        });
      } else { cb(); }
    } catch (e) { cb(); }
  }
  function grabApiBase() {
    return SERVER_BASE;
  }
  function grabFetchOpts(method, body) {
    var opts = { method: method, headers: { 'Content-Type': 'application/json' } };
    if (_grabSession && _grabSession.username) {
      // 已登录：用 cookie 认证
      opts.credentials = 'include';
    }
    if (body) opts.body = JSON.stringify(body);
    return opts;
  }

  // ------------------------------------------------------------------
  // 存储
  function loadRecords(cb) {
    try {
      var api = (typeof chrome !== 'undefined' && chrome.storage && chrome.storage.local) || null;
      if (api) api.get(STORE_KEY, function (obj) { cb((obj && obj[STORE_KEY]) || []); });
      else cb([]);
    } catch (e) { cb([]); }
  }
  function saveRecords(list, cb) {
    try {
      var api = (typeof chrome !== 'undefined' && chrome.storage && chrome.storage.local) || null;
      if (api) { var o = {}; o[STORE_KEY] = list; api.set(o, cb || function(){}); }
      else if (cb) cb();
    } catch (e) { if (cb) cb(); }
  }

  // ------------------------------------------------------------------
  // 工具
  function clean(s) {
    return (s || '').replace(/\s+/g, ' ').trim();
  }
  function nowISO() {
    return new Date().toISOString().slice(0, 19).replace('T', ' ');
  }

  // ------------------------------------------------------------------
  // 定位"当前岗位详情面板"
  // Boss 是列表+右栏：整页同时有几十个卡片标题 + 右侧一个详情面板。
  // 若直接对整页抓，会命中列表第一张卡片而非当前右栏岗位。
  // 策略：找到含正文特征（岗位职责/任职要求/职位描述）的节点，
  // 向上收敛到一个"同时含薪资或较大容器"的面板根，字段都限定在面板内找。
  function findDetailRoot() {
    // 找所有含职责正文特征的元素
    var dutyEls = Array.prototype.slice.call(document.querySelectorAll('div,section,article'))
      .filter(function (el) {
        var t = el.textContent || '';
        return /岗位职责|工作职责|职位描述|岗位描述|任职要求|岗位要求/.test(t);
      });
    // 对每个，向上找"最近含薪资"的祖先作为候选面板；取文本最短者（最内层面板）
    var best = null, bestLen = Infinity;
    for (var i = 0; i < dutyEls.length; i++) {
      var node = dutyEls[i];
      var panel = null;
      // 先看自身，再逐级向上，最多 6 层
      var cur = node;
      for (var up = 0; up < 6 && cur && cur !== document.body; up++) {
        var ct = cur.textContent || '';
        if (/(?:\d+(?:\.\d+)?\s*[-~至到]\s*\d+(?:\.\d+)?\s*[Kk千万元]|[\ue000-\uf8ff]+\s*[-~至到]?\s*[\ue000-\uf8ff]+[Kk千万元])/.test(ct)) { panel = cur; break; }
        cur = cur.parentElement;
      }
      if (panel) {
        var len = panel.textContent.length;
        if (len < bestLen) { bestLen = len; best = panel; }
      }
    }
    return best || document;
  }

  // ==================== 多平台分派 ====================
  function detectPlatform() {
    var h = location.hostname;
    if (/zhipin/.test(h)) return 'boss';
    if (/51job/.test(h)) return '51job';
    if (/liepin/.test(h)) return 'liepin';
    if (/zhaopin/.test(h)) return 'zhilian';
    if (/yupao/.test(h)) return 'yupao';
    return 'other';
  }
  function isDetailPage() {
    var p = location.pathname;
    if (/zhipin/.test(location.hostname)) return /job_detail|geek\/job\b|job\/\d|geek\/jobs/.test(location.href);
    if (/51job/.test(location.hostname)) return /\/\d+\.html$|job/.test(p) && !/search|list/.test(p);
    if (/liepin/.test(location.hostname)) return /\/a\/\d+\.shtml|^\/job\//.test(p) && !/search|list|job\/search/.test(p);
    if (/zhaopin/.test(location.hostname)) return /jobdetail|job_detail/.test(location.href) || /^\/(job|jobdetail)\//.test(p);
    if (/yupao/.test(location.hostname)) return /zhaogong|zhaopin|job|gongzuo/.test(p) && !/search|list/.test(p);
    return false;
  }

  // ---- 通用解析器（51job / 猎聘 / 智联 / 鱼泡 共用文本锚点）----
  // 返回 rec，缺的字段进 selfDiag；快照会存全页文本，贰贰可逐平台精调。
  function parseGeneric(platform) {
    var rawT = (document.body && document.body.innerText) || (document.documentElement && document.documentElement.textContent) || '';
    var T = clean(rawT);
    var rec = {
      platform: platform, raw_id: '', url: location.href,
      grabbed_at: nowISO(), grabbed_from: 'full-page'
    };
    // 标题：优先 document.title（"岗位名 薪资 | 公司 | 平台"）截前段，再 h1/h2
    var title = '';
    var dt = (document.title || '').replace(/\s*[|｜]\s*/g, ' ').replace(/(招聘|前程无忧|BOSS直聘|猎聘网?|智联招聘)/g, ' ').trim();
    var NAV = /^(APP下载|在线简历|首页|搜索|登录|注册|我的|消息|职场资讯|企业培训|公司|校园|测评|商城)/;
    var h1 = document.querySelector('h1');
    if (h1) { var t1 = clean(h1.textContent).split(/\s/)[0]; if (t1 && t1.length >= 2 && t1.length <= 40 && !NAV.test(t1)) title = t1; }
    if (!title) {
      var hs = document.querySelectorAll('h1,h2,h3,[class*="job-title"],[class*="job-name"],[class*="tleft"],[class*="jname"],[class*="j_tit"]');
      for (var i = 0; i < hs.length; i++) {
        var ht = clean(hs[i].textContent).split(/\s/)[0];
        if (ht && ht.length >= 2 && ht.length <= 40 && !NAV.test(ht) && !/(公司|集团|招聘|首页|登录)/.test(ht)) { title = ht; break; }
      }
    }
    if (!title) {
      // 从 document.title 提取真正的岗位名。猎聘格式如"【杭州 电商渠道客户经理招聘】-猎头顾问..."，
      // 51job 如"岗位名招聘 | 城市 | 薪资 | 公司 | 平台"。统一剥掉【城市】、招聘、平台等噪音。
      var seg = dt.replace(/[【】\[\]]/g, ' ').split(/\s+/).filter(Boolean);
      // 去尾部噪音词，取第一个不含"招聘/平台名/城市/顾问"的段，再拼回岗位名
      var named = seg.filter(function (s) {
        return !/招聘|猎聘|前程无忧|BOSS直聘|智联招聘|猎头/ .test(s) && s.length >= 2;
      });
      // 常见：#城市# 开头，跳过纯城市段
      var CITIES = /^(北京|上海|广州|深圳|杭州|南京|苏州|宁波|武汉|成都|长沙|西安|重庆|天津|合肥|福州|厦门|青岛|济南|郑州|无锡|嘉兴|湖州|绍兴|金华|台州|温州|东莞|佛山|珠海|中山|泉州|昆明|贵阳|南昌|沈阳|大连|长春|哈尔滨|太原|兰州|全国)$/;
      var cand = named.find(function (s) { return !CITIES.test(s) && !/-/.test(s) && s.length >= 2; });
      if (cand && cand.length >= 2 && cand.length <= 40) title = cand;
      // 退而求其次：取第一个非城市段
      if (!title) {
        var seg2 = seg.find(function (s) { return !CITIES.test(s) && s.length >= 2 && !/\d/.test(s) && !NAV.test(s); });
        if (seg2) title = seg2;
      }
    }
    rec.title = (title || '').replace(/\s*[（(].*?[）)]\s*$/, '').trim();
    // 公司：href 含 company/gs/comp 的链接文本，或工商/公司名锚点
    var company = '';
    // 猎聘特化：页面上方常是猎头/中介公司，实际用人单位在"职位介绍"正文里（例如
    // "XX有限公司——品牌xx 岗位名"）。优先从职位介绍段落找全称，别信顶部猎头公司。
    if (platform === 'liepin') {
      var introIdx = T.indexOf('职位介绍');
      var introSeg = (introIdx !== -1 ? T.slice(introIdx, introIdx + 260) : T);
      var lm = introSeg.match(/([\u4e00-\u9fa5（）()]{2,28}?(?:有限公司|有限责任公司|股份有限公司|集团有限公司|集团))(?![\u4e00-\u9fa5])/);
      if (lm) { var ltmp = lm[0]; if(!/年|月|经验|本科|大专|以上/.test(ltmp)) company = ltmp.trim(); }
    }
    // 优先：全称（含 有限公司/集团）
    // 全称匹配：中文串内不得含 年/月/本科/经验 等 meta 词，避免粘连
    if (!company) {
      var mFull = T.match(/([\u4e00-\u9fa5（）()]{2,28}?(?:有限公司|有限责任公司|股份有限公司|集团有限公司|集团))(?![\u4e00-\u9fa5])/);
      if (mFull) { var tmp=mFull[0]; if(/年|月|经验|本科|大专|以上/.test(tmp)) mFull=null; }
      if (mFull) { company = mFull[0].trim(); }
    }
    if (!company) {
      var cLink = document.querySelector('a[href*="company"],a[href*="gs"],a[href*="/comp"],a[href*="gongsi"]');
      if (cLink) {
        var ct = clean(cLink.textContent);
        var cm2 = ct.match(/([\u4e00-\u9fa5]{2,20}?(?:公司|集团|科技|网络|电商|贸易|实业))/);
        company = cm2 ? cm2[0] : ct.split(/\s/)[0];
      }
    }
    rec.company = company || '';
    // 薪资：兼容 千/月 万/月 K 等
    var sm = T.match(/(\d+(?:\.\d+)?\s*[-~至到]\s*\d+(?:\.\d+)?\s*[Kk千万元万])|(\d+(?:\.\d+)?\s*[Kk千万元万]\s*[-~至到]\s*\d+(?:\.\d+)?\s*[Kk千万元万])|面议|薪资面议/);
    rec.salary = sm ? sm[0] : '';
    // 城市/经验/学历：标题后 200 字内
    var city='',exp='',edu='';
    var anchor = T;
    var cm = anchor.match(/(北京|上海|广州|深圳|杭州|南京|苏州|宁波|武汉|成都|长沙|西安|重庆|天津|合肥|福州|厦门|青岛|济南|郑州|无锡|嘉兴|湖州|绍兴|金华|台州|温州|东莞|佛山|珠海|中山|泉州|昆明|贵阳|南昌|沈阳|大连|长春|哈尔滨|太原|兰州)(?:\s*[-–·]?\s*)([\u4e00-\u9fa5]{2,8})?/);
    if (cm) { city = cm[1]; rec.district = (cm[2] && !/(年|月|本科|大专|硕士|博士|以上|经验|届|招)/.test(cm[2])) ? cm[2] : ''; }
    var em = anchor.match(/([\d]+\s*年(?:以上|以内)?|[\d]+\s*[-~至]\s*[\d]+\s*年|经验不限|无需经验|无经验|在校\/应届|应届生)/);
    if (em) exp = em[1].replace(/\s+/g, '');
    var edm = anchor.match(/(学历不限|本科|硕士|博士|大专|专科|中专|高中|初中)/);
    if (edm) edu = edm[1];
    rec.city = city||''; rec.experience = exp||''; rec.education = edu||'';
    // JD：职位描述/岗位职责/任职要求锚点切
    var duty='', req='';
    var dIdx = T.search(/职位描述|岗位职责|工作职责|岗位描述/);
    var rIdx = T.search(/任职要求|岗位要求|任职资格|职位要求/);
    var tailIdx = T.search(/工作地址|联系方式|公司介绍|相似职位|工商信息|投递|立即沟通|职能类别|职能|关键字|关键词|地图完整地址|点击查看地图|公司信息|温馨提示|安全提醒/);
    if (dIdx !== -1) {
      // 51job 页面顶部常有假"职位描述"标签（后面跟"竞争力分析微信分享"等杂词），
      // 真正的职责锚点是带序号/冒号的"一、岗位职责"等。从命中的位置往后找真锚点。
      var sub = T.slice(dIdx, dIdx + 200);
      var realD = sub.search(/(?:一、|二、|三、|四、|五、|六、)?(?:职位描述|岗位职责|工作职责|岗位描述)\s*[:：]/);
      var realIdx = realD !== -1 ? dIdx + realD : dIdx;
      var dEnd = (rIdx > realIdx && rIdx !== -1) ? rIdx : (tailIdx > realIdx && tailIdx !== -1 ? tailIdx : realIdx+600);
      duty = T.slice(realIdx, dEnd).replace(/^(?:一、|二、|三、|四、|五、|六、)?(?:职位描述|岗位职责|工作职责|岗位描述)\s*[:：]?/, '').trim();
    }
    if (rIdx !== -1) { var rEnd = (tailIdx > rIdx && tailIdx !== -1) ? tailIdx : rIdx+400; req = T.slice(rIdx, rEnd).replace(/^(任职要求|岗位要求|任职资格|职位要求)\s*[:：]?/, '').trim(); }
    rec.duty = duty; rec.requirements = req;
    // 地址
    var addr='';
    var am = T.match(/(工作地址|工作地点|上班地址)\s*[:：]?\s*([\u4e00-\u9fa5A-Za-z0-9\-–·号栋楼座园城路街道巷弄区镇室层#（）()]{4,60})/);
    if (am) addr = am[2].split(/[；;]|\d+、/)[0].trim();
    rec.location = addr || '';
    // 招聘官：51job 页面有 "职位招聘官" 后跟姓名
    var hm = T.match(/职位招聘官\s*[:：]?\s*\n?\s*([\u4e00-\u9fa5]{2,4})/);
    if (!hm) hm = T.match(/招聘官\s*[:：]?\s*([\u4e00-\u9fa5]{2,4})/);
    rec.hr_name = hm ? hm[1] : '';
    rec.biz = '';
    rec.selfDiag = { missing: ['company','title','salary','duty','requirements','location','city'].filter(function(k){return !rec[k];}) };
    var idm = location.pathname.match(/(\d{6,})(?:\.html?|$)|([A-Za-z0-9]{10,})/);
    rec.raw_id = idm ? (idm[1]||idm[2]) : urlHash(rec.title+'|'+rec.company);
    return rec;
  }

  // 多平台统一入口：分派到 Boss 专用解析或通用解析
  function extractJob(root) {
    var platform = detectPlatform();
    if (platform === 'boss') {
      return parseBossDetail(root);
    }
    if (!isDetailPage()) return null;
    return parseGeneric(platform);
  }

  // ------------------------------------------------------------------
  // 字段抓取
  // 传入"包含岗位详情的根元素"；缺省时自动定位当前详情面板。
  function parseBossDetail(root) {
    // 完整详情页模式：URL 含 /job_detail/ 或 geek/job/（词边界，排除 geek/jobs 列表页）→ 整页解析；否则右栏/列表页用详情面板
    var fullPage = /job_detail|geek\/job\b|job\/\d/.test(location.href);
    // 列表页（URL 是 geek/jobs 之类）：用 findDetailRoot 收敛到当前打开的详情面板
    var panel = null;
    if (!fullPage) {
      try { panel = findDetailRoot(); } catch (e) { panel = null; }
      if (panel && panel !== document) root = panel;
    }
    if (root === document) {
      root = document;
    }
    // 全文：必须用 body.innerText（document.textContent 规范上为空）
    // 若已收敛到面板，用面板内文本（更干净，不含列表噪音）
    var rawT = (root && root !== document && root.innerText) || (document.body && document.body.innerText) || (document.documentElement && document.documentElement.textContent) || '';
    // BOSS 薪资字体反爬：解码 PUA 数字
    var decoder = makeBossSalaryDecoder();
    if (decoder) rawT = decoder(rawT);
    var T = clean(rawT);
    var rec = {
      platform: 'boss',
      raw_id: '',
      url: location.href,
      grabbed_at: nowISO(),
      grabbed_from: fullPage ? 'full-page' : 'detail-panel'
    };

    // ---- 标题：完整页 h1；侧滑 h2 ----
    var title = '';
    var h1 = root.querySelector('h1');
    if (h1) { var t1 = clean(h1.textContent); if (t1 && t1.length <= 40) title = t1; }
    if (!title) {
      var hs = root.querySelectorAll('h2,h3,[class*="job-title"],[class*="job-name"],[class*="name"]');
      for (var i = 0; i < hs.length; i++) {
        var ht = clean(hs[i].textContent);
        if (ht && ht.length >= 2 && ht.length <= 30 && !/^(Boss|下载|打开|更多)/.test(ht)) { title = ht; break; }
      }
    }
    if (!title) {
      // 兜底1：从"收藏/立即沟通"（BOSS 岗位操作区）往前找标题，通常是岗位名
      var opsIdx = T.indexOf('收藏');
      var seg = opsIdx !== -1 ? T.slice(0, opsIdx) : T;
      var fm = seg.match(/([\u4e00-\u9fa5A-Za-z0-9（）()]{2,25})(?=\s*(?:杭州|北京|上海|广州|深圳|[\ue000-\uf8ff]|$))/);
      if (fm && !/^(首页|职位|公司|校园|海归|消息|简历|推荐|地图|搜索|登录|注册)/.test(fm[1])) title = fm[1].trim();
    }
    if (!title) {
      // 兜底2：第一个非导航非薪资的中文段
      var fm2 = T.match(/([\u4e00-\u9fa5A-Za-z0-9（）()]{2,25}?)\s*[\u4e00-\u9fa5A-Za-z0-9]/);
      if (fm2 && !/[\ue000-\uf8ff]/.test(fm2[1]) && !/[Kk]薪?$/.test(fm2[1]) && !/^(首页|职位|公司|校园|海归|消息|简历|推荐|地图|搜索|登录|注册)/.test(fm2[1])) title = fm2[1].trim();
    }
    rec.title = (title || '').replace(/\s*[（(].*?[）)]\s*$/, '').trim();

    // ---- 公司名：优先"工商信息→公司名称"后的全称；再取标题区品牌名；再全文全称兜底 ----
    var company = '';
    var bizIdx = T.indexOf('工商信息');
    if (bizIdx !== -1) {
      var afterBiz = T.slice(bizIdx, bizIdx + 120);
      var bizM = afterBiz.match(/公司名称\s*([\u4e00-\u9fa5（）()]{2,40}?(?:有限公司|有限责任公司|股份有限公司|集团))/);
      if (bizM) company = bizM[1].trim();
    }
    if (!company) {
      var compA = root.querySelector('a[href*="company"],a[href*="/gongsi/"],a[href*="/web/geek/company"]');
      if (compA) {
        var ct = clean(compA.textContent).replace(/[（(].*?[)）]/g, '').trim();
        if (ct && ct.length >= 2 && ct.length <= 30 && !/(查看|职位|公司基本信息)/.test(ct)) company = ct;
      }
    }
    if (!company) {
      var m2 = T.match(/(?:[\u4e00-\u9fa5]{1,8}[（(][\u4e00-\u9fa5]{1,8}[)）])?[\u4e00-\u9fa5]{2,16}(?:有限公司|有限责任公司|股份有限公司|集团有限公司|集团)/);
      if (m2) company = m2[0];
    }
    rec.company = company || '';

    // ---- 薪资：数字-数字 K/万/千 或 面议 ----
    var sal = '';
    var sm = T.match(/(\d+(?:\.\d+)?\s*[-~至到]\s*\d+(?:\.\d+)?\s*(?:[Kk千万元]|k))(?:[·\s]?(\d{2})薪)?|面议|薪资面议/);
    if (sm) sal = sm[0];
    // 去掉可能紧跟的公司名粘连
    sal = (sal || '').split(/[·\s](?=[\u4e00-\u9fa5])/)[0].trim();
    rec.salary = sal || '';

    // ---- meta：城市·区域·经验·学历（标题后第一段元信息）----
    var city='', district='', experience='', education='';
    // 从薪资出现位置向后 120 字符里找 meta
    var afterSal='';
    if (sm && sm.index != null) { afterSal = T.slice(sm.index, sm.index + 160); }
    else { afterSal = T.slice(0, 400); }
    var cityM = afterSal.match(/(北京|上海|广州|深圳|杭州|南京|苏州|宁波|武汉|成都|长沙|西安|重庆|天津|合肥|福州|厦门|青岛|济南|郑州|无锡|嘉兴|湖州|绍兴|金华|台州|温州|东莞|佛山|珠海|中山|泉州|昆明|贵阳|南昌|沈阳|大连|长春|哈尔滨|太原|兰州)(?:[·\-–]|\s)?([\u4e00-\u9fa5]{2,6}?)?/);
    if (cityM) { city = cityM[1]; if (cityM[2] && !/(本科|大专|硕士|经验|年)/.test(cityM[2])) district = cityM[2]; }
    var expM = afterSal.match(/(经验不限|在校\/应届|应届生|[\d]+\s*年(?:以上|以内)?|[\d]+\s*[-~至]\s*[\d]+\s*年)/);
    if (expM) experience = expM[1].replace(/\s+/g,'');
    var eduM = afterSal.match(/(学历不限|本科|硕士|博士|大专|专科|中专|高中|初中)/);
    if (eduM) education = eduM[1];
    rec.city = city; rec.district = district;
    rec.experience = experience || ''; rec.education = education || '';

    // ---- JD：按锚点切（职位描述→任职要求→工商信息/公司介绍→END）----
    var duty='', req='', extra='';
    var dIdx = T.search(/职位描述|岗位职责|工作职责|岗位描述/);
    var rIdx = T.search(/任职要求|岗位要求|任职资格/);
    var gsIdx = T.search(/工商信息|公司介绍|团队介绍|工作地址|工作地点|相似职位/);
    // 53job/Boss 详情页"职位描述"标签下常有技能标签云（如"媒介投放经验 KOL/达人投放"），
    // 真正职责正文在"一、岗位职责：/岗位职责："等带序号或冒号的锚点后。跳过标签云：
    if (dIdx !== -1) {
      var sub2 = T.slice(dIdx, dIdx + 260);
      var realD = sub2.search(/(?:一、|二、|三、|四、|五、|六、)?(?:岗位职责|工作职责|职位描述|岗位描述)\s*[：:]/);
      if (realD !== -1) dIdx = dIdx + realD;
      else {
        // 找不到带冒号的职责锚点，退而找"岗位职责"+标签后的真实开始（跳过技能标签段）
        var lab = sub2.search(/[\u4e00-\u9fa5A-Za-z\/]{2,40}经验\s+(?:[\u4e00-\u9fa5A-Za-z\/]{2,40}经验?\s*)+?(?:一、|岗位职责|工作职责)/);
        if (lab !== -1) dIdx = dIdx + lab;
      }
    }
    if (dIdx !== -1) {
      var dEnd = (rIdx !== -1 && rIdx > dIdx) ? rIdx : (gsIdx !== -1 && gsIdx > dIdx ? gsIdx : dIdx+400);
      duty = T.slice(dIdx, dEnd).replace(/^(?:一、|二、|三、|四、|五、|六、)?(?:职位描述|岗位职责|工作职责|岗位描述)\s*[:：]?/, '').trim();
    }
    if (rIdx !== -1) {
      var rEnd = (gsIdx !== -1 && gsIdx > rIdx) ? gsIdx : (rIdx+300);
      req = T.slice(rIdx, rEnd).replace(/^(任职要求|岗位要求|任职资格)\s*[:：]?/, '').trim();
    }
    // 去掉尾部"发布于/xx 人"等噪音
    duty = duty.replace(/\s*(发布于|更新于|刚刚|x 人看过).*$/, '');
    req = req.replace(/\s*(发布于|更新于|刚刚).*$/, '');
    rec.duty = duty; rec.requirements = req;

    // ---- 地址：优先"工作地点：xxx"；其次"工作地址 xxx" ----
    var addr = '';
    var aM = T.match(/工作地点\s*[:：]?\s*([\u4e00-\u9fa5A-Za-z0-9\-–·号栋楼座园城路街道巷弄区镇室层#（）()]+)/);
    if (!aM) aM = T.match(/工作地址\s*[:：]?\s*([\u4e00-\u9fa5A-Za-z0-9\-–·号栋楼座园城路街道巷弄区镇室层#（）()]+)/);
    if (aM) {
      addr = aM[1].split(/[；;]|\d+、|查看地图|相关推荐|地图/)[0].trim();
    }
    rec.location = addr || '';

    // ---- HR：找"名字 在线/活跃 … 人事/招聘者/HR" 模式 ----
    var hr='';
    var hrM = T.match(/([\u4e00-\u9fa5·]{2,5}(?:女士|先生|小姐)?)\s+(?:刚刚在线|在线|刚刚活跃|今日活跃|本周活跃|今日在线|本周在线)\s+[\u4e00-\u9fa5A-Za-z0-9·]{1,25}\s+·\s+(?:人事|招聘者|HR|招聘)/);
    if (hrM) hr = hrM[1].replace(/\s+/g,'').trim();
    if (!hr) {
      var hrM2 = T.match(/([\u4e00-\u9fa5·]{2,5})\s*·\s*(?:人事|招聘者|HR|招聘|BOSS)/);
      if (hrM2) hr = hrM2[1].replace(/\s+/g,'').trim();
    }
    rec.hr_name = hr;

    // ---- 工商信息：公司全称/法人/成立/注册资金 ----
    var biz='';
    var bIdx = T.search(/工商信息/);
    if (bIdx !== -1) {
      biz = T.slice(bIdx+4, bIdx+200).split(/相似职位|企业信息/)[0].replace(/\s{2,}/g,' ').trim().slice(0,160);
    }
    rec.biz = biz;

    rec.selfDiag = {
      missing: ['company','title','salary','duty','requirements','location','city']
        .filter(function(k){ return !rec[k]; })
    };
    var idm = (location.pathname+location.search).match(/(?:job_detail\/|jobId=|job\/)([^&/?]+)/i);
    rec.raw_id = idm ? idm[1].replace(/^job_detail\//,'') : urlHash(rec.title+'|'+rec.company+'|'+rec.salary);
    if (rec.raw_id.length > 32) rec.raw_id = urlHash(rec.raw_id);
    return rec;
  }


  function urlHash(s) {
    var h = 0;
    for (var i = 0; i < (s || '').length; i++) { h = ((h << 5) - h) + s.charCodeAt(i); h |= 0; }
    return ('x' + Math.abs(h)).toString(36).slice(0, 16);
  }

  // ------------------------------------------------------------------
  // BOSS 薪资字体反爬解码
  // BOSS 把数字映射到 Unicode 私有区（U+E031~E03A，每次请求随机），
  // 靠自定义字体在浏览器里渲染回数字。解法：canvas 用页面字体渲染
  // PUA 字符和标准数字 0-9，逐像素对比字形建立映射表。
  // 返回一个函数：把文本里的 PUA 数字替换回阿拉伯数字。
  function makeBossSalaryDecoder() {
    try {
      if (typeof document === 'undefined' || !document.body) return null;
      // 找薪资元素，拿到自定义字体名
      var salEl = null;
      var all = document.querySelectorAll('.job-salary,[class*="salary"],[class*="pay"],[class*="money"],div,span');
      for (var i = 0; i < all.length; i++) {
        var t = (all[i].textContent || '');
        if (/[\ue000-\uf8ff]/.test(t) && t.length < 60) { salEl = all[i]; break; }
      }
      if (!salEl) return null;
      var fontFamily = '';
      try { fontFamily = window.getComputedStyle(salEl).fontFamily || ''; } catch (e) {}
      if (!fontFamily) return null;
      var font = fontFamily.split(',')[0].trim().replace(/^['"]|['"]$/g, '');
      var fontSize = 32;
      try { var fs = parseFloat(window.getComputedStyle(salEl).fontSize); if (fs && fs > 8) fontSize = fs; } catch (e) {}

      var canvas = document.createElement('canvas');
      canvas.width = 80; canvas.height = 100;
      var ctx = canvas.getContext('2d');
      // 先确保自定义字体已加载，避免渲染成豆腐块
      var ok = false;
      if (document.fonts && document.fonts.check) {
        try { ok = document.fonts.check('32px ' + font); } catch (e) {}
      }
      if (!ok) return null;

      // 渲染 0-9 位图
      function bitmapOf(ch) {
        ctx.clearRect(0, 0, 80, 100);
        ctx.font = fontSize + 'px ' + font;
        ctx.textBaseline = 'top';
        ctx.fillText(ch, 8, 12);
        return ctx.getImageData(0, 0, 80, 100).data;
      }
      var digits = [];
      for (var d = 0; d <= 9; d++) digits.push(bitmapOf(String(d)));

      // 渲染 PUA 字符并与 0-9 对比，取相似度最高者
      var map = {};
      for (var cp = 0xe000; cp <= 0xf8ff; cp++) {
        var ch = String.fromCharCode(cp);
        var has = false;
        for (var j = 0; j < all.length; j++) { if ((all[j].textContent || '').indexOf(ch) !== -1) { has = true; break; } }
        if (!has) continue;
        var pb = bitmapOf(ch);
        var best = -1, bestScore = 0;
        for (var d2 = 0; d2 <= 9; d2++) {
          var same = 0, total = 0;
          var db = digits[d2];
          for (var k = 0; k < pb.length; k += 16) {
            var a = pb[k + 3] > 40 ? 1 : 0;
            var b = db[k + 3] > 40 ? 1 : 0;
            if (a === b) same++; else total++;
          }
          var score = same / Math.max(same + total, 1);
          if (score > bestScore) { bestScore = score; best = d2; }
        }
        if (bestScore > 0.85) map[cp] = String(best);
      }
      if (Object.keys(map).length === 0) return null;
      return function (text) {
        if (!text || !/[\ue000-\uf8ff]/.test(text)) return text;
        return Array.prototype.map.call(String(text), function (c) {
          var cp = c.charCodeAt(0);
          return (cp in map) ? map[cp] : c;
        }).join('');
      };
    } catch (e) { return null; }
  }

  // ------------------------------------------------------------------
  // 手动触发：注入悬浮按钮「+ 抓取」。点一下抓当前右栏岗位。
  // 不做 MutationObserver 自动抓——避免把不想要的岗位也收进来。
  // ------------------------------------------------------------------

  function grabCurrent(silent) {
    var rec = extractJob(document);
    if (!rec || !rec.title) {
      var pf = detectPlatform();
      toast('⚠ 当前不是岗位详情页（识别为 ' + pf + '），请先点开一个岗位详情');
      return null;
    }
    // 存浏览器本地（离线兜底）
    loadRecords(function (list) {
      var hit = list.some(function (r) { return (r.raw_id && rec.raw_id && r.raw_id === rec.raw_id); });
      if (!hit) {
        list.unshift(rec);
        if (list.length > 500) list.length = 500;
        saveRecords(list, function () {});
      }
    });
    // ===== 自动上报到本地服务（需 python run.py serve 在跑）=====
    var jd = (rec.duty || '') + (rec.requirements ? '\n\n任职要求：\n' + rec.requirements : '');
    var payload = {
      platform: rec.platform || detectPlatform(),
      company: rec.company || '',
      title: rec.title,
      salary_raw: rec.salary || '',
      city: rec.city || '',
      district: rec.district || '',
      experience: rec.experience || '',
      education: rec.education || '',
      jd: jd || '',
      address: rec.location || '',
      url: rec.url || '',
      hr_name: rec.hr_name || ''
    };
    var snapshot = {
      url: location.href,
      title: document.title,
      text: (document.body ? document.body.innerText : '').slice(0, 12000),
      parsed: rec,
      grabbed_at: nowISO()
    };
    var posted = false;
    var base = grabApiBase();
    try {
      fetch(base + '/api/jobs', grabFetchOpts('POST', payload)
      ).then(function(r){ return r.json(); }).then(function(d){
        posted = true;
        // 存快照供贰贰校准
        fetch(base + '/api/snapshot', grabFetchOpts('POST', snapshot)
        ).catch(function(){});
        var missing = (rec.selfDiag && rec.selfDiag.missing && rec.selfDiag.missing.length) ? '（缺:' + rec.selfDiag.missing.join('/') + '）' : '';
        toast('已抓取：' + rec.title + (d.result === 'new' ? ' [新增]' : (d.result === 'merged' ? ' [已合并]' : ' [重复]')) + missing);
      }).catch(function(e){
        toast('上报失败: ' + (e && e.message ? e.message : e) + '（目标 ' + base + '）');
      });
    } catch (e) {
      toast('已抓取(本地)，但自动上报失败: ' + e.message);
    }
    return rec;
  }

  // ---- 悬浮按钮 ----
  var BTN_ID = 'bossGrab_fab';
  function addFab() {
    if (document.getElementById(BTN_ID)) return;
    var fab = document.createElement('div');
    fab.id = BTN_ID;
    fab.textContent = '+ 抓取岗位';
    fab.title = '点一下，把当前右侧这个岗位收进 job-hub';
    fab.style.cssText =
      'position:fixed;right:22px;bottom:24px;z-index:2147483646;' +
      'background:#2563eb;color:#fff;border:none;border-radius:999px;' +
      'padding:10px 16px;font-size:14px;font-weight:600;cursor:pointer;' +
      'box-shadow:0 4px 16px rgba(37,99,235,.4);user-select:none;' +
      'font-family:system-ui,-apple-system,"Microsoft YaHei",sans-serif;' +
      'display:flex;align-items:center;gap:6px;';
    fab.innerHTML = '<span style="font-size:16px;line-height:1">＋</span><span>抓取岗位</span>';
    // 点击抓取
    fab.addEventListener('click', function (e) {
      e.preventDefault(); e.stopPropagation();
      grabCurrent();
    });
    // 可拖动
    makeDraggable(fab);
    document.body.appendChild(fab);
  }

  function makeDraggable(el) {
    var sx = 0, sy = 0, ox = 0, oy = 0, dragging = false;
    el.addEventListener('mousedown', function (e) {
      if (e.target.tagName === 'BUTTON' || e.target.closest('button')) return; // 保留按钮原生点击不拖
      dragging = true;
      sx = e.clientX; sy = e.clientY;
      var r = el.getBoundingClientRect();
      ox = r.right; oy = r.bottom;
      el.style.transition = 'none';
      e.preventDefault();
    });
    window.addEventListener('mousemove', function (e) {
      if (!dragging) return;
      var dx = e.clientX - sx, dy = e.clientY - sy;
      el.style.right = 'auto';
      el.style.bottom = 'auto';
      el.style.left = Math.max(0, ox + dx - el.offsetWidth) + 'px';
      el.style.top = Math.max(0, oy + dy - el.offsetHeight) + 'px';
    });
    window.addEventListener('mouseup', function () {
      if (dragging) {
        dragging = false;
        el.style.transition = '';
      }
    });
  }

  function start() {
    loadGrabCfg(function(){});  // 预加载抓取上报目标配置（云端/本地）
    addFab();
    // 拖拽停止后避免被 SPA 重渲染清掉：Boss 用 Vue/React，切岗位可能重建 body 子节点
    // 这里用一个轻量观察器，只负责"悬浮按钮没了就补回来"，不做抓取
    var guard = new MutationObserver(function () {
      if (!document.getElementById(BTN_ID)) addFab();
    });
    guard.observe(document.body, { childList: true, subtree: true });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }

  // ------------------------------------------------------------------
  // 浮层提示
  function toast(msg) {
    var el = document.getElementById(TOAST_ID);
    if (!el) {
      el = document.createElement('div');
      el.id = TOAST_ID;
      el.style.cssText =
        'position:fixed;right:24px;bottom:76px;z-index:2147483647;background:#111827;color:#fff;' +
        'padding:10px 16px;border-radius:8px;font-size:13px;box-shadow:0 4px 14px rgba(0,0,0,.25);' +
        'max-width:70%;pointer-events:none;opacity:0;transition:opacity .3s;' +
        'font-family:system-ui,sans-serif;';
      document.body.appendChild(el);
    }
    el.textContent = msg;
    el.style.opacity = '1';
    clearTimeout(el._t);
    el._t = setTimeout(function () { el.style.opacity = '0'; }, 2600);
  }

  // 暴露给 popup / 调试
  window.__bossGrabExtract = function () { return extractJob(document); };
  window.__bossGrabManual = function () { return grabCurrent(true); };

  // 响应 popup 的"抓当前页"
  chrome.runtime.onMessage.addListener(function (msg, sender, sendResponse) {
    if (msg && msg.type === 'BOSSGRAB_MANUAL') {
      var r = grabCurrent();
      if (r) sendResponse({ title: r.title }); else sendResponse({ title: '' });
      return false;
    }
  });
})();
