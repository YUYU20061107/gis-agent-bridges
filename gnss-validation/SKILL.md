# SKILL — gnss-validation（GNSS×GIS 离线轨迹验证桥）

给调用本桥的 Agent 的规矩。先读完再调工具。

## 定位

离线验证桥：输入是 `GNSS_WORK_DIR` 内的本地文件（NMEA/GPX 轨迹、GeoJSON 参考图层），输出是可复算的偏离/异常/分层统计与纠偏新文件。v0 不连设备、不联网、没有实时流（v0.2 才计划）。

## 调用顺序（推荐）

1. `gnss_status` 先看轨迹成色：点数、fix 分布、HDOP 范围、时间跨度、坏校验和计数。fix 里「无定位」占比高、HDOP 普遍 >5 的轨迹，先告诉用户数据本身可疑，再谈验证。
2. `gnss_detect_jumps` 先排跳点/漂移，再做偏离统计——跳点不排掉，RMS 会被个别坏点带偏。
3. `gnss_validate_against_layer` / `gnss_accuracy_report`（带 layer）给偏离结论；超限清单里每点带最近点坐标，可抽点复算。
4. 纠偏三件套按问题选：系统性整体偏移用 `gnss_correct_offset`（≥2 个可信配对）；贴路用 `gnss_correct_snap`；随机抖动用 `gnss_correct_smooth`。纠偏前先把原统计留档，纠偏后重新 validate 对比。

## 红线

- **自洽统计不是精度真值**：没给 layer 的 `gnss_accuracy_report` 只量抖动，系统偏移看不见。向用户汇报时必须带上 basis 字段口径，不许把 self-consistency 的数字说成「精度」。
- **单配对不纠偏**：`gnss_correct_offset` 只给 1 个配对时桥只报偏移量、不产文件，这是口径不是故障，不要绕（比如把同一个配对复制两份）。
- **写文件先 confirm**：三个 correct 工具都要用户明确同意后才传 `confirm=true`；输出名先想好，撞名会被拒（永不覆盖），不要换个名默默重试而不告知。
- **距离是平面近似**：汇报偏离数字时带上口径（等距圆柱近似、公里级适用）。跨城长轨迹先分段，不要整条一个结论。
- **未实机校准**：本桥停在协议自检级。合成自检通过 ≠ 真实轨迹验证过；涉及真实轨迹的结论要注明「未经 CALIBRATION 对账」。
- 路径只用工作目录内相对路径；被 `PATH_OUTSIDE_WORKDIR` 拒绝时不要试图绕（绝对路径、软链接都不行），让用户把文件放进工作目录。

## 参数速查

- `gnss_validate_against_layer`：`threshold_m` 默认 10（米）。行人轨迹对道路中心线验证时，道路半宽本身就有几米，阈值别设得比路宽还小。
- `gnss_detect_jumps`：`max_speed_mps` 默认 60（车载可放宽到 70+，步行收紧到 5–8）；`max_accel_mps2` 默认 15；漂移三参数默认 5 m / 30 s / 2 m。
- `gnss_correct_smooth`：`window` 须 ≥3 奇数，默认 5。窗口越大越平滑，也越容易把真实转弯抹圆角。
- HDOP 分层口径：≤1 / 1–2 / 2–5 / >5 / 未知。
