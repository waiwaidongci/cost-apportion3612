from fastapi import APIRouter, Depends, HTTPException

from src.config.database import database
from src.controllers.auth import current, editor
from src.models.stress import RiskBook, StressTrial
from src.schemas.requests import RiskBookInput, StressTrialInput
from src.services.stress_service import create_risk_book, submit_trial
from src.utils.serialize import row

router = APIRouter()


@router.get('/risk-books')
def risk_books(db=Depends(database), u=Depends(current)):
    return [row(x) for x in db.query(RiskBook).order_by(RiskBook.id.desc()).all()]


@router.post('/risk-books')
def create_book(b: RiskBookInput, db=Depends(database), u=Depends(editor)):
    return row(create_risk_book(db, u, b))


@router.get('/stress-trials')
def trials(db=Depends(database), u=Depends(current)):
    return [row(x) for x in
            db.query(StressTrial).order_by(StressTrial.id.desc()).all()]


@router.get('/stress-trials/{id}')
def trial_detail(id: int, db=Depends(database), u=Depends(current)):
    obj = db.get(StressTrial, id)
    if not obj:
        raise HTTPException(404, '试算任务不存在')
    return row(obj)


@router.post('/stress-trials')
def create_trial(b: StressTrialInput, db=Depends(database), u=Depends(editor)):
    return row(submit_trial(db, u, b))
