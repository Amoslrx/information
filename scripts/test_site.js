/* ============================================================
   站点自检(Node, 零依赖)。
   为什么需要它: 本机沙箱禁止 Chrome/Edge 启动(需要命名管道做进程间通信),
   无法用真实浏览器做渲染验证。于是用最小 DOM 桩在 Node 里跑 app.js,
   抓取它写进 innerHTML 的内容做断言。

   覆盖:
     A. index.html 里被 app.js 引用的元素 id 是否都存在(防拼写错误)
     B. app.js 能否无异常跑完初始化
     C. 渲染结果的关键统计与抽样内容是否正确
     D. 筛选 / 排序 / 搜索逻辑是否符合预期

   运行: node scripts/test_site.js
   ============================================================ */
'use strict';

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = path.resolve(__dirname, '..');
const SITE = path.join(ROOT, 'site');

let pass = 0, fail = 0;
const failures = [];

function ok(cond, label, detail) {
  if (cond) { pass++; console.log('  ✓ ' + label); }
  else { fail++; failures.push(label + (detail ? ' — ' + detail : '')); console.log('  ✗ ' + label + (detail ? ' — ' + detail : '')); }
}

/* ---------- 最小 DOM 桩 ---------- */
/* 真实 DOM 对 innerHTML / textContent 赋值会做字符串强制转换,
   桩也照做, 否则会报出浏览器里根本不存在的"类型错误"。 */
function makeEl(id) {
  const attrs = Object.create(null);
  const el = {
    id: id, value: '', checked: false,
    hidden: false, style: {}, href: '',
    tagName: '', children: [],
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    addEventListener() {},
    appendChild(child) { el.children.push(child); return child; },
    removeChild(child) {
      const i = el.children.indexOf(child);
      if (i >= 0) el.children.splice(i, 1);
      return child;
    },
    querySelectorAll() { return []; },
    querySelector() { return null; },
    // 真实属性存储: data-* 这类状态必须能读回来,
    // 否则"分类切换"之类依赖属性的逻辑在测试里完全看不见。
    setAttribute(k, v) { attrs[k] = String(v); },
    getAttribute(k) {
      return Object.prototype.hasOwnProperty.call(attrs, k) ? attrs[k] : null;
    },
    removeAttribute(k) { delete attrs[k]; },
    closest() { return null; },
  };
  let _html = '', _text = '';
  Object.defineProperty(el, 'innerHTML', {
    get() { return _html; },
    set(v) { _html = v == null ? '' : String(v); },
  });
  Object.defineProperty(el, 'textContent', {
    get() { return _text; },
    set(v) { _text = v == null ? '' : String(v); },
  });
  return el;
}

function makeDom(selectDefaults) {
  const els = Object.create(null);
  const created = [];
  const document = {
    readyState: 'complete',
    body: makeEl('body'),
    getElementById(id) {
      if (!els[id]) {
        const e = makeEl(id);
        // 真实浏览器里 <select> 没有 selected 时取第一个 option 的值。
        // 桩必须照做, 否则"默认筛选状态"这类 bug 在测试里根本暴露不出来。
        if (selectDefaults && Object.prototype.hasOwnProperty.call(selectDefaults, id)) {
          e.value = selectDefaults[id];
        }
        els[id] = e;
      }
      return els[id];
    },
    querySelectorAll() { return []; },
    querySelector() { return null; },
    addEventListener() {},
    createElement(tag) {
      const e = makeEl(null);
      e.tagName = String(tag).toUpperCase();
      created.push(e);
      return e;
    },
  };
  return { document, els, created };
}

// 从 index.html 解析每个 <select> 的默认值(第一个 option)。
// 惰性求值: html 在文件后面才读取, 这里不能直接引用。
let _selectDefaults = null;
function getSelectDefaults() {
  if (_selectDefaults) return _selectDefaults;
  _selectDefaults = {};
  for (const m of html.matchAll(/<select\s+id="([^"]+)"[^>]*>([\s\S]*?)<\/select>/g)) {
    const first = m[2].match(/<option\s+value="([^"]*)"/);
    _selectDefaults[m[1]] = first ? first[1] : '';
  }
  return _selectDefaults;
}

/* ---------- 载入 ---------- */
const html = fs.readFileSync(path.join(SITE, 'index.html'), 'utf8');
const appSrc = fs.readFileSync(path.join(SITE, 'app.js'), 'utf8');
const dataSrc = fs.readFileSync(path.join(SITE, 'data.js'), 'utf8');

console.log('=== A. HTML / JS 一致性 ===');

// app.js 里 $('xxx') 用到的 id
const usedIds = new Set();
for (const m of appSrc.matchAll(/\$\('([A-Za-z0-9_\-]+)'\)/g)) usedIds.add(m[1]);
// document.getElementById / querySelector 直接调用
for (const m of appSrc.matchAll(/getElementById\('([A-Za-z0-9_\-]+)'\)/g)) usedIds.add(m[1]);

const htmlIds = new Set();
for (const m of html.matchAll(/\sid="([^"]+)"/g)) htmlIds.add(m[1]);

const missing = [...usedIds].filter(id => !htmlIds.has(id));
ok(missing.length === 0, 'app.js 引用的 id 全部存在于 index.html',
   missing.length ? '缺失: ' + missing.join(', ') : '');

// app.js 里用到的 class 选择器(仅查 .xxx 形式)
const usedCls = new Set();
for (const m of appSrc.matchAll(/querySelectorAll\('\.([A-Za-z0-9_\-]+)'\)/g)) usedCls.add(m[1]);
const cssSrc = fs.readFileSync(path.join(SITE, 'style.css'), 'utf8');
const styledCls = new Set();
for (const m of cssSrc.matchAll(/\.([A-Za-z][A-Za-z0-9_\-]*)/g)) styledCls.add(m[1]);
const unstyled = [...usedCls].filter(c => !styledCls.has(c));
ok(unstyled.length === 0, 'app.js 用到的 class 在 CSS 里有定义',
   unstyled.length ? '未定义: ' + unstyled.join(', ') : '');

// 三个 view 的 id 与 tab 的 data-view 对得上
const views = new Set([...html.matchAll(/id="view-([a-z]+)"/g)].map(m => m[1]));
const tabViews = new Set([...html.matchAll(/data-view="([a-z]+)"/g)].map(m => m[1]));
const viewMismatch = [...tabViews].filter(v => !views.has(v)).concat(
  [...views].filter(v => !tabViews.has(v)));
ok(viewMismatch.length === 0, 'tab 的 data-view 与 section id 一一对应',
   viewMismatch.length ? '不匹配: ' + viewMismatch.join(', ') : '');

console.log('\n=== B. 用 DOM 桩运行 app.js ===');

/** 在给定 location 下跑一遍 app.js, 返回它写出的 DOM 内容。 */
function runApp(loc) {
  const dom = makeDom(getSelectDefaults());
  const historyCalls = [];
  const windowObj = {
    scrollTo() {},
    history: { replaceState(a, b, url) { historyCalls.push(url); } },
  };
  const sandbox = {
    window: windowObj, document: dom.document, console, URL,
    Date, Math, JSON, String, Number, RegExp, Array, Object,
    isFinite, parseInt, parseFloat, setTimeout,
    location: Object.assign({ hash: '', pathname: '/', search: '' }, loc),
    navigator: { clipboard: null },
  };
  vm.createContext(sandbox);
  vm.runInContext(dataSrc, sandbox, { filename: 'data.js' });
  vm.runInContext(appSrc, sandbox, { filename: 'app.js' });
  return { els: dom.els, created: dom.created, windowObj, historyCalls };
}

// 线上部署(Netlify 根域名)
const REMOTE = {
  href: 'https://xjtu-ee.netlify.app/',
  protocol: 'https:',
  hostname: 'xjtu-ee.netlify.app',
};
// GitHub Pages 子路径, 用来验证不写死域名的写法是否成立
const SUBPATH = {
  href: 'https://someone.github.io/comp-site/',
  protocol: 'https:',
  hostname: 'someone.github.io',
};
// 本地直接双击打开
const LOCAL = {
  href: 'file:///F:/site/index.html',
  protocol: 'file:',
  hostname: '',
};

let els, created, windowObj, remoteHistory = [], initError = null;
try {
  const r = runApp(REMOTE);
  els = r.els; created = r.created; windowObj = r.windowObj; remoteHistory = r.historyCalls;
} catch (e) {
  initError = e;
}
ok(!initError, 'app.js 初始化无异常', initError ? initError.message : '');
if (initError) { console.log('\n' + initError.stack); process.exit(1); }

const DATA = windowObj.SITE_DATA;
ok(!!DATA && Array.isArray(DATA.competitions), 'data.js 注入 window.SITE_DATA');
console.log('    数据: 竞赛 %d / 通知 %d', DATA.competitions.length, DATA.notices.length);

console.log('\n=== C. 渲染结果断言 ===');

const catHTML = els.catList.innerHTML || '';
const noticeHTML = els.noticeList.innerHTML || '';
const headHTML = els.headStats.innerHTML || '';

const cardCount = (catHTML.match(/class="card /g) || []).length;
ok(cardCount === DATA.competitions.length,
   `默认渲染全部 ${DATA.competitions.length} 张竞赛卡片`, '实际 ' + cardCount);

// 通知页默认只显示"竞赛相关"(过滤掉行政/教学通知)
const noticeCount = (noticeHTML.match(/class="notice"/g) || []).length;
const compRelated = DATA.notices.filter(n => n.isCompetition).length;
ok(noticeCount === compRelated,
   `默认只渲染竞赛相关通知 ${compRelated} 条`, '实际 ' + noticeCount);
ok(noticeCount < DATA.notices.length,
   '默认过滤掉了非竞赛通知', `${noticeCount} / ${DATA.notices.length}`);
ok(noticeHTML.includes('badge b-site'), '通知渲染了来源徽章');

ok(/共 \d+ 条/.test(els.resultCount.textContent || ''), '结果计数已写入');
ok(els.tabCountCat.textContent === String(DATA.competitions.length), 'tab 上的竞赛数正确',
   'tabCountCat=' + els.tabCountCat.textContent);
ok(els.tabCountNotice.textContent === String(DATA.notices.length), 'tab 上的通知数正确');

// 头部统计
ok(headHTML.includes(String(DATA.competitions.length)), '头部统计含竞赛数');
ok(headHTML.includes(String(DATA.notices.length)), '头部统计含通知数');

// 抽样: 相关度 5 分的核心赛事必须在默认列表里
const core = ['全国大学生电子设计竞赛', '全国大学生数学建模竞赛', '“西门子杯”中国智能制造挑战赛'];
core.forEach(function (name) {
  ok(catHTML.includes(name), '核心赛事在列表中: ' + name);
});

// 徽章渲染
ok(catHTML.includes('badge b-ee5'), '渲染了相关度 5 分徽章');
ok(catHTML.includes('badge b-a'), '渲染了西交 A 类徽章');
ok(catHTML.includes('badge b-moe'), '渲染了教育部目录徽章');

// 通知分组与关联
ok(noticeHTML.includes('group-head'), '通知按月分组渲染');
ok(noticeHTML.includes('badge-link'), '通知渲染了「对应竞赛」可点击徽章');
ok(noticeHTML.includes('target="_blank"'), '通知链接为新窗口打开');

// 说明页
ok((els.caveatList.innerHTML || '').includes('旧版'), '说明页列出数据缺陷');
ok((els.sourceList.innerHTML || '').includes('教育部'), '说明页列出数据来源');
ok((els.footMeta.textContent || '').includes('数据生成于'), '页脚含数据生成时间');

console.log('\n=== D. 年度节律与日历 ===');

const rhythmHTML = els.rhythmList.innerHTML || '';
const chartHTML = els.monthChart.innerHTML || '';

ok(els.tabCountRhythm.textContent === String(DATA.cadenceCount),
   'tab 上的节律数正确', 'tabCountRhythm=' + els.tabCountRhythm.textContent);

const barCount = (chartHTML.match(/class="bar-col/g) || []).length;
ok(barCount === 12, '月度柱状图渲染 12 根柱子', '实际 ' + barCount);

const histSum = Object.keys(DATA.monthHistogram || {})
  .reduce((a, k) => a + DATA.monthHistogram[k], 0);
ok(histSum === DATA.stats.notices, '月度分布合计等于通知总数',
   histSum + ' vs ' + DATA.stats.notices);

// 节律页默认按"电气相关度 >= 4"筛选(下拉第一个选项), 所以不是全部 37 个
const cadAll = DATA.competitions.filter(c => c.cadence);
const cadCore = cadAll.filter(c => (c.ee || 0) >= 4);
const rcardCount = (rhythmHTML.match(/class="rcard[" ]/g) || []).length;
ok(rcardCount === cadCore.length,
   `默认按相关度>=4渲染节律卡片 ${cadCore.length} 张`,
   rcardCount + ' vs ' + cadCore.length);
ok(cadCore.length < cadAll.length, '节律默认过滤掉了相关度较低的竞赛',
   `${cadCore.length} / ${cadAll.length}`);

// 同理: 没有附加 class 的格子是 class="ms", 有附加的是 class="ms …", 两者都要算
const stripCells = (rhythmHTML.match(/class="ms[" ]/g) || []).length;
ok(stripCells === rcardCount * 12, '每张节律卡片有 12 个月份格',
   stripCells + ' vs ' + (rcardCount * 12));

ok(/高峰是/.test(els.rhythmInsight.innerHTML || ''), '生成了高峰月洞察文案');
ok((els.rhythmCaveat.textContent || '').includes('不是官方赛程'), '节律页标注了推断性质');

// 下拉框: 按"挂在哪个 select 上"判断, 不要靠在 created 里的顺序
const monthOpts = (els.rMonth.children || []).filter(e => e.tagName === 'OPTION');
ok(monthOpts.length === 12, '月份下拉填充了 12 个选项', '实际 ' + monthOpts.length);
ok(monthOpts.length === 12 && monthOpts[0].textContent === '一 月' &&
   monthOpts[11].textContent === '十二 月',
   '月份下拉选项文案正确',
   monthOpts.length === 12 ? monthOpts[0].textContent + ' … ' + monthOpts[11].textContent : '');

// 来源下拉: 由数据里实际出现的来源动态生成
const siteOpts = (els.nSite.children || []).filter(e => e.tagName === 'OPTION');
const siteNames = Object.keys(DATA.stats.bySite || {});
ok(siteOpts.length === siteNames.length,
   `来源下拉填充了 ${siteNames.length} 个来源`,
   '实际 ' + siteOpts.length);

// 日历文件存在且事件数对得上
const calDir = path.join(SITE, 'calendar');
['all.ics', 'ee-core.ics'].forEach(function (fn) {
  const p = path.join(calDir, fn);
  ok(fs.existsSync(p), '日历文件存在: ' + fn);
  if (!fs.existsSync(p)) return;
  const ics = fs.readFileSync(p, 'utf8');
  ok(ics.startsWith('BEGIN:VCALENDAR'), fn + ' 以 BEGIN:VCALENDAR 开头');
  ok(ics.trimEnd().endsWith('END:VCALENDAR'), fn + ' 以 END:VCALENDAR 结尾');
  ok(ics.includes('\r\n'), fn + ' 使用 CRLF 换行(符合 RFC 5545)');
  const evs = (ics.match(/BEGIN:VEVENT/g) || []).length;
  ok(evs === (ics.match(/END:VEVENT/g) || []).length, fn + ' VEVENT 开闭配对');
  ok(evs > 0, fn + ' 含事件', '实际 ' + evs);
  const maxLen = Math.max(...ics.split('\r\n').map(l => Buffer.byteLength(l, 'utf8')));
  ok(maxLen <= 75, fn + ' 行长不超 75 字节', '实际 ' + maxLen);
  // 每个事件必须有稳定 UID、年度重复、提前提醒
  ok((ics.match(/^UID:/gm) || []).length === evs, fn + ' 每个事件都有 UID');
  ok((ics.match(/^RRULE:FREQ=YEARLY$/gm) || []).length === evs, fn + ' 每个事件都是年度重复');
  ok((ics.match(/^TRIGGER:-P\d+D$/gm) || []).length === evs, fn + ' 每个事件都有提前提醒');
  // UID 不得是 Python hash() 那种随机值(纯数字大整数)
  const uids = ics.match(/^UID:(.+)$/gm) || [];
  const suspicious = uids.filter(u => /^UID:xjtu-ee-comp-\d{6,}@/.test(u));
  ok(suspicious.length === 0, fn + ' UID 为确定性值(非 hash() 随机数)',
     suspicious.slice(0, 2).join(', '));
  // 日历事件数不得超过可推断节律的竞赛数
  ok(evs <= DATA.cadenceCount, fn + ' 事件数不超过节律竞赛数');
});

// 节律字段完整性
const cad = DATA.competitions.filter(c => c.cadence);
ok(cad.length === DATA.cadenceCount, '自带节律的竞赛数与统计一致',
   cad.length + ' vs ' + DATA.cadenceCount);
const badWin = cad.filter(c => {
  const w = c.cadence;
  return !(w.windowStart >= 1 && w.windowStart <= 12 && w.windowEnd >= 1 && w.windowEnd <= 12);
});
ok(badWin.length === 0, '节律窗口月份取值合法', badWin.length ? badWin.length + ' 条越界' : '');
const badCov = cad.filter(c => c.cadence.coverage < 0.6);
ok(badCov.length === 0, '节律窗口覆盖率均 >= 60%', badCov.length ? badCov.length + ' 条不足' : '');
const badYears = cad.filter(c => c.cadence.yearsObserved < 2);
ok(badYears.length === 0, '节律样本年数均 >= 2',
   badYears.length ? badYears.map(c => c.name).join(', ') : '');

// 跨年窗口判定(如 12–1 月)不能漏
function inWin(c, m) {
  const s = c.cadence.windowStart, e = c.cadence.windowEnd;
  return s <= e ? (m >= s && m <= e) : (m >= s || m <= e);
}
const wrap = cad.filter(c => c.cadence.windowStart > c.cadence.windowEnd);
ok(wrap.every(c => inWin(c, 12) && inWin(c, 1)),
   '跨年窗口(如 12–1 月)判定正确',
   wrap.length ? '检查 ' + wrap.map(c => c.name).join(', ') : '(无跨年窗口)');

console.log('\n=== E. 筛选 / 排序 / 搜索逻辑 ===');

// 直接复用 app.js 里的口径做独立复算, 与渲染出的卡数对比
function countByOwn(eeMin, cat, moe, recentOnly) {
  const DAY = 86400000;
  const t = new Date(); const today = new Date(t.getFullYear(), t.getMonth(), t.getDate());
  return DATA.competitions.filter(function (c) {
    if (eeMin && !(c.ee != null && c.ee >= eeMin)) return false;
    if (cat === '__unknown') { if (c.xjtuCat !== '未认定(待核)') return false; }
    else if (cat && c.xjtuCat !== cat) return false;
    if (moe === 'yes' && !c.inMoe) return false;
    if (moe === 'no' && c.inMoe) return false;
    if (recentOnly) {
      if (!c.latestNotice) return false;
      const d = new Date(c.latestNotice.date + 'T00:00:00');
      if (Math.round((today - d) / DAY) > 90) return false;
    }
    return true;
  }).length;
}

// 这些是数据层的口径, 用来确认 app.js 拿到的字段齐备
const ee5 = DATA.competitions.filter(c => c.ee === 5).length;
ok(ee5 === 10, '相关度 5 分共 10 条', '实际 ' + ee5);

const withUrl = DATA.competitions.filter(c => c.url).length;
ok(withUrl === 83, '含官网 URL 共 83 条', '实际 ' + withUrl);

const matched = DATA.notices.filter(n => n.competition).length;
ok(matched === DATA.stats.noticesMatched, '通知关联数与统计一致',
   matched + ' vs ' + DATA.stats.noticesMatched);

const unknown = countByOwn(0, '__unknown');
const known = DATA.competitions.length - unknown;
ok(known === 19, '有西交认定的共 19 条', '实际 ' + known);

// 日期解析健壮性: 所有通知日期都必须是 YYYY-MM-DD
const badDate = DATA.notices.filter(n => !/^\d{4}-\d{2}-\d{2}$/.test(n.date));
ok(badDate.length === 0, '所有通知日期格式合法', badDate.length ? badDate.length + ' 条异常' : '');

// 所有通知 URL 都必须是绝对地址
const badUrl = DATA.notices.filter(n => !/^https?:\/\//.test(n.url));
ok(badUrl.length === 0, '所有通知 URL 为绝对地址', badUrl.length ? badUrl.slice(0, 2).map(x => x.url).join(', ') : '');

// 竞赛名唯一(抽屉按名称索引, 重名会导致点错)
const names = DATA.competitions.map(c => c.name);
const dup = names.filter((n, i) => names.indexOf(n) !== i);
ok(dup.length === 0, '竞赛名称唯一(抽屉按名索引)', dup.length ? dup.join(', ') : '');

// 每条通知关联的竞赛名必须能在竞赛表里找到
const nameSet = new Set(names);
const orphan = DATA.notices.filter(n => n.competition && !nameSet.has(n.competition));
ok(orphan.length === 0, '通知关联的竞赛名都能在竞赛表中找到',
   orphan.length ? orphan.length + ' 条孤儿, 例: ' + orphan[0].competition : '');

console.log('\n=== F. 部署相关 ===');

// 订阅网址必须是绝对地址, 否则日历 App 抓不到
const uCore = els.urlCore.value || '';
const uAll = els.urlAll.value || '';
ok(/^https:\/\/xjtu-ee\.netlify\.app\/calendar\/ee-core\.ics$/.test(uCore),
   '电气核心日历给出绝对订阅网址', uCore);
ok(/^https:\/\/xjtu-ee\.netlify\.app\/calendar\/all\.ics$/.test(uAll),
   '全部日历给出绝对订阅网址', uAll);
ok((els.calUrlHint.textContent || '').indexOf('可订阅') >= 0,
   '线上环境提示可直接订阅',
   (els.calUrlHint.textContent || '').slice(0, 30));

// 子路径部署(GitHub Pages)不能写死域名
let sub = null;
try { sub = runApp(SUBPATH); } catch (e) { /* 下面断言会失败并显示原因 */ }
ok(!!sub && /^https:\/\/someone\.github\.io\/comp-site\/calendar\/all\.ics$/
     .test(sub.els.urlAll.value || ''),
   'GitHub Pages 子路径下网址正确(未写死域名)',
   sub ? sub.els.urlAll.value : 'runApp 抛异常');

// 本地打开要给提示, 而不是给一个不能用的地址
let loc = null;
try { loc = runApp(LOCAL); } catch (e) { /* 同上 */ }
ok(!!loc && (loc.els.calUrlHint.textContent || '').indexOf('本地') >= 0,
   '本地打开时提示不能真正订阅',
   loc ? (loc.els.calUrlHint.textContent || '').slice(0, 30) : 'runApp 抛异常');
ok(!!loc && /^file:\/\/\/.*\/calendar\/all\.ics$/.test(loc.els.urlAll.value || ''),
   '本地打开时网址仍由 location 正确推导',
   loc ? loc.els.urlAll.value : 'runApp 抛异常');

// _headers: 没有正确的 MIME, 日历订阅在 Netlify 上会失败
const headersPath = path.join(SITE, '_headers');
ok(fs.existsSync(headersPath), '存在 site/_headers(drag&drop 部署也生效)');
if (fs.existsSync(headersPath)) {
  const h = fs.readFileSync(headersPath, 'utf8');
  ok(/text\/calendar/.test(h), '_headers 为 .ics 指定 text/calendar');
  ok(/\/calendar\/\*\.ics/.test(h), '_headers 覆盖 /calendar/*.ics');
}

// netlify.toml: Git 部署时的构建配置
const tomlPath = path.join(ROOT, 'netlify.toml');
ok(fs.existsSync(tomlPath), '存在 netlify.toml');
if (fs.existsSync(tomlPath)) {
  const t = fs.readFileSync(tomlPath, 'utf8');
  ok(/publish\s*=\s*"site"/.test(t), 'netlify.toml 发布目录为 site');
}

// data.js 里写的日历路径必须真的存在
const calRefs = [DATA.calendar && DATA.calendar.all, DATA.calendar && DATA.calendar.eeCore];
calRefs.forEach(function (rel) {
  ok(!!rel && fs.existsSync(path.join(SITE, rel)), 'data.js 引用的日历文件存在: ' + rel);
});

// 发布目录里不该混入不该公开的东西
const forbidden = ['data.js.bak', '.env', 'node_modules'];
forbidden.forEach(function (f) {
  if (f === 'node_modules') return;   // 目录, 单独判断
  ok(!fs.existsSync(path.join(SITE, f)), '发布目录无 ' + f);
});
ok(!fs.existsSync(path.join(SITE, 'node_modules')), '发布目录无 node_modules');

// 所有发布资源的引用都是小写(Netlify/Linux 区分大小写, Windows 不区分, 本地测不出)
const htmlRefs = [...html.matchAll(/(?:src|href)="([^"#:]+)"/g)]
  .map(m => m[1]).filter(r => !/^https?:/.test(r));
const badCase = htmlRefs.filter(r => r !== r.toLowerCase() && !/[\u4e00-\u9fa5]/.test(r));
ok(badCase.length === 0, 'HTML 引用的资源路径大小写安全(线上 Linux 区分大小写)',
   badCase.join(', '));

// 标签页 hash 路由: #rhythm 应能直接激活对应标签(404 页也靠它跳转)
let hashRun = null;
try { hashRun = runApp({ href: 'https://x.netlify.app/#rhythm', protocol: 'https:',
                         hostname: 'x.netlify.app', hash: '#rhythm', pathname: '/' }); }
catch (e) { /* 断言会失败 */ }
ok(!!hashRun && hashRun.historyCalls.indexOf('#rhythm') >= 0,
   '支持 #rhythm 之类 hash 直接进入标签页',
   hashRun ? JSON.stringify(hashRun.historyCalls) : 'runApp 抛异常');

// 无 hash 时不应改写地址
ok(remoteHistory.length === 0, '默认(无 hash)不写入 history',
   JSON.stringify(remoteHistory));

console.log('\n=== G. 常用网站 ===');

const linkHTML = els.linkList.innerHTML || '';
const LINKS = DATA.quickLinks || [];

ok(LINKS.length > 0, '载入了常用网站数据', LINKS.length + ' 个');
ok(els.tabCountLinks.textContent === String(LINKS.length),
   'tab 上的常用网站数正确', 'tabCountLinks=' + els.tabCountLinks.textContent);

const lcardCount = (linkHTML.match(/class="lcard"/g) || []).length;
ok(lcardCount === LINKS.length, `默认渲染全部 ${LINKS.length} 个网站卡片`,
   '实际 ' + lcardCount);

// 每张卡片必须有可点的跳转链接和可用的复制按钮(这是用户明确要的功能)
ok((linkHTML.match(/class="btn-primary btn-sm"/g) || []).length === LINKS.length,
   '每个网站都有「点击跳转」按钮');
ok((linkHTML.match(/class="cal-copy" data-url=/g) || []).length === LINKS.length,
   '每个网站都有带 data-url 的「复制地址」按钮');
ok((linkHTML.match(/class="lurl"/g) || []).length === LINKS.length,
   '每个网站都显示了完整网址');

// 所有网址必须是绝对地址(复制出去要能直接用)
const badLinkUrl = LINKS.filter(l => !/^https?:\/\//.test(l.url || ''));
ok(badLinkUrl.length === 0, '所有网站网址都是绝对地址',
   badLinkUrl.map(l => l.name).join(', '));

// 名称/网址不得重复。**忽略协议**比较: 同一个站常同时有 http/https 两个版本
// (实践教学中心就出现过), 只比字符串会漏掉这类重复。
const linkKey = u => String(u || '').trim().toLowerCase()
  .replace(/^https?:\/\//, '').replace(/^www\./, '').replace(/\/+$/, '');
const dupKey = LINKS.map(l => linkKey(l.url));
const dupUrl = dupKey.filter((u, i, a) => a.indexOf(u) !== i);
ok(dupUrl.length === 0, '没有重复的网址(忽略协议与 www)',
   [...new Set(dupUrl)].join(', '));

const dupName = LINKS.map(l => l.name).filter((n, i, a) => a.indexOf(n) !== i);
ok(dupName.length === 0, '没有重名的网站', [...new Set(dupName)].join(', '));

// 分类: chips 数量 = 分类数 + 1(全部)
const chipHTML = els.linkChips.innerHTML || '';
const chipCount = (chipHTML.match(/class="chip/g) || []).length;
const cats = [...new Set(LINKS.map(l => l.category))];
ok(chipCount === cats.length + 1,
   `分类 chips = 分类数 + 1(全部)`, `${chipCount} vs ${cats.length + 1}`);
ok(chipHTML.includes('全部'), 'chips 含「全部」');
// 每个条目都要有分类, 否则会从分类视图里消失
const noCat = LINKS.filter(l => !l.category);
ok(noCat.length === 0, '每个网站都有分类', noCat.map(l => l.name).join(', '));

// 复制功能的降级路径: 「复制地址」按钮旁边没有 input, 必须能临时造 textarea
ok(/createElement\('textarea'\)/.test(appSrc),
   '复制降级路径会临时创建 textarea(应对无 input 的按钮)');
ok(/navigator\.clipboard/.test(appSrc), '优先使用 clipboard API');

console.log('\n' + '='.repeat(52));
console.log(`通过 ${pass} 项, 失败 ${fail} 项`);
if (fail) {
  console.log('\n失败项:');
  failures.forEach(f => console.log('  - ' + f));
  process.exit(1);
}
console.log('全部通过。');
