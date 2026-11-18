import {heading} from '../components/common/header.js';
import {esc} from '../utils/format.js';
import {status} from '../components/common/status.js';

const num = (name, label, value, min = 0) =>
  `<label>${label}<input name="${name}" type="number" min="${min}" step="1" value="${esc(value)}" required></label>`;

// 单行风险：名称、有理数概率（a/b）、按部门增量
function riskRow(depts, idx) {
  return `<div class="policy-row risk-row" data-idx="${idx}">
    <label>风险名称<input class="risk-name" value="风险${idx + 1}" required></label>
    <label>概率 a/b<input class="risk-prob" value="1/2" pattern="\\d+\\/\\d+|\\d+" required></label>
    <div class="risk-inc">
      ${depts.map(d => `<label>${esc(d)}<input class="risk-amount" data-dept="${esc(d)}" type="number" min="0" step="1" value="0"></label>`).join('')}
    </div>
    <button type="button" class="remove-risk-row">删除风险</button>
  </div>`;
}

function fracCell(f) {
  if (!f) return '';
  return `<span class="frac" title="精确分数">${esc(f.fraction)}</span><small class="frac-dec">≈ ${esc(f.decimal)}</small>`;
}

function resultPanel(t) {
  const r = t.result;
  if (!r) {
    return `<p class="empty">${t.error ? esc(t.error) : '排队中，worker 执行精确试算后在此展示（约 1 秒刷新）。'}</p>`;
  }
  const deptRows = r.department_tail_mean_cents.map(x => ({
    部门: x.department,
    基准成本分: r.base_cost_cents[r.departments.indexOf(x.department)],
    '尾部5%平均成本（精确分数）': fracCell(x.tail_mean_cents),
  }));
  const sumFraction = r.department_tail_mean_cents
    .map(x => x.tail_mean_cents.fraction).join(' + ');
  return `<section class="report">
    <div class="metrics">
      <div><small>超预算概率</small><strong>${fracCell(r.over_budget_probability)}</strong></div>
      <div><small>项目尾部5%均值（分）</small><strong>${fracCell(r.project_tail_mean_cents)}</strong></div>
      <div><small>实际尾部质量</small><strong>${fracCell(r.tail_mass)}</strong></div>
      <div><small>临界档同额比例 α</small><strong>${fracCell(r.cutoff_alpha)}</strong></div>
    </div>
    <p class="method">${esc(r.method)}</p>
    <p>场景数 ${r.scenario_count}（独立风险 2^n）· 统一公分母 L=${r.common_denominator} · 临界项目总额：${r.cutoff_total_cents ?? '无（整桶恰为5%）'} 分 · 耗时 ${r.elapsed_seconds}s</p>
    <h3>这 5% 里各部门的平均成本（精确分数）</h3>
    ${deptTable(deptRows)}
    <p class="checksum">部门合计校验：${esc(sumFraction)} = ${esc(r.project_tail_mean_cents.fraction)}
      （${r.identity_holds ? '✓ 部门合计等于项目尾部均值' : '✗ 守恒失败'}）</p>
    <details><summary>冻结的报告与风险版本快照（SHA256 ${esc(t.checksum)}）</summary>
      <pre style="white-space:pre-wrap;overflow-wrap:anywhere;font-size:11px">${esc(JSON.stringify(t.snapshot, null, 2))}</pre>
    </details>
  </section>`;
}

function deptTable(rows) {
  if (!rows.length) return '<p class="empty">无部门数据。</p>';
  const cols = Object.keys(rows[0]);
  const fracCol = '尾部5%平均成本（精确分数）';
  return '<div class="table-wrap"><table><thead><tr>' +
    cols.map(k => '<th>' + esc(k) + '</th>').join('') +
    '</tr></thead><tbody>' +
    rows.map(row => '<tr>' + cols.map(k =>
      k === fracCol ? `<td>${row[k]}</td>` : `<td>${esc(row[k])}</td>`).join('') +
      '</tr>').join('') +
    '</tbody></table></div>';
}

export function stress(c, d, selected) {
  const approved = d.runs.filter(r => r.approved && r.status === 'completed');
  const chosen = approved.find(r => r.id === selected) || approved[0];
  // 部门来自所选已复核报告的透视结果
  const depts = chosen ? [...new Set(chosen.result.rows.map(x => x.部门))] : [];
  const trial = d.stress_trials.find(t => t.id === d.stress_selected) || d.stress_trials[0];
  return heading('BUDGET STRESS / 06', '预算压力试算（精确分数尾部）',
    '基于已复核报告登记独立风险，按有理数概率整项发生；取项目总额最贵 5%（同额等比例），输出超预算概率与各部门尾部平均成本，30 秒超时拒绝发布。') +
    `<form id="riskbook-form" class="inline-form">
      <label>风险版本名<input name="version" value="风险口径-v1" required></label>
      <span>共 <b id="risk-count">1</b> 项风险 · 增量合计上限 10000 分</span>
    </form>
    <div id="risk-rows">${depts.length ? riskRow(depts, 0) : '<p class="empty">请先在“核算与复核”页复核一份报告。</p>'}</div>
    ${depts.length ? '<button type="button" id="add-risk-row">增加风险（最多30项）</button>' : ''}
    <button type="button" id="save-riskbook" ${depts.length ? '' : 'disabled'}>登记风险版本</button>
    <h2>发起预算压力试算</h2>
    <form id="stress-form" class="inline-form">
      <label>试算名称<input name="name" value="十一月预算压力试算" required></label>
      <label>已复核报告<select name="run_id">${approved.map(r => `<option value="${r.id}" ${chosen && chosen.id === r.id ? 'selected' : ''}>${esc(r.name)}</option>`).join('')}</select></label>
      <label>风险版本<select name="risk_book_id">${d.risk_books.map(b => `<option value="${b.id}">${esc(b.version)}（${b.data.risks.length}项）</option>`).join('')}</select></label>
      ${num('budget_cents', '预算（整数分）', 20000)}
      <button ${approved.length && d.risk_books.length ? '' : 'disabled'}>排队试算</button>
    </form>
    <h2>试算任务</h2>
    <div class="run-layout"><aside class="run-list">${
      d.stress_trials.length
        ? d.stress_trials.map(t => `<button class="select-trial" data-id="${t.id}">${esc(t.name)} ${status(t.status)}</button>`).join('')
        : '<p class="empty">暂无试算任务。</p>'
    }</aside><div>${trial ? resultPanel(trial) : ''}</div></div>`;
}
