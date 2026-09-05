// popup 逻辑
var STORE_KEY = 'bossGrab_records';
var SESSION_KEY = 'bossGrab_session'; // {token, username}

function load(cb) {
  chrome.storage.local.get(STORE_KEY, function (o) { cb(o[STORE_KEY] || []); });
}
function save(list, cb) {
  var o = {}; o[STORE_KEY] = list; chrome.storage.local.set(o, function () { cb && cb(); });
}

// ===== 登录逻辑 =====
var loginForm = document.getElementById('login-form');
var userInfo = document.getElementById('user-info');
var loggedUser = document.getElementById('logged-user');
var loginBtn = document.getElementById('login-btn');
var loginHint = document.getElementById('login-hint');
var logoutBtn = document.getElementById('logout-btn');

function showLoginHint(msg, isErr) {
  loginHint.textContent = msg;
  loginHint.style.color = isErr ? '#dc2626' : '#16a34a';
}

function getServerBase() {
  // 默认云端，不可改
  return 'https://pathtojob.icu:8765';
}

function checkLogin() {
  chrome.storage.local.get(SESSION_KEY, function (o) {
    var s = o && o[SESSION_KEY];
    if (s && s.username) {
      loginForm.style.display = 'none';
      userInfo.style.display = '';
      loggedUser.textContent = s.username;
    } else {
      loginForm.style.display = '';
      userInfo.style.display = 'none';
    }
  });
}

loginBtn.addEventListener('click', function () {
  var u = document.getElementById('l-user').value.trim();
  var p = document.getElementById('l-pwd').value;
  if (!u || !p) { showLoginHint('请输入用户名和密码', true); return; }
  loginBtn.disabled = true;
  loginBtn.textContent = '登录中…';
  showLoginHint('', false);

  var base = getServerBase();
  fetch(base + '/api/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: u, password: p }),
    credentials: 'include'
  }).then(function (r) { return r.json(); }).then(function (d) {
    loginBtn.disabled = false;
    loginBtn.textContent = '登录云端';
    if (!d.ok) { showLoginHint(d.error || '登录失败', true); return; }
    var o = {}; o[SESSION_KEY] = { token: 'cookie', username: u };
    chrome.storage.local.set(o, function () {
      checkLogin();
      showLoginHint('', false);
    });
  }).catch(function (e) {
    loginBtn.disabled = false;
    loginBtn.textContent = '登录云端';
    showLoginHint('网络错误', true);
  });
});

logoutBtn.addEventListener('click', function () {
  var base = getServerBase();
  fetch(base + '/api/logout', { method: 'POST', credentials: 'include' }).catch(function () {});
  chrome.storage.local.remove(SESSION_KEY, function () { checkLogin(); });
});

checkLogin();

// ===== 列表逻辑 =====
var listEl = document.getElementById('list');
var countEl = document.getElementById('count');
var toastEl = document.getElementById('toast');

function showToast(msg) {
  toastEl.textContent = msg;
  toastEl.style.opacity = '1';
  clearTimeout(showToast._t);
  showToast._t = setTimeout(function () { toastEl.style.opacity = '0'; }, 1800);
}

function esc(s) {
  return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function render(list) {
  countEl.textContent = list.length + ' 条';
  if (!list.length) {
    listEl.innerHTML = '<div class="empty">还没抓到岗位。<br>去 Boss直聘 点开一个岗位详情，<br>会自动抓取；或点上方「抓当前页」。</div>';
    return;
  }
  listEl.innerHTML = '';
  list.forEach(function (r, idx) {
    var d = document.createElement('div');
    d.className = 'item';
    var diag = r.selfDiag && r.selfDiag.missing && r.selfDiag.missing.length
      ? '<span style="color:#d97706"> ⚠缺:' + esc(r.selfDiag.missing.join('/')) + '</span>' : '';
    d.innerHTML =
      '<div class="info">' +
        '<div class="t">' + esc(r.title || '(未识别标题)') + '</div>' +
        '<div class="sub">' + esc(r.company || '?') + ' · ' + esc(r.salary || '?') +
          (r.location ? ' · ' + esc(r.location) : '') + ' · ' + esc(r.grabbed_at || '') + diag + '</div>' +
      '</div>' +
      '<button class="del" title="删除">&times;</button>';
    d.querySelector('.del').addEventListener('click', function () {
      list.splice(idx, 1);
      save(list, function () { render(list); });
    });
    listEl.appendChild(d);
  });
}

function refresh() { load(render); }

function buildTsv(list) {
  var lines = ['公司\t岗位\t薪资\t城市\t经验\t学历'];
  list.forEach(function (r) {
    lines.push([
      r.company || '', r.title || '', r.salary || '',
      r.location || '', r.experience || '', r.education || ''
    ].join('\t'));
  });
  return lines.join('\n');
}

document.getElementById('copyTsv').addEventListener('click', function () {
  load(function (list) {
    if (!list.length) { showToast('还没有记录'); return; }
    copyText(buildTsv(list));
    showToast('已复制 ' + list.length + ' 条');
  });
});

document.getElementById('clear').addEventListener('click', function () {
  if (!confirm('清空全部已抓岗位？')) return;
  save([], function () { render([]); showToast('已清空'); });
});

document.getElementById('manual').addEventListener('click', function () {
  chrome.tabs.query({ active: true, currentWindow: true }, function (tabs) {
    var tab = tabs && tabs[0];
    if (!tab) { showToast('无法获取当前标签'); return; }
    chrome.tabs.sendMessage(tab.id, { type: 'BOSSGRAB_MANUAL' }, function (resp) {
      if (chrome.runtime.lastError || !resp) {
        showToast('当前页不是招聘网站，或需刷新后重试');
        return;
      }
      refresh();
      showToast(resp.title ? ('已抓取：' + resp.title) : '本页未识别到岗位详情');
    });
  });
});

function copyText(text) {
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(function () {}, function () { fallback(text); });
  } else fallback(text);
}
function fallback(text) {
  var ta = document.createElement('textarea');
  ta.value = text; document.body.appendChild(ta); ta.select();
  document.execCommand('copy'); document.body.removeChild(ta);
}

refresh();
