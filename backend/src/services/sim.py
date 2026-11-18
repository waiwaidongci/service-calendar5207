import time,traceback
from fastapi import HTTPException
from src.models.run import Run
from src.models.sim import Sim,SimTier
from src.services.audit import log
from src.services.simulation import Clock,prepare_orders,initial_state,run_batch,build_result,validate_sim_params,BATCH_SIZE
from src.utils.serialize import row
TIERS_PER_TICK=4   # 每个worker周期最多推进的档位数
_CACHE={}          # 进程内 (sim_id,generation) -> (Clock,orders)，重启后自动重建
def _engine(sim,run):
 key=(sim.id,sim.generation);hit=_CACHE.get(key)
 if hit is None:
  if len(_CACHE)>16:_CACHE.clear()
  hit=(Clock(run.snapshot['policy']),prepare_orders(run.snapshot,sim.params));_CACHE[key]=hit
 return hit
def _params(body):
 return {'handle_minutes':{k:float(v) for k,v in body.handle_minutes.items()},'tiers':[{'name':t.name,'staff':t.staff} for t in body.tiers]}
def _add_tiers(db,sim,generation,t0):
 for slot,t in enumerate(sim.params['tiers']):
  db.add(SimTier(sim_id=sim.id,generation=generation,slot=slot,label=t['name'],staff=t['staff'],status='queued',progress=0,checkpoint=initial_state(t['staff'],t0),result=None,error=''))
def create_sim(db,user,body):
 run=db.get(Run,body.run_id)
 if not run: raise HTTPException(404,'报告不存在')
 if run.status!='completed' or not run.approved: raise HTTPException(409,'试算需引用已复核报告')
 params=_params(body);validate_sim_params(params,run.snapshot)
 t0=prepare_orders(run.snapshot,params)[0][0];now=time.time()
 sim=Sim(name=body.name,run_id=run.id,params=params,generation=1,published=0,status='queued',error='',created=now,updated=now)
 db.add(sim);db.flush();_add_tiers(db,sim,1,t0);log(db,user.email,'sim.create',sim.name+'#g1');db.commit();return get_sim(db,sim.id)
def rerun_sim(db,user,sim_id,body):
 sim=db.query(Sim).filter(Sim.id==sim_id).with_for_update().first()
 if not sim: raise HTTPException(404,'试算不存在')
 run=db.get(Run,sim.run_id)
 params=_params(body);validate_sim_params(params,run.snapshot)
 t0=prepare_orders(run.snapshot,params)[0][0];g=sim.generation+1
 sim.generation=g;sim.params=params;sim.status='queued';sim.error='';sim.updated=time.time()
 # 仅保留已发布代结果，清理被替换的旧档；进行中的旧批处理因代际护栏自然丢弃，不覆盖新结果
 db.query(SimTier).filter(SimTier.sim_id==sim.id,SimTier.generation.notin_([g,sim.published])).delete(synchronize_session=False)
 _add_tiers(db,sim,g,t0);log(db,user.email,'sim.rerun',sim.name+'#g'+str(g));db.commit();return get_sim(db,sim.id)
def tier_brief(t):
 ck=t.checkpoint or {};now=ck.get('now') or 0
 inflight=sum(1 for x in ck.get('inflight') or [] if x and x.get('free_at',0)>now)
 return {'id':t.id,'slot':t.slot,'label':t.label,'staff':t.staff,'generation':t.generation,'status':t.status,'progress':t.progress,'backlog':len(ck.get('backlog') or []),'inflight':inflight,'error':t.error or ''}
def sim_view(sim,tiers):
 data=row(sim)
 cur=sorted((t for t in tiers if t.generation==sim.generation),key=lambda t:t.slot)
 pub=sorted((t for t in tiers if sim.published and t.generation==sim.published),key=lambda t:t.slot)
 data['tiers']=[tier_brief(t) for t in cur]
 data['published_tiers']=[{'slot':t.slot,'label':t.label,'staff':t.staff,'result':t.result} for t in pub if t.status=='completed' and t.result]
 return data
def list_sims(db):
 sims=db.query(Sim).order_by(Sim.id.desc()).limit(50).all();ids=[s.id for s in sims]
 tiers=db.query(SimTier).filter(SimTier.sim_id.in_(ids)).all() if ids else []
 by_sim={}
 for t in tiers:by_sim.setdefault(t.sim_id,[]).append(t)
 return [sim_view(s,by_sim.get(s.id,[])) for s in sims]
def get_sim(db,sim_id):
 sim=db.get(Sim,sim_id)
 if not sim: raise HTTPException(404,'试算不存在')
 return sim_view(sim,db.query(SimTier).filter(SimTier.sim_id==sim.id).all())
def sim_tick(db,batch_size=BATCH_SIZE):
 # 发布兜底扫描：同一代两档都完成才原子发布；任一档失败则保留旧版
 for sim in db.query(Sim).filter(Sim.status.in_(['queued','running'])).all():
  tiers=db.query(SimTier).filter_by(sim_id=sim.id,generation=sim.generation).all()
  if len(tiers)==2 and all(t.status=='completed' for t in tiers):_publish(db,sim.id,sim.generation)
 candidates=(db.query(SimTier).join(Sim,SimTier.sim_id==Sim.id).filter(SimTier.status.in_(['queued','running']),SimTier.generation==Sim.generation,Sim.status.in_(['queued','running'])).order_by(SimTier.id).limit(TIERS_PER_TICK).all())
 for tier in candidates:_process(db,tier,batch_size)
def _publish(db,sim_id,generation):
 # 仅当本代仍是最新一代才发布：旧试算晚到不覆盖新结果
 n=db.query(Sim).filter(Sim.id==sim_id,Sim.generation==generation).update({'published':generation,'status':'completed','error':'','updated':time.time()},synchronize_session=False)
 if n==1:
  db.query(SimTier).filter(SimTier.sim_id==sim_id,SimTier.generation<generation).delete(synchronize_session=False)
  log(db,'worker','sim.publish',str(sim_id)+'#g'+str(generation))
 db.commit()
def _process(db,tier,batch_size):
 sim_id,generation=tier.sim_id,tier.generation
 try:
  sim=db.get(Sim,sim_id);run=db.get(Run,sim.run_id)
  clock,orders=_engine(sim,run)
  state=tier.checkpoint;run_batch(clock,orders,state,batch_size);done=bool(state['done'])
  values={'status':'completed' if done else 'running','progress':len(orders) if done else state['i'],'checkpoint':state,'error':''}
  if done:values['result']=build_result(clock,state,tier.label,tier.staff)
  n=db.query(SimTier).filter(SimTier.id==tier.id,SimTier.generation==generation).update(values,synchronize_session=False)
  if n!=1:
   db.rollback();return   # 新一代已替换本档：晚到的批结果丢弃
  db.query(Sim).filter(Sim.id==sim_id,Sim.generation==generation,Sim.status=='queued').update({'status':'running'},synchronize_session=False)
  db.query(Sim).filter(Sim.id==sim_id,Sim.generation==generation).update({'updated':time.time()},synchronize_session=False)
  db.commit()
 except Exception as exc:
  db.rollback();traceback.print_exc();message=str(exc)[:1900]
  db.query(SimTier).filter(SimTier.sim_id==sim_id,SimTier.generation==generation,SimTier.status!='completed').update({'status':'failed','error':message},synchronize_session=False)
  db.query(Sim).filter(Sim.id==sim_id,Sim.generation==generation,Sim.status.in_(['queued','running'])).update({'status':'failed','error':message,'updated':time.time()},synchronize_session=False)
  log(db,'worker','sim.failed',str(sim_id)+'#g'+str(generation));db.commit()
