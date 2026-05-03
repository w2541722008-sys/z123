"""数据访问层 —— 集中管理所有 SQL 查询。

设计原则：
    - SQL 只在本层出现，routers 和 services 不直接写 SQL
    - 每个 repository 按领域划分（character、user、chat 等）
    - 函数接收 conn 参数，不负责事务管理（commit/rollback 由调用方控制）
"""
