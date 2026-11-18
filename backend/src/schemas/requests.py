from pydantic import BaseModel,Field
class Login(BaseModel): email:str; password:str
class DataInput(BaseModel): data:dict
class RunInput(BaseModel): name:str=Field(min_length=2,max_length=120); policy_id:int; period:str='全部'
class ReviewInput(BaseModel): note:str=Field(min_length=4,max_length=2000)
class ScheduleInput(BaseModel): name:str=Field(min_length=2,max_length=120); run_id:int; interval_seconds:int=Field(ge=5,le=86400)
class RiskInput(BaseModel):
 name:str=Field(min_length=1,max_length=120)
 probability:str=Field(min_length=1,max_length=40)
 increments:dict[str,int]
class RiskBookInput(BaseModel):
 version:str=Field(min_length=2,max_length=120)
 risks:list[RiskInput]=Field(min_length=1,max_length=30)
class StressTrialInput(BaseModel):
 name:str=Field(min_length=2,max_length=120)
 run_id:int
 risk_book_id:int
 budget_cents:int=Field(ge=0)
