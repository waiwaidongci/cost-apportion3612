"""预算压力试算引擎测试：小例穷举核对、同额临界点、守恒、超时与校验。"""
import os
import sys
import time
import unittest
from fractions import Fraction

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.services.stress import (  # noqa: E402
    StressTimeout, StressValidation, stress_trial, normalize_input,
    MAX_RISKS, MAX_DEPTS, MAX_INCREMENT_SUM,
)
from tests.brute import brute_force  # noqa: E402


def f(obj):
    return Fraction(obj['numerator'], obj['denominator'])


class ExhaustiveSmallCases(unittest.TestCase):
    def compare(self, base, budget, risks):
        result = stress_trial(base, budget, risks)
        ref = brute_force(base, budget, risks)
        self.assertEqual(f(result['over_budget_probability']), ref['over'])
        self.assertEqual(f(result['tail_mass']), ref['tail_mass'])
        self.assertEqual(f(result['cutoff_alpha']), ref['alpha'])
        self.assertEqual(result['cutoff_total_cents'], ref['cutoff_total'])
        self.assertEqual(f(result['project_tail_mean_cents']), ref['project_mean'])
        got = [f(x['tail_mean_cents']) for x in result['department_tail_mean_cents']]
        self.assertEqual(got, ref['dept_mean'])
        # 部门合计必须等于项目尾部均值
        self.assertEqual(sum(got, Fraction(0)), ref['project_mean'])
        self.assertTrue(result['identity_holds'])

    def test_single_risk_half(self):
        # 1/2 概率发生：两档同额桶各 1/2，5% 落在低档内 -> alpha=1/10
        self.compare({'甲': 100, '乙': 0}, 100,
                     [{'name': 'r1', 'probability': '1/2',
                       'increments': {'甲': 50}}])

    def test_cutoff_exact_five_percent(self):
        # 概率 1/20 的风险：最贵档恰为 5%，整桶纳入，无临界 alpha 之外的比例
        self.compare({'甲': 10}, 0,
                     [{'probability': '1/20', 'increments': {'甲': 90}}])

    def test_equal_totals_different_dept_mix(self):
        # 两个风险增量总额相同（同额），但推高不同部门：临界档必须等比例
        risks = [
            {'probability': '1/3', 'increments': {'甲': 30}},
            {'probability': '1/3', 'increments': {'乙': 30}},
        ]
        self.compare({'甲': 0, '乙': 0}, 1000, risks)

    def test_risk_hits_multiple_departments(self):
        risks = [
            {'probability': '2/5', 'increments': {'甲': 10, '乙': 20, '丙': 30}},
            {'probability': '3/7', 'increments': {'乙': 15}},
        ]
        self.compare({'甲': 5, '乙': 7, '丙': 0}, 40, risks)

    def test_zero_and_certain_risks(self):
        risks = [
            {'probability': '0', 'increments': {'甲': 999}},          # 剔除
            {'probability': '1', 'increments': {'乙': 12}},           # 确定性
            {'probability': '1/4', 'increments': {'甲': 8}},
        ]
        self.compare({'甲': 100, '乙': 50}, 200, risks)

    def test_zero_increment_risk_still_changes_mass(self):
        # 零增量风险不改变成本，但改变场景权重，尾概率口径仍须与穷举一致
        risks = [
            {'probability': '1/2', 'increments': {'甲': 0, '乙': 0}},
            {'probability': '1/3', 'increments': {'甲': 60}},
        ]
        self.compare({'甲': 10, '乙': 20}, 1000, risks)

    def test_many_random_small_cases(self):
        import random
        rng = random.Random(20261118)
        for case in range(60):
            m = rng.randint(1, 4)
            depts = ['部门%d' % i for i in range(m)]
            base = {d: rng.randint(0, 200) for d in depts}
            n = rng.randint(1, 6)
            risks = []
            for i in range(n):
                p = rng.choice(['1/2', '1/3', '2/3', '1/5', '3/7', '1/20', '0', '1'])
                hit = rng.sample(depts, rng.randint(1, m))
                risks.append({'probability': p,
                              'increments': {d: rng.randint(0, 40) for d in hit}})
            budget = rng.randint(0, 400)
            self.compare(base, budget, risks)


class HandComputed(unittest.TestCase):
    def test_half_probability_alpha_one_tenth(self):
        # 两场景各 1/2：最贵档（150，质量 1/2）本身已超过目标 1/20，
        # 因此它整体作为同额临界档，alpha=(1/20)/(1/2)=1/10。
        # 尾部条件均值 = (150 × 1/2 × 1/10) ÷ 1/20 = 150。
        result = stress_trial({'甲': 100}, 1000,
                              [{'probability': '1/2', 'increments': {'甲': 50}}])
        self.assertEqual(f(result['cutoff_alpha']), Fraction(1, 10))
        self.assertEqual(f(result['project_tail_mean_cents']), Fraction(150))
        self.assertEqual(f(result['tail_mass']), Fraction(1, 20))

    def test_over_budget_strict_inequality(self):
        # 预算 150：仅高档 150 不“严格大于”，超预算概率为 0
        result = stress_trial({'甲': 100}, 150,
                              [{'probability': '1/2', 'increments': {'甲': 50}}])
        self.assertEqual(f(result['over_budget_probability']), Fraction(0))
        result2 = stress_trial({'甲': 100}, 149,
                               [{'probability': '1/2', 'increments': {'甲': 50}}])
        self.assertEqual(f(result2['over_budget_probability']), Fraction(1, 2))


class Validation(unittest.TestCase):
    def test_limits(self):
        base = {'d%d' % i: 1 for i in range(MAX_DEPTS)}
        risks = [{'probability': '1/2', 'increments': {'d0': 1}}
                 for _ in range(MAX_RISKS)]
        stress_trial(base, 10, risks)  # 不抛异常
        with self.assertRaises(StressValidation):
            stress_trial(base, 10, risks + risks[:1])
        with self.assertRaises(StressValidation):
            stress_trial({'d%d' % i: 1 for i in range(MAX_DEPTS + 1)}, 10, risks[:1])

    def test_increment_sum_cap(self):
        base = {'甲': 0}
        risks = [{'probability': '1/2',
                  'increments': {'甲': MAX_INCREMENT_SUM + 1}}]
        with self.assertRaises(StressValidation):
            stress_trial(base, 0, risks)
        # 恰好在上限内可用
        stress_trial(base, 0,
                     [{'probability': '1/2',
                       'increments': {'甲': MAX_INCREMENT_SUM}}])

    def test_bad_probability_and_increment(self):
        with self.assertRaises(StressValidation):
            stress_trial({'甲': 0}, 0,
                         [{'probability': '3/2', 'increments': {'甲': 1}}])
        with self.assertRaises(StressValidation):
            stress_trial({'甲': 0}, 0,
                         [{'probability': 'x', 'increments': {'甲': 1}}])
        with self.assertRaises(StressValidation):
            stress_trial({'甲': 0}, 0,
                         [{'probability': '1/2', 'increments': {'乙': 1}}])
        with self.assertRaises(StressValidation):
            stress_trial({'甲': 0}, 0,
                         [{'probability': '1/2', 'increments': {'甲': -1}}])

    def test_normalize_certain_risk_folded(self):
        depts, base, eff, budget, raw = normalize_input(
            {'甲': 10}, 5,
            [{'probability': '1', 'increments': {'甲': 7}},
             {'probability': '1/2', 'increments': {'甲': 3}}])
        self.assertEqual(base, [17])
        self.assertEqual(len(eff), 1)
        self.assertEqual(raw, 2)

    def test_no_stochastic_risk_single_scenario(self):
        # 全部 p=0/p=1：仅一个确定性场景，临界档 alpha=1/20，尾均即该场景成本
        result = stress_trial({'甲': 100, '乙': 20}, 500, [
            {'probability': '0', 'increments': {'甲': 9000}},
            {'probability': '1', 'increments': {'乙': 30}},
        ])
        self.assertEqual(result['stochastic_risk_count'], 0)
        self.assertEqual(result['scenario_count'], 1)
        self.assertEqual(f(result['tail_mass']), Fraction(1, 20))
        self.assertEqual(f(result['cutoff_alpha']), Fraction(1, 20))
        self.assertEqual(f(result['project_tail_mean_cents']), Fraction(150))
        dept = {x['department']: f(x['tail_mean_cents'])
                for x in result['department_tail_mean_cents']}
        self.assertEqual(dept, {'甲': Fraction(100), '乙': Fraction(50)})
        self.assertTrue(result['identity_holds'])


class Timeout(unittest.TestCase):
    def test_timeout_rejects(self):
        base = {'d%d' % i: 100 for i in range(20)}
        risks = [{'probability': '%d/%d' % (i + 1, i + 3),
                  'increments': {'d%d' % (i % 20): 300}}
                 for i in range(30)]
        # 负超时使截止时刻已过期：首个风险纳入前即拒绝发布
        started = time.monotonic()
        with self.assertRaises(StressTimeout):
            stress_trial(base, 10 ** 9, risks, timeout_seconds=-1.0)
        self.assertLess(time.monotonic() - started, 5)


class Performance(unittest.TestCase):
    def test_worst_case_under_30s(self):
        # 接近最坏规模：30 风险、20 部门、增量总和恰好 1 万分，异分母概率
        base = {'部门%02d' % i: 1000 for i in range(20)}
        risks = []
        # 每项总增量 333~334，30 项合计 <= 10000
        for i in range(30):
            denom = 2 * (i + 3)
            hit = ['部门%02d' % ((i + j) % 20) for j in range(1 + i % 4)]
            per = 333 // len(hit)
            inc = {d: per for d in hit}
            risks.append({
                'name': '风险%02d' % i,
                'probability': '%d/%d' % (denom // 2 + 1, denom),
                'increments': inc,
            })
        total = sum(sum(r['increments'].values()) for r in risks)
        self.assertLessEqual(total, 10000)
        started = time.monotonic()
        result = stress_trial(base, 10 ** 9, risks, timeout_seconds=30)
        elapsed = time.monotonic() - started
        self.assertLess(elapsed, 30)
        self.assertTrue(result['identity_holds'])
        print('\n最坏规模耗时 %.2fs，场景数 %d，公分母位数 %d，增量合计 %d'
              % (elapsed, result['scenario_count'],
                 len(str(result['common_denominator'])), total))


if __name__ == '__main__':
    unittest.main(verbosity=2)
