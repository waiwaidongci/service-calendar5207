// API实体字段约定：来源{id,natural_key,data}、口径{id,version,data}、报告{id,status,snapshot,checksum,result,approved}、计划{next_at,enabled}、试算{id,run_id,params,generation,published,status,tiers,published_tiers}。
export const ENTITY_KEYS=['sources','policies','runs','schedules','deliveries','sims'];
