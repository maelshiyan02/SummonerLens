/*!
 * SummonerLens · 仪表板核心逻辑（纯函数，无 DOM 依赖）
 *
 * 设计约束：
 *  1) 同一份文件既在浏览器（window.SLCore）也可被 node `require()` —— 便于 headless 单测。
 *  2) 所有函数**纯**：不读全局、不碰 DOM、不改入参。
 *  3) 图表 option 在此集中构造，`js/app.js` 只负责挂载与交互。
 *
 * 口径与 Python 层（python/stats/wilson.py）保持一致：样本分档 low<250 / medium 250-999 / high>=1000。
 * 颜色遵循中文习惯：胜率高/协同 lift 为正 → 红；低/为负 → 绿。（见计划书「区域约定」）
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else {
    root.SLCore = factory();
  }
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  var VERSION = '1.0.0';
  var RANK_METHOD = 'sample_tier_then_wilson_lower_bound_v1';

  var TIER_ORDER = { high: 2, medium: 1, low: 0 };
  var TIER_COLOR = { high: '#e8b23a', medium: '#4a9eff', low: '#7b8496' };
  var RARITY_COLOR = { '棱彩': '#c86bff', '黄金': '#e8b23a', '白银': '#b8c0cc', '青铜': '#c08050' };
  var ROLE_COLOR = {
    '战士': '#d9534f', '坦克': '#8ab4f8', '法师': '#a06cf0',
    '刺客': '#e07a3f', '射手': '#3fc0a0', '辅助': '#5fc76a'
  };

  // ---------------------------------------------------------------- 归一化 / 搜索
  function normalize(s) {
    return String(s == null ? '' : s).replace(/\s+/g, '').toLowerCase();
  }

  function tierColor(tier) {
    return TIER_COLOR[tier] || TIER_COLOR.low;
  }

  function roleColor(role) {
    return ROLE_COLOR[role] || '#7b8496';
  }

  /** 别名/昵称 → 英雄数值 key；未命中返回 null。index 形如 {'快乐风男': 157} */
  function decodeAlias(aliasIndex, raw) {
    var key = normalize(raw);
    if (!key) { return null; }
    if (Object.prototype.hasOwnProperty.call(aliasIndex, key)) {
      return aliasIndex[key];
    }
    return null;
  }

  /** 在英雄列表里按 名称/称号/别名 模糊搜索，返回命中的英雄对象数组（保序、去重）。 */
  function searchHeroes(heroes, aliasIndex, query) {
    var q = normalize(query);
    if (!q) { return []; }
    var exact = decodeAlias(aliasIndex, query);
    var out = [];
    var seen = {};
    if (exact != null) {
      heroes.forEach(function (h) {
        if (h.key === exact && !seen[h.key]) { seen[h.key] = 1; out.push(h); }
      });
    }
    heroes.forEach(function (h) {
      if (seen[h.key]) { return; }
      var hay = [h.name, h.title].concat(h.aliases || []).map(normalize).join('|');
      if (hay.indexOf(q) >= 0) { seen[h.key] = 1; out.push(h); }
    });
    return out;
  }

  // ---------------------------------------------------------------- 筛选
  function filterByTier(rows, tier) {
    if (!tier || tier === 'all') { return rows.slice(); }
    return rows.filter(function (r) { return r.sample_tier === tier; });
  }

  function filterByStratum(rows, stratum) {
    if (!stratum || stratum === 'all') {
      return rows.filter(function (r) { return r.stratum === 'all'; });
    }
    return rows.filter(function (r) { return r.stratum === stratum; });
  }

  function filterByRecommendation(rows, level) {
    if (!level || level === 'all') { return rows.slice(); }
    return rows.filter(function (r) { return r.recommendation_level === level; });
  }

  /** 按角色筛选英雄统计行（需 heroKey→roles 映射）。 */
  function filterByRole(rows, role, heroRoles) {
    if (!role || role === 'all') { return rows.slice(); }
    return rows.filter(function (r) {
      var roles = (heroRoles && heroRoles[r.key]) || r.roles || [];
      return roles.indexOf(role) >= 0;
    });
  }

  /** HEROES 列表 → {key: [roles]}，供 filterByRole 使用。 */
  function buildRoleMap(heroes) {
    var m = {};
    (heroes || []).forEach(function (h) { m[h.key] = h.roles || []; });
    return m;
  }

  function topN(rows, n) {
    return rows.slice(0, n == null ? rows.length : n);
  }

  /** 行显示名：兼容英雄/Augment/切片表（不同表用不同 id 字段）。 */
  function rowLabel(r) {
    if (!r) { return '—'; }
    if (r.name) { return r.name; }
    if (r.champion_name) { return r.champion_name; }
    if (r.augment_name) { return r.augment_name; }
    var id = (r.key != null) ? r.key : (r.champion_id != null ? r.champion_id
      : (r.augment_id != null ? r.augment_id : r.item_id));
    return id != null ? ('#' + id) : '—';
  }

  // ---------------------------------------------------------------- 图表 option
  /** 英雄/Augment 排名：横向双条叠加（浅色=观测胜率 / 实色=Wilson 95% 下界）。
   *
   * 说明：真实聚合样本极大（百万级）时 Wilson 区间窄到肉眼不可见，
   * 故不用「区间带」而用「下界条」表达排序信号（下界更保守、跨样本量可比）。
   */
  function buildRankingOption(rows, opts) {
    opts = opts || {};
    var n = opts.topN || 15;
    var picked = topN(rows, n).slice().reverse(); // rank1 显示在最上
    var names = picked.map(rowLabel);
    var rawData = picked.map(function (r) {
      return { value: +r.winRate, itemStyle: { color: 'rgba(138,147,166,0.42)' } };
    });
    var lbData = picked.map(function (r) {
      return { value: +r.wilson_lower, itemStyle: { color: tierColor(r.sample_tier) } };
    });

    // 动态 x 轴范围（留边距，线条不从 0 起，便于分辨差异）
    var vals = picked.map(function (r) { return +r.wilson_lower; })
      .concat(picked.map(function (r) { return +r.winRate; }));
    var lo = Math.max(0, Math.floor((Math.min.apply(null, vals) - 0.03) * 50) / 50);
    var hi = Math.min(1, Math.ceil((Math.max.apply(null, vals) + 0.03) * 50) / 50);

    return {
      backgroundColor: 'transparent',
      grid: { left: 100, right: 44, top: 12, bottom: 28 },
      tooltip: {
        trigger: 'axis', axisPointer: { type: 'shadow' },
        formatter: function (ps) {
          var i = ps[0].dataIndex;
          var r = picked[i];
          return '<b>' + rowLabel(r) + '</b><br/>' +
            '观测胜率 ' + pct(r.winRate) + '<br/>' +
            '<b>Wilson 下界 ' + pct(r.wilson_lower) + '</b><br/>' +
            '95% CI [' + pct(r.wilson_lower) + ', ' + pct(r.wilson_upper) + ']<br/>' +
            '样本 ' + fmtInt(r.games) + '（' + tierZh(r.sample_tier) + '）<br/>' +
            '推荐级 ' + recZh(r.recommendation_level);
        }
      },
      xAxis: {
        type: 'value', min: opts.xMin != null ? opts.xMin : lo, max: opts.xMax != null ? opts.xMax : hi,
        axisLabel: { formatter: function (v) { return (v * 100).toFixed(0) + '%'; }, color: '#8a93a6' },
        splitLine: { lineStyle: { color: 'rgba(255,255,255,0.06)' } }
      },
      yAxis: {
        type: 'category', data: names, inverse: false,
        axisLabel: { color: '#c8d0de', fontSize: 12 },
        axisLine: { lineStyle: { color: 'rgba(255,255,255,0.12)' } },
        axisTick: { show: false }
      },
      series: [
        {
          name: '观测胜率', type: 'bar', barWidth: 15, barGap: '-100%', z: 1,
          silent: true, tooltip: { show: false }, data: rawData
        },
        {
          name: 'Wilson 下界', type: 'bar', barWidth: 15, z: 2, data: lbData,
          label: { show: false }
        }
      ]
    };
  }

  /** 样本档分布：环形图。 */
  function buildTierDonutOption(rows) {
    var order = ['high', 'medium', 'low'];
    var counts = { high: 0, medium: 0, low: 0 };
    rows.forEach(function (r) { if (counts[r.sample_tier] != null) { counts[r.sample_tier]++; } });
    var data = order.filter(function (t) { return counts[t] > 0; }).map(function (t) {
      return { name: tierZh(t), value: counts[t], itemStyle: { color: TIER_COLOR[t] } };
    });
    return {
      backgroundColor: 'transparent',
      tooltip: { trigger: 'item', formatter: '{b}：{c} 项（{d}%）' },
      legend: { bottom: 0, textStyle: { color: '#c8d0de' }, icon: 'circle' },
      series: [{
        type: 'pie', radius: ['46%', '70%'], center: ['50%', '45%'], avoidLabelOverlap: true,
        label: { color: '#c8d0de', formatter: '{b}\n{c}' },
        labelLine: { lineStyle: { color: 'rgba(255,255,255,0.25)' } },
        data: data
      }]
    };
  }

  /** 协同热力图：英雄(×) × Augment(×) 的 lift_vs_hero。 */
  function buildSynergyHeatmapOption(rows, opts) {
    opts = opts || {};
    var heroes = [], augs = [];
    var hi = {}, ai = {};
    rows.forEach(function (r) {
      var hn = r.champion_name || ('#' + r.champion_id);
      var an = r.augment_name || ('#' + r.augment_id);
      if (hi[hn] == null) { hi[hn] = heroes.length; heroes.push(hn); }
      if (ai[an] == null) { ai[an] = augs.length; augs.push(an); }
    });
    var data = rows.map(function (r) {
      var v = r.lift_vs_hero;
      return [ai[r.augment_name || ('#' + r.augment_id)],
              hi[r.champion_name || ('#' + r.champion_id)],
              v == null ? 0 : +v];
    });
    var maxAbs = 0.001;
    rows.forEach(function (r) {
      var v = Math.abs(+r.lift_vs_hero || 0);
      if (v > maxAbs) { maxAbs = v; }
    });
    return {
      backgroundColor: 'transparent',
      tooltip: {
        position: 'top',
        formatter: function (p) {
          var r = rows[p.dataIndex];
          return '<b>' + (r.champion_name || r.champion_id) + '</b> × <b>' +
            (r.augment_name || r.augment_id) + '</b><br/>' +
            '组合胜率 ' + pct(r.winRate) + '<br/>' +
            '英雄边际 ' + pct(r.expected_hero_wr) + '<br/>' +
            '<b>lift ' + signedPct(r.lift_vs_hero) + '</b><br/>样本 ' + fmtInt(r.games);
        }
      },
      grid: { left: 90, right: 24, top: 16, bottom: 64 },
      xAxis: {
        type: 'category', data: augs, splitArea: { show: true },
        axisLabel: { color: '#c8d0de', rotate: 24 }, axisLine: { lineStyle: { color: 'rgba(255,255,255,0.12)' } }
      },
      yAxis: {
        type: 'category', data: heroes, splitArea: { show: true },
        axisLabel: { color: '#c8d0de' }, axisLine: { lineStyle: { color: 'rgba(255,255,255,0.12)' } }
      },
      visualMap: {
        min: -maxAbs, max: maxAbs, calculable: true, orient: 'horizontal',
        left: 'center', bottom: 4, textStyle: { color: '#c8d0de' },
        text: ['协同↑（红）', '协同↓（绿）'],
        inRange: { color: ['#3fc76a', '#1b2230', '#ff5b5b'] }
      },
      series: [{
        name: 'lift_vs_hero', type: 'heatmap', data: data,
        label: {
          show: true, color: '#e8edf6', fontSize: 11,
          formatter: function (p) { return signedPct(p.value[2], 0); }
        },
        emphasis: { itemStyle: { borderColor: '#fff', borderWidth: 1 } }
      }]
    };
  }

  /** MMR 分布直方图（含分层阈值线）。 */
  function buildMmrHistogramOption(players, opts) {
    opts = opts || {};
    var vals = players.map(function (p) { return +p.estimated_mmr; });
    var bin = opts.bin || 50;
    var lo = Math.floor((Math.min.apply(null, vals)) / bin) * bin;
    var hi = Math.ceil((Math.max.apply(null, vals)) / bin) * bin;
    var bins = [], counts = [];
    for (var x = lo; x <= hi; x += bin) {
      bins.push(x);
      counts.push(vals.filter(function (v) { return v >= x && v < x + bin; }).length);
    }
    var thr = opts.thresholds || {};
    // 类目轴上 markLine 的 xAxis 会被当作「索引」，故用分箱索引（数值会被误当索引而越界）
    function snapIdx(v) {
      var i = Math.round((v - lo) / bin);
      return Math.max(0, Math.min(bins.length - 1, i));
    }
    var marks = ['thr40', 'thr20'].filter(function (k) { return thr[k] != null; }).map(function (k) {
      return {
        xAxis: snapIdx(thr[k]),
        lineStyle: { color: k === 'thr20' ? '#e8b23a' : '#4a9eff', type: 'dashed', width: 2 },
        label: {
          formatter: (k === 'thr20' ? '前20% ' : '前40% ') + Math.round(thr[k]),
          color: k === 'thr20' ? '#e8b23a' : '#4a9eff', fontSize: 11, position: 'insideEndTop'
        }
      };
    });
    return {
      backgroundColor: 'transparent',
      tooltip: { trigger: 'axis', formatter: function (ps) { return 'MMR ' + ps[0].axisValue + '–' + (ps[0].axisValue + bin) + '：' + ps[0].data + ' 人'; } },
      grid: { left: 44, right: 20, top: 20, bottom: 34 },
      xAxis: { type: 'category', data: bins, axisLabel: { color: '#8a93a6' }, axisLine: { lineStyle: { color: 'rgba(255,255,255,0.12)' } } },
      yAxis: { type: 'value', name: '玩家数', nameTextStyle: { color: '#8a93a6' }, axisLabel: { color: '#8a93a6' }, splitLine: { lineStyle: { color: 'rgba(255,255,255,0.06)' } } },
      series: [{
        type: 'bar', data: counts, barCategoryGap: '12%',
        itemStyle: { color: '#4a9eff' }, markLine: { silent: true, symbol: 'none', data: marks }
      }]
    };
  }

  /** 协同对比：组合胜率 vs 英雄边际胜率（按 lift 降序），稀疏数据比热力图更清晰。 */
  function buildSynergyCompareOption(rows, opts) {
    opts = opts || {};
    var n = opts.topN || 12;
    var picked = rows.slice().sort(function (a, b) {
      return (+b.lift_vs_hero || 0) - (+a.lift_vs_hero || 0);
    }).slice(0, n).reverse();
    var labels = picked.map(function (r) {
      return (r.champion_name || r.champion_id) + ' × ' + (r.augment_name || r.augment_id);
    });
    return {
      backgroundColor: 'transparent',
      grid: { left: 150, right: 40, top: 30, bottom: 28 },
      legend: { top: 0, textStyle: { color: '#c8d0de' }, data: ['组合胜率', '英雄边际'] },
      tooltip: {
        trigger: 'axis', axisPointer: { type: 'shadow' },
        formatter: function (ps) {
          var i = ps[0].dataIndex;
          var r = picked[i];
          return '<b>' + labels[i] + '</b><br/>' +
            '组合胜率 ' + pct(r.winRate) + '<br/>' +
            '英雄边际 ' + pct(r.expected_hero_wr) + '<br/>' +
            '<b>lift ' + signedPct(r.lift_vs_hero) + '</b>（vs 全局 ' + signedPct(r.lift_vs_global) + '）<br/>' +
            '样本 ' + fmtInt(r.games);
        }
      },
      xAxis: {
        type: 'value', min: 0.3, max: 0.7,
        axisLabel: { formatter: function (v) { return (v * 100).toFixed(0) + '%'; }, color: '#8a93a6' },
        splitLine: { lineStyle: { color: 'rgba(255,255,255,0.06)' } }
      },
      yAxis: {
        type: 'category', data: labels, axisLabel: { color: '#c8d0de', fontSize: 11, width: 140, overflow: 'truncate' },
        axisLine: { lineStyle: { color: 'rgba(255,255,255,0.12)' } }, axisTick: { show: false }
      },
      series: [
        {
          name: '组合胜率', type: 'bar', barWidth: 9,
          data: picked.map(function (r) {
            return { value: +r.winRate, itemStyle: { color: (+r.lift_vs_hero >= 0) ? '#ff5b5b' : '#3fc76a' } };
          }),
          label: {
            show: true, position: 'right', color: '#c8d0de', fontSize: 11,
            formatter: function (p) { return signedPct(picked[p.dataIndex].lift_vs_hero, 0); }
          }
        },
        {
          name: '英雄边际', type: 'scatter', symbol: 'diamond', symbolSize: 11,
          itemStyle: { color: '#ffffff' }, z: 5,
          data: picked.map(function (r, i) { return [+r.expected_hero_wr, labels[i]]; })
        }
      ]
    };
  }

  // ---------------------------------------------------------------- 汇总 / KPI
  function kpis(bundle) {
    var heroRows = (bundle.datasets.hero_ranking || { rows: [] }).rows;
    var augRows = (bundle.datasets.augment_ranking || { rows: [] }).rows;
    var fm = bundle.fixture_meta || {};
    var ad = fm.anti_domination || {};
    return {
      heroCount: heroRows.length,
      augmentCount: augRows.length,
      aliasCount: Object.keys(bundle.alias_index || {}).length,
      heroTotal: (bundle.heroes || []).length,
      fixtureRecords: fm.n_records || 0,
      mmrCorr: fm.mmr_recovery_corr != null ? fm.mmr_recovery_corr : null,
      antiDemoted: !!ad.demoted,
      antiRawTop: ad.raw_top != null ? ad.raw_top : null,
      antiWilsonRank: ad.raw_top_wilson_rank != null ? ad.raw_top_wilson_rank : null,
      metaVersion: bundle.meta_version
    };
  }

  /** 取"真实聚合"英雄排名行（hexdata）。 */
  function realHeroRows(bundle) {
    return ((bundle.datasets || {}).hero_ranking || { rows: [] }).rows;
  }
  /** 取"合成夹具"英雄统计行。 */
  function fixtureHeroRows(bundle) {
    return ((bundle.datasets || {}).fixture_hero_stats || { rows: [] }).rows;
  }

  /** 数据集的来源徽标文案。 */
  function provenanceOf(bundle, key) {
    var p = (((bundle.datasets || {})[key] || {}).prov) || { kind: 'unavailable' };
    return p;
  }

  // ---------------------------------------------------------------- 小工具
  function pct(v) {
    if (v == null || isNaN(v)) { return '—'; }
    return (v * 100).toFixed(2) + '%';
  }
  function signedPct(v, digits) {
    if (v == null || isNaN(v)) { return '—'; }
    var d = digits == null ? 1 : digits;
    return (v >= 0 ? '+' : '') + (v * 100).toFixed(d) + 'pp';
  }
  function fmtInt(v) {
    if (v == null || isNaN(v)) { return '—'; }
    return Number(v).toLocaleString('en-US');
  }
  function tierZh(t) { return { high: '高样本', medium: '中样本', low: '低样本' }[t] || t; }
  function recZh(r) { return { strong: '强力推荐', recommend: '可参考', none: '样本不足' }[r] || r; }

  return {
    VERSION: VERSION,
    RANK_METHOD: RANK_METHOD,
    TIER_ORDER: TIER_ORDER,
    TIER_COLOR: TIER_COLOR,
    RARITY_COLOR: RARITY_COLOR,
    ROLE_COLOR: ROLE_COLOR,
    normalize: normalize,
    tierColor: tierColor,
    roleColor: roleColor,
    decodeAlias: decodeAlias,
    searchHeroes: searchHeroes,
    filterByTier: filterByTier,
    filterByStratum: filterByStratum,
    filterByRecommendation: filterByRecommendation,
    filterByRole: filterByRole,
    buildRoleMap: buildRoleMap,
    topN: topN,
    rowLabel: rowLabel,
    buildRankingOption: buildRankingOption,
    buildTierDonutOption: buildTierDonutOption,
    buildSynergyHeatmapOption: buildSynergyHeatmapOption,
    buildSynergyCompareOption: buildSynergyCompareOption,
    buildMmrHistogramOption: buildMmrHistogramOption,
    kpis: kpis,
    realHeroRows: realHeroRows,
    fixtureHeroRows: fixtureHeroRows,
    provenanceOf: provenanceOf,
    pct: pct,
    signedPct: signedPct,
    fmtInt: fmtInt,
    tierZh: tierZh,
    recZh: recZh
  };
});
