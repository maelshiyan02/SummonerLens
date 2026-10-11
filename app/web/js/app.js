/*!
 * SummonerLens · 仪表板装配层（DOM + ECharts）
 * 纯逻辑一律在 core.js；本文件只做「取数 → 组 option → 挂载 → 交互」。
 */
(function () {
  'use strict';
  var C = window.SLCore;
  var BUNDLE_URL = 'data/dashboard.json';
  var AUTO_MS = 10000;

  var state = {
    bundle: null,
    dataset: 'real',      // real | fixture
    entity: 'hero',       // hero | augment（排名面板）
    tier: 'all',
    rec: 'all',
    role: 'all',
    stratum: 'all',
    query: '',
    pinnedHero: null,
    tab: 'overview',
    metaVersion: null,    // 当前选定元数据版本（版本选择器驱动）
    autoTimer: null
  };

  var charts = {};
  var roleMap = {};
  var metaHeroMap = {};   // {key: {name,title,roles,aliases}} —— 选定版本的英雄字典

  function $(id) { return document.getElementById(id); }

  function chart(id) {
    var el = $(id);
    var c = charts[id];
    if (!c) {
      c = echarts.init(el, null, { renderer: 'canvas' });
      charts[id] = c;
    }
    return c;
  }

  /** 稳健绘制：先按容器当前尺寸 resize，再 setOption。
   *  面板从 display:none 切回可见时容器尺寸会变，必须 resize 后再画，
   *  否则会出现「坐标轴画了、柱体不可见」的零尺寸陷阱。 */
  function draw(id, option) {
    var c = chart(id);
    c.resize();
    c.setOption(option, true);
    return c;
  }

  function drawEmpty(id, text) {
    var c = chart(id);
    c.resize();
    c.clear();
    c.setOption(emptyOption(text), true);
    return c;
  }

  function resizeAll() {
    Object.keys(charts).forEach(function (k) { charts[k].resize(); });
  }

  // ---------------------------------------------------------------- 取数
  // 离线优先：构建期生成的内联数据束（data/dashboard.js）在 file:// 下也能用（脚本不受 CORS 限制）。
  // 以本地服务打开时优先 fetch 取最新（刷新/重建后生效），失败再退回内联。
  function loadBundle(force) {
    if (!force && window.__SL_BUNDLE__) {
      return Promise.resolve(window.__SL_BUNDLE__);
    }
    var url = BUNDLE_URL + (force ? ('?t=' + Date.now()) : '');
    return fetch(url, { cache: 'no-store' }).then(function (r) {
      if (!r.ok) { throw new Error('HTTP ' + r.status); }
      return r.json();
    }).catch(function (e) {
      if (window.__SL_BUNDLE__) { return window.__SL_BUNDLE__; }
      throw e;
    });
  }

  function rebuildOnServer() {
    // 本地服务下触发服务端重建数据束（file:// 下会失败，忽略）
    return fetch('/api/rebuild', { method: 'POST' }).then(function (r) { return r.json(); })
      .catch(function () { return { ok: false }; });
  }

  // ---------------------------------------------------------------- 版本 / 名称解析
  /** 选定 meta 版本下某英雄 key 的显示名（离线切换版本用）。 */
  function nameOf(key) {
    if (metaHeroMap[key]) { return metaHeroMap[key].name; }
    var h = (state.bundle.heroes || []).filter(function (x) { return x.key === key; })[0];
    return h ? h.name : ('#' + key);
  }

  /** 由 bundle.metas[ver] 构建 key→hero 字典。 */
  function buildMetaMap(ver) {
    var m = (state.bundle.metas || {})[ver];
    var map = {};
    if (m && m.heroes) {
      m.heroes.forEach(function (h) { map[h.key] = h; });
    }
    return map;
  }

  // ---------------------------------------------------------------- 筛选
  function filteredHeroRows() {
    var b = state.bundle;
    var rows = state.dataset === 'real' ? C.realHeroRows(b) : C.fixtureHeroRows(b);
    rows = C.filterByTier(rows, state.tier);
    rows = C.filterByRecommendation(rows, state.rec);
    rows = C.filterByRole(rows, state.role, roleMap);
    if (state.pinnedHero != null) {
      rows = rows.filter(function (r) { return r.key === state.pinnedHero; });
    }
    // 用选定 meta 版本的正式名覆盖（离线版本切换）
    rows.forEach(function (r) { r.name = nameOf(r.key); });
    return rows;
  }

  function filteredAugmentRows() {
    var b = state.bundle;
    var rows = (state.dataset === 'real'
      ? ((b.datasets.augment_ranking || {}).rows || [])
      : ((b.datasets.fixture_augment_stats || {}).rows || []));
    return C.filterByTier(rows, state.tier);
  }

  function filteredPairs() {
    var b = state.bundle;
    if (state.dataset !== 'fixture') { return []; }
    var rows = ((b.datasets.fixture_hero_augment_pairs || {}).rows || []);
    if (state.pinnedHero != null) {
      rows = rows.filter(function (r) { return r.champion_id === state.pinnedHero; });
    }
    return rows;
  }

  function filteredTriples() {
    var b = state.bundle;
    if (state.dataset !== 'fixture') { return []; }
    var rows = ((b.datasets.fixture_hero_augment_item_triples || {}).rows || []);
    if (state.pinnedHero != null) {
      rows = rows.filter(function (r) { return r.champion_id === state.pinnedHero; });
    }
    return rows;
  }

  function sliceRows() {
    var b = state.bundle;
    var rows = ((b.datasets.fixture_slices_hero_stats || {}).rows || []);
    var s = state.dataset === 'fixture' ? state.stratum : 'all';
    return C.filterByStratum(rows, s).filter(function (r) {
      return state.rec === 'all' || r.recommendation_level === state.rec;
    });
  }

  // ---------------------------------------------------------------- 顶栏 / 侧栏
  function renderChrome() {
    var b = state.bundle;
    var k = C.kpis(b);
    $('pill-meta').textContent = '版本 ' + (state.metaVersion || b.meta_version || '—');
    $('pill-updated').textContent = '更新于 ' + (b.generated_at || '—').replace('T', ' ');

    var isReal = state.dataset === 'real';
    var pill = $('pill-provenance');
    pill.className = 'pill ' + (isReal ? 'real' : 'fixture');
    $('pill-text').textContent = isReal ? '真实聚合 · hexdata' : '合成夹具 · 仅引擎校验';
    $('dataset-hint').textContent = isReal
      ? 'hexdata 群体聚合样本（前 12）'
      : '合成夹具（173 英雄 / 223 Augment / 4973 局）';

    // 底部溯源
    var cit = b.hexdata_citation || {};
    $('foot').innerHTML =
      '<span>📊 ' + (cit.attribution_text || '数据来源：Hexdata（https://hexdata.com.cn）') + '</span>' +
      '<span>Build: ' + (cit.buildId || '—') + '</span>' +
      '<span>Patch: ' + (cit.reportPatch || '—') + ' · 数据日期 ' + (cit.reportDate || '—') + '</span>' +
      '<span>schema ' + b.schema + '</span>';
    void k;
  }

  function renderBanner(elId, isFixture, extra) {
    var el = $(elId);
    if (isFixture) {
      el.innerHTML = '<div class="banner">⚠️ <div><b>合成夹具</b>（synthetic_fixture）—— 由 <code>gen_fixture.py</code> 以固定种子生成，' +
        '<b>仅用于引擎数值校验</b>，绝非真实数据，不得作为对外结论。' + (extra || '') + '</div></div>';
    } else {
      el.innerHTML = '<div class="banner real">✅ <div><b>真实聚合数据</b>（hexdata）—— 群体样本关联，非因果；引用须标注来源 + buildId + patch + 日期。' +
        (extra || '') + '</div></div>';
    }
  }

  // ---------------------------------------------------------------- 概览
  function renderOverview() {
    var b = state.bundle;
    var k = C.kpis(b);
    renderBanner('ov-banner', state.dataset === 'fixture');

    var cards = [
      ['数据源', state.dataset === 'real' ? 'hexdata 真实' : '合成夹具'],
      ['英雄（真实榜）', k.heroCount + ' <small>名</small>'],
      ['Augment（真实榜）', k.augmentCount + ' <small>个</small>'],
      ['别名词典', k.aliasCount + ' <small>条</small>'],
      ['夹具对局', k.fixtureRecords ? C.fmtInt(k.fixtureRecords) + ' <small>局</small>' : '—'],
      ['MMR 反推相关', k.mmrCorr != null ? k.mmrCorr : '—'],
      ['反霸榜', k.antiDemoted ? ('raw#' + k.antiRawTop + ' → #' + k.antiWilsonRank) : '—']
    ];
    $('ov-kpis').innerHTML = cards.map(function (c) {
      return '<div class="kpi"><div class="k">' + c[0] + '</div><div class="v">' + c[1] + '</div></div>';
    }).join('');

    var rows = state.entity === 'hero' ? filteredHeroRows() : filteredAugmentRows();
    $('ov-rank-tag').textContent = state.entity === 'hero' ? '英雄 · Wilson 下界' : 'Augment · Wilson 下界';
    draw('chart-tier', C.buildTierDonutOption(rows));
    if (!rows.length) {
      drawEmpty('chart-ov-rank', '当前筛选下无数据');
    } else {
      draw('chart-ov-rank', C.buildRankingOption(rows, { topN: 8 }));
    }

    // 经济强度榜 + 风险备注（已抓未展示维度，M5-4 顺带接入）
    var econ = b.economy_leaders || [];
    var ehead = '<thead><tr><th>#</th><th>英雄</th><th>经济关联/百局</th><th>推荐占比</th><th>对局</th></tr></thead>';
    var ebody = econ.length
      ? econ.map(function (e) {
          return '<tr><td class="num">' + (e.rank || '') + '</td><td><b>' + (e.name || e.heroId || '') + '</b></td>' +
            '<td class="num">' + (e.winAssociationPerHundred != null ? C.fmtInt(Math.round(e.winAssociationPerHundred * 100) / 100) : '—') + '</td>' +
            '<td class="num">' + (e.recommendedShare != null ? C.pct(e.recommendedShare) : '—') + '</td>' +
            '<td class="num">' + (e.games != null ? C.fmtInt(e.games) : '—') + '</td></tr>';
        }).join('')
      : '<tr><td colspan="5" class="hint">无数据</td></tr>';
    $('tbl-econ').innerHTML = ehead + '<tbody>' + ebody + '</tbody>';

    var rn = b.risk_notes || [];
    $('ov-risk').innerHTML = rn.length
      ? rn.map(function (t) { return '<li>' + t + '</li>'; }).join('')
      : '<li class="hint">无</li>';
  }

  function emptyOption(text) {
    return {
      backgroundColor: 'transparent',
      title: { text: text, left: 'center', top: 'middle', textStyle: { color: '#8a93a6', fontSize: 14, fontWeight: 'normal' } },
      xAxis: { show: false }, yAxis: { show: false }, series: []
    };
  }

  // ---------------------------------------------------------------- 排名
  function renderRanking() {
    var isHero = state.entity === 'hero';
    var rows = isHero ? filteredHeroRows() : filteredAugmentRows();
    $('rk-title').textContent = (isHero ? '英雄排名' : 'Augment 排名') +
      (state.dataset === 'real' ? '（hexdata 真实聚合）' : '（合成夹具）');
    $('rk-count').textContent = rows.length + ' 项';
    renderBanner('rk-banner', state.dataset === 'fixture');

    var c = chart('chart-rank');
    if (!rows.length) {
      drawEmpty('chart-rank', '当前筛选下无数据（请放宽筛选项）');
    } else {
      draw('chart-rank', C.buildRankingOption(rows, { topN: Math.min(rows.length, 24) }));
    }
    void c;

    var cols = isHero
      ? ['#', '英雄', '角色', '样本', '档位', '观测胜率', 'Wilson 下界', '95% CI', '推荐级']
      : ['#', 'Augment', '稀有度', '样本', '档位', '观测胜率', 'Wilson 下界', '95% CI', '推荐级'];
    var head = '<thead><tr>' + cols.map(function (c0) { return '<th>' + c0 + '</th>'; }).join('') + '</tr></thead>';
    var body = '<tbody>' + rows.map(function (r) {
      var roles = (roleMap[r.key] || r.roles || []).map(function (x) {
        return '<span class="role-tag" style="background:' + C.roleColor(x) + '">' + x + '</span>';
      }).join(' ');
      var mid = isHero ? roles : ('<span class="tag-mini ' + r.sample_tier + '">' + (r.rarity || '—') + '</span>');
      return '<tr>' +
        '<td class="num">' + r.rank + '</td>' +
        '<td><b>' + C.rowLabel(r) + '</b></td>' +
        '<td>' + mid + '</td>' +
        '<td class="num">' + C.fmtInt(r.games) + '</td>' +
        '<td><span class="tag-mini ' + r.sample_tier + '">' + C.tierZh(r.sample_tier) + '</span></td>' +
        '<td class="num">' + C.pct(r.winRate) + '</td>' +
        '<td class="num">' + C.pct(r.wilson_lower) + '</td>' +
        '<td class="num">' + C.pct(r.wilson_lower) + ' ~ ' + C.pct(r.wilson_upper) + '</td>' +
        '<td>' + C.recZh(r.recommendation_level) + '</td>' +
        '</tr>';
    }).join('') + '</tbody>';
    $('tbl-rank').innerHTML = head + body;
  }

  // ---------------------------------------------------------------- 协同
  function renderSynergy() {
    var isFixture = state.dataset === 'fixture';
    renderBanner('sy-banner', isFixture,
      isFixture ? '' : ' 真实协同表需要本人对局（WeGame/LCU）或更细粒度聚合数据，当前不可用。');

    var c = chart('chart-synergy');
    if (!isFixture) {
      drawEmpty('chart-synergy', '真实聚合数据暂不提供协同表');
      $('tbl-synergy').innerHTML = '';
      $('sy-tag').textContent = '不可用';
      return;
    }
    var pairs = filteredPairs();
    var triples = filteredTriples();
    $('sy-tag').textContent = pairs.length + ' 组合';
    if (!pairs.length) {
      drawEmpty('chart-synergy', '当前筛选下无组合（试试清除英雄筛选）');
    } else if (pairs.length >= 12) {
      draw('chart-synergy', C.buildSynergyHeatmapOption(pairs));
    } else {
      draw('chart-synergy', C.buildSynergyCompareOption(pairs));
    }
    void c;

    var head = '<thead><tr><th>英雄</th><th>Augment</th><th>装备</th><th>样本</th><th>组合胜率</th>' +
      '<th>英雄边际</th><th>lift vs 英雄</th><th>lift vs 全局</th><th>档位</th></tr></thead>';
    var body = '<tbody>' + pairs.map(function (r) {
      return '<tr><td><b>' + (r.champion_name || r.champion_id) + '</b></td>' +
        '<td>' + (r.augment_name || r.augment_id) + '</td><td>—</td>' +
        '<td class="num">' + C.fmtInt(r.games) + '</td>' +
        '<td class="num">' + C.pct(r.winRate) + '</td>' +
        '<td class="num">' + C.pct(r.expected_hero_wr) + '</td>' +
        '<td class="num ' + (r.lift_vs_hero >= 0 ? 'pos' : 'neg') + '">' + C.signedPct(r.lift_vs_hero) + '</td>' +
        '<td class="num ' + (r.lift_vs_global >= 0 ? 'pos' : 'neg') + '">' + C.signedPct(r.lift_vs_global) + '</td>' +
        '<td><span class="tag-mini ' + r.sample_tier + '">' + C.tierZh(r.sample_tier) + '</span></td></tr>';
    }).join('') + triples.map(function (r) {
      return '<tr><td><b>' + (r.champion_name || r.champion_id) + '</b></td>' +
        '<td>' + (r.augment_name || r.augment_id) + '</td>' +
        '<td>' + (r.item_name || r.item_id) + '</td>' +
        '<td class="num">' + C.fmtInt(r.games) + '</td>' +
        '<td class="num">' + C.pct(r.winRate) + '</td>' +
        '<td class="num">' + C.pct(r.expected_hero_wr) + '</td>' +
        '<td class="num ' + (r.lift_vs_hero >= 0 ? 'pos' : 'neg') + '">' + C.signedPct(r.lift_vs_hero) + '</td>' +
        '<td class="num ' + (r.lift_vs_global >= 0 ? 'pos' : 'neg') + '">' + C.signedPct(r.lift_vs_global) + '</td>' +
        '<td><span class="tag-mini ' + r.sample_tier + '">' + C.tierZh(r.sample_tier) + '</span></td></tr>';
    }).join('') + '</tbody>';
    $('tbl-synergy').innerHTML = head + body;
  }

  // ---------------------------------------------------------------- 分层
  function renderStrata() {
    var isFixture = state.dataset === 'fixture';
    var c = chart('chart-mmr');
    if (!isFixture) {
      renderBanner('st-banner', false, ' 玩家分层（MMR 反推）基于本人自采对局，当前为合成夹具演示。');
      drawEmpty('chart-mmr', '真实分层需本人对局数据');
      $('tbl-strata').innerHTML = '';
      drawEmpty('chart-slice', '真实分层需本人对局数据');
      $('st-slice-tag').textContent = '不可用';
      return;
    }
    renderBanner('st-banner', true);
    var b = state.bundle;
    var players = ((b.datasets.fixture_player_mmr || {}).rows || []);
    var strata = (b.fixture_meta || {}).strata || {};
    draw('chart-mmr', C.buildMmrHistogramOption(players, {
      thresholds: { thr20: strata.thr20, thr40: strata.thr40 }
    }));

    var n = players.length;
    var sum = (b.fixture_meta || {}).slice_summary || {};
    var rows = [
      ['全量 all', sum.all ? sum.all.matches : n, sum.all ? sum.all.global_winRate : null, n],
      ['前 40% top40', sum.top40 ? sum.top40.matches : '—', sum.top40 ? sum.top40.global_winRate : null,
        strata.k40 != null ? strata.k40 : '—'],
      ['前 20% top20', sum.top20 ? sum.top20.matches : '—', sum.top20 ? sum.top20.global_winRate : null,
        strata.k20 != null ? strata.k20 : '—']
    ];
    $('tbl-strata').innerHTML =
      '<thead><tr><th>分层</th><th>对局数</th><th>群体胜率</th><th>玩家数</th></tr></thead><tbody>' +
      rows.map(function (r) {
        return '<tr><td><b>' + r[0] + '</b></td><td class="num">' + C.fmtInt(r[1]) + '</td>' +
          '<td class="num">' + (r[2] != null ? C.pct(r[2]) : '—') + '</td>' +
          '<td class="num">' + r[3] + '</td></tr>';
      }).join('') +
      '</tbody>';

    var srows = sliceRows();
    $('st-slice-tag').textContent = '分层：' + ({ all: '全量', top40: '前 40%', top20: '前 20%' }[state.stratum] || state.stratum) + ' · ' + srows.length + ' 项';
    if (!srows.length) {
      drawEmpty('chart-slice', '当前分层无数据');
    } else {
      draw('chart-slice', C.buildRankingOption(srows, { topN: Math.min(srows.length, 24) }));
    }
    void c;
  }

  // ---------------------------------------------------------------- 版本 / 趋势
  function renderVersion() {
    var b = state.bundle;
    var vc = (b.version_changes || []).filter(function (p) { return p.to === state.metaVersion; })[0];

    // ---- 版本变更（元数据，真实数据）----
    if (!vc) {
      $('vc-title').textContent = '版本变更 · ' + state.metaVersion;
      $('vc-summary-tag').textContent = '最早快照 · 无更早版本可对比';
      drawEmpty('chart-vc', '该版本是最早快照，无更早版本可对比');
      $('tbl-vc').innerHTML = '';
      renderBanner('vc-banner', false, ' 当前选定 ' + state.metaVersion + ' 为最早快照。');
      $('tr-tag').textContent = '—';
      drawEmpty('chart-trend', '无趋势数据');
      return;
    }
    var s = vc.summary || {};
    $('vc-title').textContent = '版本变更 · ' + vc.from + ' → ' + vc.to;
    $('vc-summary-tag').textContent = '英雄 +' + (s.champions_added || 0) + ' / -' +
      (s.champions_removed || 0) + ' / ~' + (s.champions_changed || 0) +
      '｜装备 +' + (s.items_added || 0) + ' / -' + (s.items_removed || 0);
    if (vc.status === 'ok') {
      draw('chart-vc', C.buildChangesSummaryOption(s));
    } else {
      drawEmpty('chart-vc', '版本对比不可用：' + (vc.detail || vc.status));
    }

    var changed = (vc.champions && vc.champions.changed) || [];
    var added = (vc.champions && vc.champions.added) || [];
    var removed = (vc.champions && vc.champions.removed) || [];
    var rows = changed.map(function (c) {
      return { cls: 'chg-changed', kind: '变更', name: c.name, fields: c.fields || [] };
    }).concat(added.map(function (c) { return { cls: 'chg-added', kind: '新增', name: c.name, fields: [] }; }))
      .concat(removed.map(function (c) { return { cls: 'chg-removed', kind: '移除', name: c.name, fields: [] }; }));
    var head = '<thead><tr><th>类型</th><th>英雄</th><th>改动字段</th></tr></thead>';
    var body = rows.length
      ? rows.map(function (r) {
          var tags = (r.fields || []).map(function (f) { return '<span class="field-tag">' + f + '</span>'; }).join('');
          return '<tr><td><span class="' + r.cls + '">' + r.kind + '</span></td>' +
            '<td><b>' + r.name + '</b></td><td><div class="field-tags">' + tags + '</div></td></tr>';
        }).join('')
      : '<tr><td colspan="3" class="hint">本版本无英雄/装备变更</td></tr>';
    $('tbl-vc').innerHTML = head + '<tbody>' + body + '</tbody>';

    // ---- 聚合趋势（英雄胜率跨版本）----
    var tr = b.trend || {};
    var trTag = $('tr-tag');
    if (tr.kind === 'synthetic_fixture') {
      trTag.textContent = '演示（合成）· 当前 ' + (tr.current || 0) + '/2 真实快照';
      renderBanner('vc-banner', true,
        ' 元数据对比 ' + vc.from + ' → ' + vc.to + '（真实数据）。⚠️ 聚合趋势仅 1 份真实快照，' +
        '下图为依据单份真实数据合成的演示序列，非真实趋势；真实趋势随定时抓取积累后自动替换。');
    } else if (tr.kind === 'real_aggregate') {
      trTag.textContent = '真实聚合 · ' + (tr.current || 0) + ' 份快照';
      renderBanner('vc-banner', false,
        ' 元数据对比 ' + vc.from + ' → ' + vc.to + '（真实数据）；聚合趋势含 ' + (tr.current || 0) + ' 份真实快照。');
    } else {
      trTag.textContent = '不可用';
      renderBanner('vc-banner', false, ' 元数据对比 ' + vc.from + ' → ' + vc.to + '（真实数据）。');
    }
    if (tr.kind === 'unavailable') {
      drawEmpty('chart-trend', '无趋势数据');
    } else {
      draw('chart-trend', C.buildTrendOption(tr, metaHeroMap));
    }
  }

  // ---------------------------------------------------------------- 搜索
  function renderSearch() {
    var el = $('search-result');
    var q = state.query;
    if (!q) { el.innerHTML = ''; return; }
    var hits = C.searchHeroes(state.bundle.heroes, state.bundle.alias_index, q).slice(0, 6);
    if (!hits.length) {
      el.innerHTML = '<div class="hint">未命中：' + q + '</div>';
      return;
    }
    el.innerHTML = hits.map(function (h) {
      var roles = (h.roles || []).map(function (x) {
        return '<span class="role-tag" style="background:' + C.roleColor(x) + '">' + x + '</span>';
      }).join('');
      return '<div class="hit" data-key="' + h.key + '"><span class="nm">' + h.name + '</span>' +
        '<span class="ti">' + (h.title || '') + '</span><span class="roles">' + roles + '</span></div>';
    }).join('');
    Array.prototype.forEach.call(el.querySelectorAll('.hit'), function (node) {
      node.addEventListener('click', function () {
        var key = Number(node.getAttribute('data-key'));
        state.pinnedHero = (state.pinnedHero === key) ? null : key;
        apply();
      });
    });
  }

  // ---------------------------------------------------------------- 应用
  function apply() {
    renderChrome();
    renderSearch();
    var fn = { overview: renderOverview, ranking: renderRanking, synergy: renderSynergy,
      strata: renderStrata, version: renderVersion }[state.tab];
    if (fn) { fn(); }
    // 概览/排名依赖同一批筛选：切换 tab 时已重绘当前面板
  }

  function activateTab(name) {
    state.tab = name;
    Array.prototype.forEach.call($('tabs').children, function (b) {
      b.classList.toggle('active', b.getAttribute('data-tab') === name);
    });
    ['overview', 'ranking', 'synergy', 'strata', 'version'].forEach(function (p) {
      $('panel-' + p).classList.toggle('active', p === name);
    });
    // 面板从 display:none 变可见后容器才有尺寸：强制回流 → 立即绘制 → 再兜一次 resize
    void $('panel-' + name).offsetHeight;
    apply();
    setTimeout(function () { apply(); resizeAll(); }, 60);
  }

  // ---------------------------------------------------------------- 刷新 / 自愈
  function refresh(useServerRebuild) {
    var btn = $('btn-refresh');
    btn.disabled = true;
    var p = useServerRebuild ? rebuildOnServer() : Promise.resolve();
    p.then(function () { return loadBundle(true); })
      .then(function (b) {
        state.bundle = b;
        apply();
      })
      .catch(function (e) {
        showError('刷新失败：' + e.message);
      })
      .then(function () { btn.disabled = false; });
  }

  function toggleAuto() {
    var btn = $('btn-auto');
    if (state.autoTimer) {
      clearInterval(state.autoTimer);
      state.autoTimer = null;
      btn.textContent = '自动刷新：关';
      btn.classList.remove('active');
    } else {
      state.autoTimer = setInterval(function () { refresh(false); }, AUTO_MS);
      btn.textContent = '自动刷新：开';
      btn.classList.add('active');
    }
  }

  function showError(msg) {
    var boot = $('boot');
    if (boot) { boot.remove(); }
    var el = document.createElement('div');
    el.className = 'center-msg';
    el.innerHTML = '<div class="big">🛰️</div>' +
      '<div><b>无法载入数据束</b>：' + msg + '</div>' +
      '<div class="hint">若以 <code>file://</code> 直接打开，浏览器会拦截本地 fetch。请改用本地服务：</div>' +
      '<div><code>python python/bridge/serve.py --open</code></div>';
    document.querySelector('.content').appendChild(el);
  }

  // ---------------------------------------------------------------- 事件绑定
  function bind() {
    $('seg-dataset').addEventListener('click', function (e) {
      var b = e.target.closest('button'); if (!b) { return; }
      state.dataset = b.getAttribute('data-dataset');
      state.pinnedHero = null;
      Array.prototype.forEach.call(this.children, function (x) { x.classList.toggle('active', x === b); });
      apply();
    });

    // 排名面板「英雄 / Augment」子切换
    var segEnt = document.createElement('div');
    segEnt.className = 'seg'; segEnt.style.marginLeft = 'auto';
    segEnt.innerHTML = '<button data-entity="hero" class="active">英雄</button>' +
      '<button data-entity="augment">Augment</button>';
    $('panel-ranking').querySelector('.card-hd').appendChild(segEnt);
    segEnt.addEventListener('click', function (e) {
      var b = e.target.closest('button'); if (!b) { return; }
      state.entity = b.getAttribute('data-entity');
      Array.prototype.forEach.call(this.children, function (x) { x.classList.toggle('active', x === b); });
      apply();
    });
    var segOv = segEnt.cloneNode(true);
    $('panel-overview').querySelector('.card-hd').appendChild(segOv);
    segOv.addEventListener('click', function (e) {
      var b = e.target.closest('button'); if (!b) { return; }
      state.entity = b.getAttribute('data-entity');
      apply();
    });

    function chips(id, field) {
      $(id).addEventListener('click', function (e) {
        var c = e.target.closest('.chip'); if (!c) { return; }
        state[field] = c.getAttribute('data-' + (field === 'rec' ? 'rec' : field));
        Array.prototype.forEach.call(this.children, function (x) { x.classList.toggle('active', x === c); });
        apply();
      });
    }
    chips('chips-tier', 'tier');
    chips('chips-rec', 'rec');
    chips('chips-role', 'role');
    chips('chips-stratum', 'stratum');

    var t = null;
    $('search').addEventListener('input', function (e) {
      clearTimeout(t);
      var v = e.target.value;
      t = setTimeout(function () { state.query = v; renderSearch(); }, 120);
    });

    $('tabs').addEventListener('click', function (e) {
      var b = e.target.closest('button'); if (!b) { return; }
      activateTab(b.getAttribute('data-tab'));
    });

    $('btn-refresh').addEventListener('click', function () { refresh(true); });
    $('btn-auto').addEventListener('click', toggleAuto);
    window.addEventListener('resize', resizeAll);

    // 版本选择器（M5-4）
    var selVer = $('sel-ver');
    var metas = ((state.bundle.versions && state.bundle.versions.snapshots) || [])
      .filter(function (s) { return s.kind === 'meta'; });
    selVer.innerHTML = metas.map(function (s) {
      return '<option value="' + s.id + '">' + s.id + (s.is_latest ? '（最新）' : '') + '</option>';
    }).join('');
    if (!state.metaVersion) {
      state.metaVersion = state.bundle.meta_version ||
        (metas.length ? metas[metas.length - 1].id : null);
    }
    selVer.value = state.metaVersion;
    metaHeroMap = buildMetaMap(state.metaVersion);
    selVer.addEventListener('change', function () {
      state.metaVersion = selVer.value;
      metaHeroMap = buildMetaMap(state.metaVersion);
      var qs = new URLSearchParams(window.location.search);
      qs.set('ver', state.metaVersion);
      history.replaceState(null, '', '?' + qs.toString());
      apply();
    });

    document.addEventListener('keydown', function (e) {
      if (e.key === '/' && document.activeElement !== $('search')) {
        e.preventDefault(); $('search').focus();
      }
    });
  }

  // ---------------------------------------------------------------- URL 深链
  // 支持 ?dataset=fixture&tab=ranking&entity=augment&tier=high&stratum=top20&q=亚索
  // （既方便分享视图，也让 headless 渲染校验可逐视图截图）
  function applyUrlParams() {
    var qs = new URLSearchParams(window.location.search);
    var map = { dataset: 'dataset', tab: 'tab', entity: 'entity', tier: 'tier',
      rec: 'rec', role: 'role', stratum: 'stratum' };
    Object.keys(map).forEach(function (k) {
      var v = qs.get(k);
      if (v) { state[map[k]] = v; }
    });
    var q = qs.get('q');
    if (q) { state.query = q; }
    var pin = qs.get('pin');
    if (pin) { state.pinnedHero = Number(pin); }
    var ver = qs.get('ver');
    if (ver) {
      state.metaVersion = ver;
      var sv = $('sel-ver');
      if (sv) { sv.value = ver; }
      metaHeroMap = buildMetaMap(state.metaVersion);
    }

    // 同步 UI 高亮
    function sync(sel, attr, val) {
      var nodes = document.querySelectorAll(sel);
      Array.prototype.forEach.call(nodes, function (n) {
        n.classList.toggle('active', n.getAttribute(attr) === val);
      });
    }
    sync('#seg-dataset button', 'data-dataset', state.dataset);
    sync('#chips-tier .chip', 'data-tier', state.tier);
    sync('#chips-rec .chip', 'data-rec', state.rec);
    sync('#chips-role .chip', 'data-role', state.role);
    sync('#chips-stratum .chip', 'data-stratum', state.stratum);
    sync('.seg button[data-entity]', 'data-entity', state.entity);
  }

  // ---------------------------------------------------------------- 启动
  function boot() {
    loadBundle(false).then(function (b) {
      state.bundle = b;
      roleMap = C.buildRoleMap(b.heroes);
      var bootEl = $('boot');
      if (bootEl) { bootEl.remove(); }
      bind();
      applyUrlParams();
      if (state.tab !== 'overview') { activateTab(state.tab); } else { apply(); }
      setTimeout(resizeAll, 60);
      window.__SL_READY__ = true;
    }).catch(function (e) {
      showError(e.message || String(e));
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
