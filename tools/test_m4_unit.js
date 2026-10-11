#!/usr/bin/env node
/*!
 * M4 · 仪表板核心逻辑单元测试（node，无需浏览器）
 *
 * 覆盖：别名归一/搜索、筛选联动、图表 option 构造、数据集来源标注。
 * 用法：
 *   node tools/test_m4_unit.js              正常：全绿，退出码 0
 *   node tools/test_m4_unit.js --self-test  故障注入：只改**输入**、判据不变 → 必须变红，退出码 1
 *
 * 纪律（见 kb/M11）：绿/红共用同一套 check 与判据，只换输入；否则断言只是装饰品。
 */
'use strict';
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const CORE = path.join(ROOT, 'app', 'web', 'js', 'core.js');
const BUNDLE = path.join(ROOT, 'app', 'web', 'data', 'dashboard.json');

const SELF = process.argv.includes('--self-test');

if (!fs.existsSync(BUNDLE)) {
  console.error('❌ 缺少数据束：' + BUNDLE + '\n   先运行：python python/bridge/build_viz_bundle.py');
  process.exit(2);
}

const C = require(CORE);
const bundle = JSON.parse(fs.readFileSync(BUNDLE, 'utf8'));

let pass = 0, fail = 0;
const failures = [];
function check(name, cond) {
  if (cond) { pass++; }
  else { fail++; failures.push(name); }
}
function group(title) { console.log('\n' + title); }

// ---------------------------------------------------------------- 取数（故障注入点）
const realRows = C.realHeroRows(bundle);
const augRows = ((bundle.datasets || {}).augment_ranking || { rows: [] }).rows;
const fixHero = C.fixtureHeroRows(bundle);
const fixAug = ((bundle.datasets || {}).fixture_augment_stats || { rows: [] }).rows;
const pairs = ((bundle.datasets || {}).fixture_hero_augment_pairs || { rows: [] }).rows;
const players = ((bundle.datasets || {}).fixture_player_mmr || { rows: [] }).rows;
const slices = ((bundle.datasets || {}).fixture_slices_hero_stats || { rows: [] }).rows;
const roleMap = C.buildRoleMap(bundle.heroes);

if (SELF) {
  // 只改输入，不改判据 —— 下列断言应因此变红
  bundle.alias_index['快乐风男'] = 777;          // 破坏别名映射
  realRows.reverse();                            // 破坏排名顺序（rank1 不再在末位）
  fixHero.splice(0, fixHero.length,
    ...fixHero.filter(function (r) { return r.sample_tier === 'low'; })); // 破坏档位筛选前提
  players.pop();                                 // 破坏直方图总数
  pairs.pop();                                   // 破坏热力/对比矩阵行数
  slices.splice(0, slices.length,
    ...slices.filter(function (r) { return r.stratum === 'top40'; }));    // 破坏分层筛选前提
}

// ---------------------------------------------------------------- A. 别名归一 / 搜索
group('A. 别名归一 / 搜索');
check('normalize 去空白并小写', C.normalize(' 快乐 风男 ') === '快乐风男' && C.normalize('TF') === 'tf');
check('normalize null 安全', C.normalize(null) === '' && C.normalize(undefined) === '');
check('decodeAlias 昵称 快乐风男 → 157', C.decodeAlias(bundle.alias_index, '快乐风男') === 157);
check('decodeAlias 全名 亚索 → 157', C.decodeAlias(bundle.alias_index, '亚索') === 157);
check('decodeAlias 英文缩写 TF → 4', C.decodeAlias(bundle.alias_index, 'TF') === 4);
check('decodeAlias 昵称 火女 → 1', C.decodeAlias(bundle.alias_index, '火女') === 1);
check('decodeAlias 未命中 → null', C.decodeAlias(bundle.alias_index, '不存在的英雄zzz') === null);
check('decodeAlias 空串 → null', C.decodeAlias(bundle.alias_index, '   ') === null);

const hitYasuo = C.searchHeroes(bundle.heroes, bundle.alias_index, '亚索');
check('searchHeroes("亚索") 命中且精确项排首位', hitYasuo.length > 0 && hitYasuo[0].key === 157);
check('searchHeroes("火女") 命中安妮(1)', C.searchHeroes(bundle.heroes, bundle.alias_index, '火女')
  .some(function (h) { return h.key === 1; }));
check('searchHeroes 空串 → 空数组', C.searchHeroes(bundle.heroes, bundle.alias_index, '').length === 0);
check('searchHeroes 未命中 → 空数组', C.searchHeroes(bundle.heroes, bundle.alias_index, 'zzzzz').length === 0);
check('searchHeroes 结果无重复', (function () {
  var k = C.searchHeroes(bundle.heroes, bundle.alias_index, '亚').map(function (h) { return h.key; });
  return new Set(k).size === k.length;
})());

// ---------------------------------------------------------------- B. 档位口径
group('B. 样本档口径（与 python/stats/wilson.py 对齐）');
check('档位序 high > medium > low', C.TIER_ORDER.high > C.TIER_ORDER.medium && C.TIER_ORDER.medium > C.TIER_ORDER.low);
check('tierZh 三档齐备', C.tierZh('high') === '高样本' && C.tierZh('medium') === '中样本' && C.tierZh('low') === '低样本');
check('tierColor 三档齐备且互异', C.tierColor('high') !== C.tierColor('medium') && C.tierColor('medium') !== C.tierColor('low'));
check('recZh 三档齐备', C.recZh('strong') === '强力推荐' && C.recZh('recommend') === '可参考' && C.recZh('none') === '样本不足');
check('RANK_METHOD 与 M3 一致', C.RANK_METHOD === 'sample_tier_then_wilson_lower_bound_v1');

// ---------------------------------------------------------------- C. 筛选联动
group('C. 筛选联动');
// 注意：每条「只留 X」都必须同时断言**非空**，否则空数组的 .every() 恒真（空结果判 FAIL）。
check('filterByTier high 只留 high', (function () {
  var r = C.filterByTier(fixHero, 'high');
  return r.length > 0 && r.every(function (x) { return x.sample_tier === 'high'; });
})());
check('filterByTier low 只留 low', (function () {
  var r = C.filterByTier(fixHero, 'low');
  return r.length > 0 && r.every(function (x) { return x.sample_tier === 'low'; });
})());
check('filterByTier all = 恒等（不变性）', C.filterByTier(fixHero, 'all').length === fixHero.length);
check('filterByRecommendation strong 只留 strong', (function () {
  var r = C.filterByRecommendation(fixHero, 'strong');
  return r.length > 0 && r.every(function (x) { return x.recommendation_level === 'strong'; });
})());
check('filterByRecommendation all = 恒等', C.filterByRecommendation(fixHero, 'all').length === fixHero.length);
check('filterByStratum top20 只留 top20', (function () {
  var r = C.filterByStratum(slices, 'top20');
  return r.length > 0 && r.every(function (x) { return x.stratum === 'top20'; });
})());
check('filterByStratum all 只留 all', (function () {
  var r = C.filterByStratum(slices, 'all');
  return r.length > 0 && r.every(function (x) { return x.stratum === 'all'; });
})());
check('filterByRole 战士 命中且仅命中战士', (function () {
  var rows = C.filterByRole(fixHero, '战士', roleMap);
  return rows.length > 0 && rows.every(function (r) { return (roleMap[r.key] || []).indexOf('战士') >= 0; });
})());
check('filterByRole all = 恒等', C.filterByRole(fixHero, 'all', roleMap).length === fixHero.length);
check('buildRoleMap 覆盖全部英雄', Object.keys(roleMap).length === bundle.heroes.length);
check('筛选收敛：tier∩rec ⊆ 各自', (function () {
  var a = C.filterByTier(fixHero, 'high');
  var b = C.filterByRecommendation(a, 'strong');
  return b.length <= a.length;
})());

// ---------------------------------------------------------------- D. 图表 option
group('D. 图表 option 构造');
// 独立基准：用各行自带的 `rank` 字段确定真实名次，不依赖数组顺序（否则「反转输入」改不动判据）。
const DI = bundle.dataset_index || {};
function byRank(rows) { return rows.slice().sort(function (a, b) { return a.rank - b.rank; }); }
const top5 = byRank(realRows).slice(0, 5); // rank 1..5

const opt = C.buildRankingOption(realRows, { topN: 5 });
check('排名 option 取 topN 条类目', opt.yAxis.data.length === 5);
check('排名 option 末位 = rank1（自上而下名次递增）',
  opt.yAxis.data[opt.yAxis.data.length - 1] === C.rowLabel(top5[0]));
check('排名 option 首位 = 第5名', opt.yAxis.data[0] === C.rowLabel(top5[4]));
check('排名 option 下界序列与 rank 基准对应', (function () {
  var d = opt.series[1].data.map(function (x) { return x.value; });
  var expect = top5.slice().reverse().map(function (r) { return +r.wilson_lower; });
  return d.length === 5 && d.every(function (v, i) { return Math.abs(v - expect[i]) < 1e-12; });
})());
check('排名 option x 轴范围包含 top5 全部取值', (function () {
  var lo = Math.min.apply(null, top5.map(function (r) { return +r.wilson_lower; }));
  var hi = Math.max.apply(null, top5.map(function (r) { return +r.winRate; }));
  return opt.xAxis.min <= lo && opt.xAxis.max >= hi;
})());
check('排名 option 双条叠加（barGap 负值）', opt.series[0].barGap === '-100%' && opt.series.length === 2);
check('排名 option 档位着色一致（按 rank 基准）', (function () {
  var d = opt.series[1].data;
  return d.every(function (x, i) { return x.itemStyle.color === C.tierColor(top5.slice().reverse()[i].sample_tier); });
})());

const donut = C.buildTierDonutOption(fixHero);
check('环形图总数 = 夹具英雄总数（独立基准）',
  donut.series[0].data.reduce(function (a, x) { return a + x.value; }, 0) === DI.fixture_hero_stats.rows);
check('环形图仅含存在档位', donut.series[0].data.every(function (x) { return x.value > 0; }));

const hm = C.buildSynergyHeatmapOption(pairs);
check('协同热力图 x/y 为去重维', (function () {
  var xs = {}, ys = {};
  pairs.forEach(function (r) {
    xs[r.augment_name || r.augment_id] = 1;
    ys[r.champion_name || r.champion_id] = 1;
  });
  return hm.xAxis.data.length === Object.keys(xs).length && hm.yAxis.data.length === Object.keys(ys).length;
})());
check('协同热力图数据行数 = 组合数（独立基准）',
  hm.series[0].data.length === DI.fixture_hero_augment_pairs.rows);
check('协同热力图 visualMap 以 0 为中心', hm.visualMap.min < 0 && hm.visualMap.max > 0 &&
  Math.abs(hm.visualMap.min + hm.visualMap.max) < 1e-12);
check('协同热力图 lift 值域与输入一致', (function () {
  var v = hm.series[0].data.map(function (x) { return x[2]; });
  var e = pairs.map(function (r) { return +r.lift_vs_hero; });
  return v.length === e.length && v.every(function (x, i) { return Math.abs(x - e[i]) < 1e-12; });
})());

const cmp = C.buildSynergyCompareOption(pairs);
check('协同对比图按 lift 降序（最高 lift 在末位）', (function () {
  if (!pairs.length) return false;
  var maxLift = Math.max.apply(null, pairs.map(function (r) { return +r.lift_vs_hero; }));
  var topLabel = cmp.yAxis.data[cmp.yAxis.data.length - 1];
  var r = pairs.filter(function (x) { return +x.lift_vs_hero === maxLift; })[0];
  return topLabel === ((r.champion_name || r.champion_id) + ' × ' + (r.augment_name || r.augment_id));
})());
check('协同对比图行数 = 组合数（独立基准）', cmp.series[0].data.length === DI.fixture_hero_augment_pairs.rows);
check('协同对比图含组合胜率与英雄边际两条序列', cmp.series.length === 2);

const hist = C.buildMmrHistogramOption(players, { thresholds: { thr20: 1712.1, thr40: 1570.7 } });
check('MMR 直方图总数 = 分层玩家数（独立基准：fixture_meta.strata.n）',
  hist.series[0].data.reduce(function (a, b) { return a + b; }, 0) === bundle.fixture_meta.strata.n);
check('MMR 阈值线落在分箱范围内', hist.series[0].markLine.data.every(function (m) {
  return m.xAxis >= 0 && m.xAxis <= hist.xAxis.data.length - 1;
}));
check('MMR 阈值线数量 = 2', hist.series[0].markLine.data.length === 2);

// ---------------------------------------------------------------- E. 度量格式化
group('E. 度量格式化');
check('pct 百分比两位小数', C.pct(0.5742) === '57.42%');
check('pct 空值 → —', C.pct(null) === '—' && C.pct(undefined) === '—');
check('signedPct 带符号与 pp 单位', C.signedPct(0.1379) === '+13.8pp' && C.signedPct(-0.079) === '-7.9pp');
check('fmtInt 千分位', C.fmtInt(1829755) === '1,829,755');
check('rowLabel 兼容不同 id 字段',
  C.rowLabel({ name: 'A' }) === 'A' && C.rowLabel({ champion_name: 'B' }) === 'B' &&
  C.rowLabel({ key: 9 }) === '#9' && C.rowLabel({}) === '—');

// ---------------------------------------------------------------- F. KPI / 溯源
group('F. KPI 与来源标注（合规）');
const k = C.kpis(bundle);
check('kpis 英雄数 = 真实榜行数', k.heroCount === realRows.length);
check('kpis 别名数 > 0', k.aliasCount > 0);
check('kpis 含 metaVersion', !!k.metaVersion);
const idx = bundle.dataset_index || {};
check('每个数据集都标了来源 kind', Object.keys(idx).every(function (kk) {
  return ['real_aggregate', 'synthetic_fixture'].indexOf(idx[kk].kind) >= 0;
}));
check('真实聚合数据集不得标 synthetic_fixture', idx.hero_ranking.kind === 'real_aggregate' &&
  idx.augment_ranking.kind === 'real_aggregate');
check('夹具数据集必须标 synthetic_fixture', idx.fixture_hero_stats.kind === 'synthetic_fixture');
check('bundle 必须带警告文案', Array.isArray(bundle.warnings) && bundle.warnings.length > 0);
check('hexdata 引用四字段齐备', (function () {
  var c = bundle.hexdata_citation || {};
  return !!c.buildId && !!c.reportPatch && !!c.reportDate;
})());
check('别名索引非空且为数值映射', Object.keys(bundle.alias_index).length > 100 &&
  Object.keys(bundle.alias_index).every(function (kk) { return typeof bundle.alias_index[kk] === 'number'; }));

// ---------------------------------------------------------------- 汇总
console.log('\n' + '─'.repeat(56));
console.log('模式：' + (SELF ? '故障注入 --self-test' : '正常'));
console.log('通过 ' + pass + ' / 失败 ' + fail);
if (fail) {
  console.log('失败项：');
  failures.forEach(function (f) { console.log('  ✗ ' + f); });
}
if (SELF) {
  if (fail > 0) { console.log('\n✅ 故障注入生效：断言真变红（退出码 1）'); process.exit(1); }
  console.log('\n❌ 故障注入无效：改了输入仍是绿的 —— 断言没有分辨力！');
  process.exit(3);
}
if (fail === 0) { console.log('\n✅ 全部通过'); process.exit(0); }
process.exit(1);
