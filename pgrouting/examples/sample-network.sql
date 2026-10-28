-- sample-network.sql — pgRouting 消费侧只读桥的最小样本边表
--
-- 用途：给没有现成 PostgreSQL + PostGIS + pgRouting 环境的试用者一份
-- 可立即导入的小图。它只创建/重建 sample_ways 并写入 6 条演示边；
-- 不创建其他业务表。cost / reverse_cost 是演示用旅行权重，不是按
-- 几何长度计算的距离。
--
-- 警告：本脚本会 DROP 并重建 sample_ways。只许在一次性的本地样本库
-- （例如同目录 docker-compose.yml 创建的 pgrouting_sample）执行，
-- 不要对生产库或已有真实边表执行。
--
-- 图结构（节点坐标均为 WGS84 经纬度）：
--   1 = (0.00, 0.00)   2 = (0.01, 0.00)   3 = (0.02, 0.00)
--   4 = (0.01, 0.01)   5 = (0.02, 0.01)
--
-- 边表（id: source -> target, cost / reverse_cost）：
--   1: 1 -> 2,  2 / 2
--   2: 2 -> 3,  2 / 2
--   3: 1 -> 4,  1 / 1
--   4: 4 -> 5,  1 / 1
--   5: 5 -> 3,  1 / 1
--   6: 2 -> 5, 10 / 10
--
-- 以下预期值是在运行桥之前，仅按上表逐条相加得到的独立参照；
-- 不是桥的输出，也不得反过来用桥的输出改写：
--   * network_summary：node_count = 5，edge_count = 6。
--   * route 1 -> 3（directed=true）候选简单路径：
--       1-2-3       = 2 + 2         = 4
--       1-4-5-3     = 1 + 1 + 1     = 3  <-- 唯一最短
--       1-2-5-3     = 2 + 10 + 1    = 13
--     预期节点序列 [1, 4, 5, 3]，边序列 [3, 4, 5]，total_cost = 3。
--   * route 1 -> 5（directed=true）：1-4-5 = 1 + 1 = 2，为唯一最短；
--     预期节点序列 [1, 4, 5]，边序列 [3, 4]，total_cost = 2。
--   * export 1 -> 3：应有 3 个 features，与边序列 [3, 4, 5] 对应。

BEGIN;

-- 扩展创建可重复执行；已存在时不会报错。
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pgrouting;

DROP TABLE IF EXISTS sample_ways;

CREATE TABLE sample_ways (
    id           bigint PRIMARY KEY,
    source       bigint NOT NULL,
    target       bigint NOT NULL,
    cost         double precision NOT NULL,
    reverse_cost double precision NOT NULL,
    geom         geometry(LineString, 4326) NOT NULL
);

INSERT INTO sample_ways (id, source, target, cost, reverse_cost, geom)
VALUES
    (1, 1, 2,  2,  2,
     ST_GeomFromText('LINESTRING(0 0, 0.01 0)', 4326)),
    (2, 2, 3,  2,  2,
     ST_GeomFromText('LINESTRING(0.01 0, 0.02 0)', 4326)),
    (3, 1, 4,  1,  1,
     ST_GeomFromText('LINESTRING(0 0, 0.01 0.01)', 4326)),
    (4, 4, 5,  1,  1,
     ST_GeomFromText('LINESTRING(0.01 0.01, 0.02 0.01)', 4326)),
    (5, 5, 3,  1,  1,
     ST_GeomFromText('LINESTRING(0.02 0.01, 0.02 0)', 4326)),
    (6, 2, 5, 10, 10,
     ST_GeomFromText('LINESTRING(0.01 0, 0.02 0.01)', 4326));

COMMIT;
