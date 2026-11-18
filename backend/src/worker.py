import time,json,traceback
from pathlib import Path
import redis
from src.config.database import Base,engine,Session
from src.config.settings import REDIS_URL
from src.models import identity,source,run,stress
from src.models.run import Run
from src.models.stress import StressTrial
from src.services.calculation import calculate
from src.services.delivery import tick
from src.services.stress_service import run_trial,STRESS_QUEUE,StressTimeout,StressValidation
Base.metadata.create_all(engine)
r=redis.Redis.from_url(REDIS_URL)
while True:
 Path('/tmp/worker-heartbeat').write_text(str(time.time()))
 try:
  item=r.lpop('report-jobs')
  if item:
   with Session() as db:
    job=db.get(Run,int(item))
    if job and job.status=='queued':
     job.status='running';db.commit()
     try: job.result=calculate(job.snapshot['sources'],job.snapshot['policy']);job.status='completed'
     except Exception as exc: job.status='failed';job.error=str(exc);traceback.print_exc()
     db.commit()
  stress_item=r.lpop(STRESS_QUEUE)
  if stress_item:
   with Session() as db:
    job=db.get(StressTrial,int(stress_item))
    if job and job.status=='queued':
     job.status='running';db.commit()
     try:
      # 30 秒墙钟超时由引擎抛 StressTimeout，失败即拒绝发布（不写 result）
      job.result=run_trial(job);job.status='completed'
     except (StressTimeout,StressValidation) as exc:
      job.status='failed';job.error='拒绝发布：'+str(exc);traceback.print_exc()
     except Exception as exc:
      job.status='failed';job.error=str(exc);traceback.print_exc()
     db.commit()
  with Session() as db: tick(db)
 except Exception: traceback.print_exc()
 time.sleep(1)
