# 002 排班试算

SQLAlchemy启动自动创建 staffing_sims 与 staffing_sim_tiers 两表；staffing_sim_tiers 含 (sim_id, generation, slot) 唯一约束。存量数据库无需数据迁移：新表为空表，已复核报告快照直接被试算引用。代际演进说明：重算仅递增 staffing_sims.generation 并插入新代档位行；已发布代结果保留至新一代两档完成后由worker原子切换并清理更老档位行。
