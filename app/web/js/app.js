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
    resgEntity: 'hero',   // hero | augment | item（RESG 完整池面板）
    resgSortKey: 'rank',  // 表头排序键
    resgSortDir: 'asc',   // asc | desc
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

  // ---------------------------------------------------------------- 个人战绩
  function buildPersonalChampionOption(bc) {
    var picked = bc.slice().sort(function (a, b) { return b.games - a.games; })
      .slice(0, 12).reverse();
    var names = picked.map(function (r) { return r.champion_name || ('#' + r.champion_id); });
    var data = picked.map(function (r) {
      var wr = r.win_rate || 0;
      return { value: r.games, itemStyle: { color: wr >= 0.5 ? '#ff5b5b' : '#3fc76a' } };
    });
    return {
      backgroundColor: 'transparent',
      grid: { left: 120, right: 40, top: 10, bottom: 24 },
      tooltip: {
        trigger: 'axis', axisPointer: { type: 'shadow' },
        formatter: function (ps) {
          var r = picked[ps[0].dataIndex];
          return '<b>' + (r.champion_name || r.champion_id) + '</b><br/>对局 ' + r.games +
            '<br/>胜率 ' + C.pct(r.win_rate);
        }
      },
      xAxis: { type: 'value', axisLabel: { color: '#8a93a6' },
        splitLine: { lineStyle: { color: 'rgba(255,255,255,0.06)' } } },
      yAxis: { type: 'category', data: names, axisLabel: { color: '#c8d0de', fontSize: 12 },
        axisLine: { lineStyle: { color: 'rgba(255,255,255,0.12)' } }, axisTick: { show: false } },
      series: [{
        type: 'bar', data: data, barWidth: 15,
        label: { show: true, position: 'right', color: '#c8d0de',
          formatter: function (p) { return picked[p.dataIndex].games; } }
      }]
    };
  }

  // ---------------------------------------------------------------- RESG · 完整池排名
  var RESG_TIER_MAP = { T0: 3, T1: 2, T2: 1, T3: 0, T4: 0 };  // tier 强度映射

  /** RESG tier 彩色 tag：T0 红（顶级）→ T4 灰（垫底）。 */
  function resgTierTag(tier) {
    var colors = { T0: '#ff5b5b', T1: '#e8b23a', T2: '#4a9eff', T3: '#7b8496', T4: '#555d6b' };
    var c = colors[tier] || '#6b7484';
    return '<span class="tag-mini" style="background:' + c + '">' + (tier || '—') + '</span>';
  }

  /** 通用表头排序：点击列头切换升/降序。 */
  function _sortRows(rows, key, dir) {
    var d = dir === 'asc' ? 1 : -1;
    return rows.slice().sort(function (a, b) {
      var av = a[key], bv = b[key];
      if (typeof av === 'number' && typeof bv === 'number') { return (av - bv) * d; }
      av = (av == null ? '' : String(av));
      bv = (bv == null ? '' : String(bv));
      return av.localeCompare(bv, 'zh-CN') * d;
    });
  }

  /** 生成表头 HTML：带排序指示器，点击触发 state 更新 + 重绘。 */
  function _resgHeader(cols) {
    var html = '<thead><tr>';
    cols.forEach(function (col, i) {
      var indicator = '';
      if (col.sortable) {
        var active = state.resgSortKey === col.key;
        indicator = active ? (state.resgSortDir === 'asc' ? ' ▲' : ' ▼') : '';
        html += '<th class="sortable' + (active ? ' active' : '') + '" data-sort="' + col.key + '">'
          + col.label + indicator + '</th>';
      } else {
        html += '<th>' + col.label + '</th>';
      }
    });
    html += '</tr></thead>';
    return html;
  }

  function renderResg() {
    var b = state.bundle;
    var entity = state.resgEntity;

    // entity 切换 seg：首次渲染时注入
    var segEnt = $('panel-resg').querySelector('.card-hd .seg');
    if (!segEnt) {
      segEnt = document.createElement('div');
      segEnt.className = 'seg';
      segEnt.style.marginLeft = 'auto';
      segEnt.innerHTML = '<button data-entity="hero" class="active">英雄</button>' +
        '<button data-entity="augment">海克斯</button>' +
        '<button data-entity="item">装备</button>';
      $('panel-resg').querySelector('.card-hd').appendChild(segEnt);
      segEnt.addEventListener('click', function (e) {
        var btn = e.target.closest('button'); if (!btn) { return; }
        state.resgEntity = btn.getAttribute('data-entity');
        state.resgSortKey = 'rank'; state.resgSortDir = 'asc';
        Array.prototype.forEach.call(this.children, function (x) {
          x.classList.toggle('active', x === btn);
        });
        renderResg();
      });
    }
    // 同步状态高亮
    Array.prototype.forEach.call(segEnt.querySelectorAll('button'), function (btn) {
      btn.classList.toggle('active', btn.getAttribute('data-entity') === entity);
    });

    // 横幅
    var prov = C.provenanceOf(b, entity === 'hero' ? 'resg_champions'
      : entity === 'augment' ? 'resg_augments' : 'resg_items');
    var bannerEl = $('rg-banner');
    if (entity === 'item') {
      bannerEl.innerHTML = '<div class="banner"><div><b>⚠️ 装备聚合数据暂缺</b>——' +
        'RESG / hexdata 均未提供装备维度的公开聚合胜率端点。' +
        '以下展示 A12 元数据装备列表（870 件）含模式归属标注，聚合胜率数据缺口待数据源出现后接入。</div></div>';
    } else {
      bannerEl.innerHTML = '<div class="banner real"><div><b>RESG 完整聚合数据</b>（resg.top）——' +
        (prov.attribution || '来源：RESG resg.top') +
        '｜版本 ' + (prov.resg_version || '—') + '｜完整英雄/海克斯池。</div></div>';
    }

    $('rg-title').textContent = (entity === 'hero' ? '完整英雄池排名（173）'
      : entity === 'augment' ? '完整海克斯池排名（211）'
      : '装备列表（A12 元数据）');

    // --- hero 表格 ---
    if (entity === 'hero') {
      var dataset = (b.datasets.resg_champions || { rows: [] });
      var rows = dataset.rows || [];
      // 应用筛选
      rows = C.filterByTier(rows, state.tier);
      rows = C.filterByRecommendation(rows, state.rec);
      rows = rows.filter(function (r) {
        return state.role === 'all' || (r.roles || []).indexOf(state.role) >= 0;
      });
      // 表头排序
      if (state.resgSortKey !== 'rank') {
        rows = _sortRows(rows, state.resgSortKey, state.resgSortDir);
      }
      $('rg-count').textContent = rows.length + ' 项';

      if (!rows.length) {
        $('tbl-resg').innerHTML = '<thead><tr><th class="hint">当前筛选下无数据</th></tr></thead><tbody></tbody>';
        return;
      }

      var cols = [
        { key: 'rank', label: '#', sortable: true },
        { key: 'name', label: '英雄', sortable: false },
        { key: 'title', label: '称号', sortable: false },
        { key: 'roles', label: '角色', sortable: false },
        { key: 'games', label: '场次', sortable: true },
        { key: 'winRate', label: '胜率', sortable: true },
        { key: 'tier_hint', label: 'Tier', sortable: false },
        { key: 'wilson_lower', label: 'Wilson 下界', sortable: true },
        { key: 'recommendation_level', label: '推荐级', sortable: false },
      ];
      var html = _resgHeader(cols) + '<tbody>';
      rows.forEach(function (r) {
        var roles = (r.roles || []).map(function (x) {
          return '<span class="role-tag" style="background:' + C.roleColor(x) + '">' + x + '</span>';
        }).join(' ');
        var rowClass = r.sample_tier === 'low' ? 'tier-row-low' : '';
        html += '<tr class="' + rowClass + '">' +
          '<td class="num">' + r.rank + '</td>' +
          '<td><b>' + r.name + '</b></td>' +
          '<td class="dim">' + (r.title || '') + '</td>' +
          '<td>' + roles + '</td>' +
          '<td class="num">' + C.fmtInt(r.games) + '</td>' +
          '<td class="num">' + C.pct(r.winRate) + '</td>' +
          '<td>' + resgTierTag(r.tier_hint) + '</td>' +
          '<td class="num">' + C.pct(r.wilson_lower) + '</td>' +
          '<td>' + C.recZh(r.recommendation_level) + '</td>' +
          '</tr>';
      });
      html += '</tbody>';
      $('tbl-resg').innerHTML = html;
    }

    // --- augment 表格 ---
    else if (entity === 'augment') {
      var dataset2 = (b.datasets.resg_augments || { rows: [] });
      var rows2 = dataset2.rows || [];
      rows2 = C.filterByTier(rows2, state.tier);
      rows2 = C.filterByRecommendation(rows2, state.rec);
      if (state.resgSortKey !== 'rank') {
        rows2 = _sortRows(rows2, state.resgSortKey, state.resgSortDir);
      }
      $('rg-count').textContent = rows2.length + ' 项';

      if (!rows2.length) {
        $('tbl-resg').innerHTML = '<thead><tr><th class="hint">当前筛选下无数据</th></tr></thead><tbody></tbody>';
        return;
      }

      var cols2 = [
        { key: 'rank', label: '#', sortable: true },
        { key: 'name', label: '海克斯', sortable: false },
        { key: 'games', label: '场次', sortable: true },
        { key: 'winRate', label: '胜率', sortable: true },
        { key: 'pickRate', label: '登场率', sortable: true },
        { key: 'tier_hint', label: 'Tier', sortable: false },
        { key: 'quality', label: 'Quality', sortable: true },
        { key: 'wilson_lower', label: 'Wilson 下界', sortable: true },
        { key: 'recommendation_level', label: '推荐级', sortable: false },
      ];
      var html2 = _resgHeader(cols2) + '<tbody>';
      rows2.forEach(function (r) {
        var rarity = r.rarity ? ('<span class="tag-mini">' + r.rarity + '</span>') : '';
        var rowClass2 = r.sample_tier === 'low' ? 'tier-row-low' : '';
        html2 += '<tr class="' + rowClass2 + '">' +
          '<td class="num">' + r.rank + '</td>' +
          '<td><b>' + r.name + '</b>' + rarity + '</td>' +
          '<td class="num">' + C.fmtInt(r.games) + '</td>' +
          '<td class="num">' + C.pct(r.winRate) + '</td>' +
          '<td class="num">' + C.pct(r.pickRate) + '</td>' +
          '<td>' + resgTierTag(r.tier_hint) + '</td>' +
          '<td class="num">' + (r.quality != null ? r.quality : '—') + '</td>' +
          '<td class="num">' + C.pct(r.wilson_lower) + '</td>' +
          '<td>' + C.recZh(r.recommendation_level) + '</td>' +
          '</tr>';
      });
      html2 += '</tbody>';
      $('tbl-resg').innerHTML = html2;
    }

    // --- item 表格（元数据：870 件装备 + 模式归属；无聚合胜率） ---
    else {
      var items = (datasets.resg_items && datasets.resg_items.rows) || [];
      $('rg-count').textContent = items.length + ' 件';

      // 模式标签颜色
      var modeColor = {
        'SR': '#4a9eff', 'ARAM': '#ffb04a', 'ClassicRift': '#4a9eff',
        'Arena': '#a78bfa', 'Swiftplay': '#22d3ee', 'TFT': '#00d664'
      };
      function modeTag(m) {
        var bg = modeColor[m] || '#666';
        return '<span class="tag" style="background:' + bg + ';color:#fff;font-size:11px;padding:1px 5px;border-radius:8px;margin-right:2px">' + m + '</span>';
      }

      var header = '<thead><tr>' +
        '<th data-key="name">装备</th>' +
        '<th data-key="gold_base" data-num>基础价</th>' +
        '<th data-key="gold_total" data-num>总价</th>' +
        '<th data-key="id_family">分类</th>' +
        '<th>模式归属</th>' +
        '<th>ARAM 可用</th>' +
        '</tr></thead>';

      var sorted = items.slice();
      if (state.resgSortKey) {
        var sk = state.resgSortKey;
        var sd = state.resgSortDir === 'asc' ? 1 : -1;
        sorted.sort(function (a, b) {
          var av = sk === 'gold_base' || sk === 'gold_total' || sk === 'id'
            ? (a[sk] || 0) : (a[sk] || '');
          var bv = sk === 'gold_base' || sk === 'gold_total' || sk === 'id'
            ? (b[sk] || 0) : (b[sk] || '');
          return (av > bv ? 1 : av < bv ? -1 : 0) * sd;
        });
      } else {
        sorted.sort(function (a, b) { return (a.id || 0) - (b.id || 0); });
      }

      var body = sorted.map(function (r) {
        var modes = (r.modes || []).map(modeTag).join('');
        var aramOk = r.aram_mode
          ? '<span style="color:#00d664">✓</span>'
          : '<span style="color:#555">—</span>';
        return '<tr>' +
          '<td><b>' + (r.name || '—') + '</b>' +
          ' <span style="color:#555;font-size:11px">#' + r.id + '</span></td>' +
          '<td class="num">' + (r.gold_base || 0) + '</td>' +
          '<td class="num">' + (r.gold_total || 0) + '</td>' +
          '<td>' + (r.id_family || '') + '</td>' +
          '<td>' + modes + '</td>' +
          '<td>' + aramOk + '</td>' +
          '</tr>';
      }).join('');

      // 顶部说明条
      $('rg-banner').innerHTML =
        '<div style="background:rgba(74,158,255,0.08);border-left:3px solid #4a9eff;' +
        'padding:8px 12px;font-size:12px;color:#aeb6c2">' +
        'ℹ️ 装备聚合胜率数据源缺失（RESG/hexdata 均无公开端点）。' +
        '当前展示 A12 装备元数据（' + items.length + ' 件）含模式归属标注；' +
        '聚合胜率待数据源出现后接入。' +
        '</div>';

      $('tbl-resg').innerHTML = header + '<tbody>' + body + '</tbody>';
    }

    // 表头排序事件绑定（用事件委托，保证重绘后仍生效）
    var tbl = $('tbl-resg');
    tbl.onclick = function (e) {
      var th = e.target.closest('th.sortable');
      if (!th) { return; }
      var key = th.getAttribute('data-sort');
      if (state.resgSortKey === key) {
        state.resgSortDir = (state.resgSortDir === 'asc') ? 'desc' : 'asc';
      } else {
        state.resgSortKey = key;
        state.resgSortDir = (key === 'rank' || key === 'games' || key === 'winRate'
          || key === 'wilson_lower' || key === 'pickRate') ? 'desc' : 'asc';
      }
      renderResg();
    };
  }

  function renderPersonal() {
    var b = state.bundle;
    var p = b.personal || { kind: 'unavailable' };
    var el = $('ps-banner');
    if (p.kind === 'unavailable') {
      el.innerHTML = '<div class="banner">⚠️ <div><b>暂无本人对局数据</b>—— 运行 ' +
        '<code>python python/etl/fetch_lcu.py</code>（英雄联盟客户端开着时）或 ' +
        '<code>fetch_wegame.py</code> 采集后，本页自动填充。</div></div>';
      $('ps-kpis').innerHTML = '';
      $('ps-dmg-breakdown').innerHTML = '';
      drawEmpty('chart-personal-champ', '暂无本人对局');
      var emptyChamp = '<thead><tr><th>英雄</th><th>对局</th><th>胜率</th><th>KDA</th>' +
        '<th>平均伤害</th><th>平均金</th><th>平均视野</th><th>平均CS</th></tr></thead>' +
        '<tbody><tr><td colspan="8" class="hint">无数据</td></tr></tbody>';
      $('tbl-personal-champ').innerHTML = emptyChamp;
      var emptyRec = '<thead><tr><th>时间</th><th>英雄</th><th>结果</th><th>K/D/A</th>' +
        '<th>金</th><th>视野</th><th>CS</th><th>来源</th><th>详情</th></tr></thead>' +
        '<tbody><tr><td colspan="9" class="hint">无数据</td></tr></tbody>';
      $('tbl-personal-recent').innerHTML = emptyRec;
      $('ps-recent-tag').textContent = '—';
      return;
    }
    el.innerHTML = '<div class="banner real">✅ <div><b>本人对局数据</b>（LCU/WeGame 自采）—— ' +
      '仅次级佐证，隐藏战绩取不到，不得与群体聚合混同为因果。</div></div>';

    var s = p.summary || {};
    var cards = [
      ['总对局', C.fmtInt(s.games)],
      ['胜率', C.pct(s.win_rate)],
      ['平均 KDA', s.kda != null ? s.kda.toFixed(2) : '—'],
      ['平均击杀', s.avg_kills != null ? s.avg_kills.toFixed(1) : '—'],
      ['平均死亡', s.avg_deaths != null ? s.avg_deaths.toFixed(1) : '—'],
      ['平均助攻', s.avg_assists != null ? s.avg_assists.toFixed(1) : '—'],
      ['平均伤害', s.avg_damage != null ? C.fmtInt(Math.round(s.avg_damage)) : '—'],
      ['平均承伤', s.avg_damage_taken != null ? C.fmtInt(Math.round(s.avg_damage_taken)) : '—'],
      ['平均金', s.avg_gold != null ? C.fmtInt(Math.round(s.avg_gold)) : '—'],
      ['平均视野', s.avg_vision != null ? s.avg_vision.toFixed(1) : '—'],
      ['平均CS', s.avg_cs != null ? s.avg_cs.toFixed(1) : '—'],
    ];
    $('ps-kpis').innerHTML = cards.map(function (c) {
      return '<div class="kpi"><div class="k">' + c[0] + '</div><div class="v">' + c[1] + '</div></div>';
    }).join('');

    // 伤害构成（魔/物/真）
    var db = p.damage_breakdown || { magic: 0, physical: 0, true: 0 };
    var tot = (db.magic + db.physical + db.true) || 1;
    var pct = function (x) { return (x * 100).toFixed(1) + '%'; };
    $('ps-dmg-breakdown').innerHTML =
      '<div class="bar3">' +
        '<span class="seg m" style="width:' + (db.magic * 100 / tot) + '%" title="魔法 ' + pct(db.magic) + '"></span>' +
        '<span class="seg p" style="width:' + (db.physical * 100 / tot) + '%" title="物理 ' + pct(db.physical) + '"></span>' +
        '<span class="seg t" style="width:' + (db.true * 100 / tot) + '%" title="真实 ' + pct(db.true) + '"></span>' +
      '</div>' +
      '<div class="legend">' +
        '<i class="m"></i>魔法 ' + pct(db.magic) +
        ' <i class="p"></i>物理 ' + pct(db.physical) +
        ' <i class="t"></i>真实 ' + pct(db.true) + '</div>';

    var bc = p.by_champion || [];
    if (!bc.length) {
      drawEmpty('chart-personal-champ', '无英雄维度数据');
    } else {
      draw('chart-personal-champ', buildPersonalChampionOption(bc));
    }
    var champHead = '<thead><tr><th>英雄</th><th>对局</th><th>胜率</th><th>KDA</th>' +
      '<th>平均伤害</th><th>平均金</th><th>平均视野</th><th>平均CS</th></tr></thead>';
    var champBody = bc.length ? bc.map(function (r) {
      return '<tr><td><b>' + (r.champion_name || ('#' + r.champion_id)) + '</b></td>' +
        '<td class="num">' + C.fmtInt(r.games) + '</td>' +
        '<td class="num ' + (r.win_rate >= 0.5 ? 'pos' : 'neg') + '">' + C.pct(r.win_rate) + '</td>' +
        '<td class="num">' + (r.kda != null ? r.kda.toFixed(2) : '—') + '</td>' +
        '<td class="num">' + (r.avg_damage != null ? C.fmtInt(Math.round(r.avg_damage)) : '—') + '</td>' +
        '<td class="num">' + (r.avg_gold != null ? C.fmtInt(Math.round(r.avg_gold)) : '—') + '</td>' +
        '<td class="num">' + (r.avg_vision != null ? r.avg_vision.toFixed(1) : '—') + '</td>' +
        '<td class="num">' + (r.avg_cs != null ? r.avg_cs.toFixed(1) : '—') + '</td></tr>';
    }).join('') : '<tr><td colspan="8" class="hint">无</td></tr>';
    $('tbl-personal-champ').innerHTML = champHead + '<tbody>' + champBody + '</tbody>';

    var rec = p.recent || [];
    $('ps-recent-tag').textContent = rec.length + ' 局';
    var recHead = '<thead><tr><th>时间</th><th>英雄</th><th>结果</th><th>K/D/A</th>' +
      '<th>金</th><th>视野</th><th>CS</th><th>来源</th><th>详情</th></tr></thead>';
    var recBody = rec.length ? rec.map(function (r, idx) {
      var d = r.game_creation ? new Date(r.game_creation * 1000) : null;
      var ds = d ? (d.getFullYear() + '-' + ('0' + (d.getMonth() + 1)).slice(-2) + '-' +
        ('0' + d.getDate()).slice(-2)) : '—';
      var sf = r.self || {};
      var kda = [sf.kills, sf.deaths, sf.assists].map(function (x) { return x == null ? '—' : x; }).join('/');
      return '<tr class="clickable" onclick="__psToggle(' + idx + ')">' +
        '<td>' + ds + '</td>' +
        '<td><b>' + (sf.champion_name || ('#' + (sf.champion_id || '?'))) + '</b></td>' +
        '<td class="num ' + (r.win ? 'pos' : 'neg') + '">' + (r.win ? '胜' : '负') + '</td>' +
        '<td class="num">' + kda + '</td>' +
        '<td class="num">' + (sf.gold != null ? C.fmtInt(sf.gold) : '—') + '</td>' +
        '<td class="num">' + (sf.vision != null ? sf.vision.toFixed(0) : '—') + '</td>' +
        '<td class="num">' + (sf.cs != null ? sf.cs.toFixed(0) : '—') + '</td>' +
        '<td>' + (r.source || '—') + '</td>' +
        '<td class="num"><span class="lnk">展开 ▾</span></td></tr>' +
        '<tr id="ps-detail-' + idx + '" style="display:none"><td colspan="9">' +
        renderPsDetail(r) + '</td></tr>';
    }).join('') : '<tr><td colspan="9" class="hint">无</td></tr>';
    $('tbl-personal-recent').innerHTML = recHead + '<tbody>' + recBody + '</tbody>';
  }

  function renderPsDetail(r) {
    var sf = r.self || {};
    var mk = function (label, val) {
      return '<div class="kv"><span>' + label + '</span><b>' + val + '</b></div>';
    };
    var html = '<div class="ps-detail">';
    html += '<div class="ps-self">';
    html += '<h4>本人 · ' + (sf.champion_name || '') + ' · ' + (r.win ? '胜利' : '失败') + '</h4>';
    html += mk('K/D/A', [sf.kills, sf.deaths, sf.assists].join('/') +
      (sf.kda != null ? '（KDA ' + sf.kda + '）' : ''));
    html += mk('对英雄伤害', sf.dmg_champ != null ? C.fmtInt(sf.dmg_champ) : '—');
    html += mk('伤害构成', '魔 ' + (sf.magic != null ? C.fmtInt(sf.magic) : '—') + ' / 物 ' +
      (sf.phys != null ? C.fmtInt(sf.phys) : '—') + ' / 真 ' + (sf.true != null ? C.fmtInt(sf.true) : '—'));
    html += mk('承伤/减伤', (sf.dmg_taken != null ? C.fmtInt(sf.dmg_taken) : '—') + ' / ' +
      (sf.dmg_mitigated != null ? C.fmtInt(sf.dmg_mitigated) : '—'));
    html += mk('金/视野/CS', C.fmtInt(sf.gold != null ? sf.gold : 0) + ' / ' +
      (sf.vision != null ? sf.vision.toFixed(0) : '—') + ' / ' + (sf.cs != null ? sf.cs.toFixed(0) : '—'));
    html += mk('治疗', sf.heal != null ? C.fmtInt(sf.heal) : '—');
    html += mk('装备', (sf.items && sf.items.length) ? sf.items.join(', ') : '—');
    html += mk('海克斯', (sf.augments && sf.augments.length) ? sf.augments.join(', ') : '—');
    html += mk('符文', (sf.primary_style != null ? '主' + sf.primary_style : '') +
      (sf.secondary_style != null ? ' / 副' + sf.secondary_style : '') +
      ((sf.perks && sf.perks.length) ? ' / ' + sf.perks.join(',') : ''));
    html += mk('多杀', '双' + (sf.multikills ? sf.multikills.double : 0) + ' 三' +
      (sf.multikills ? sf.multikills.triple : 0) + ' 四' + (sf.multikills ? sf.multikills.quadra : 0) +
      ' 五' + (sf.multikills ? sf.multikills.penta : 0) + (sf.first_blood ? ' 一血' : ''));
    html += '</div>';
    html += '<div class="ps-teams">';
    (r.participants || []).forEach(function (pp) {
      html += '<div class="ps-p ' + (pp.win ? 'win' : 'lose') + '">' +
        '<span class="t' + (pp.team_id == 100 ? ' b' : ' r') + '">' +
        (pp.team_id == 100 ? '蓝' : '红') + '</span> ' +
        '<b>' + (pp.champion_name || '?') + '</b> ' +
        '<span class="nm">' + (pp.summoner_name || '') + '</span> ' +
        '<span class="num">' + [pp.kills, pp.deaths, pp.assists].join('/') + '</span> ' +
        '<span class="dim">伤害 ' + (pp.dmg_champ != null ? C.fmtInt(pp.dmg_champ) : '—') +
        ' · 金 ' + (pp.gold != null ? C.fmtInt(pp.gold) : '—') + '</span></div>';
    });
    html += '</div>';
    html += '</div>';
    return html;
  }

  window.__psToggle = function (idx) {
    var row = document.getElementById('ps-detail-' + idx);
    if (row) { row.style.display = (row.style.display === 'none') ? '' : 'none'; }
  };

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
      strata: renderStrata, version: renderVersion, resg: renderResg, personal: renderPersonal }[state.tab];
    if (fn) { fn(); }
    // 概览/排名依赖同一批筛选：切换 tab 时已重绘当前面板
  }

  function activateTab(name) {
    state.tab = name;
    Array.prototype.forEach.call($('tabs').children, function (b) {
      b.classList.toggle('active', b.getAttribute('data-tab') === name);
    });
    ['overview', 'ranking', 'synergy', 'strata', 'version', 'resg', 'personal'].forEach(function (p) {
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
