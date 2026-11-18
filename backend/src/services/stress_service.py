"""预算压力试算服务：从已复核报告抽取部门成本、冻结版本、入队。"""
import hashlib
import json
import time

from fastapi import HTTPException

from src.config.settings import REDIS_URL
from src.models.run import Run
from src.models.stress import RiskBook, StressTrial
from src.services.audit import log
from src.services.stress import stress_trial, StressValidation, StressTimeout
import redis

STRESS_QUEUE = 'stress-jobs'
STRESS_TIMEOUT_SECONDS = 30.0


def department_base_costs(run):
    """从报告核算结果按部门汇总基准成本（整数分）。

    报告 rows 为 期间×部门×费用类别 的透视，按部门求和即各部门基准成本；
    公共成本已在核算阶段分摊到部门，故部门合计等于报告总额，守恒。
    """
    result = run.result or {}
    rows = result.get('rows') or []
    if not rows:
        raise HTTPException(422, '报告没有可用于试算的核算结果')
    costs = {}
    for row in rows:
        dept = row['部门']
        amount = row['分摊金额分']
        if not isinstance(amount, int) or amount < 0:
            raise HTTPException(422, '报告金额不是非负整数分，无法试算')
        costs[dept] = costs.get(dept, 0) + amount
    if not costs:
        raise HTTPException(422, '报告未包含任何部门成本')
    return costs


def create_risk_book(db, user, body):
    data = {'risks': [r.model_dump() for r in body.risks]}
    if db.query(RiskBook).filter_by(version=body.version).first():
        raise HTTPException(409, '风险版本名已存在，请使用新版本名')
    book = RiskBook(version=body.version, data=data, created=time.time())
    db.add(book)
    log(db, user.email, 'riskbook.create', body.version)
    db.commit()
    return book


def submit_trial(db, user, body):
    run = db.get(Run, body.run_id)
    if not run:
        raise HTTPException(404, '报告不存在')
    if run.status != 'completed' or not run.approved:
        raise HTTPException(409, '仅可对已复核报告发起预算压力试算')
    book = db.get(RiskBook, body.risk_book_id)
    if not book:
        raise HTTPException(404, '风险版本不存在')

    base_costs = department_base_costs(run)
    # 排队前先用同一套校验快速失败，避免无效任务进入队列
    from src.services.stress import normalize_input
    try:
        normalize_input(base_costs, body.budget_cents, book.data['risks'])
    except StressValidation as exc:
        raise HTTPException(422, str(exc))

    snapshot = {
        'run_id': run.id,
        'run_name': run.name,
        'run_checksum': run.checksum,
        'base_costs': base_costs,
        'risk_book_id': book.id,
        'risk_book_version': book.version,
        'risks': book.data['risks'],
        'budget_cents': body.budget_cents,
    }
    checksum = hashlib.sha256(
        json.dumps(snapshot, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    trial = StressTrial(
        name=body.name, status='queued', run_id=run.id,
        risk_book_id=book.id, budget_cents=body.budget_cents,
        snapshot=snapshot, checksum=checksum, created=time.time(),
    )
    db.add(trial)
    log(db, user.email, 'stress.queue', body.name)
    db.commit()
    redis.Redis.from_url(REDIS_URL).rpush(STRESS_QUEUE, trial.id)
    return trial


def run_trial(trial):
    """worker 调用：在冻结快照上执行精确试算，超时/校验失败标记 failed，拒绝发布。"""
    result = stress_trial(
        trial.snapshot['base_costs'],
        trial.snapshot['budget_cents'],
        trial.snapshot['risks'],
        timeout_seconds=STRESS_TIMEOUT_SECONDS,
    )
    result['checksum'] = trial.checksum
    return result


__all__ = ['RiskBook', 'StressTrial', 'create_risk_book', 'submit_trial',
           'run_trial', 'STRESS_QUEUE', 'StressTimeout', 'StressValidation']
