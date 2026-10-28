# 贡献指南（Contributing）

欢迎提交 Issue、校准记录、文档修正与代码补丁。这个项目的第一原则
是**证据与标注一致**：没在真实软件上跑过的能力，不写成已校准；
没复现的问题，不写成已修复。

## 提 Issue

- 普通故障用 Bug 模板，先在仓内样本数据上尝试复现。
- 实机校准结果用 Calibration 模板，写清软件版本、系统、Python/
  厂商运行时、逐项结果与失败证据。
- 新功能用 Feature 模板，先说明真实 GIS 工作流与安全边界。
- 安全问题不要开普通 Issue，按 `SECURITY.md` 的私密路径报告。

提交前请删除 token、密码、API Key、私人工程路径与未脱敏日志。

## 本地检查

在仓库根目录运行：

```bash
python -m compileall -q .
python manifest/build_manifest.py
python manifest/check_readme_counts.py
python manifest/check_invariants.py
python scripts/quickstart.py --sample-qgis
```

再运行你改动包的自检：

```bash
python <package>/live/selftest.py
```

若改了工具面，必须重新生成 `manifest/tools-manifest.json`，并同步根
README 软件矩阵、包 README、SKILL.md 与 CHANGELOG.md。

## 提 PR

1. 一个 PR 只做一类事：一个包的功能、一个校准批次或一组文档修复。
2. 写清证据等级：工程自报、文件读取、独立复跑、实机校准分别标注。
3. 写操作必须保留 confirm 闸；新工具不得提供任意代码执行、任意
   SQL 或任意 URL 抓取通道。
4. 不提交厂商组件、真实凭据、用户工程、数据库转储或未脱敏截图。
5. 若结论只在某个版本/模式成立，把环境写进 `docs/CALIBRATION.md`，
   不要把一个包的结论套到另一个包。

## 行为准则

参与讨论时保持具体、尊重与就事论事；不发布他人的私人信息，不用
人身攻击代替技术证据。维护者可移除骚扰、spam 与明显恶意内容。
