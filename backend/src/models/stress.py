from sqlalchemy import Column,Integer,String,JSON,Text,Float
from src.config.database import Base


class RiskBook(Base):
    """风险登记簿：仅新增版本，不覆盖；试算排队时冻结其版本内容。"""
    __tablename__ = 'risk_books'
    id = Column(Integer, primary_key=True)
    version = Column(String(120), unique=True)
    data = Column(JSON, nullable=False)          # {risks: [...]}
    created = Column(Float)


class StressTrial(Base):
    """预算压力试算任务。

    排队瞬间冻结报告（Run）快照、风险版本（RiskBook）快照与预算，
    此后报告或风险被并发编辑都不影响本任务结果（与 Run 的冻结口径一致）。
    """
    __tablename__ = 'stress_trials'
    id = Column(Integer, primary_key=True)
    name = Column(String(120))
    status = Column(String(20))                  # queued/running/completed/failed
    run_id = Column(Integer)
    risk_book_id = Column(Integer)
    budget_cents = Column(Integer)
    snapshot = Column(JSON)                      # 冻结的报告+风险+预算
    checksum = Column(String(64))
    result = Column(JSON)
    error = Column(Text)
    created = Column(Float)
