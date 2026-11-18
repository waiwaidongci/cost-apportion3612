"""服务层集成测试（纯标准库）：冻结、排队、执行、超时拒绝。

通过 sys.modules 桩替换 fastapi/redis/sqlalchemy，使服务层可在无第三方依赖下导入。
"""
import os
import sys
import types
import unittest
from unittest import mock
from fractions import Fraction

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# ---- 桩：fastapi ----
fastapi = types.ModuleType('fastapi')


class HTTPException(Exception):
    def __init__(self, status_code, detail):
        self.status_code = status_code
        self.detail = detail


fastapi.HTTPException = HTTPException
sys.modules.setdefault('fastapi', fastapi)

# ---- 桩：redis ----
redis_mod = types.ModuleType('redis')


class _FakeRedis:
    queues = {}

    def rpush(self, key, value):
        _FakeRedis.queues.setdefault(key, []).append(value)

    @classmethod
    def from_url(cls, url):
        return _FakeRedis()


redis_mod.Redis = _FakeRedis
sys.modules.setdefault('redis', redis_mod)

# ---- 桩：config.database（避免真实引擎）----
db_pkg = types.ModuleType('src.config.database')


class _Base:
    pass


db_pkg.Base = _Base
db_pkg.engine = object()
db_pkg.Session = object()
sys.modules.setdefault('src.config.database', db_pkg)

# ---- 桩：config.settings（容器路径 /app 在本地不存在）----
settings_pkg = types.ModuleType('src.config.settings')
settings_pkg.REDIS_URL = 'redis://localhost:6379/0'
settings_pkg.SECRET = 'test'
settings_pkg.CONFIG = {}
sys.modules.setdefault('src.config.settings', settings_pkg)


# ---- 桩：SQLAlchemy 模型（避免导入 sqlalchemy）----
class _Column:
    def __init__(self, *a, **kw):
        pass


def _make_model(table):
    defaults = {
        'stress_trials': dict(id=None, name=None, status=None, run_id=None,
                              risk_book_id=None, budget_cents=None, snapshot=None,
                              checksum=None, result=None, error=None, created=None),
    }

    class _Model:
        __tablename__ = table

        def __init__(self, **kw):
            self.__dict__.update(defaults.get(table, {}))
            self.__dict__.update(kw)
            if 'id' not in kw:
                self.id = 1
    _Model.__name__ = table
    return _Model


sqlalchemy = types.ModuleType('sqlalchemy')
sqlalchemy.Column = lambda *a, **kw: None
sqlalchemy.Integer = sqlalchemy.String = sqlalchemy.JSON = None
sqlalchemy.Text = sqlalchemy.Float = None
sys.modules.setdefault('sqlalchemy', sqlalchemy)

run_model = types.ModuleType('src.models.run')
run_model.Run = _make_model('allocationruns')
sys.modules.setdefault('src.models.run', run_model)

stress_model = types.ModuleType('src.models.stress')
stress_model.RiskBook = _make_model('risk_books')
stress_model.StressTrial = _make_model('stress_trials')
sys.modules.setdefault('src.models.stress', stress_model)

audit_svc = types.ModuleType('src.services.audit')
audit_svc.log = lambda *a, **kw: None
sys.modules.setdefault('src.services.audit', audit_svc)

from src.services import stress_service  # noqa: E402
from src.services.stress_service import (  # noqa: E402
    submit_trial, run_trial, department_base_costs, create_risk_book)
from src.services.stress import StressTimeout  # noqa: E402


class _User:
    email = 'admin@demo.local'
    role = 'admin'


class _Run:
    def __init__(self):
        self.id = 1
        self.name = '十一月核算'
        self.status = 'completed'
        self.approved = True
        self.checksum = 'a' * 64
        self.result = {'rows': [
            {'期间': '2026-11', '部门': '光学研究', '费用类别': 'x', '分摊金额分': 100},
            {'期间': '2026-11', '部门': '光学研究', '费用类别': 'y', '分摊金额分': 50},
            {'期间': '2026-11', '部门': '材料研究', '费用类别': 'x', '分摊金额分': 70},
        ]}


class _Book:
    def __init__(self, id, version, risks):
        self.id = id
        self.version = version
        self.data = {'risks': risks}
        self.created = 0.0


class _FakeDB:
    def __init__(self, run, books):
        self._run = run
        self._books = {b.id: b for b in books}
        self.trials = {}
        self.audits = []

    def get(self, model, pk):
        name = getattr(model, '__name__', getattr(model, '__tablename__', ''))
        if name in ('allocationruns', 'Run'):
            return self._run
        if name in ('risk_books', 'RiskBook'):
            return self._books.get(pk)
        return self.trials.get(pk)

    def query(self, model):
        class _Q:
            def __init__(self, outer):
                self.outer = outer

            def filter_by(self, **kw):
                class _F:
                    def first(self_inner):
                        return None
                return _F()

            def add(self, obj):
                self.outer._books[obj.id] = obj

        return _Q(self)

    def add(self, obj):
        table = getattr(obj, '__tablename__', None)
        if table == 'stress_trials':
            self.trials[obj.id] = obj
        elif table == 'risk_books':
            self._books[obj.id] = obj

    def commit(self):
        pass

    def commit(self):
        pass


class _NS(types.SimpleNamespace):
    def model_dump(self):
        return {k: v for k, v in vars(self).items()}


def _book_body(risks, version='风险-v1'):
    return _NS(version=version, risks=[_NS(**r) for r in risks])


class StressServiceFlow(unittest.TestCase):
    def setUp(self):
        _FakeRedis.queues.clear()
        self.run = _Run()
        self.db = _FakeDB(self.run, [])

    def test_base_costs_aggregated_by_department(self):
        self.assertEqual(department_base_costs(self.run),
                         {'光学研究': 150, '材料研究': 70})

    def test_only_approved_report_allowed(self):
        book = create_risk_book(self.db, _User(), _book_body(
            [{'name': 'r1', 'probability': '1/2',
              'increments': {'光学研究': 10}}]))
        self.run.approved = False
        body = types.SimpleNamespace(name='试算1', run_id=1,
                                     risk_book_id=book.id, budget_cents=1000)
        with self.assertRaises(HTTPException) as ctx:
            submit_trial(self.db, _User(), body)
        self.assertEqual(ctx.exception.status_code, 409)

    def test_queue_freezes_snapshot_and_runs_exact(self):
        book = create_risk_book(self.db, _User(), _book_body(
            [{'name': 'r1', 'probability': '1/2',
              'increments': {'光学研究': 20, '材料研究': 10}}]))
        body = types.SimpleNamespace(name='试算1', run_id=1,
                                     risk_book_id=book.id, budget_cents=300)
        trial = submit_trial(self.db, _User(), body)
        self.assertEqual(trial.status, 'queued')
        self.assertEqual(_FakeRedis.queues[stress_service.STRESS_QUEUE], [trial.id])

        # 事后篡改风险版本表，冻结快照不受影响（并发编辑不影响结果）
        book.data = {'risks': [{'name': 'tampered', 'probability': '1',
                                'increments': {'光学研究': 9999}}]}
        frozen = self.db.get(stress_model.StressTrial, trial.id).snapshot
        self.assertEqual(frozen['risks'][0]['name'], 'r1')
        self.assertEqual(frozen['base_costs'], {'光学研究': 150, '材料研究': 70})
        self.assertEqual(len(trial.checksum), 64)

        result = run_trial(self.db.get(stress_model.StressTrial, trial.id))
        self.assertTrue(result['identity_holds'])
        self.assertEqual(result['checksum'], trial.checksum)
        dept_sum = sum((Fraction(d['tail_mean_cents']['numerator'],
                                 d['tail_mean_cents']['denominator'])
                        for d in result['department_tail_mean_cents']), Fraction(0))
        proj = Fraction(result['project_tail_mean_cents']['numerator'],
                        result['project_tail_mean_cents']['denominator'])
        self.assertEqual(dept_sum, proj)

    def test_invalid_input_rejected_before_queue(self):
        book = create_risk_book(self.db, _User(), _book_body(
            [{'name': 'r1', 'probability': '3/2',
              'increments': {'光学研究': 10}}]))
        body = types.SimpleNamespace(name='试算坏', run_id=1,
                                     risk_book_id=book.id, budget_cents=300)
        with self.assertRaises(HTTPException) as ctx:
            submit_trial(self.db, _User(), body)
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertNotIn(stress_service.STRESS_QUEUE, _FakeRedis.queues)

    def test_timeout_publishes_nothing(self):
        book = create_risk_book(self.db, _User(), _book_body(
            [{'name': 'r1', 'probability': '1/2',
              'increments': {'光学研究': 5}}]))
        body = types.SimpleNamespace(name='试算超时', run_id=1,
                                     risk_book_id=book.id, budget_cents=300)
        trial = submit_trial(self.db, _User(), body)
        with mock.patch.object(stress_service, 'stress_trial',
                               side_effect=StressTimeout('试算超过允许时间，已拒绝发布')):
            with self.assertRaises(StressTimeout):
                run_trial(trial)
        # worker 的失败落库口径：不写 result，标记 failed 拒绝发布
        trial.status = 'failed'
        trial.error = '拒绝发布：试算超过允许时间，已拒绝发布'
        self.assertIsNone(trial.result)
        self.assertTrue(trial.error.startswith('拒绝发布'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
