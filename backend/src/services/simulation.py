"""排班试算引擎：沿用已复核报告冻结的到单时间与业务日历，对两档人手做离散事件模拟。
纯标准库实现，不依赖Web/数据库；状态为可JSON序列化的断点，支持十万单分批计算与中断续跑。"""
import math
from datetime import datetime,timedelta,time
from zoneinfo import ZoneInfo
from heapq import heappush,heappop,heapify
BATCH_SIZE=2000      # 每批处理的到单/接单事件数；十万单按此分批
MAX_ORDERS=200000    # 单次试算样本上限
MAX_STAFF=500        # 单档人手上限
METHOD='沿用已复核报告冻结的到单时间与业务日历；按优先级设定单均办理耗时；到单按时刻排序后，空闲人员优先接SLA阈值更紧的单，同档先到先办；办理只占用营业分钟，跨午休/假日/非工作日由同一人续办；等待与办理均只计营业分钟；等待+办理超过SLA阈值记为超时（恰等不算）；样本分批处理，断点保留积压与在办单。'
WARNINGS=['试算基于报告冻结快照，底稿后续变更不影响本结果','办理耗时为按优先级的设定值，未模拟人员差异与真实波动','结果用于排班前的人手对比，不构成对业务的实时承诺']
class Clock:
 """业务时钟：营业分钟累计、下一可开工时刻、跨休息顺延。"""
 def __init__(self,policy):
  self.zone=ZoneInfo(policy['timezone']);self.weekdays=set(policy['weekdays']);self.holidays=set(policy.get('holidays',[]));self.windows=sorted(policy['windows'])
  self.origin=None;self.cum={};self.totals={}
 def day_total(self,d):
  t=self.totals.get(d)
  if t is None:
   t=sum(e-s for s,e in self.windows) if d.weekday() in self.weekdays and d.isoformat() not in self.holidays else 0
   self.totals[d]=t
  return t
 def cum_at(self,d):
  if self.origin is None:self.origin=d;self.cum[d]=0.0;return 0.0
  hit=self.cum.get(d)
  if hit is not None:return hit
  if d>self.origin:
   cur=max(self.cum);base=self.cum[cur]
   while cur<d:base+=self.day_total(cur);cur+=timedelta(days=1);self.cum[cur]=base
  else:
   cur=min(self.cum);base=self.cum[cur]
   while cur>d:cur-=timedelta(days=1);base-=self.day_total(cur);self.cum[cur]=base
  return self.cum[d]
 def bm(self,ts):
  # 至ts（epoch秒）累计的营业分钟
  local=datetime.fromtimestamp(ts,self.zone);d=local.date();base=self.cum_at(d)
  if self.day_total(d):
   midnight=datetime.combine(d,time(),self.zone)
   for s,e in self.windows:
    ws=midnight+timedelta(minutes=s);we=midnight+timedelta(minutes=e);hi=min(local,we)
    if hi>ws:base+=(hi-ws).total_seconds()/60
  return base
 def next_business(self,ts):
  # 不早于ts的最早可开工时刻（落在某工作时窗内）
  local=datetime.fromtimestamp(ts,self.zone)
  while True:
   d=local.date()
   if self.day_total(d):
    midnight=datetime.combine(d,time(),self.zone)
    for s,e in self.windows:
     ws=midnight+timedelta(minutes=s);we=midnight+timedelta(minutes=e)
     if local<we:return (ws if local<ws else local).timestamp()
   local=datetime.combine(d+timedelta(days=1),time(),self.zone)
 def advance(self,ts,minutes):
  # 从营业时刻ts起消耗minutes营业分钟，返回完工墙上时刻（跨休息顺延）
  local=datetime.fromtimestamp(ts,self.zone);left=float(minutes)
  while True:
   d=local.date()
   if self.day_total(d):
    midnight=datetime.combine(d,time(),self.zone)
    for s,e in self.windows:
     ws=midnight+timedelta(minutes=s);we=midnight+timedelta(minutes=e)
     if local<we:
      start=ws if local<ws else local;avail=(we-start).total_seconds()/60
      if left<=avail:return (start+timedelta(minutes=left)).timestamp()
      left-=avail
   local=datetime.combine(d+timedelta(days=1),time(),self.zone)
def prepare_orders(snapshot,params):
 """冻结快照+耗时参数 → (到单时刻,优先级,SLA分钟,办理分钟) 列表，按到单时刻稳定排序。"""
 sla=snapshot['policy']['sla_minutes'];handle=params['handle_minutes'];orders=[]
 for s in snapshot['sources']:
  p=s['priority']
  if p not in sla:raise ValueError('优先级无SLA口径：'+str(p))
  if p not in handle:raise ValueError('优先级缺少办理耗时：'+str(p))
  try:moment=datetime.fromisoformat(s['opened'])
  except Exception:raise ValueError('到单时间须为ISO格式')
  if not moment.tzinfo:raise ValueError('到单时间须带时区')
  orders.append((moment.timestamp(),p,float(sla[p]),float(handle[p])))
 if not orders:raise ValueError('报告快照没有到单样本')
 if len(orders)>MAX_ORDERS:raise ValueError('样本超过单次试算上限'+str(MAX_ORDERS))
 orders.sort(key=lambda o:o[0])
 return orders
def initial_state(staff,first_arrival):
 """初始断点：free为[空闲时刻,人员序号]堆，backlog为[SLA,到单时刻,单号]堆，inflight为在办单。"""
 return {'i':0,'free':[[first_arrival,s] for s in range(staff)],'backlog':[],'inflight':[None]*staff,'now':first_arrival,'agg':{'count':0,'wait_sum':0.0,'wait_max':0.0,'handle_sum':0.0,'overdue':0,'by':{},'t0':None,'last_done':None},'done':False}
def _assign(clock,state,slot,seq,order,start):
 arrival,prio,sla,handle=order
 done_at=clock.advance(start,handle);free_at=clock.next_business(done_at)
 wait=clock.bm(start)-clock.bm(arrival)
 agg=state['agg'];agg['count']+=1;agg['wait_sum']+=wait;agg['handle_sum']+=handle
 if wait>agg['wait_max']:agg['wait_max']=wait
 overdue=1 if wait+handle>sla else 0;agg['overdue']+=overdue
 by=agg['by'].get(prio)
 if by is None:by=agg['by'][prio]={'count':0,'wait_sum':0.0,'wait_max':0.0,'handle_sum':0.0,'overdue':0}
 by['count']+=1;by['wait_sum']+=wait;by['handle_sum']+=handle
 if wait>by['wait_max']:by['wait_max']=wait
 by['overdue']+=overdue
 if agg['t0'] is None or arrival<agg['t0']:agg['t0']=arrival
 if agg['last_done'] is None or done_at>agg['last_done']:agg['last_done']=done_at
 heappush(state['free'],[free_at,slot]);state['inflight'][slot]={'seq':seq,'free_at':free_at};state['now']=start
def run_batch(clock,orders,state,batch_size=BATCH_SIZE):
 """处理至多batch_size个事件（到单或接单），状态原地推进；任意时刻中断均可凭断点续跑。
 事件顺序：到单一律先入积压；不晚于最早空闲时刻的到单先并入（同时刻公平竞争）；
 空闲人员被唤醒到下一可开工时刻后，统一接SLA最紧的积压单，同档先到先办。"""
 free=state['free'];backlog=state['backlog'];n=len(orders);work=0
 while work<batch_size and not state['done']:
  i=state['i'];f=free[0][0]
  if i<n and orders[i][0]<=f:
   o=orders[i];heappush(backlog,[o[2],o[0],i]);state['i']=i+1
  elif backlog:
   slot=heappop(free)[1];_,_,seq=heappop(backlog);o=orders[seq]
   _assign(clock,state,slot,seq,o,clock.next_business(f if f>o[0] else o[0]))
  elif i<n:
   # 无积压且人员空闲：到单入积压，空闲人员唤醒到下一可开工时刻（不提前承诺接单）
   o=orders[i];a=o[0];s=clock.next_business(a)
   heappush(backlog,[o[2],a,i]);state['i']=i+1
   for entry in free:
    if entry[0]<=a:entry[0]=s
   heapify(free)
  else:state['done']=True
  work+=1
def build_result(clock,state,label,staff):
 agg=state['agg'];count=agg['count'];rows=[]
 for prio in sorted(agg['by']):
  p=agg['by'][prio];c=p['count']
  rows.append({'优先级':prio,'样本数':c,'平均等待营业分钟':p['wait_sum']/c,'最大等待营业分钟':p['wait_max'],'单均办理营业分钟':p['handle_sum']/c,'超时数':p['overdue'],'超时率':p['overdue']/c})
 span=clock.bm(agg['last_done'])-clock.bm(agg['t0']) if agg['t0'] is not None else 0
 summary={'档位':label,'人手':staff,'样本数':count,'平均等待营业分钟':agg['wait_sum']/count if count else 0,'最大等待营业分钟':agg['wait_max'],'办理营业分钟合计':agg['handle_sum'],'超时数':agg['overdue'],'超时率':agg['overdue']/count if count else 0,'收尾营业分钟':span}
 return {'summary':summary,'rows':rows,'method':METHOD,'warnings':WARNINGS}
def validate_sim_params(params,snapshot):
 if not isinstance(params,dict):raise ValueError('试算参数不合法')
 tiers=params.get('tiers')
 if not isinstance(tiers,list) or len(tiers)!=2:raise ValueError('试算需恰好两档人手')
 names=set();staffs=set()
 for t in tiers:
  if not isinstance(t,dict):raise ValueError('档位参数不合法')
  name=t.get('name');staff=t.get('staff')
  if not isinstance(name,str) or not 1<=len(name)<=40:raise ValueError('档位名称需1到40字')
  if isinstance(staff,bool) or not isinstance(staff,int) or not 1<=staff<=MAX_STAFF:raise ValueError('档位人数需为1到'+str(MAX_STAFF)+'的整数')
  if name in names:raise ValueError('两档名称不可重复')
  names.add(name);staffs.add(staff)
 if len(staffs)!=2:raise ValueError('两档人手数不可相同')
 handle=params.get('handle_minutes')
 if not isinstance(handle,dict) or not handle:raise ValueError('请按优先级填写每单办理耗时')
 for k,v in handle.items():
  if not isinstance(k,str) or not k:raise ValueError('优先级名称不合法')
  if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or not 1<=v<=100000:raise ValueError('办理耗时需为1到100000的营业分钟数')
 if not isinstance(snapshot,dict):raise ValueError('报告快照不合法')
 sla=(snapshot.get('policy') or {}).get('sla_minutes') or {}
 sources=snapshot.get('sources') or []
 if not sources:raise ValueError('报告快照没有到单样本')
 if len(sources)>MAX_ORDERS:raise ValueError('样本超过单次试算上限'+str(MAX_ORDERS))
 for s in sources:
  p=s.get('priority') if isinstance(s,dict) else None
  if p not in sla:raise ValueError('优先级无SLA口径：'+str(p))
  if p not in handle:raise ValueError('优先级缺少办理耗时：'+str(p))
 for k in handle:
  if k not in sla:raise ValueError('办理耗时优先级不在口径中：'+k)
