# 示例提示词 — gnss-validation

把下面这些话发给接了本桥的 Agent 即可（文件先放进 `GNSS_WORK_DIR`）。

## 看轨迹成色

> 先用 gnss_status 看一下 `morning-run.nmea`：多少个点、fix 分布怎么样、HDOP 范围和时间跨度是多少，坏校验和多不多？

## 排异常

> 对 `morning-run.nmea` 跑 gnss_detect_jumps（步行场景，max_speed_mps 设 6），把可疑点和理由列出来，漂移段单独说。

## 对路网验证

> 用 gnss_validate_against_layer 把 `morning-run.nmea` 对 `road.geojson` 验证，阈值 10 m：偏离中位数/RMS 是多少，超限点有几个、都在哪一段？

## 分层精度报告

> 给 `morning-run.nmea` 出一份 accuracy_report（带 `road.geojson`）：按 fix 类型和 HDOP 段拆开看，RTK固定 和 GPS 的 RMS 差多少？

> 同一条轨迹不给图层再出一份，说明白 basis 是自洽统计、不是精度真值，自洽量到的抖动有多大。

## 纠偏（都会先要你确认）

> 把 `morning-run.nmea` 吸附到 `road.geojson` 上，输出 `morning-run-snapped.geojson`，告诉我每点最大/平均修正量，确认后再写。

> 这条轨迹整体偏了：我有两个控制点配对（观测点↔真值点）……用 gnss_correct_offset 纠偏输出新文件，并对比纠偏前后的中位偏离。

> 只给一个配对时先别纠偏，把偏移量报给我就行。
