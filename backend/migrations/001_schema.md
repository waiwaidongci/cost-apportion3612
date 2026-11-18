# 初始结构

SQLAlchemy启动创建以下业务表：costperiods, costentrys, allocationrules, allocationruns, delivery_schedules, deliveries、users、audits。Source专属JSON字段由对应validation严格校验；Policy为不可覆盖的版本记录；Run保存source/policy冻结快照；Period仅用于已有期间选择器，不计入核心复杂度。已有数据库升级需先备份，后续字段演进应以独立迁移执行。

# 002 预算压力试算

新增 `risk_books`（风险登记簿，仅追加版本，data 存 risks 数组）与 `stress_trials`（试算任务，snapshot 冻结报告部门成本/风险版本/预算并保存 SHA256，result 存精确分数结果，error 记录超时或校验失败）。`Base.metadata.create_all` 启动时自动建表，无需手工 DDL；旧库升级前先备份。试算队列使用 Redis 列表 `stress-jobs`，与 `report-jobs` 相互独立。
