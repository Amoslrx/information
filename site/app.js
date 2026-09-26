/* ============================================================
   西交电气 · 竞赛信息站 — 前端逻辑
   零依赖。数据来自 window.SITE_DATA (由 scripts/build_site_data.py 生成)。
   ============================================================ */
(function () {
  'use strict';

  var D = window.SITE_DATA || {};
  var COMPS = D.competitions || [];
  var NOTICES = D.notices || [];
  var STATS = D.stats || {};

  var FRESH_DAYS = 90;          // "近期有通知"的判定阈值
  var UNKNOWN_CAT = '未认定(待核)';

  /* ---------------- 工具 ---------------- */

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function today() {
    var d = new Date();
    return new Date(d.getFullYear(), d.getMonth(), d.getDate());
  }

  function parseDate(s) {
    var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s || '');
    return m ? new Date(+m[1], +m[2] - 1, +m[3]) : null;
  }

  function daysSince(s) {
    var d = parseDate(s);
    if (!d) return Infinity;
    return Math.round((today() - d) / 86400000);
  }

  function agoText(days) {
    if (!isFinite(days)) return '';
    if (days < 0) return '未来';
    if (days === 0) return '今天';
    if (days === 1) return '昨天';
    if (days < 30) return days + ' 天前';
    if (days < 365) return Math.floor(days / 30) + ' 个月前';
    return Math.floor(days / 365) + ' 年前';
  }

  function isFresh(dateStr) { return daysSince(dateStr) <= FRESH_DAYS; }

  /** 距目标日期还有多少天(未来为正)。 */
  function daysUntil(dateStr) {
    var d = parseDate(dateStr);
    if (!d) return null;
    return Math.round((d - today()) / 86400000);
  }

  /** "2026-10-15" -> "10月15日" */
  function fmtDeadline(dateStr) {
    var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(dateStr || '');
    return m ? (+m[2]) + '月' + (+m[3]) + '日' : (dateStr || '');
  }

  function $(id) { return document.getElementById(id); }

  /* ---------------- 搜索匹配 ---------------- */

  /**
   * 搜索用的文本归一化。
   *
   * 朴素子串匹配在中文里很难用: 标题常写成「四、六级」「"挑战杯"」
   * 「全国大学生（电子设计）竞赛」, 用户输入「四六级」「挑战杯」就搜不到。
   * 所以两边都先归一化 —— 全角转半角、去掉所有标点与空白 —— 再比较,
   * 这样「四、六级」与「四六级」归一化后是同一个串。
   */
  var PUNCT_RE = /[\s\-_.,;:!?'"`~@#$%^&*()\[\]{}<>\/\\|+=、，。；：！？""''《》〈〉【】〔〕（）·—…￥　]/g;

  function normText(s) {
    return String(s == null ? '' : s)
      .replace(/[\uFF01-\uFF5E]/g, function (ch) {   // 全角 ASCII -> 半角
        return String.fromCharCode(ch.charCodeAt(0) - 0xFEE0);
      })
      .toLowerCase()
      .replace(PUNCT_RE, '');
  }

  /**
   * 归一化后再包含匹配; 不中时退回"顺序子序列"匹配,
   * 于是「电赛」也能搜到「电子设计竞赛」。
   * 返回 2 = 包含(精确), 1 = 模糊(子序列), 0 = 不匹配。
   */
  function matchScore(hay, needle) {
    if (!needle) return 2;
    if (hay.indexOf(needle) >= 0) return 2;
    if (needle.length < 2) return 0;      // 单字的模糊匹配噪声太大, 不做
    var i = 0;
    for (var j = 0; j < hay.length && i < needle.length; j++) {
      if (hay[j] === needle[i]) i++;
    }
    return i === needle.length ? 1 : 0;
  }

  /** 把若干字段拼成已归一化的搜索串。 */
  function haystack(parts) {
    return normText(parts.filter(Boolean).join(' '));
  }

  /* ---------------- 徽章 ---------------- */

  function eeClass(ee) { return 'b-ee' + (ee || 1); }

  function eeBadge(ee) {
    if (ee == null) return '';
    var label = ee === 5 ? '5 · 电气核心' : ee + ' 分';
    return '<span class="badge ' + eeClass(ee) + '">' + label + '</span>';
  }

  function catBadge(cat) {
    if (!cat) return '';
    if (cat === UNKNOWN_CAT) {
      return '<span class="badge b-unk" title="西交旧名单里没有此赛事，不代表学校未认定">未认定（待核）</span>';
    }
    var cls = cat === 'A类' ? 'b-a' : (cat === 'B类' ? 'b-b' : (cat === 'C类' ? 'b-c' : 'b-unk'));
    var tip = cat === 'C类' ? ' title="电气工程学院认定的 C 类竞赛"' : '';
    return '<span class="badge ' + cls + '"' + tip + '>西交 ' + esc(cat) + '</span>';
  }

  function moeBadge(c) {
    return c.inMoe
      ? '<span class="badge b-moe" title="在教育部目录内">教育部目录 #' + esc(c.moeNo) + '</span>'
      : '<span class="badge b-level">不在教育部目录</span>';
  }

  /* ---------------- 顶部统计 ---------------- */

  function renderHead() {
    $('headStats').innerHTML = [
      ['竞赛条目', STATS.competitions],
      ['电气相关(≥4)', countEE(4)],
      ['可报名', (COMPS.filter(function (c) { return c.isRecruiting; })).length],
      ['校内通知', STATS.notices]
    ].map(function (p) {
      return '<div class="stat"><b>' + p[1] + '</b><span>' + p[0] + '</span></div>';
    }).join('');
    $('tabCountCat').textContent = String(STATS.competitions || 0);
    $('tabCountNotice').textContent = String(STATS.notices || 0);
    $('tabCountRhythm').textContent = String(D.cadenceCount || 0);
    $('tabCountLinks').textContent = String((D.quickLinks || []).length);

    $('footMeta').textContent = '数据生成于 ' + (D.generatedAt || '—') +
      '｜竞赛 ' + (STATS.competitions || 0) + ' 条、通知 ' + (STATS.notices || 0) +
      ' 条（抓取 ' + (STATS.crawledPages || 0) + ' 页，' +
      (STATS.noticeFrom || '—') + ' ~ ' + (STATS.noticeTo || '—') + '）';
  }

  function countEE(min) {
    return COMPS.filter(function (c) { return c.ee != null && c.ee >= min; }).length;
  }

  /* ---------------- 标签页 ---------------- */

  function activateView(name, doScroll) {
    var tabs = document.querySelectorAll('.tab');
    var views = document.querySelectorAll('.view');
    Array.prototype.forEach.call(tabs, function (x) {
      x.classList.toggle('is-active', x.getAttribute('data-view') === name);
    });
    Array.prototype.forEach.call(views, function (v) {
      v.classList.toggle('is-active', v.id === 'view-' + name);
    });
    if (doScroll) {
      try { window.scrollTo({ top: 0, behavior: 'smooth' }); }
      catch (e) { try { window.scrollTo(0, 0); } catch (e2) { /* 忽略 */ } }
    }
    // 让标签页可以分享(例如群里发一句"看年度节律"直接给链接),
    // 404 页面也靠这个跳转。用 replaceState 避免每次点击都留历史记录。
    try {
      var url = (name === 'catalog')
        ? location.pathname + location.search
        : '#' + name;
      if (window.history && window.history.replaceState) {
        window.history.replaceState(null, '', url);
      }
    } catch (e) { /* file:// 下可能受限, 忽略 */ }
  }

  function initTabs() {
    var tabs = document.querySelectorAll('.tab');
    Array.prototype.forEach.call(tabs, function (t) {
      t.addEventListener('click', function () {
        activateView(t.getAttribute('data-view'), true);
      });
    });
    // 支持用 #rhythm / #notices / #about 直接进入对应标签
    var h = String(location.hash || '').replace(/^#/, '');
    if (h && document.getElementById('view-' + h)) {
      activateView(h, false);
    }
  }

  /* ---------------- 竞赛目录 ---------------- */

  function readCatFilters() {
    return {
      q: $('q').value.trim().toLowerCase(),
      ee: $('fEE').value,
      cat: $('fCat').value,
      moe: $('fMoe').value,
      sort: $('fSort').value,
      recent: $('fRecent').checked,
      open: $('fOpen').checked
    };
  }

  function filterComps(f) {
    return COMPS.filter(function (c) {
      // "可报名" = 有未过期截止时间, 或正在校内选拔
      if (f.open && !c.isRecruiting) return false;
      if (f.ee && !(c.ee != null && c.ee >= +f.ee)) return false;
      if (f.cat === '__unknown') { if (c.xjtuCat !== UNKNOWN_CAT) return false; }
      else if (f.cat && c.xjtuCat !== f.cat) return false;
      if (f.moe === 'yes' && !c.inMoe) return false;
      if (f.moe === 'no' && c.inMoe) return false;
      if (f.recent && !(c.latestNotice && isFresh(c.latestNotice.date))) return false;
      if (f.q) {
        var hay = haystack([c.name, c.alias, c.organizer, c.reason, c.dept,
                            c.domain, c.contact,
                            c.moeNo ? String(c.moeNo) : '']);
        if (matchScore(hay, normText(f.q)) === 0) return false;
      }
      return true;
    });
  }

  function sortComps(list, how) {
    var byEE = function (a, b) { return (b.ee || 0) - (a.ee || 0); };
    var arr = list.slice();
    if (how === 'ee') {
      arr.sort(function (a, b) { return byEE(a, b) || a.name.localeCompare(b.name, 'zh'); });
    } else if (how === 'deadline') {
      // 可报名的排最前(有明确截止的按截止日由近到远), 其余按相关度
      arr.sort(function (a, b) {
        var oa = a.isRecruiting ? 1 : 0, ob = b.isRecruiting ? 1 : 0;
        if (oa !== ob) return ob - oa;
        var da = a.openDeadline || '', db = b.openDeadline || '';
        if (da && db) return da.localeCompare(db);
        if (da !== db) return db ? 1 : -1;
        return byEE(a, b);
      });
    } else if (how === 'recent') {
      arr.sort(function (a, b) {
        var da = a.latestNotice ? a.latestNotice.date : '';
        var db = b.latestNotice ? b.latestNotice.date : '';
        if (da !== db) return db > da ? 1 : -1;
        return byEE(a, b);
      });
    } else if (how === 'notices') {
      arr.sort(function (a, b) { return (b.noticeCount || 0) - (a.noticeCount || 0) || byEE(a, b); });
    } else if (how === 'moe') {
      arr.sort(function (a, b) {
        var ma = a.moeNo == null ? 9999 : a.moeNo;
        var mb = b.moeNo == null ? 9999 : b.moeNo;
        return ma - mb;
      });
    } else if (how === 'name') {
      arr.sort(function (a, b) { return a.name.localeCompare(b.name, 'zh'); });
    }
    return arr;
  }

  function renderCatalog() {
    var f = readCatFilters();
    var list = sortComps(filterComps(f), f.sort);

    $('resultCount').textContent = '共 ' + list.length + ' 条' +
      (list.length !== COMPS.length ? '（总 ' + COMPS.length + ' 条）' : '');

    $('catEmpty').hidden = list.length > 0;
    $('catList').innerHTML = list.map(cardHTML).join('');

    Array.prototype.forEach.call($('catList').querySelectorAll('.card'), function (el) {
      el.addEventListener('click', function (ev) {
        // 点官网链接时不打开抽屉
        if (ev.target.closest('a')) return;
        openCompDrawer(el.getAttribute('data-name'));
      });
    });
  }

  function cardHTML(c) {
    var fresh = c.latestNotice && isFresh(c.latestNotice.date);
    var alias = c.alias ? ' <span class="alias">（西交名单：' + esc(c.alias) + '）</span>' : '';

    var meta = [];
    if (c.organizer) meta.push('<span><span class="k">主办</span> ' + esc(c.organizer) + '</span>');
    if (c.dept) meta.push('<span><span class="k">归口</span> ' + esc(c.dept) + '</span>');
    if (c.level) meta.push('<span><span class="k">级别</span> ' + esc(c.level) + '</span>');

    var foot = [];
    if (c.url) {
      foot.push('<a class="link-official" href="' + esc(c.url) + '" target="_blank" ' +
                'rel="noopener">官网 ' + esc(c.domain || '链接') + ' ↗</a>');
    }
    // 可报名: 最显眼的位置。两种来源分开说清楚, 不含糊
    if (c.isOpen) {
      foot.unshift('<span class="open-tag">报名中 · ' + fmtDeadline(c.openDeadline) +
                   ' 截止（还剩 ' + daysUntil(c.openDeadline) + ' 天）</span>');
    } else if (c.isSelecting) {
      var sn = c.selectNotice || {};
      foot.unshift('<span class="open-tag is-select">校内选拔中 · ' +
                   esc(sn.date || '') + ' 发布通知</span>');
    }
    if (c.latestNotice) {
      foot.push('<span class="notice-tag' + (fresh ? ' is-fresh' : '') + '">' +
                '最新通知 ' + esc(c.latestNotice.date) +
                '（' + agoText(daysSince(c.latestNotice.date)) + '）· 共 ' +
                c.noticeCount + ' 条</span>');
    } else {
      foot.push('<span class="notice-tag">暂无关联通知</span>');
    }
    if (c.campusNoticeCount) {
      foot.push('<span class="notice-tag is-campus">校内选拔 ' + c.campusNoticeCount + ' 条</span>');
    }

    return '' +
      '<article class="card ee' + (c.ee || 1) +
        (c.isOpen ? ' is-open' : (c.isSelecting ? ' is-selecting' : '')) +
        '" data-name="' + esc(c.name) + '">' +
        '<div class="card-top">' +
          '<h3 class="card-title">' + esc(c.name) + alias + '</h3>' +
        '</div>' +
        '<div class="badges">' +
          (c.isOpen ? '<span class="badge b-open">报名中</span>' : '') +
          (c.isSelecting ? '<span class="badge b-select">校内选拔中</span>' : '') +
          eeBadge(c.ee) + catBadge(c.xjtuCat) + moeBadge(c) +
          (c.dept ? '<span class="badge b-dept">' + esc(c.dept) + '</span>' : '') +
        '</div>' +
        (meta.length ? '<div class="card-meta">' + meta.join('') + '</div>' : '') +
        (c.reason ? '<p class="card-reason">' + esc(c.reason) + '</p>' : '') +
        '<div class="card-foot">' + foot.join('') + '</div>' +
      '</article>';
  }

  /* ---------------- 抽屉详情 ---------------- */

  function openCompDrawer(name) {
    var c = null;
    for (var i = 0; i < COMPS.length; i++) { if (COMPS[i].name === name) { c = COMPS[i]; break; } }
    if (!c) return;

    var rel = NOTICES.filter(function (n) { return n.competition === c.name; })
                     .sort(function (a, b) { return b.date.localeCompare(a.date); });

    var rows = [
      ['电气相关度', c.ee != null ? c.ee + ' / 5' : '—'],
      ['西交认定', c.xjtuCat],
      ['级别', c.level || '—'],
      ['归口部门', c.dept || '—'],
      ['专项负责人', c.contact || '—'],
      ['教育部目录', c.inMoe ? '在目录内（第 ' + c.moeNo + ' 项）' : '不在 84 项目录内'],
      ['主办单位', c.organizer || '—'],
      ['西交名单用名', c.alias || '—'],
      ['数据来源', c.source || '—']
    ].map(function (r) {
      return '<div class="d-row"><span class="k">' + r[0] + '</span>' +
             '<span class="v">' + esc(r[1]) + '</span></div>';
    }).join('');

    var noticesHTML = rel.length
      ? rel.slice(0, 30).map(function (n) {
          return '<a class="d-notice" href="' + esc(n.url) + '" target="_blank" rel="noopener">' +
                 esc(n.title) + '<span class="dd">' + esc(n.date) +
                 '（' + agoText(daysSince(n.date)) + '）</span></a>';
        }).join('') + (rel.length > 30 ? '<p class="muted">仅显示最近 30 条</p>' : '')
      : '<p class="muted">没有匹配到校内通知。可能是该赛事近年未办，或通知标题里没有出现可识别的赛名。</p>';

    $('drawerBody').innerHTML =
      '<h2>' + esc(c.name) + '</h2>' +
      '<div class="badges">' + eeBadge(c.ee) + catBadge(c.xjtuCat) + moeBadge(c) +
        (c.level ? '<span class="badge b-level">' + esc(c.level) + '</span>' : '') + '</div>' +
      (c.reason ? '<p class="card-reason" style="margin-top:12px">' + esc(c.reason) + '</p>' : '') +
      '<div class="d-sec"><h3>基本信息</h3>' + rows + '</div>' +
      '<div class="d-sec"><h3>相关校内通知（' + rel.length + '）</h3>' + noticesHTML + '</div>' +
      '<div class="d-actions">' +
        (c.url ? '<a class="btn-primary" href="' + esc(c.url) + '" target="_blank" rel="noopener">前往官网 ↗</a>' : '') +
      '</div>';

    $('drawer').hidden = false;
    $('overlay').hidden = false;
    document.body.style.overflow = 'hidden';
  }

  function closeDrawer() {
    $('drawer').hidden = true;
    $('overlay').hidden = true;
    document.body.style.overflow = '';
  }

  /* ---------------- 校内通知 ---------------- */

  function readNoticeFilters() {
    return {
      q: $('nq').value.trim().toLowerCase(),
      scope: $('nScope').value,
      site: $('nSite').value,
      range: $('nRange').value,
      sort: $('nSort').value
    };
  }

  function renderNotices() {
    var f = readNoticeFilters();
    var list = NOTICES.filter(function (n) {
      if (f.scope === 'competition' && !n.isCompetition) return false;
      if (f.scope === 'campus' && !n.isCampus) return false;
      if (f.scope === 'deadline' && !n.deadline) return false;
      if (f.scope === 'matched' && !n.competition) return false;
      if (f.scope === 'unmatched' && n.competition) return false;
      if (f.site && n.site !== f.site) return false;
      if (f.range && daysSince(n.date) > +f.range) return false;
      if (f.q && matchScore(haystack([n.title, n.competition, n.site]),
                            normText(f.q)) === 0) return false;
      return true;
    });

    list.sort(function (a, b) {
      return f.sort === 'dateAsc' ? a.date.localeCompare(b.date) : b.date.localeCompare(a.date);
    });

    $('noticeCount').textContent = '共 ' + list.length + ' 条' +
      (list.length !== NOTICES.length ? '（总 ' + NOTICES.length + ' 条）' : '');
    $('noticeEmpty').hidden = list.length > 0;

    // 按年月分组
    var out = [], lastGroup = null;
    list.forEach(function (n) {
      var g = n.date.slice(0, 7);
      if (g !== lastGroup) {
        out.push('<div class="group-head">' + g.replace('-', ' 年 ') + ' 月</div>');
        lastGroup = g;
      }
      var sub = [];
      if (n.site) {
        sub.push('<span class="badge b-site">' + esc(n.site) + '</span>');
      }
      if (n.deadline) {
        var dl = daysUntil(n.deadline);
        var dlCls = dl !== null && dl >= 0 ? 'deadline-tag is-open' : 'deadline-tag';
        sub.push('<span class="' + dlCls + '">报名截止 ' + fmtDeadline(n.deadline) +
                 (dl !== null && dl >= 0 ? '（还剩 ' + dl + ' 天）' : '（已过）') + '</span>');
      }
      if (n.isCampus) sub.push('<span class="badge b-campus">校内选拔</span>');
      if (n.competition) {
        sub.push('<button class="badge-link" data-name="' + esc(n.competition) + '">' +
                 '对应：' + esc(n.competition) + '</button>');
      } else {
        sub.push('<span class="badge b-unk">未关联到竞赛</span>');
      }
      if (isFresh(n.date)) sub.push('<span class="fresh-dot">NEW</span>');

      out.push(
        '<div class="notice">' +
          '<span class="notice-date">' + esc(n.date) + '</span>' +
          '<div class="notice-main">' +
            '<a class="notice-title" href="' + esc(n.url) + '" target="_blank" rel="noopener">' +
              esc(n.title) + '</a>' +
            '<div class="notice-sub">' + sub.join('') + '</div>' +
          '</div>' +
        '</div>');
    });

    $('noticeList').innerHTML = out.join('');

    Array.prototype.forEach.call($('noticeList').querySelectorAll('.badge-link'), function (b) {
      b.addEventListener('click', function () { openCompDrawer(b.getAttribute('data-name')); });
    });
  }

  /* ---------------- 年度节律 ---------------- */

  var MONTH_CN = ['一', '二', '三', '四', '五', '六',
                  '七', '八', '九', '十', '十一', '十二'];

  function calCompetitions() {
    return COMPS.filter(function (c) { return !!c.cadence; });
  }

  function inWindow(cad, m) {
    var s = cad.windowStart, e = cad.windowEnd;
    if (s <= e) return m >= s && m <= e;
    return m >= s || m <= e;              // 跨年窗口, 如 12–1 月
  }

  function renderMonthChart() {
    var hist = D.monthHistogram || {};
    var vals = [];
    for (var m = 1; m <= 12; m++) vals.push(hist[String(m)] || 0);
    var max = Math.max.apply(null, vals.concat([1]));
    var total = vals.reduce(function (a, b) { return a + b; }, 0);

    // 找出高峰月(计数 >= 最大值的 60%)
    var peak = [];
    for (var i = 0; i < 12; i++) { if (vals[i] >= max * 0.6 && vals[i] > 0) peak.push(i + 1); }

    var nowMonth = new Date().getMonth() + 1;

    $('monthChart').innerHTML = vals.map(function (v, i) {
      var m = i + 1;
      var h = max ? Math.round((v / max) * 100) : 0;
      var cls = 'bar-col';
      if (peak.indexOf(m) >= 0) cls += ' is-peak';
      if (m === nowMonth) cls += ' is-now';
      return '<div class="' + cls + '" title="' + MONTH_CN[i] + '月：' + v + ' 条通知">' +
               '<span class="bar-num">' + (v || '') + '</span>' +
               '<div class="bar" style="height:' + h + '%"></div>' +
               '<span class="bar-lbl">' + MONTH_CN[i] + '</span>' +
             '</div>';
    }).join('');

    var peakTxt = peak.map(function (m) { return m + ' 月'; }).join('、');
    $('rhythmInsight').innerHTML =
      '共 ' + total + ' 条校内通知（2018–2026）。<strong>发通知的高峰是 ' + peakTxt +
      '</strong>，这个窗口最该盯紧。当前是 <strong>' + nowMonth + ' 月</strong>' +
      (peak.indexOf(nowMonth) >= 0 ? '，正在高峰期内。' : '。');
    $('monthChartNote').textContent =
      '深色为高峰月，蓝色描边为当前月份。数据来源：实践教学中心竞赛栏目历史通知。';
  }

  function renderRhythm() {
    var all = calCompetitions();
    var f = {
      q: $('rq').value.trim().toLowerCase(),
      month: $('rMonth').value,
      ee: $('rEE').value,
      sort: $('rSort').value
    };

    var list = all.filter(function (c) {
      if (f.ee && !(c.ee != null && c.ee >= +f.ee)) return false;
      if (f.month && !inWindow(c.cadence, +f.month)) return false;
      if (f.q && matchScore(haystack([c.name]), normText(f.q)) === 0) return false;
      return true;
    });

    if (f.sort === 'months') {
      list.sort(function (a, b) {
        return a.cadence.windowStart - b.cadence.windowStart ||
               (b.ee || 0) - (a.ee || 0);
      });
    } else if (f.sort === 'ee') {
      list.sort(function (a, b) { return (b.ee || 0) - (a.ee || 0); });
    } else {
      list.sort(function (a, b) { return b.cadence.yearsObserved - a.cadence.yearsObserved; });
    }

    $('rhythmCount').textContent = '共 ' + list.length + ' 个竞赛有年度节律' +
      (list.length !== all.length ? '（总 ' + all.length + ' 个）' : '');
    $('rhythmEmpty').hidden = list.length > 0;

    var nowMonth = new Date().getMonth() + 1;

    $('rhythmList').innerHTML = list.map(function (c) {
      var cad = c.cadence;
      var strip = '';
      for (var m = 1; m <= 12; m++) {
        var cls = 'ms';
        if (inWindow(cad, m)) cls += ' in-win';
        if ((cad.stableMonths || []).indexOf(m) >= 0) cls += ' is-stable';
        if (m === nowMonth && inWindow(cad, m)) cls += ' is-now';
        strip += '<i class="' + cls + '" title="' + MONTH_CN[m - 1] + '月：' +
                 ((cad.months || {})[String(m)] || 0) + ' 条">' +
                 '<span>' + MONTH_CN[m - 1].slice(0, 1) + '</span></i>';
      }
      var confTxt = { high: '样本充足', medium: '样本中等', low: '样本偏少' }[cad.confidence] || '';
      var isNow = inWindow(cad, nowMonth);

      return '' +
        '<div class="rcard' + (isNow ? ' is-now' : '') + '" data-name="' + esc(c.name) + '">' +
          '<div class="rcard-main">' +
            '<h3>' + esc(c.name) + (isNow ? ' <span class="badge b-now">本月窗口</span>' : '') + '</h3>' +
            '<div class="badges">' + eeBadge(c.ee) + catBadge(c.xjtuCat) +
              '<span class="badge b-level">往年 ' + esc(cad.windowLabel) + '</span>' +
              '<span class="badge b-uniq">' + cad.yearsObserved + ' 年 · ' + confTxt + '</span>' +
            '</div>' +
          '</div>' +
          '<div class="mstrip" role="img" aria-label="通知月份分布">' + strip + '</div>' +
        '</div>';
    }).join('');

    Array.prototype.forEach.call($('rhythmList').querySelectorAll('.rcard'), function (el) {
      el.addEventListener('click', function () { openCompDrawer(el.getAttribute('data-name')); });
    });
  }

  /* ---------------- 日历订阅网址 ---------------- */

  /**
   * 把相对路径转成可订阅的绝对网址。
   * 订阅必须用绝对网址: 日历 App 会定期回来抓取, 给它相对路径或本地文件都没用。
   * 用 new URL(..., location.href) 而不是写死域名, 这样本地预览 / Netlify 根域名 /
   * GitHub Pages 子路径都能正确工作。
   */
  function absUrl(rel) {
    try {
      return new URL(rel, location.href).href;
    } catch (e) {
      return rel;
    }
  }

  function isLocal() {
    try {
      return location.protocol === 'file:' ||
             /^(localhost|127\.0\.0\.1|\[::1\])$/.test(location.hostname);
    } catch (e) {
      return false;
    }
  }

  function copyText(text, btn) {
    var flash = function (msg) {
      var old = btn.textContent;
      btn.textContent = msg;
      btn.classList.add('is-done');
      setTimeout(function () {
        btn.textContent = old;
        btn.classList.remove('is-done');
      }, 1600);
    };
    var fallback = function () {
      var ok = false;
      var input = btn.parentNode ? btn.parentNode.querySelector('input') : null;
      if (input) {
        // 日历订阅那种: 旁边就有一个 readonly input
        var ro = input.readOnly;
        input.readOnly = false;
        input.select();
        if (input.setSelectionRange) input.setSelectionRange(0, input.value.length);
        try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
        input.readOnly = ro;
      } else {
        // 「复制地址」按钮旁边没有 input, 临时造一个 textarea 来选中复制
        var ta = document.createElement('textarea');
        ta.value = text;
        ta.setAttribute('readonly', '');
        ta.style.position = 'fixed';
        ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.select();
        if (ta.setSelectionRange) ta.setSelectionRange(0, ta.value.length);
        try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
        if (ta.parentNode && ta.parentNode.removeChild) ta.parentNode.removeChild(ta);
      }
      flash(ok ? '已复制' : '请手动复制');
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(
        function () { flash('已复制'); },
        function () { fallback(); });
    } else {
      fallback();
    }
  }

  function renderCalendarBox() {
    var cal = D.calendar || {};
    var coreMin = cal.eeCoreMin || 4;
    var core = calCompetitions().filter(function (c) { return (c.ee || 0) >= coreMin; }).length;
    var all = calCompetitions().length;

    $('calCoreDesc').textContent = core + ' 个赛事，电气相关度 ' + coreMin + ' 分及以上';
    $('calAllDesc').textContent = all + ' 个赛事，含相关度较低但节律清晰的';

    $('urlCore').value = absUrl(cal.eeCore || 'calendar/ee-core.ics');
    $('urlAll').value = absUrl(cal.all || 'calendar/all.ics');

    $('calUrlHint').textContent = isLocal()
      ? '当前是本地打开，上面显示的是本地地址，不能真正订阅。部署到公网后这里会自动变成可订阅的网址。'
      : '上面就是可订阅的完整网址，复制后粘到日历 App 里即可。日历会定期回来抓取最新内容。';

    $('rhythmCaveat').textContent = '说明：年度节律是从历史校内通知统计推断的窗口（覆盖 60% 以上历史通知），' +
      '不是官方赛程，只表示往年在这些月份发过通知。样本不足 2 年的竞赛不给出节律。';
  }

  function initRhythm() {
    // 填充月份下拉(用中文月份)
    var sel = $('rMonth');
    for (var m = 1; m <= 12; m++) {
      var o = document.createElement('option');
      o.value = String(m);
      o.textContent = MONTH_CN[m - 1] + ' 月';
      sel.appendChild(o);
    }
    renderMonthChart();
    renderCalendarBox();
    renderRhythm();
  }

  function initNotices() {
    // 用数据里实际出现的来源填充下拉, 避免写死
    var seen = [];
    NOTICES.forEach(function (n) {
      if (n.site && seen.indexOf(n.site) < 0) seen.push(n.site);
    });
    seen.sort();
    var sel = $('nSite');
    seen.forEach(function (s) {
      var o = document.createElement('option');
      o.value = s;
      o.textContent = s + '（' + NOTICES.filter(function (n) {
        return n.site === s;
      }).length + ' 条）';
      sel.appendChild(o);
    });
  }

  /* ---------------- 常用网站 ---------------- */

  var LINKS = [];        // 载入后填充(见 initLinks)

  function linkCategories() {
    var order = (D.quickLinkCategories || []).slice();
    var seen = {};
    LINKS.forEach(function (l) { seen[l.category] = (seen[l.category] || 0) + 1; });
    var out = order.filter(function (c) { return seen[c]; });
    Object.keys(seen).forEach(function (c) {
      if (out.indexOf(c) < 0) out.push(c);
    });
    return out;
  }

  function renderLinkChips(active) {
    var cats = linkCategories();
    var html = '<button class="chip' + (!active ? ' is-on' : '') +
               '" data-cat="">全部 ' + LINKS.length + '</button>';
    html += cats.map(function (c) {
      var n = LINKS.filter(function (l) { return l.category === c; }).length;
      return '<button class="chip' + (active === c ? ' is-on' : '') +
             '" data-cat="' + esc(c) + '">' + esc(c) + ' ' + n + '</button>';
    }).join('');
    $('linkChips').innerHTML = html;
  }

  function renderQuickLinks() {
    var q = normText($('lq').value);
    var cat = $('linkChips').getAttribute('data-active') || '';
    var list = LINKS.filter(function (l) {
      if (cat && l.category !== cat) return false;
      if (q) {
        var hay = haystack([l.name, l.url, l.desc, l.category]
          .concat(l.tags || []));
        if (matchScore(hay, q) === 0) return false;
      }
      return true;
    });

    $('linkCount').textContent = '共 ' + list.length + ' 个' +
      (list.length !== LINKS.length ? '（总 ' + LINKS.length + ' 个）' : '');
    $('linkEmpty').hidden = list.length > 0;

    $('linkList').innerHTML = list.map(function (l) {
      var tags = (l.tags || []).map(function (t) {
        return '<span class="badge b-tag">' + esc(t) + '</span>';
      }).join('');
      return '' +
        '<div class="lcard">' +
          '<div class="lcard-head">' +
            '<h3>' + esc(l.name) + '</h3>' +
            '<span class="badge b-cat">' + esc(l.category) + '</span>' +
          '</div>' +
          '<code class="lurl">' + esc(l.url) + '</code>' +
          (l.desc ? '<p class="ldesc">' + esc(l.desc) + '</p>' : '') +
          (tags ? '<div class="badges">' + tags + '</div>' : '') +
          '<div class="lacts">' +
            '<a class="btn-primary btn-sm" href="' + esc(l.url) +
              '" target="_blank" rel="noopener">点击跳转</a>' +
            '<button class="cal-copy" data-url="' + esc(l.url) + '">复制地址</button>' +
          '</div>' +
        '</div>';
    }).join('');
  }

  function initLinks() {
    LINKS = D.quickLinks || [];
    if (!LINKS.length) return;
    $('linkChips').setAttribute('data-active', '');
    renderLinkChips('');

    var note = $('linkNote');
    if (note) {
      note.textContent = '共 ' + LINKS.length +
        ' 个站点，每条都实测过连通性。标「统一认证」的站点要用统一身份认证账号登录；' +
        '校外访问校内资源走 WebVPN。';
    }
    renderQuickLinks();
  }

  /* ---------------- 说明页 ---------------- */

  function renderAbout() {
    $('caveatList').innerHTML = (D.caveats || []).map(function (t) {
      return '<li>' + esc(t) + '</li>';
    }).join('');

    var src = D.sources || {};
    $('sourceList').innerHTML = [
      src.moe ? '<li>' + esc(src.moe) + '</li>' : ''
    ].concat((src.noticeSites || []).map(function (s) {
      return '<li><a href="' + esc(s.base || '') + '" target="_blank" rel="noopener">' +
             esc(s.label) + '</a>　只抓通知列表页，不抓正文</li>';
    })).concat(
      Object.keys(src.noticeSkipped || {}).length ? [
        '<li class="muted">已评估但未纳入：' +
        Object.keys(src.noticeSkipped).map(function (k) {
          return esc(k.split('/')[0]);
        }).join('、') + '</li>'
      ] : []
    ).join('');

    // 通知页的来源说明
    var names = (src.noticeSites || []).map(function (s) { return s.label; });
    $('srcNotice').textContent = names.length ? names.join(' · ') : '西安交通大学各站点';
  }

  /* ---------------- 事件绑定 ---------------- */

  function bind() {
    var catInputs = ['q', 'fEE', 'fCat', 'fMoe', 'fSort', 'fRecent', 'fOpen'];
    catInputs.forEach(function (id) {
      var el = $(id);
      el.addEventListener(id === 'q' ? 'input' : 'change', function () {
        $('qClear').hidden = !$('q').value;
        renderCatalog();
      });
    });
    $('qClear').addEventListener('click', function () {
      $('q').value = ''; $('qClear').hidden = true; renderCatalog();
    });
    $('reset').addEventListener('click', function () {
      $('q').value = ''; $('qClear').hidden = true;
      $('fEE').value = ''; $('fCat').value = ''; $('fMoe').value = '';
      $('fSort').value = 'ee'; $('fRecent').checked = false; $('fOpen').checked = false;
      renderCatalog();
    });

    ['nq', 'nScope', 'nSite', 'nRange', 'nSort'].forEach(function (id) {
      var el = $(id);
      el.addEventListener(id === 'nq' ? 'input' : 'change', function () {
        $('nqClear').hidden = !$('nq').value;
        renderNotices();
      });
    });
    $('nqClear').addEventListener('click', function () {
      $('nq').value = ''; $('nqClear').hidden = true; renderNotices();
    });
    $('nReset').addEventListener('click', function () {
      $('nq').value = ''; $('nqClear').hidden = true;
      $('nScope').value = 'competition'; $('nSite').value = '';
      $('nRange').value = ''; $('nSort').value = 'date';
      renderNotices();
    });

    $('drawerClose').addEventListener('click', closeDrawer);
    $('overlay').addEventListener('click', closeDrawer);
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') closeDrawer();
    });

    ['rq', 'rMonth', 'rEE', 'rSort'].forEach(function (id) {
      var el = $(id);
      el.addEventListener(id === 'rq' ? 'input' : 'change', function () {
        $('rqClear').hidden = !$('rq').value;
        renderRhythm();
      });
    });
    $('rqClear').addEventListener('click', function () {
      $('rq').value = ''; $('rqClear').hidden = true; renderRhythm();
    });
    $('rReset').addEventListener('click', function () {
      $('rq').value = ''; $('rqClear').hidden = true;
      $('rMonth').value = ''; $('rEE').value = '4'; $('rSort').value = 'months';
      renderRhythm();
    });

    // 日历订阅网址复制
    $('copyCore').addEventListener('click', function () {
      copyText($('urlCore').value, $('copyCore'));
    });
    $('copyAll').addEventListener('click', function () {
      copyText($('urlAll').value, $('copyAll'));
    });

    // 常用网站: 分类 chips 与复制按钮都用容器级委托,
    // 因为内容是动态重建的, 逐个绑会丢。
    $('lq').addEventListener('input', function () {
      $('lqClear').hidden = !$('lq').value;
      renderQuickLinks();
    });
    $('lqClear').addEventListener('click', function () {
      $('lq').value = ''; $('lqClear').hidden = true; renderQuickLinks();
    });
    $('lReset').addEventListener('click', function () {
      $('lq').value = ''; $('lqClear').hidden = true;
      $('linkChips').setAttribute('data-active', '');
      renderLinkChips('');
      renderQuickLinks();
    });
    $('linkChips').addEventListener('click', function (e) {
      var t = e.target;
      if (!t || !t.getAttribute) return;
      var cat = t.getAttribute('data-cat');
      if (cat === null || cat === undefined) return;
      $('linkChips').setAttribute('data-active', cat);
      renderLinkChips(cat);
      renderQuickLinks();
    });
    $('linkList').addEventListener('click', function (e) {
      var t = e.target;
      if (!t || !t.getAttribute) return;
      var url = t.getAttribute('data-url');
      if (!url) return;
      copyText(url, t);
    });
  }

  /* ---------------- 启动 ---------------- */

  function init() {
    if (!COMPS.length) {
      document.querySelector('main').innerHTML =
        '<div class="empty">没有读到数据。请先运行 <code>python scripts\\build_site_data.py</code> 生成 <code>site/data.js</code>。</div>';
      return;
    }
    renderHead();
    initTabs();
    renderCatalog();
    initNotices();
    renderNotices();
    initRhythm();
    initLinks();
    renderAbout();
    bind();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
