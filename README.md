# 宣传资质证据覆盖口径与抽查修订

各表为本地合成业务记录，身份与机构代号不对应真实对象。

## 资料格式

资料为 UTF-8 编码、首行为列名的 CSV。空字段表示没有记录，不表示零。连续日号采用同一份内部日历。

| 文件 | 列 | 登记口径 |
| --- | --- | --- |
| `shows.csv` | `show`、`channel`、`category`、`day`、`minutes`、`host` | 单场分钟总长，category 是声明类别，不代表资质等级。 |
| `segments.csv` | `segment`、`show`、`start`、`end`、`candidates`、`known`、`ref`、`state` | 分段的候选出镜人用 &#124; 分隔；同一原分段的更正不额外增加时长。 |
| `policy.csv` | `id`、`channel`、`category`、`start`、`end`、`evidence_kind` | 适用采用左闭右开日期；每个展示类别按渠道定义材料类型。 |
| `credentials.csv` | `doc`、`person`、`kind`、`channel`、`category`、`start`、`end`、`known`、`state`、`replaces` | 可追溯生效由 start 表示，known 为实际获知日期；unsupported 为明确不支持；replaces 指被订正的回执。 |
| `requests.csv` | `request`、`segment`、`doc_hint`、`requested`、`owner`、`state` | 同一凭据可服务多个复核请求，doc_hint 只是希望取得的材料代号。 |
| `reports.csv` | `report`、`asof`、`from_day`、`to_day`、`kind` | 历史考核与现时材料回看的日期边界。 |
| `comparisons.csv` | `comparison`、`asof`、`base_start`、`base_stop`、`test_start`、`test_stop`、`mode`、`min_improvement` | 比较用日号上下端点均含，selected 指采用 reference 表约定构成；最后一列是月会上认定实质改善的最低百分点。 |
| `reference.csv` | `channel`、`category`、`slot`、`target_share` | 会前约定的展示分钟构成；没有对应事实的格不能当作零证据分钟。 |
| `show_slots.csv` | `show`、`slot` | 展示的运营时段。 |
| `verification_options.csv` | `request`、`source`、`relates`、`cost`、`known`、`available_before` | 待获得的材料候选，relates 是可能涉及的登记对象，不宣称必有正面证据；成本单位为查档工时。 |
| `verification_budget.csv` | `week`、`source`、`hours`、`already_assigned` | 各资料源的工时额度及已预约的请求。 |

## 检查资料

使用 Python 3.11 和标准库。在项目根目录运行：

```sh
python3 -m unittest discover -s tests -v
```

`tests/test_sources.py` 核对资料格式与引用，不生成业务结论；`tests/test_coverage.py`
锁定核验引擎的业务口径（三桶、口径切换、撤回与更正链、联合身份枚举等）。

## 核验引擎与月会报告

- `analysis/coverage_engine.py`：按 asof 时点装载材料，实施主体/类别/渠道/有效期
  四维匹配、左闭右开口径、replaces 更正链与分段撤回链，输出 covered / unsupported /
  pending 三桶，以及分钟口径与独立出镜人口径两套汇总。
- `analysis/build_report.py`：生成月会报告 `analysis/report.md`（同时打印到标准输出）。
  数据目录与脚本目录分离，运行使用隔离模式：

```sh
python3 -I analysis/build_report.py
python3 -I -m unittest discover -s tests -v
```

历史考核（m1，asof=21）按当次口径与材料找回；现时回看（m2，asof=26）不覆盖历史结论。
两期比较（v1/v2）只在相同渠道 × 声称类别 × 时段的可判定格内进行，口径切换、结构缺格
与证据订正效应单列，不以两次覆盖率相减充当改善。
