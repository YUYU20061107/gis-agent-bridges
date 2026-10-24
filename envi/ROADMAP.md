# ROADMAP — envi-bridge

## 当前状态（v0.1）

- 盘点层（.hdr 纯 Python 解析 + inventory/backup）：VM 自造样本实测通过，
  与 ENVI 版本无关，可直接用。
- MCP 协议层：selftest 6/6 PASS。
- 任务层（idlpy 无头会话 → ENVITask）：多策略实验性实现，**未在真实
  ENVI 上校准**，待按 docs/CALIBRATION.md 实机收紧。

## 待实机校准清单（有 ENVI 的机器上逐项做）

1. probe_api.py：ENVI/IDL 版本、任务名枚举命中的是哪个策略（via）。
2. envi_describe_task 对 2–3 个常用任务（如 SpectralIndex、
   ClassificationAggregation）的参数名单与 describe 输出对账。
3. envi_run_task 在副本数据上跑通一个只读入参、输出到副本目录的任务，
   核对 outputs 回收与参数 set 方式（大小写策略）。
4. envi_export_raster_subset 的 Sub_RECT 签名与 Export 落盘行为。
5. idlpy 会话长驻的稳定性：连续多次 run_task 后会话是否泄漏/失效。

## 候选演进（未排期）

- **v0.2 任务层收紧**：校准后把命中的策略写死、删冗余策略，补常用任务
  的参数模板（植被指数、分类、镶嵌）与输出回收规范。
- **盘点层增强**：递归目录扫描、.hdr 与数据文件配对异常清单
  （孤儿 .hdr / 缺头数据文件）、批量大小核对报告。
- **实时版（IDL 驻留扩展）**：用 IDL 在 ENVI 进程内开本地服务，转发
  ENVITask 与当前视图对象——这是本系列里唯一需要换实现语言的成员，
  成本高、需随 ENVI 大版本维护。评估结论：**技术上可做，优先级后置**；
  在没有明确需求与实机维护条件前不启动，README/HEADLESS 的"无头版"
  定位不变。
- **与其他成员的统一**：待系列合集仓的统一 README/索引页落地后，
  本包的工具命名与回报格式如需微调，跟随合集规范一次性对齐。

## 明确不做

- 不做 GUI 会话附着的任何模拟实现（文件回退、自起 GUI 会话冒充实时）。
- 不绕过或代管 ENVI/IDL 许可；不在包内分发任何 ENVI/IDL 组件。

v0.2（2026-10-24）：selftest 改后台线程+队列读行（弃 select，修 Windows 管道问题）；新增 scripts/verify_project.py（.hdr 文件对盘点 + 伴生文件完整性 + --copy-to 副本重盘）与 ENGINEERING-PLAYBOOK.md；token 仍只用环境变量 ENVI_BRIDGE_TOKEN（无 token 文件）；工具清单（7 个）、confirm 闸与 BAD_TOKEN 语义不变，仍仅无头，idlpy 任务层未做实机校准。
