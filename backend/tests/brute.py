"""穷举参考实现：枚举全部 2^n 场景，仅用于小例核对引擎。"""
from fractions import Fraction
from itertools import product


def brute_force(base_costs, budget, risks):
    depts = list(base_costs.keys())
    base = [base_costs[d] for d in depts]
    probs, incs = [], []
    for risk in risks:
        p = Fraction(risk['probability']) if isinstance(risk['probability'], str) \
            else Fraction(risk['probability'], 1)
        inc = [risk['increments'].get(d, 0) for d in depts]
        probs.append(p)
        incs.append(inc)

    scenarios = []  # (项目总额, 概率, 部门成本列表)
    for bits in product((0, 1), repeat=len(risks)):
        prob = Fraction(1)
        dept_cost = base[:]
        for on, p, inc in zip(bits, probs, incs):
            prob *= p if on else (1 - p)
            if on:
                dept_cost = [c + v for c, v in zip(dept_cost, inc)]
        scenarios.append((sum(dept_cost), prob, dept_cost))

    total_mass = sum(s[1] for s in scenarios)
    assert total_mass == 1

    over = sum(s[1] for s in scenarios if s[0] > budget)

    # 5% 尾部：整桶 + 同额临界档等比例
    target = Fraction(1, 20)
    order = sorted(scenarios, key=lambda s: -s[0])
    full_mass = Fraction(0)
    full_totals = set()
    cutoff_total = None
    alpha = Fraction(1)
    i = 0
    while i < len(order):
        total = order[i][0]
        bucket = [s for s in order if s[0] == total]
        bucket_mass = sum(s[1] for s in bucket)
        if full_mass + bucket_mass <= target:
            full_mass += bucket_mass
            full_totals.add(total)
            i += len(bucket)
            continue
        cutoff_total = total
        alpha = Fraction(target - full_mass, bucket_mass)
        break

    project_contrib = Fraction(0)
    dept_contrib = [Fraction(0) for _ in depts]
    for total, prob, dept_cost in order:
        if total in full_totals:
            factor = Fraction(1)
        elif total == cutoff_total:
            factor = alpha
        else:
            factor = Fraction(0)
        project_contrib += prob * total * factor
        for j in range(len(depts)):
            dept_contrib[j] += prob * dept_cost[j] * factor

    tail_mass = full_mass + (alpha * sum(s[1] for s in order
                                         if s[0] == cutoff_total)
                             if cutoff_total is not None else Fraction(0))
    assert tail_mass == Fraction(1, 20)
    # 条件均值（这 5% 里的平均成本）= 尾部贡献 / 尾部质量
    project_mean = project_contrib / tail_mass
    dept_mean = [v / tail_mass for v in dept_contrib]

    return {
        'over': over,
        'tail_mass': tail_mass,
        'cutoff_total': cutoff_total,
        'alpha': alpha,
        'project_mean': project_mean,
        'dept_mean': dept_mean,
        'depts': depts,
    }
