from sqlalchemy import Column,Integer,String,JSON,Text,Float,UniqueConstraint
from src.config.database import Base
class Sim(Base):
 __tablename__='staffing_sims'
 id=Column(Integer,primary_key=True); name=Column(String(120)); run_id=Column(Integer); params=Column(JSON); generation=Column(Integer,default=1); published=Column(Integer,default=0); status=Column(String(20),default='queued'); error=Column(Text,default=''); created=Column(Float); updated=Column(Float)
class SimTier(Base):
 __tablename__='staffing_sim_tiers'
 __table_args__=(UniqueConstraint('sim_id','generation','slot',name='uq_sim_tier'),)
 id=Column(Integer,primary_key=True); sim_id=Column(Integer); generation=Column(Integer); slot=Column(Integer); label=Column(String(40)); staff=Column(Integer); status=Column(String(20),default='queued'); progress=Column(Integer,default=0); checkpoint=Column(JSON); result=Column(JSON); error=Column(Text,default='')
