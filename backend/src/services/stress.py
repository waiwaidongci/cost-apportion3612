"""预算压力试算：独立伯努利风险的精确尾部（CVaR 5%）算法。

口径
----
- 每个风险相互独立，以有理数概率 p（0<=p<=1）整项发生；一旦发生，
  向若干部门同时增加非负整数分成本。
- 一个“场景”是所有风险发生与否的一个组合。令 L 为各概率分母的最小公倍数，
  则每个场景概率都可写成 整数权重 / L^n，全部用大整数精确计算，不引入浮点。
- 5% 尾部：把场景按“项目总额”从高到低累计概率，先整桶纳入；
  当纳入下一档（同一项目总额）会超过 5% 时，该档全部场景按同一比例 alpha 纳入，
  即同额场景等比例。alpha 与所有结果均保留精确分数（fractions.Fraction）。
- 超预算概率：项目总额严格大于预算的场景概率之和。
- 部门尾均值之和按构造恒等于项目尾部均值（结果内含 identity_holds 断言值）。

规模约束：风险 <= 30、部门 <= 20、风险增量总和 <= 10000 分；
deadline 为单调墙钟（time.monotonic）截止时刻，超时抛 StressTimeout，
由 worker 记为 failed，拒绝发布结果。
"""
import time
from fractions import Fraction
from math import gcd

MAX_RISKS = 30
MAX_DEPTS = 20
MAX_INCREMENT_SUM = 10000
TAIL = Fraction(1, 20)          # 最贵 5%
DEADLINE_TICK = 4096            # 每隔若干次内层迭代检查一次超时


class StressTimeout(Exception):
    """超过允许墙钟时间，拒绝发布。"""


class StressValidation(Exception):
    """输入不合法。"""


def _lcm(x, y):
    return x // gcd(x, y) * y


def _parse_ratio(value, name):
    """把 'a/b'、整数或 Fraction 解析为 [0,1] 内的 Fraction。"""
    if isinstance(value, bool):
        raise StressValidation(name + '概率不合法')
    if isinstance(value, int):
        frac = Fraction(value, 1)
    elif isinstance(value, str):
        text = value.strip()
        if '/' in text:
            top, _, bottom = text.partition('/')
            try:
                frac = Fraction(int(top), int(bottom))
            except (ValueError, ZeroDivisionError):
                raise StressValidation(name + '概率分数不合法')
        else:
            try:
                frac = Fraction(int(text), 1)
            except ValueError:
                raise StressValidation(name + '概率不合法')
    elif isinstance(value, Fraction):
        frac = value
    else:
        raise StressValidation(name + '概率必须为有理数（整数或 a/b）')
    if frac < 0 or frac > 1:
        raise StressValidation(name + '概率必须落在 [0,1]')
    return frac


def _nonneg_int(value, name):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise StressValidation(name + '必须为非负整数分')
    return value


def normalize_input(base_costs, budget, risks):
    """校验并归一化输入。

    返回 (depts, base[含 p=1 确定性增量], 有效随机风险列表, budget, 原始风险数)。
    概率为 0 的风险剔除；概率为 1 的风险折叠为确定性增量，不参与 DP。
    """
    if not isinstance(base_costs, dict) or not base_costs:
        raise StressValidation('报告部门成本不能为空')
    if len(base_costs) > MAX_DEPTS:
        raise StressValidation('部门数不允许超过 %d' % MAX_DEPTS)
    depts = list(base_costs.keys())
    for d in depts:
        if not isinstance(d, str) or not d:
            raise StressValidation('部门名不合法')
        _nonneg_int(base_costs[d], '部门基准成本')
    if len(set(depts)) != len(depts):
        raise StressValidation('部门名重复')
    budget = _nonneg_int(budget, '预算')
    if not isinstance(risks, list) or not risks:
        raise StressValidation('至少需要一项风险')
    if len(risks) > MAX_RISKS:
        raise StressValidation('风险数不允许超过 %d' % MAX_RISKS)

    base = [base_costs[d] for d in depts]
    effective = []
    increment_sum = 0
    for idx, risk in enumerate(risks):
        name = str(risk.get('name') or ('风险%d' % (idx + 1)))
        if not 1 <= len(name) <= 120:
            raise StressValidation('风险名称长度需在 1-120 字之间')
        prob = _parse_ratio(risk.get('probability'), name)
        inc_raw = risk.get('increments')
        if not isinstance(inc_raw, dict) or not inc_raw:
            raise StressValidation(name + '至少影响一个部门')
        inc = [0] * len(depts)
        for dept, amount in inc_raw.items():
            if dept not in base_costs:
                raise StressValidation(name + '引用了报告之外的部门：%s' % dept)
            amount = _nonneg_int(amount, name + '增量')
            inc[depts.index(dept)] = amount
            increment_sum += amount
        if increment_sum > MAX_INCREMENT_SUM:
            raise StressValidation('风险增量总和不允许超过 %d 分' % MAX_INCREMENT_SUM)
        if prob == 0:
            continue                      # 永不发生，直接剔除
        if prob == 1:
            base = [b + v for b, v in zip(base, inc)]
            continue
        effective.append({'name': name, 'prob': prob, 'inc': inc})
    return depts, base, effective, budget, len(risks)


def _stress_dp(base, effective, deadline):
    """整数权重动态规划。

    weights[k]：项目风险增量总额为 k 的场景整数权重；
    gs[j][k]：增量总额为 k 的场景中，部门 j 的“权重×部门增量成本”之和；
    L：统一公分母（场景总权重 = L^n）。
    部门完整成本的加权和在汇总时由 gs[j][k] + weights[k]*base[j] 得到。
    """
    n = len(effective)
    L = 1
    for risk in effective:
        L = _lcm(L, risk['prob'].denominator)

    m = len(base)
    cap = sum(sum(r['inc']) for r in effective)
    size = cap + 1
    weights = [0] * size
    weights[0] = 1
    gs = [[0] * size for _ in range(m)]

    ticks = 0
    for risk in effective:
        if time.monotonic() > deadline:
            raise StressTimeout('试算超过允许时间，已拒绝发布')
        a = risk['prob'].numerator * (L // risk['prob'].denominator)
        b = L - a                       # 不发生分支的权重
        inc = risk['inc']
        total_inc = sum(inc)
        # 每轮用全新数组做 0/1 背包，完全避免原地覆盖（含单风险占满容量的情形）。
        new_weights = [0] * size
        new_gs = [[0] * size for _ in range(m)]
        for k in range(size):
            w = weights[k]
            if w == 0:
                continue
            # 不发生分支：权重乘 b，部门加权成本同比乘 b
            new_weights[k] += w * b
            for j in range(m):
                new_gs[j][k] += gs[j][k] * b
            # 发生分支：权重乘 a，部门增量成本计入加权和
            if total_inc:
                new_weights[k + total_inc] += w * a
                for j in range(m):
                    new_gs[j][k + total_inc] += (gs[j][k] + w * inc[j]) * a
            else:
                # 零增量风险：与不发生分支同档，权重合计 w*(a+b)=w*L
                new_weights[k] += w * a
                for j in range(m):
                    new_gs[j][k] += gs[j][k] * a
            ticks += 1
            if ticks == DEADLINE_TICK:
                ticks = 0
                if time.monotonic() > deadline:
                    raise StressTimeout('试算超过允许时间，已拒绝发布')
        weights = new_weights
        gs = new_gs
    return weights, gs, L, cap


def stress_trial(base_costs, budget, risks, timeout_seconds=30.0):
    """完整精确试算，返回可 JSON 序列化的结果字典（分数以 {n,d,...} 表示）。"""
    started = time.monotonic()
    deadline = started + timeout_seconds
    depts, base, effective, budget, raw_count = normalize_input(
        base_costs, budget, risks)
    m = len(depts)
    n = len(effective)

    weights, gs, L, cap = _stress_dp(base, effective, deadline)
    total_weight = L ** n
    base_total = sum(base)

    # 第一遍：确定尾部整桶档与同额临界档。
    # target = 总权重 / 20（5%）。从最高档向下累计整桶权重 full_weight；
    # 下一档装不下时，它就是临界档，档内全部场景按同一 alpha 等比例纳入。
    target = Fraction(total_weight, 20)
    full_weight = 0
    full = [False] * (cap + 1)      # 整桶纳入的增量档
    cutoff_k = None
    alpha = Fraction(1)
    for k in range(cap, -1, -1):
        w = weights[k]
        if w == 0:
            continue
        if full_weight + w <= target:
            full_weight += w
            full[k] = True
            continue
        cutoff_k = k
        alpha = Fraction(target - full_weight, w)
        break

    # 第二遍：超预算权重、尾部贡献（未归一化），全部用 Fraction 精确聚合。
    over_weight = 0
    project_tail_contrib = Fraction(0)
    dept_tail_contrib = [Fraction(0) for _ in range(m)]
    for k, w in enumerate(weights):
        if w == 0:
            continue
        project_total = base_total + k
        if project_total > budget:
            over_weight += w
        if full[k]:
            factor = Fraction(1)
        elif k == cutoff_k:
            factor = alpha
        else:
            factor = Fraction(0)
        if factor == 0:
            continue
        bucket_mass = Fraction(w, total_weight)
        project_tail_contrib += bucket_mass * project_total * factor
        for j in range(m):
            # 桶内部门 j 的加权成本 = (gs + 权重×基准) / 总权重
            dept_weighted = Fraction(gs[j][k] + w * base[j], total_weight)
            dept_tail_contrib[j] += dept_weighted * factor

    over_prob = Fraction(over_weight, total_weight)
    tail_mass = Fraction(full_weight, total_weight) + (
        alpha * Fraction(weights[cutoff_k], total_weight)
        if cutoff_k is not None else Fraction(0))
    # 总概率质量为 1，选取规则保证纳入质量恰为 5%（单桶场景用 alpha=1/20 截取）。
    assert tail_mass == TAIL, '尾部质量必须恰为 5%，实际 %s' % tail_mass
    # 条件均值（“这 5% 里的平均成本”，即标准 CVaR）= 尾部贡献 / 尾部质量。
    project_tail_mean = project_tail_contrib / tail_mass
    dept_tail_mean = [v / tail_mass for v in dept_tail_contrib]

    # 守恒断言：部门尾均值之和必须等于项目尾部均值。
    identity_holds = sum(dept_tail_mean, Fraction(0)) == project_tail_mean
    if not identity_holds:
        raise AssertionError('尾部部门合计不守恒')

    elapsed = time.monotonic() - started
    return {
        'budget_cents': budget,
        'departments': depts,
        'base_cost_cents': base,
        'risk_count': raw_count,
        'stochastic_risk_count': n,
        'scenario_count': 2 ** n,
        'common_denominator': L,
        'over_budget_probability': _frac(over_prob),
        'tail_mass': _frac(tail_mass),
        'cutoff_total_cents': None if cutoff_k is None else base_total + cutoff_k,
        'cutoff_alpha': _frac(alpha),
        'project_tail_mean_cents': _frac(project_tail_mean),
        'department_tail_mean_cents': [
            {'department': d, 'tail_mean_cents': _frac(v)}
            for d, v in zip(depts, dept_tail_mean)
        ],
        'identity_holds': identity_holds,
        'elapsed_seconds': round(elapsed, 4),
        'method': ('独立伯努利风险，公分母 %d 整数权重 DP 按项目总额分桶；'
                   '最贵 5%% 先整桶纳入，同额临界档按 alpha 等比例纳入；'
                   '全程精确分数，部门尾均值之和等于项目尾部均值。' % L),
    }


def _frac(value):
    """精确分数序列化：分子/分母 + 有限位十进展示，原始分数永不丢精度。"""
    value = Fraction(value)
    return {
        'numerator': value.numerator,
        'denominator': value.denominator,
        'fraction': '%d/%d' % (value.numerator, value.denominator),
        'decimal': _decimal(value),
    }


def _decimal(value, places=12):
    value = Fraction(value)
    if value.denominator == 1:
        return str(value.numerator)
    sign = '-' if value.numerator < 0 else ''
    whole, rem = divmod(abs(value.numerator), value.denominator)
    digits = []
    for _ in range(places):
        rem *= 10
        digits.append(str(rem // value.denominator))
        rem %= value.denominator
    text = '%s%s.%s' % (sign, whole, ''.join(digits))
    return text.rstrip('0').rstrip('.') if '.' in text else text
