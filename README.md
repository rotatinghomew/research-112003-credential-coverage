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

## 检查资料

使用 Python 3.11 和标准库。在项目根目录运行：

```sh
python3 -m unittest discover -s tests -v
```

这项检查核对资料格式与引用，不生成业务结论。
