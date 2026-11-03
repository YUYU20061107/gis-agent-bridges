# G1 动词语义契约集 · 第一批草稿（2026-11-03）

- 归属：GIS 平台 v0.3 批 0 / G1。本文是**设计草稿**，依据 `V03-WORKLIST-V2-GENERALIZED-20261103.md` 的 R1（契约先行）、R2（通用骨架＋薄适配）、R3（能力三级）、R4（一致性即证据）起草；批 1 复核后才可称定版。
- 输入账本：`leaves-full.json`（195 叶，含 `tier/status/kind/native/bts/note`）、G3 变更日志、B1 一轮与二轮对账。本文**不修改**注册表、代码或 v0/v0.1/v0.2 本体。
- 契约优先方向：契约规定跨后端应实现的规范语义；现有 `verbs.json` 或某家原生工具若是原地改写、隐式重投影、隐式修几何等行为，均视为实现待对齐项，不能反过来改写契约。

## 挑选口径（首批 10 个）

入选条件同时满足：①至少一条注册表叶为 `tier=core`，且动词本身在 G3 口径中属 core 语义；②是其他操作的基础依赖，或默认值/CRS/破坏性语义分歧最容易造成静默错误；③能在 G2 中用同一输入做跨后端等价断言；④优先覆盖生命周期、结构编辑、纵向组合、投影、基础分析、叠加与空间连接。

首批名单（10 个）：

| # | VID | 动词 | 首批角色 |
|---:|---|---|---|
| 1 | V05 | `gis_create_dataset` | 数据集生命周期入口 |
| 2 | V06 | `gis_add_field` | 结构编辑（新增） |
| 3 | V07 | `gis_delete_field` | 结构编辑（删除） |
| 4 | V12 | `gis_merge_datasets` | 纵向组合与 schema 基线 |
| 5 | V14 | `gis_assign_projection` | CRS 元数据赋值 |
| 6 | V15 | `gis_reproject` | CRS 坐标变换 |
| 7 | V18 | `gis_buffer` | 基础邻域分析 |
| 8 | V19 | `gis_clip` | 基础范围裁剪（矢量/栅格） |
| 9 | V20 | `gis_overlay` | 二元叠加动词族（七个 operation 变体） |
| 10 | V22 | `gis_spatial_join` | 空间查询/连接 |

口径说明与未入选原因：

- 注册表 40 个统一动词中**没有** `gis_open_dataset`、`gis_close_dataset` 等显式打开/关闭动词。现行对象模型以逻辑 dataset 引用为输入，句柄由适配器在单次调用内打开并释放；本文不虚构不存在的动词。V05 是本批的生命周期入口，句柄生命周期写入模板全局约定。
- `gis_measure`（V31）四叶均为 `tier=extended`（仅 PostGIS 落地），按本批严格的 core 口径不入选，不把它误标为 core；量测契约放下一批随 extended 扩批处理。
- `gis_append_dataset`（V13）暂未单列：先由 V12 定住纵向组合、schema 兼容与目标存在性规则；V13 的“已存在目标＋R2”语义和 QGIS/SuperMap 证据形态不同，放下一批单独立约。B1 二轮已确认 SuperMap `DatasetVector.append` 类级路径，该事实在 V12 的实现/证据字段中注明，但不冒充 V13 已完成契约。
- `gis_list_algorithms` / `gis_describe_algorithm` 是注册表查询而非数据语义操作，本批先让位于会产生或改变空间数据的核心动词。

---

# A. 契约模板

## A.1 每个动词必须写满的 14 个字段

| 字段 | 名称 | 必填内容与判定标准 |
|---|---|---|
| F01 | 身份与范围 | 契约 ID、VID、统一动词名、tier 口径、适用后端集合、变体轴（如 kind/input_type/operation）、明确的非适用范围。不得用某一家产品名替代统一语义。 |
| F02 | 一句话语义与非目标 | 一句话说明“输入在满足什么条件时，产生什么逻辑结果”；同时写清不做什么（例如 assign projection 不改坐标、clip 不做属性连接），防止近义动词混用。 |
| F03 | 输入签名 | 逐参数列明：名、逻辑类型、必填/可选、默认值、单位、枚举域、互斥/依赖关系。没有默认值必须明写“无默认，缺失即 `INVALID_ARGUMENT`”；不许把后端原生默认带入契约。 |
| F04 | 输入对象与几何维数 | 输入对象种类（vector/raster/table/service 等）、几何基类型、单/多几何、坐标维数（2D/Z/M/ZM）、栅格波段/像元维数、是否允许多个输入；不适用项也要明写不适用。 |
| F05 | 输出签名与后置条件 | 输出对象引用、对象种类、几何/栅格结构、要素数或像元网格的变化规则、目标已存在时行为、空结果是否成功、回包摘要字段。输出必须是可独立引用的成果或明确的结果对象。 |
| F06 | CRS 与单位约定 | CRS 身份、轴序、未知 CRS、输入间 CRS 一致性、是否允许变换、距离/面积单位、地理坐标系下的量测方法、Z/M 的处理。禁止“同 SRID 整数即同 CRS”的简化。 |
| F07 | 属性 schema、ID 与空值 | 字段名/类型/长度/精度/可空/默认值/域与索引的保留规则，字段冲突处理，稳定键与生成 ID 的地位，`null` 与 0/空字符串的严格区分，行序是否属于语义。 |
| F08 | 容差与确定性 | 几何/数值/栅格等价容差，是否允许 snapping、简化、自动修复、随机性；平局裁决、排序与浮点比较方法。未声明的容差不得由后端自行决定。 |
| F09 | 副作用、原子性与输入保护 | 输入是否允许被修改；目标写入是否全有全无；失败时回滚/隔离要求；临时对象清理；并发或目标已存在时的行为。 |
| F10 | 破坏性等级与确认门 | 给出基础 R0–R3、动态升降级条件、需要的确认材料。R3 必须绑定 `confirm + target_echo + preflight_id`；许可闸如适用，必须先于确认门。 |
| F11 | 失败与 `NOT_SUPPORTED` 口径 | 逐类列出错误码及何时使用；明确区分能力不支持、映射未验、参数错误、数据错误、CRS 错误、确认/许可拦截、后端故障。`NOT_SUPPORTED` 只能表示所选后端/变体在契约范围内无可用实现路线，不得用它掩盖其他失败。 |
| F12 | 后端落点与实现路线 | 逐后端列注册表 `kind/native/template` 或目标实现路线：`native`、`template`、`gateway_synthesis`、`copy_on_write_adapter`、`derived` 等。实现路线是设计目标，不等于当前可用状态。 |
| F13 | 跨后端语义等价判据 | 写成 G2 可执行的断言：同输入下成功/失败类别、对象种类、几何、拓扑、schema、属性多重集、CRS、栅格网格、输入未变等分别如何判等；同时声明哪些差异（生成 ID、物理行序、内部格式、耗时）不属于语义。 |
| F14 | 证据状态快照（正交字段） | 记录快照日期、逐后端 `tier/status/kind/native/bts` 及 B1 等覆盖层注记。证据状态只描述“当前查验到哪里”，**不属于语义契约本身**；契约写作、tier 或实现路线均不得把 `unverified/not_supported/pending` 升格为已验证。 |

## A.2 模板全局约定

### A.2.1 对象、句柄与命名

1. `dataset`、`input`、`target` 等参数均是网关逻辑引用，不把某个后端的物理路径、表名或内存句柄当作统一语义。
2. 适配器可在一次调用内打开/关闭后端句柄；句柄泄漏是实现缺陷，不是统一动词，也不在回包中伪装成“关闭成功”。
3. 目标名、字段名先按统一命名规则校验，再进入确认和执行。名称只差大小写而在目标后端会冲突时，必须在执行前以 `SCHEMA_MISMATCH` 或 `INVALID_ARGUMENT` 明确失败，不许静默改名。
4. 除动词契约明确允许外，`target` 必须是不存在的逻辑引用；已存在即 `ALREADY_EXISTS`，不提供隐式 overwrite。

### A.2.2 “原数据不动、输出新成果”总则

- 除显式生命周期销毁动词（不在本批）外，凡会改变输入的几何、属性值、schema、CRS 元数据或栅格值的操作，**规范形态一律 copy-on-write：输入保持不变，结果写入新的 `target`**。
- 某家原生工具只有原地形态时，适配器必须先复制到 target 再执行，或以等价事务实现；不能把原生原地行为登记为契约等价。
- `gis_reproject` 的 `overwrite=true` 是现行签名中的例外通道，不推荐作为规范用法；一旦使用即动态升 R3，且仍须在回包中如实标明输入被覆盖。

### A.2.3 CRS、维数与单位的统一语言

- CRS 身份由 authority、code、版本/WKT2 摘要共同确定；`srid` 只是当前接口中的整数简写。轴序以 CRS 定义为准，跨后端比较前先规范化到该轴序。
- 几何维数写成“基类型 × 坐标维数”，如 `Polygon × ZM`。基类型集合：Point、MultiPoint、LineString、MultiLineString、Polygon、MultiPolygon、GeometryCollection。不得把栅格行列维数混称几何 Z 维。
- 未知 CRS 不是 EPSG:4326，也不是 SRID 0 的同义词。空间量测、叠加、连接、缓冲在未知 CRS 下默认失败；只有 CRS 元数据赋值的动词可以把未知 CRS 作为待修正输入状态。
- 距离参数的规范量纲是米；输入若使用 CRS 线性单位或字段值，必须在契约参数中显式换算。地理坐标的度数不得直接当米。
- Z 只在输入、CRS/垂直基准与后端能力都明确时参与变换；M 默认原样保留，不因二维运算被静默丢弃。后端不能保留 Z/M 时应返回 `DIMENSION_MISMATCH` 或 `NOT_SUPPORTED`，不能降维后报成功。

### A.2.4 默认值纪律

- 契约未写默认值即表示**无跨后端默认**。参数缺失时，要么在 F03 中规定为必填，要么返回参数错误；不许分别继承 ArcGIS、QGIS、PostGIS、SuperMap 的原生默认。
- 空结果在语义上成立时是成功，例如裁剪后无要素、overlay 的某一分支为空；“空”不自动等于失败。
- 不做隐式重投影、不做隐式 schema 强转、不做隐式几何修复、不做隐式简化/吸附。后端若技术上无法关闭自动修复，必须在回包 `warnings` 中披露 `precision_or_repair_applied`，G2 中单独判定，不能与未修复结果默认等价。

### A.2.5 原子性与回包后置条件

规范回包至少包含：`verb`、`vid`、实际 `level`、`backend`、输入引用、输出引用（如有）、`input_unchanged`、输出摘要、实现路线/轮子名、`warnings`。输出摘要按对象种类包含要素数与几何类型/维数/CRS/schema 摘要，或栅格行列、像元大小、原点、波段、NoData 摘要。

多输入、多字段、多变体操作默认全有全无。后端已部分写入而适配器无法回滚时，不得报普通成功，也不得谎称 `input_unchanged=true`；应隔离未完成 target 并返回 `TARGET_STATE_UNKNOWN`，供人工处置。

### A.2.6 R0–R3 语义

| 等级 | 契约含义 | 最低门槛 |
|---|---|---|
| R0 | 只读或只产生非持久结果，不写数据集 | 无 confirm |
| R1 | 新建独立持久成果，不修改输入 | `confirm=true`（沿用现行网关治理） |
| R2 | 改变已有对象的 schema、内容或解释元数据，或影响面较大；即使规范形态 copy-on-write，也不因此自动降为 R1 | `confirm=true`，回包必须标明逻辑变更对象 |
| R3 | 语义上销毁数据/字段/对象，或明确覆盖已有成果 | `confirm=true`＋`target_echo` 逐字回显＋单次有效 `preflight_id` 影响面预检；额外通道隔离按现行治理 |

动态升降级只能收紧不能放宽。后端能力不足不会降低等级；copy-on-write 降低的是物理风险，不自动改变该动词的治理分类，是否调整留 G1 定版复核。

### A.2.7 错误码最小集

| 错误码 | 使用边界 |
|---|---|
| `NOT_SUPPORTED` | 所选后端/变体没有契约允许的实现路线，或该组合被契约明确排除；无副作用，不消耗 confirm/preflight。 |
| `UNVERIFIED_MAPPING` | 注册表已有落点但状态为 `unverified`，或桥侧工具仍 pending 到不能执行；不能与 `NOT_SUPPORTED` 混用。 |
| `INVALID_ARGUMENT` | 参数缺失、类型/枚举错误、互斥参数同传、目标等于输入但未走显式覆盖通道。 |
| `NOT_FOUND` | 输入逻辑引用不存在或在所选后端不可见。 |
| `ALREADY_EXISTS` | target 已存在且契约不允许覆盖。 |
| `SCHEMA_MISMATCH` | 字段名/类型/长度/几何类型/维数等不满足动词的兼容规则。 |
| `CRS_MISMATCH` | 输入 CRS 已知但彼此不同，且动词不负责变换。 |
| `UNKNOWN_CRS` | 必须知道 CRS 才能安全执行而输入 CRS 未知。 |
| `DIMENSION_MISMATCH` | 2D/Z/M/ZM 或单/多几何形态不满足契约且不能无损转换。 |
| `GEOMETRY_INVALID` | 输入几何无效且调用方未显式先行校验/修复；不得自动修复后静默成功。 |
| `CONFIRM_REQUIRED` / `PREFLIGHT_REQUIRED` | 确认材料缺失或预检回执无效/已使用。 |
| `LICENSE_BLOCKED` | 许可闸拦截；发生于 confirm 之前。 |
| `BACKEND_ERROR` | 后端执行故障且不属于以上类别；须带脱敏后的原生错误摘要。 |
| `TARGET_STATE_UNKNOWN` | 失败后无法确认 target 是否部分提交。 |

### A.2.8 通用等价容差（G2 起点，不是实测结论）

- 纯结构/元数据操作：坐标序列在规范化序列化后应逐值一致；只允许浮点文本表示差异，数值相对差 ≤1e-12。
- 一般矢量分析：在统一量测 CRS 下，几何 Hausdorff 距离 ≤ max(1e-6 米， 1e-9 × 输入范围对角线)；面积/长度相对差 ≤1e-6；拓扑谓词结果必须一致。
- 栅格：行列数、像元大小、原点对齐、波段数、NoData 必须一致；分类值逐像元一致，连续值绝对/相对差均 ≤1e-6（取较宽者）才算等价。边界像元差异不得用“少量”含糊带过，G2 须报告差异像元数与位置。
- 属性：按要素多重集比较，不以物理行序判等；字符串逐值一致，整数逐值一致，浮点相对差 ≤1e-9，日期时间规范化到同一时区/精度后比较；`null` 只等于 `null`。
- 生成 ID、物理行序、内部文件格式、索引形态、执行耗时不属于语义；但稳定业务键属于属性语义，必须保留。

---

# B. 首批契约草稿

> 读法：每项均按 F01–F14 写满。F03 中标注“契约目标签名”的参数，是为落实 copy-on-write 而对现行签名提出的规范化目标；它不表示现行代码已经支持。F14 是 2026-11-03 快照，与 F01–F13 的规范语义正交。

## B.01 V05 `gis_create_dataset`

| 字段 | 草稿 |
|---|---|
| F01 身份与范围 | core；后端：arcgis-pro、supermap、qgis、postgis。变体轴 `kind ∈ {vector, table, raster}`。只创建空容器/空数据集，不导入数据、不从源数据复制 schema。 |
| F02 一句话语义与非目标 | 在指定后端中创建一个尚不存在、结构由参数完整声明的空数据集；不负责打开既有数据集、不负责填充记录、不负责发布。 |
| F03 输入签名 | `backend`（string，必填，无默认）；`name`（string，必填，统一命名校验）；`kind`（enum，必填）；`geometry_type`（基类型×维数，vector 必填，table 禁止，raster 不适用）；`srid`（integer，空间 kind 必填，table 必须缺失或 null）；`fields`（FieldSpec[]，可选，默认 `[]`）；`confirm`（bool，必填 true）。栅格的完整 `raster_spec` 尚未进入现行签名，见待定问题 C03。 |
| F04 输入对象与几何维数 | 无既有空间输入。vector 允许 Point/MultiPoint/LineString/MultiLineString/Polygon/MultiPolygon × 2D/Z/M/ZM；GeometryCollection 不作为首批可创建基类型。table 无几何维数。raster 只有二维空间网格，波段是通道维数而非 Z。 |
| F05 输出签名与后置条件 | 输出新 dataset 引用；要素数恒为 0；schema 与声明一致；空间 kind 的 CRS 与声明一致；name 已存在即失败，不覆盖。回包给出 `dataset`、`kind`、`geometry_type`、`crs`、`schema_hash`、`feature_count=0`。 |
| F06 CRS 与单位约定 | 空间数据集不得以“未指定”代替 CRS；`srid` 必须能解析到确定 CRS。table 不赋 CRS。创建动作不发生坐标变换。 |
| F07 属性 schema、ID 与空值 | `fields` 中每个 FieldSpec 至少含 name/type；length 仅适用于可变长类型，precision/scale 仅适用于数值类型。是否自动生成系统 ID 由后端内部处理，不属于可移植 schema；调用方声明的业务键字段按普通字段创建并标明 key 意图，不许后端静默改型。 |
| F08 容差与确定性 | 结构操作无几何容差。名称、字段顺序按声明保留；字段顺序属于 schema 摘要的一部分。 |
| F09 副作用、原子性与输入保护 | 只新增 target；创建失败不得留下半成品 dataset。若后端先建容器后加几何列/字段，适配器必须事务化或失败后清理并验证不存在。 |
| F10 破坏性等级与确认门 | R1；`confirm=true`。不因“空数据集无数据”降为 R0。 |
| F11 失败与 NOT_SUPPORTED | name 冲突 `ALREADY_EXISTS`；kind/geometry/fields 组合非法 `INVALID_ARGUMENT`；CRS 无法解析 `UNKNOWN_CRS`；字段类型不受后端支持 `NOT_SUPPORTED`；映射未验 `UNVERIFIED_MAPPING`。ArcGIS Pro raster 变体按当前注册表为 `NOT_SUPPORTED`，不能用 vector 容器冒充。 |
| F12 后端落点与实现路线 | arcgis-pro：`gp_named`（CreateFeatureClass/CreateTable，raster 无落点）；supermap：`native`（Datasource.create_dataset）；qgis：`native` PyQGIS 建层路线，不得用 Processing 冒名；postgis：`template`（create_table）。 |
| F13 跨后端语义等价判据 | 同一声明在各后端均产生空对象；kind、geometry 基类型/维数、CRS、字段名/类型/可空性一致；不得一家多生成业务字段、一家少生成。栅格在 `raster_spec` 定版前只判容器身份，不宣称完整栅格等价。 |
| F14 证据状态快照 | tier 全叶 core。status：arcgis-pro vector `ok`、table `unverified`、raster `not_supported`；supermap `ok`（桥侧 `bts=pending`）；qgis `unverified`；postgis `ok`。本契约不改变任何状态。 |

## B.02 V06 `gis_add_field`

| 字段 | 草稿 |
|---|---|
| F01 身份与范围 | core；后端：arcgis-pro、qgis、supermap、postgis。适用于 vector/table 数据集的结构扩展；不适用于给栅格波段改名或新增栅格通道。 |
| F02 一句话语义与非目标 | 在不改变既有记录与几何的前提下，生成一个比源数据集多出一个已声明字段的新数据集；不计算字段值，不把加字段与 `gis_calculate_field` 合并。 |
| F03 输入签名 | 契约目标签名：`backend`（必填）；`dataset`（必填）；`target`（必填，须不存在；现行签名缺此项，属待对齐）；`field`（FieldSpec，必填，含 name/type，可选 length/precision/scale/nullable/default/alias）；`confirm`（必填 true）。无默认字段名或类型。 |
| F04 输入对象与几何维数 | vector/table 均可；几何基类型与 2D/Z/M/ZM 必须原样保留。本动词不读几何坐标。 |
| F05 输出签名与后置条件 | 输出 target；记录数与源相同；既有字段和值逐项不变；新字段对既有记录按 FieldSpec 的 default 填充，未声明 default 时为 `null`。回包标 `logical_change=schema_add`、源/目标 schema hash 与 `input_unchanged=true`。 |
| F06 CRS 与单位约定 | CRS 不变；不触发量测或变换。字段若声明单位，只能作为字段元数据保存，不能改变数值。 |
| F07 属性 schema、ID 与空值 | 新字段名不得与既有字段重复（大小写冲突按 A.2.1 处理）。类型只接受统一 FieldType 枚举；后端无法保真 nullable/default/length/precision 时不得静默丢弃，应 `NOT_SUPPORTED`。系统 ID 与稳定键不变。 |
| F08 容差与确定性 | 既有属性逐值等价；新字段 default 为浮点时按 A.2.8 比较。字段追加位置固定为 schema 末尾，避免后端默认排序造成差异。 |
| F09 副作用、原子性与输入保护 | 规范形态 copy-on-write，源 dataset 不动。现行若干原生路径为原地加字段，适配器须先复制。字段创建与数据复制全有全无。 |
| F10 破坏性等级与确认门 | R2；`confirm=true`。虽不删数据，但改变已有对象的逻辑 schema，不降为 R1。 |
| F11 失败与 NOT_SUPPORTED | 字段已存在 `SCHEMA_MISMATCH`；FieldSpec 非法 `INVALID_ARGUMENT`；目标已存在 `ALREADY_EXISTS`；后端类型/约束无法保真 `NOT_SUPPORTED`；SuperMap 映射在注册表中仍为 `unverified` 时调用层回 `UNVERIFIED_MAPPING`，B1 类级证据不直接改写该返回。 |
| F12 后端落点与实现路线 | arcgis-pro：`arcpy.management.AddField`；qgis：`native:addfieldtoattributestable`；postgis：`add_column` template；supermap：目标路线为 `DatasetVector.create_field/create_fields/append_fields` 类方法（B1 二轮类级坐实），外加 copy-on-write adapter。 |
| F13 跨后端语义等价判据 | 同源数据、同 FieldSpec：输出记录多重集除新字段外逐项相等；新字段的型别、可空性、长度/精度与 default/null 结果一致；几何摘要与 CRS 完全一致；源对象前后摘要一致。 |
| F14 证据状态快照 | tier 全叶 core。注册表 status：arcgis-pro/qgis/postgis `ok`，supermap `unverified`。B1 二轮覆盖注记：SuperMap 类方法名已坐实，但“坐实≠可执行”，注册表状态与执行升格仍待批 1 写工具＋实机校准。 |

## B.03 V07 `gis_delete_field`

| 字段 | 草稿 |
|---|---|
| F01 身份与范围 | core；后端：arcgis-pro、qgis、supermap、postgis。适用于 vector/table 的一个或多个普通属性字段删除；几何列、系统 ID 列不在可删范围。 |
| F02 一句话语义与非目标 | 生成一个移除了指定字段及其值的新数据集，其余记录、几何和字段保持不变；不在本动词内做备份、归档或字段改名。 |
| F03 输入签名 | 契约目标签名：`backend`（必填）；`dataset`（必填）；`target`（必填，须不存在；现行签名缺此项，属待对齐）；`fields`（string[]，必填，非空，去重后至少一项）；`confirm`（必填 true）；`target_echo`（必填，逐字回显逻辑目标对象）；`preflight_id`（必填，单次有效）。 |
| F04 输入对象与几何维数 | vector/table 均可；几何基类型、坐标维数、要素数不变。 |
| F05 输出签名与后置条件 | 输出 target；schema 精确等于源 schema 减去 `fields`；未删字段值逐项不变；被删字段不出现在输出 schema 或回包属性样例中。回包给 `removed_fields`、依赖预检摘要、源/目标 schema hash。 |
| F06 CRS 与单位约定 | CRS 不变，不发生量测或坐标处理。 |
| F07 属性 schema、ID 与空值 | 待删字段必须存在；重复名先去重并在回包注明。字段被索引、域、连接、表达式或下游 schema 依赖引用时，预检必须列出；首批契约不提供 cascade 选项，有依赖即 `SCHEMA_MISMATCH` 并在 details 中列明，不能静默级联删除。稳定键字段默认不可删，除非它不是系统/业务键且预检明确列示影响。 |
| F08 容差与确定性 | 保留字段逐值等价；字段顺序保持源相对顺序。预检结果绑定 dataset 摘要、fields 集合与 target，任一变化即预检失效。 |
| F09 副作用、原子性与输入保护 | 规范形态 copy-on-write，源 dataset 不动；多个字段全有全无。原生 DeleteField/Drop Column 的原地实现必须由 adapter 先复制，不能直接作用于源对象。 |
| F10 破坏性等级与确认门 | R3；必须 `confirm + target_echo + preflight_id`。copy-on-write 只保护源对象，不把“在成果中销毁字段数据”的治理等级降为 R2。 |
| F11 失败与 NOT_SUPPORTED | 字段不存在 `SCHEMA_MISMATCH`；几何/系统字段 `INVALID_ARGUMENT`；有未解除依赖 `SCHEMA_MISMATCH`；目标已存在 `ALREADY_EXISTS`；确认材料不全分别回 `CONFIRM_REQUIRED`/`PREFLIGHT_REQUIRED`；SuperMap 注册表仍 `unverified` 时回 `UNVERIFIED_MAPPING`。 |
| F12 后端落点与实现路线 | arcgis-pro：`arcpy.management.DeleteField`；qgis：`native:deletecolumn`；postgis：`drop_column` template；supermap：`DatasetVector.remove_field` 类方法（B1 二轮类级坐实），外加 copy-on-write adapter。 |
| F13 跨后端语义等价判据 | 同源与同 fields：输出 schema 差集精确一致；保留字段属性多重集、几何、CRS、记录数一致；依赖存在时各后端都应在执行前失败，而不是一家级联、一家保留依赖。源对象摘要不变。 |
| F14 证据状态快照 | tier 全叶 core。注册表 status：arcgis-pro/qgis/postgis `ok`，supermap `unverified`。B1 二轮覆盖注记：`DatasetVector.remove_field` 类级坐实；仍待工具实现与实机校准。 |

## B.04 V12 `gis_merge_datasets`

| 字段 | 草稿 |
|---|---|
| F01 身份与范围 | core；后端：arcgis-pro、qgis、postgis、supermap。首批规范域为 **vector 数据集的纵向合并**；table 合并与 raster 镶嵌不属于本契约首批等价域。 |
| F02 一句话语义与非目标 | 把两个或更多 schema 与空间参考兼容的矢量数据集按输入顺序纵向拼接为一个新数据集；不做空间叠加、不做融合消边、不去重、不做属性连接。 |
| F03 输入签名 | `backend`（必填）；`inputs`（dataset[]，必填，长度 ≥2）；`target`（必填，须不存在）；`confirm`（必填 true）。首批无 `field_map` 参数，因此不允许调用方在本动词内声明字段改名/类型转换。 |
| F04 输入对象与几何维数 | 所有输入须为同一几何基类型与同一坐标维数。Point 与 MultiPoint、LineString 与 MultiLineString 不自动互转；GeometryCollection 只可与 GeometryCollection 合并且不作为 G2 首批核心样本。 |
| F05 输出签名与后置条件 | 输出 target；要素数等于各输入要素数之和；重复要素保留；逻辑顺序为 inputs 顺序、同一输入内保持源顺序，但物理行序不作跨后端判等依据。回包给逐输入计数与总计数。 |
| F06 CRS 与单位约定 | 所有输入 CRS 必须完全一致；不一致回 `CRS_MISMATCH`，不隐式重投影。合并本身不做量测。 |
| F07 属性 schema、ID 与空值 | 首批采用严格兼容：字段名集合、统一类型、可空性必须一致；字段顺序可不同，输出顺序取第一个输入。缺字段不得自动补 null，类型相近不得自动强转。生成 ID 可重编；稳定业务键必须保留且不保证全局唯一，重复键不自动删除。 |
| F08 容差与确定性 | 几何与属性不做数值改写；按 A.2.8 的结构操作标准比较。输入顺序是语义输入的一部分，改变 inputs 顺序可以改变逻辑顺序与输出字段顺序，但不改变要素多重集。 |
| F09 副作用、原子性与输入保护 | 所有输入不变；任一输入不兼容时整次失败，不生成部分 target；target 已存在即失败。 |
| F10 破坏性等级与确认门 | R1；`confirm=true`。 |
| F11 失败与 NOT_SUPPORTED | inputs 少于 2 个 `INVALID_ARGUMENT`；几何/维数不一致 `DIMENSION_MISMATCH`；schema 不严格兼容 `SCHEMA_MISMATCH`；CRS 不一致 `CRS_MISMATCH`；table/raster 输入在首批规范域内回 `NOT_SUPPORTED`（这是契约范围排除，不代表后端产品绝对无此能力）；SuperMap 注册表仍 `unverified` 时回 `UNVERIFIED_MAPPING`。 |
| F12 后端落点与实现路线 | arcgis-pro：`arcpy.management.Merge`；qgis：`native:mergevectorlayers`；postgis：`merge_tables` template；supermap：B1 二轮确认以 `DatasetVector.append` 逐个追加到新建 target 的实现路径（类级坐实），不是把 V13 的既有目标语义混入本动词。 |
| F13 跨后端语义等价判据 | 同组 inputs：输出要素多重集等于各输入多重集的不交并；总数、schema、CRS、几何维数一致；不得多/少要素，不得去重，不得改变属性值。源摘要逐一不变。 |
| F14 证据状态快照 | tier 全叶 core。注册表 status：arcgis-pro/qgis/postgis `ok`，supermap `unverified`。B1 二轮覆盖注记：SuperMap 合并实现路径类级坐实且要求 schema 兼容；仍待写工具与实机校准。 |

## B.05 V14 `gis_assign_projection`

| 字段 | 草稿 |
|---|---|
| F01 身份与范围 | core；后端：arcgis-pro、qgis、postgis、supermap。适用于已有空间元数据的 vector/raster；普通 table 不适用。 |
| F02 一句话语义与非目标 | 只给输出数据集赋予/覆写 CRS 元数据，坐标数值、像元值与属性均不改变；它**不是**重投影。回包必须 `metadata_only=true`。 |
| F03 输入签名 | 契约目标签名：`backend`（必填）；`dataset`（必填）；`target`（必填，须不存在；现行签名缺此项，属待对齐）；`srid`（integer，必填，须可解析到确定 CRS）；`confirm`（必填 true）。首批不支持用本动词“清除 CRS”；清除/置未知需另立语义，见 C13。 |
| F04 输入对象与几何维数 | vector/raster 均可；几何基类型、坐标维数、栅格行列/像元大小数值均不变。table 回 `NOT_SUPPORTED`。 |
| F05 输出签名与后置条件 | 输出 target 的 CRS 等于指定 CRS；坐标摘要/坐标序列与源逐值一致；范围数值的数值部分不变（其地理解释可因 CRS 改变）；回包给 `crs_before`、`crs_after`、`coordinate_digest_before/after` 且两摘要必须相等。 |
| F06 CRS 与单位约定 | 本动词是唯一允许“只改解释、不改数值”的首批动词。不得顺带做 datum shift、轴序重排或单位换算。若源 CRS 已知且与目标 CRS 不同，这仍是合法的元数据覆写，但应在回包 `warnings` 中给出 `crs_metadata_overwritten=true`，提醒调用方这是高风险纠错/赋值而非变换。 |
| F07 属性 schema、ID 与空值 | schema、字段值、稳定键、要素数/像元值全不变。 |
| F08 容差与确定性 | 坐标逐值一致，不适用分析容差。后端若在写出时重排浮点文本但数值相对差 >1e-12，不算等价。 |
| F09 副作用、原子性与输入保护 | 规范形态 copy-on-write，源 dataset 不动。原生 Define Projection/Set SRID 等多为原地元数据改写，适配器必须先复制。 |
| F10 破坏性等级与确认门 | R2；`confirm=true`。理由：数值虽不变，错误赋值会静默改变全部坐标的地理解释。 |
| F11 失败与 NOT_SUPPORTED | `srid` 无法解析 `UNKNOWN_CRS`；table `NOT_SUPPORTED`；target 已存在 `ALREADY_EXISTS`；后端只能原地改且 adapter 无法提供 copy-on-write 时，不得伪装满足契约，应回 `NOT_SUPPORTED` 并注明路线缺失；SuperMap 注册表仍 `unverified` 时回 `UNVERIFIED_MAPPING`。 |
| F12 后端落点与实现路线 | arcgis-pro：`arcpy.management.DefineProjection`；qgis：`native:assignprojection`；postgis：`set_srid` template（UpdateGeometrySRID/ST_SetSRID 路线）；supermap：`PrjCoordSys` 数据集坐标系属性路线（B1 一轮类级坐实），均需 copy-on-write adapter。 |
| F13 跨后端语义等价判据 | 输出除 CRS 元数据外与源逻辑等价：坐标摘要、几何、schema、属性、栅格网格/值均一致；CRS 身份一致。任一后端若坐标数值变化，即判不等价并归为实现错误或误调 V15。 |
| F14 证据状态快照 | tier 全叶 core。注册表 status：arcgis-pro/qgis/postgis `ok`，supermap `unverified`。B1 一轮覆盖注记：SuperMap `PrjCoordSys` 等类齐全、类级坐实；仍待具体工具签名与实机校准。 |

## B.06 V15 `gis_reproject`

| 字段 | 草稿 |
|---|---|
| F01 身份与范围 | core；后端：arcgis-pro（vector/raster）、qgis（vector/raster）、postgis、supermap。变体轴 `kind ∈ {vector, raster, table}`，其中 table 明确不适用。 |
| F02 一句话语义与非目标 | 把源数据集的坐标从源 CRS 数学变换到目标 CRS，并写入新数据集；不是只改元数据。属性与逻辑要素身份保持，坐标值通常改变。 |
| F03 输入签名 | `backend`（必填）；`input`（必填）；`target`（必填）；`target_srid`（integer，必填，须可解析）；`kind`（enum，必填，须与输入对象一致）；`resampling`（enum，raster 条件必填规则见 F06，vector 必须缺失）；`overwrite`（bool，可选，默认 false）；`confirm`（必填 true）；overwrite=true 时另须 `target_echo`、`preflight_id`。 |
| F04 输入对象与几何维数 | vector 保留基类型；坐标维数目标为同维数，Z/M 保留规则见 F06。raster 保持波段数，行列/像元大小可因变换改变。table 回 `NOT_SUPPORTED`。 |
| F05 输出签名与后置条件 | 默认 target 须不存在且不得等于 input。输出 CRS 为目标 CRS；要素数与源一致（不因变换删除要素）；raster 输出给新网格、NoData 与 resampling。overwrite=true 时才允许 target 与既有对象相同/覆盖，并须在回包标 `input_overwritten=true`。 |
| F06 CRS 与单位约定 | 源 CRS 未知回 `UNKNOWN_CRS`。必须记录实际采用的坐标操作/基准变换标识（若后端可提供）；同一源/目标 CRS 有多个候选变换且结果差超过 A.2.8 时，不得各按原生默认静默选择，应回 `CRS_MISMATCH` 并在 details 中列候选，待显式变换参数定版。Z 只有在垂直基准明确时变换，否则原值保留并 warning `z_transform_not_applied`；M 原样保留。raster 的 `resampling` 对分类栅格默认 `nearest`；连续栅格无跨后端默认，缺失时 `INVALID_ARGUMENT`，见 C12。 |
| F07 属性 schema、ID 与空值 | 属性 schema 与值不变；稳定键保留；生成 ID 可重编。不得因后端格式限制静默截断字段名或改类型。 |
| F08 容差与确定性 | 以独立参考变换或控制点判等：规范化到目标 CRS 后，坐标差按 A.2.8；栅格按 A.2.8 且必须报告重采样/网格差异。不得使用源 CRS 的角度值直接做欧氏比较。 |
| F09 副作用、原子性与输入保护 | 默认输入不变、target 全有全无。overwrite=true 是显式例外，失败时状态可能已改变，adapter 必须在预检中给出可恢复性；无法保证时不得承诺原子性，回包/错误须如实标状态。 |
| F10 破坏性等级与确认门 | 基础 R1；`overwrite=true` 动态升 R3，三件套齐全才可执行。 |
| F11 失败与 NOT_SUPPORTED | table 变体全后端 `NOT_SUPPORTED`；源 CRS 未知 `UNKNOWN_CRS`；目标 CRS 无法解析 `UNKNOWN_CRS`；kind 与对象不符 `INVALID_ARGUMENT`；无法保留 Z/M `DIMENSION_MISMATCH`；SuperMap 注册表仍 `unverified` 时回 `UNVERIFIED_MAPPING`。 |
| F12 后端落点与实现路线 | arcgis-pro：vector `arcpy.management.Project`、raster `arcpy.management.ProjectRaster`；qgis：vector `native:reprojectlayer`、raster `gdal:warpreproject`；postgis：`transform_create` template；supermap：`CoordSysTranslator` 类方法路线（B1 一轮类级坐实）。 |
| F13 跨后端语义等价判据 | 同源/同目标 CRS：输出 CRS 身份一致；要素对应关系与属性一致；用一组覆盖范围、边界与高程/量测维的控制几何回代到源 CRS 后满足容差；栅格的类别值不得因默认重采样改变。 |
| F14 证据状态快照 | tier 全叶 core。status：arcgis-pro vector/raster `ok`、table `not_supported`；qgis 同；postgis `ok`；supermap `unverified`。B1 一轮覆盖注记：SuperMap 坐标转换类级坐实；具体签名待 Help 与实机校准。 |

## B.07 V18 `gis_buffer`

| 字段 | 草稿 |
|---|---|
| F01 身份与范围 | core；后端：arcgis-pro、qgis、supermap、postgis。仅 vector 输入；输出 polygon/multipolygon 缓冲结果。 |
| F02 一句话语义与非目标 | 生成与源几何距离不超过指定缓冲距离的区域；不做邻近查询、不筛选源要素、不把缓冲区与源要素做 overlay 身份赋值。 |
| F03 输入签名 | `backend`（必填）；`input`（必填）；`target`（必填，须不存在）；`distance`（number，与 `distance_field` 二选一）；`distance_field`（string，与 `distance` 二选一）；`unit`（enum `{m, km}`，可选；规则见 F06）；`dissolve`（bool，可选，默认 false）；`confirm`（必填 true）。首批不暴露 side/end/join/segments 的后端私有参数；其规范默认写在 F08。 |
| F04 输入对象与几何维数 | Point/MultiPoint/LineString/MultiLineString/Polygon/MultiPolygon 均可，输入坐标维数可为 2D/Z/M/ZM。缓冲在水平面计算；Z 不参与距离，输出 Z/M 不作可移植语义（若后端保留须 warning）。 |
| F05 输出签名与后置条件 | dissolve=false 时每个源要素恰产生一个输出要素（可为 MultiPolygon），并保留源属性与源顺序逻辑关系；dissolve=true 时输出一个合并几何或按后端对象形态输出一个 MultiPolygon 要素，源属性不保留（除非另有分组字段，而首批签名无分组参数）。回包给解析后的 `distance_m` 或字段名、方法（planar/geodesic）与要素数。 |
| F06 CRS 与单位约定 | `distance` 的数值按 `unit` 解释，未给 unit 时：投影 CRS 用 CRS 线性单位换算为米，地理 CRS 必须显式 `unit` 且采用 geodesic。`distance_field` 的每行值同理；字段值为空/非数值即整次失败，不跳过该要素。未知 CRS 回 `UNKNOWN_CRS`。 |
| F07 属性 schema、ID 与空值 | dissolve=false 时源 schema 全保留；不得把距离字段自动删改。dissolve=true 时输出 schema 的可移植部分为空属性集，后端自动生成的 ID 不属于语义。 |
| F08 容差与确定性 | 规范端部/连接均为 round；每四分之一圆弧段数规范目标为 8，后端不能精确控制时可在 A.2.8 Hausdorff 容差内等价。负距离只允许 Polygon/MultiPolygon，点/线负缓冲回 `INVALID_ARGUMENT`；零距离对面要素按几何本身处理，对点/线产生空或退化结果的跨后端一致性留 G2，不在本草稿中伪造统一结果。 |
| F09 副作用、原子性与输入保护 | 输入不变；target 全有全无；distance_field 任一行非法时整次失败，避免部分要素静默缺失。 |
| F10 破坏性等级与确认门 | R1；`confirm=true`。 |
| F11 失败与 NOT_SUPPORTED | distance 与 distance_field 同传或均缺失 `INVALID_ARGUMENT`；单位/CRS 组合无法确定量测方法 `UNKNOWN_CRS` 或 `INVALID_ARGUMENT`；无效几何 `GEOMETRY_INVALID`；后端只能用度数平面缓冲地理坐标且无 geodesic 路线时 `NOT_SUPPORTED`，不能以错误量纲报成功。 |
| F12 后端落点与实现路线 | arcgis-pro：`arcpy.analysis.Buffer`；qgis：`native:buffer`；supermap：`supermap_create_buffer` native（桥侧 pending）；postgis：`buffer_create` template（ST_Buffer）。 |
| F13 跨后端语义等价判据 | 同输入/同距离解析：输出几何满足 A.2.8；任取源几何与输出边界的距离抽检不超过容差；dissolve=false 的要素对应与属性一致；dissolve=true 只比较合并后几何总形与总面积，不比较后端内部切分。 |
| F14 证据状态快照 | tier 全叶 core，四后端注册表 status 均为 `ok`；supermap 叶 `bts=pending`，表示桥侧执行工具待实现，不等于已实机验证。 |

## B.08 V19 `gis_clip`

| 字段 | 草稿 |
|---|---|
| F01 身份与范围 | core；后端：arcgis-pro、qgis、supermap、postgis。变体轴 `input_type ∈ {vector, raster}`；裁剪边界来自 `clip_by` 数据集，不在本动词内接受裸坐标串。 |
| F02 一句话语义与非目标 | 输出源数据与裁剪范围在空间上重叠的那部分；矢量保留源属性，栅格保留源值并把范围外置 NoData。它不是 overlay intersect：不合并裁剪层属性，不做身份/归属赋值。 |
| F03 输入签名 | `backend`（必填）；`input`（必填）；`clip_by`（必填，dataset 引用）；`target`（必填，须不存在）；`input_type`（enum，必填，须与 input 一致）；`confirm`（必填 true）。当前签名无 bbox 变体，见 C08。 |
| F04 输入对象与几何维数 | vector：任意基类型，维数保留；clip_by 须为 Polygon/MultiPolygon（若为其他几何，先由调用方构造范围，不在本动词内隐式缓冲/外包）。raster：任意波段；clip_by 同上。 |
| F05 输出签名与后置条件 | vector 输出只含与 clip_by 相交的源几何部分，源属性不变，可为空集成功。raster 输出保持源像元大小、原点对齐、波段与 NoData 定义，范围外为 NoData；输出行列可收紧到 clip_by 范围与源网格交集，但不得重采样。回包给输入/输出计数或网格摘要。 |
| F06 CRS 与单位约定 | input 与 clip_by 的 CRS 必须一致；不一致 `CRS_MISMATCH`，不隐式变换。未知 CRS `UNKNOWN_CRS`。本动词不做距离量测。 |
| F07 属性 schema、ID 与空值 | vector 输出 schema 精确等于源 schema；clip_by 属性不进入输出。raster 值与 NoData 不改。稳定键保留；被切分要素可产生多个输出要素，生成 ID 可重编，源要素追溯不作为首批语义。 |
| F08 容差与确定性 | 不做简化、吸附或几何修复。边界恰压线/点接触按 OGC 相交语义处理；G2 须包含贴边、相切、完全包含、完全不交四类样本。 |
| F09 副作用、原子性与输入保护 | input/clip_by 均不变；target 全有全无。 |
| F10 破坏性等级与确认门 | R1；`confirm=true`。 |
| F11 失败与 NOT_SUPPORTED | input_type 与对象不符 `INVALID_ARGUMENT`；clip_by 非面几何 `INVALID_ARGUMENT`；CRS 问题按 F06；无效裁剪几何 `GEOMETRY_INVALID`；某后端变体在注册表中无路线时 `NOT_SUPPORTED`，不得以 overlay 组合静默冒名（若未来采用组合路线，必须改标 gateway_synthesis 并过 G2）。 |
| F12 后端落点与实现路线 | arcgis-pro：vector `arcpy.analysis.Clip`、raster `arcpy.sa.ExtractByMask`；qgis：vector `qgis:clip`、raster `gdal:cliprasterbymasklayer`；supermap：vector `supermap_overlay_clip`、raster `supermap_clip_raster`（桥侧 pending）；postgis：vector `clip_vector`、raster `clip_raster` templates。 |
| F13 跨后端语义等价判据 | vector：输出几何等于源几何与 clip_by 并集范围的交，属性多重集按切分后的几何-属性配对比较；raster：网格对齐与像元值/NoData 逐项比较。完全不交时各后端均为空成功而非错误。 |
| F14 证据状态快照 | tier 全叶 core，八叶注册表 status 均为 `ok`；supermap 两叶 `bts=pending`。状态不因本契约改变。 |

## B.09 V20 `gis_overlay`

| 字段 | 草稿 |
|---|---|
| F01 身份与范围 | core；一个统一动词，变体轴 `operation ∈ {intersect, union, difference, erase, identity, symdifference, update}`。后端：arcgis-pro、qgis、supermap、postgis。首批核心等价域为 Polygon/MultiPolygon × Polygon/MultiPolygon；其他几何组合不宣称 core 等价。 |
| F02 一句话语义与非目标 | 按 operation 对 input 与 overlay 两组面几何做集合运算并组合属性，输出新数据集；不是 clip（clip 不带 overlay 属性），不是 dissolve（不按属性消边），不是 spatial_join（join 不切分几何）。 |
| F03 输入签名 | `backend`（必填）；`input`（必填）；`overlay`（必填）；`target`（必填，须不存在）；`operation`（enum，必填，无默认）；`confirm`（必填 true）。 |
| F04 输入对象与几何维数 | 首批核心域：两输入均为 Polygon/MultiPolygon，坐标维数相同且均为 2D 或同为 Z/M/ZM 并能被后端无损保留。线/点参与的 intersect 等组合属于后端扩展面，须另立变体契约后才可宣称等价。 |
| F05 输出签名与后置条件 | 设 A=input、B=overlay：`intersect=A∩B`；`union=A∪B`（含 A-only、B-only、A∩B 分区）；`difference=A\B`；`erase=A\B`（与 difference **同义别名**，不是第八种运算）；`identity=(A∩B)∪(A\B)`；`symdifference=(A\B)∪(B\A)`；`update=(A\B)∪B`。输出可为空集成功；几何可因切分成为 MultiPolygon/GeometryCollection 的规范化集合，G2 按几何集合判等而非逐要素外形编号。 |
| F06 CRS 与单位约定 | 两输入 CRS 必须完全一致且已知；不一致 `CRS_MISMATCH`，未知 `UNKNOWN_CRS`，不隐式重投影。面积只作为判等指标，不改变运算语义。 |
| F07 属性 schema、ID 与空值 | 输出字段规则按 operation：intersect/identity 的重叠区带 A+B 属性，identity 的 A-only 区 B 字段为 null；union 的 A-only/B-only/重叠区分别按来源带属性，缺失侧为 null；difference/erase 只带 A 属性；symdifference 的 A-only 带 A 属性、B 字段 null，B-only 反之；update 的重叠区以 B 的几何与 B 属性为准、A-only 带 A 属性。字段同名冲突时，非同源同名字段在输出中以 `a_<name>` / `b_<name>` 确定性改名，禁止静默覆盖或丢弃；同名字段若是双方稳定键且类型一致，可保留一份并在回包注明。生成 ID 可重编。 |
| F08 容差与确定性 | 不自动修复无效几何、不吸附、不简化。几何集合按 A.2.8 比较；拓扑分区必须满足：各分区互不重叠（容差内）、分区并集等于公式结果。XY 容差/分辨率的后端默认值不得带入；adapter 须显式设置到契约容差或披露无法设置。 |
| F09 副作用、原子性与输入保护 | 两输入不变；target 全有全无。任一输入无效导致整次失败，不输出部分分区。 |
| F10 破坏性等级与确认门 | R1；`confirm=true`。operation 不改变基础等级；target 与任一输入相同视为 `INVALID_ARGUMENT`，本动词不提供 overwrite 通道。 |
| F11 失败与 NOT_SUPPORTED | operation 缺失/越界 `INVALID_ARGUMENT`；非面核心域 `NOT_SUPPORTED`（契约范围排除）；无效几何 `GEOMETRY_INVALID`；某后端/operation 当前无可用路线时 `NOT_SUPPORTED`；注册表落点未验时 `UNVERIFIED_MAPPING`。**网关合成不是原生冒名**：identity/update 在 QGIS/PostGIS 的目标路线若采用 D2 合成，必须在 F12 标 `gateway_synthesis`，在实现与 G2 通过前仍按当前 status 返回，不提前报可用。 |
| F12 后端落点与实现路线 | arcgis-pro：七式均为 `gp_named` 原生（difference 与 erase 同调 `arcpy.analysis.Erase`）。qgis：intersect `qgis:intersection`、union `qgis:union`、difference/erase `qgis:difference`、symdifference `qgis:symmetricaldifference`；identity/update 当前无原生，目标路线 `gateway_synthesis`。postgis：intersect/union/difference/erase/symdifference 为 templates（ST_Intersection/ST_Union/ST_Difference/ST_SymDifference）；identity/update 当前无单函数，目标路线 `gateway_synthesis`。supermap：原生 overlay 路线；B1 定级为 intersect/union/erase/identity/update 函数坐实，symdifference 原生名 **`xor`**，difference 无独立 OverlayMode、与 erase 同义合并。 |
| F13 跨后端语义等价判据 | 同 A/B 与 operation：先按 F05 集合公式验几何并集与分区拓扑，再按来源分区验属性规则；总面积、各来源分区面积、空/非空模式须一致。difference 与 erase 在每个后端都必须给出相同逻辑结果；symdifference 不得因 SuperMap 原生名 xor 而被当作不同运算。 |
| F14 证据状态快照 | tier 28 叶全 core。注册表 status：arcgis-pro 七式 `ok`；qgis 五式 `ok`、identity/update `not_supported`；postgis 五式 `ok`、identity/update `not_supported`；supermap 七式 `unverified`。B1 两轮覆盖注记给出 SuperMap 函数/枚举定级，但不把注册表 status 升格；QGIS/PostGIS identity/update 的合成路线来自 v0.3 裁决，尚未实现/校准。 |

## B.10 V22 `gis_spatial_join`

| 字段 | 草稿 |
|---|---|
| F01 身份与范围 | core；后端：arcgis-pro、qgis、postgis、supermap。input 与 join 均为 vector；输出为带 join 属性的新数据集，input 几何不被切分。 |
| F02 一句话语义与非目标 | 对每个 input 要素，按空间谓词寻找 join 要素，并按明确的匹配/汇总规则把 join 属性写入输出；不是 overlay（不切分几何），不是属性表 join（必须有空间谓词），不是 nearest 搜索服务本身。 |
| F03 输入签名 | `backend`（必填）；`input`（必填）；`join`（必填）；`target`（必填，须不存在）；`predicate`（enum `{intersects, contains, within, nearest}`，必填，无默认）；`summary`（enum，必填，无默认；首批规范值 `{first, all}`，`aggregate` 因现行签名缺统计规格暂回 `NOT_SUPPORTED`，见 C11）；`confirm`（必填 true）。谓词方向固定为“input 几何 OP join 几何”。 |
| F04 输入对象与几何维数 | 两输入可为任意 vector 基类型，但坐标维数须一致；contains/within 对明显不可能的维数组合可产生空匹配，不自动判错。nearest 的距离在共同 CRS 下计算。 |
| F05 输出签名与后置条件 | summary=first：每个 input 恰输出一行，匹配者带所选 join 属性，未匹配者 join 属性为 null，并回包 matched/unmatched 计数。summary=all：每个匹配对输出一行，未匹配 input 输出一行 null join 属性。输出几何恒等于 input 几何。回包给多匹配计数与所用 tie-break 规则。 |
| F06 CRS 与单位约定 | 两输入 CRS 必须一致且已知；不隐式变换。nearest 的距离按 CRS 类型采用平面/测地方法并在回包注明；距离相同候选不得按后端遍历顺序随机选取。 |
| F07 属性 schema、ID 与空值 | 输出 schema = input schema + join 属性（不含 join 几何）。同名字段冲突时，join 侧字段确定性改名为 `join_<name>`；input 字段不改名。input 稳定键保留。summary=first 的候选选择规则：先按谓词成立，再按重叠面积/长度或 nearest 距离排序，最后按 join 侧稳定键的规范化字符串升序裁决；join 侧无稳定键且出现并列时回 `SCHEMA_MISMATCH` 并说明无法确定性选择，不能静默取“第一条”。 |
| F08 容差与确定性 | 谓词按 OGC 语义与 A.2.8 容差判定；边界接触是否算 intersects 按 OGC 原义为真。不得用 bbox 粗筛结果直接作为最终谓词；粗筛只可作性能预过滤，最终须做精确几何判定。 |
| F09 副作用、原子性与输入保护 | 两输入不变；target 全有全无。匹配统计与实际写入行数必须一致，否则整次失败。 |
| F10 破坏性等级与确认门 | R1；`confirm=true`。 |
| F11 失败与 NOT_SUPPORTED | predicate/summary 缺失或越界 `INVALID_ARGUMENT`；summary=aggregate 在统计规格未定版前 `NOT_SUPPORTED`；postgis 的 nearest 当前无模板回 `NOT_SUPPORTED`；supermap 当前注册表为 `not_supported`，目标虽为网关合成，未实现/未校准前仍回 `NOT_SUPPORTED`；其他后端映射未验按 `UNVERIFIED_MAPPING`。 |
| F12 后端落点与实现路线 | arcgis-pro：`arcpy.analysis.SpatialJoin` native/gp_named；qgis：`native:joinattributesbylocation`；postgis：`spatial_join` template（intersects/contains/within），nearest 无模板；supermap：**网关合成**（空间查询候选＋属性回填），B1 二轮已定性无原生空间连接函数，`JoinItem/QueryParameter.join_items` 仅属性连接，不得冒充空间连接原生实现。 |
| F13 跨后端语义等价判据 | 同两输入/同谓词/同 summary：输出行多重集、每行 input 几何与属性、所选/全部 join 属性、matched/unmatched/multi-match 计数一致。summary=first 的并列样本必须验证各后端选择同一 join 候选；若某后端无法实现确定性 tie-break，即判不等价。 |
| F14 证据状态快照 | tier 全叶 core。注册表 status：arcgis-pro `ok`；qgis `ok`；postgis intersects/contains/within `ok`、nearest `not_supported`；supermap `not_supported`。B1 二轮覆盖注记：SuperMap 无原生空间连接、转网关合成；该路线尚在批 1，不改变当前 status。 |

---

# C. 待定问题清单（全部待 Muse 复核）

> 推荐默认均按 R1/R2 与通用化方向给出：能显式就不用原生默认，能拒绝静默降级就不兼容凑合。标注“待 Muse 复核”表示本草稿不自行定版。

| # | 含混点 | 影响动词 | 推荐默认（待 Muse 复核） |
|---:|---|---|---|
| C01 | 现行 `verbs.json` 中 V06/V07/V14 等含原地改写语义，与 G1 的 copy-on-write 总则冲突；契约目标签名需新增 `target`，属接口变更而非单纯文档补充。 | V06、V07、V14（并及未来 V13） | 采用契约优先：定版时同步改签名与回包 `input_unchanged=true`；旧原地形态只可作为 adapter 内部步骤，外部不可见。**待 Muse 复核。** |
| C02 | CRS 身份现行只传 `srid` 整数，无法表达 authority 版本、自定义 CRS、WKT2、基准集合差异；同码不同定义会被误判一致。 | 全部空间动词，尤 V14/V15 | G1 定版引入 `crs` 对象（authority/code/version/wkt 可选）并保留 `srid` 兼容简写；等价判据以 CRS 对象为准。**待 Muse 复核。** |
| C03 | V05 的 raster 变体缺 extent、像元大小、行列、波段数、数据类型、NoData 等必要参数，现行签名只能建“容器壳”，无法声称完整创建语义。 | V05 | 增加 `raster_spec` 后再开放 raster 等价域；在此之前契约与 discover 均把 raster 标为“容器级、规范未完备”，不纳入 G2 通过面。**待 Muse 复核。** |
| C04 | 字段类型在各后端的长度、精度、默认值、nullable、alias、domain、index 支持差异大；静默丢约束会造成“同名不同义”。 | V05、V06、V07、V12 | 先定统一 FieldSpec 最小子集与逐项保真矩阵；后端不能保真的属性直接 `NOT_SUPPORTED`，不静默丢弃。**待 Muse 复核。** |
| C05 | V12 对异构 schema 的行业常见做法差异大：有的补 null、有的字段并集、有的要求全同；现行签名又无 `field_map`。 | V12（并及未来 V13） | 首版坚持严格同构；异构合并另加显式 `field_map` 与 null 填充规则后再开放，不把原生宽松行为当默认。**待 Muse 复核。** |
| C06 | merge/append 后是否生成来源追溯字段、稳定键冲突如何处理，各后端并不一致；自动加 provenance 字段也会改变 schema。 | V12（并及未来 V13） | 默认不虚构新字段；把“是否加 `__source_dataset/__source_id`”做成未来显式选项。稳定键只保留不保证唯一，重复不自动去重。**待 Muse 复核。** |
| C07 | buffer 的负距离、零距离退化、弧段数、端头/连接样式、地理 CRS 下 planar/geodesic 方法在各后端默认不同。 | V18 | 契约固定 round/round、每四分之一圆 8 段、地理 CRS 必须 geodesic；负距离只许面；零距离退化样本先入 G2 实测再决定是否收紧。**待 Muse 复核。** |
| C08 | V19 现行签名只有 dataset 型 `clip_by`，没有 bbox/几何字面量变体；raster 裁剪是否保持原网格还是收紧/重对齐，各工具默认也可能不同。 | V19 | 首版只认 dataset 边界且 raster 不重采样、只收紧到同网格交集；bbox 作为新变体另立参数与契约，不从 `clip_by` 字符串暗中解析。**待 Muse 复核。** |
| C09 | overlay 对点/线、多部件、GeometryCollection、无效几何与字段冲突的行业行为差异最大；只写“七式同名”不足以保证同义。 | V20 | 首版 core 等价域只收 Polygon/MultiPolygon；不自动修复；字段冲突用 `a_/b_` 确定性改名。其他几何组合逐式另立扩展契约。**待 Muse 复核。** |
| C10 | v0.2 `verbs.json` 对 V20 的旧口径称“缺式回 NOT_SUPPORTED、不许组合冒名替代”，而 v0.3 裁决 D2 又要求 identity/update 走网关合成，两者若不分开标注会互相矛盾。 | V20、V22 | 明确区分 `native` 与 `gateway_synthesis`：合成是网关正式实现路线，不是原生冒名；但在实现＋G2 通过前，证据 status 仍为 `not_supported/unverified`，调用仍按现状态返回。**待 Muse 复核。** |
| C11 | V22 的 `summary` 现行只是 string，无枚举、无基数/聚合规格；ArcGIS 的 one-to-one/one-to-many、QGIS 的 join type、PostGIS SQL 行生成规则并不天然一致，nearest 与并列候选更不一致。 | V22 | 定版时把 `summary` 收紧为枚举并要求显式传值；首版只开放 first/all，aggregate 等统计规格补齐后再开；tie-break 必须确定性，无稳定键且并列时失败。**待 Muse 复核。** |
| C12 | V15 的基准变换候选选择与 raster resampling 默认高度后端相关：同一 EPSG 变换可能有多条坐标操作，连续栅格用 nearest/bilinear/cubic 的结果也不同。 | V15 | 坐标操作必须可记录；多候选且差异超容差时不静默选默认，要求显式 transform 参数。resampling 对分类栅格默认 nearest，连续栅格必填，不继承后端默认。**待 Muse 复核。** |
| C13 | V14 只能赋一个 `srid`，无法表达“清除 CRS/置为未知”、本地工程 CRS 或仅有 WKT 的 CRS；把 0 当未知又会与合法本地标识混淆。 | V14、V05 | 增加显式 `crs` 对象与独立的 unassign 语义，不用 0/null 暗语；WKT 必须带摘要校验。**待 Muse 复核。** |
| C14 | Z/M 在 merge、overlay、reproject、buffer 中常被后端降维、复制或插值，注册表没有逐动词的维数保留矩阵。 | V12、V15、V18、V20、V22 | G1 定版前补一张“动词×后端×Z/M 行为”矩阵；不能无损保留时默认失败，不把降维结果标为等价。**待 Muse 复核。** |
| C15 | 数据集/字段名长度、保留字、大小写折叠、schema/工作空间限定方式跨后端不同，可能在 confirm 后才由后端报错，甚至被静默改名。 | 全部带 target/field 的动词 | 在网关入口做统一命名预检并把后端限制作为能力矩阵公开；执行前失败，不允许静默改名或截断。**待 Muse 复核。** |

## 草稿边界

- 本文件只完成 G1 第一批 10 个动词，不声称 40 动词契约集完成。
- 本文件中的规范目标与现行实现不一致处，已尽量在 F09/F12 或 C 部分显式标出；后续应由 G1 定版、G2 一致性测试与实现对齐共同处理，不能只改文档就算完成。
- B1 对账只改变证据覆盖注记，不改变本文 F14 所引注册表 status；后续注册表刷新须另走账目流程。

—— Muse 子代理草稿，2026-11-03
