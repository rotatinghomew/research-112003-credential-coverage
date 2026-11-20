"""生成月会核验报告（Markdown），同时打印到标准输出并写入 analysis/report.md。"""
from __future__ import annotations

import itertools
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from coverage_engine import Engine, load

OUT = Path(__file__).resolve().parent / "report.md"


def pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def minute_table(eng: Engine, verdicts: list[dict]) -> list[str]:
    agg = eng.bucket_minutes(verdicts)
    total = sum(agg.values())
    lines = ["| 桶 | 分钟 | 占比 |", "| --- | ---: | ---: |"]
    for key, name in (("covered", "有唯一适用证据"),
                      ("unsupported", "明确不支持"),
                      ("pending", "资料待核·不可判")):
        share = agg[key] / total if total else 0
        lines.append(f"| {name} | {agg[key]} | {pct(share)} |")
    lines.append(f"| **合计** | **{total}** | 100% |")
    return lines


def cell_lines(eng: Engine, verdicts: list[dict]) -> list[str]:
    rates = eng.decidable_rates(verdicts)
    persons = eng.cell_person_view(verdicts)
    lines = ["| 渠道 | 声称类别 | 时段 | 展示分钟 | 可判定覆盖率（分钟口径） | 确认覆盖出镜人 | 确认缺口出镜人 | 同人分段混合 | 仅候选未决 |",
             "| --- | --- | --- | ---: | --- | --- | --- | --- | --- |"]
    for cell, items in sorted(eng.cells(verdicts).items()):
        channel, category, slot = cell
        mins = sum(v["minutes"] for v in items)
        r = rates[cell]
        rate = ("无可判定分钟" if r is None
                else f"{pct(r['rate'])}（{r['covered']}/{r['decidable']}，另"
                      f"{r['all_minutes'] - r['decidable']}分钟不可判）")
        p = persons[cell]
        lines.append(
            f"| {channel} | {category} | {slot} | {mins} | {rate} | "
            f"{','.join(p['covered']) or '—'} | {','.join(p['gap']) or '—'} | "
            f"{','.join(p['mixed']) or '—'} | {','.join(p['unresolved']) or '—'} |")
    return lines


def segment_appendix(eng: Engine, verdicts: list[dict], asof: int) -> list[str]:
    lines = [f"| 分段 | 展示(日) | 分钟 | 出镜关联 | 逐人适用结论（asof={asof}） | 分段桶 |",
             "| --- | --- | ---: | --- | --- | --- |"]
    for v in sorted(verdicts, key=lambda x: (x["show"].day, x["segment"].segment)):
        s, show = v["segment"], v["show"]
        who = "｜".join(s.candidates) + ("（确认）" if v["unique"] else "（未决）")
        detail = "；".join(f"{p}→{lab}" for p, lab in sorted(v["per_person"].items()))
        lines.append(f"| {s.segment} | {show.show}(d{show.day}) | {v['minutes']} | {who} | {detail} | {v['bucket']} |")
    return lines


def joint_identity_range(eng: Engine, verdicts: list[dict], cell: tuple) -> dict:
    """对指定格内所有未决分段枚举联合身份分配，给出覆盖分钟的可行区间。

    反复出镜人的候选在同一分配方案中须同时成立：同一候选人在各分段的取舍
    由一次联合枚举给出，不允许逐段各自挑最有利身份。
    """
    items = [v for v in verdicts if v["cell"] == cell and not v["unique"]]
    if not items:
        return {"schemes": 0}
    options = [v["segment"].candidates for v in items]
    results = []
    for combo in itertools.product(*options):
        covered = 0
        for v, person in zip(items, combo):
            lab = v["per_person"][person]
            if lab.startswith("covered"):
                covered += v["minutes"]
        results.append((combo, covered))
    return {
        "schemes": len(results),
        "min": min(r[1] for r in results),
        "max": max(r[1] for r in results),
        "max_scheme": max(results, key=lambda r: r[1])[0],
        "total_minutes": sum(v["minutes"] for v in items),
        "segments": [v["segment"] for v in items],
    }


def build() -> str:
    eng = Engine()
    cur_asof = max(s.known for s in eng.segments)  # 27：现时材料视角
    current = eng.evaluate_window(1, 31, cur_asof)

    # 历史考核与现时回看：m1 asof21 考核 d1-21；m2 asof26 用现时材料回看同一窗口
    m1 = eng.evaluate_window(1, 21, 21)
    m2 = eng.evaluate_window(1, 21, 26)

    comps = {r["comparison"]: r for r in load("comparisons")}
    v1, v2 = comps["v1"], comps["v2"]
    v1_base = eng.evaluate_window(i(v1["base_start"]), i(v1["base_stop"]), i(v1["asof"]))
    v1_test = eng.evaluate_window(i(v1["test_start"]), i(v1["test_stop"]), i(v1["asof"]))
    v2_base = eng.evaluate_window(i(v2["base_start"]), i(v2["base_stop"]), i(v2["asof"]))
    v2_test = eng.evaluate_window(i(v2["test_start"]), i(v2["test_stop"]), i(v2["asof"]))

    L: list[str] = []
    L.append("# 宣传资质证据覆盖核验报告（截至第 27 日材料）")
    L.append("")
    L.append("> 本报告只依据本地登记材料。凭据仅在主体、声称类别、展示渠道与有效期同时匹配时"
             "计为覆盖；mobile/guidance 口径在第 15 日由 local 切换为 association（左闭右开）。"
             "三桶分别统计：**有唯一适用证据 / 明确不支持 / 资料待核不可判**，后两者不合并为“未覆盖”。")
    L.append("")

    # 1. 现时材料总览
    L.append("## 1. 现时材料视角（d1–d27 全部展示，asof=27）")
    L.append("")
    L.extend(minute_table(eng, current))
    L.append("")
    unk = eng.unknown_attribution(current)
    total_min = sum(v["minutes"] for v in current)
    L.append(f"未知归属影响范围：{unk['uncertain_minutes']} 分钟（占全部 {total_min} 分钟的 "
             f"{pct(unk['uncertain_minutes'] / total_min)}），涉及候选身份 "
             f"{', '.join(unk['uncertain_candidates'])}。"
             "其中 g10（d11 适用 local 口径）两名候选均无有效凭据，属“身份未决但证据缺口确定”，"
             "不纳入无证据承诺的身份联想式排查。")
    L.append("")
    L.append("### 1.1 按渠道 × 声称类别 × 时段的双口径覆盖")
    L.append("")
    L.extend(cell_lines(eng, current))
    L.append("")
    L.append("说明：长场次（如 s5/g6 75 分钟）与重复出镜不改变分格结论；独立出镜人在同一格内"
             "只计一次，跨渠道不相加。s10/g13 与 s5/g6 同属 p2 的 web/guidance 覆盖，人户口径只记 p2 一人。")
    L.append("")
    L.append("### 1.2 分段逐人明细")
    L.append("")
    L.extend(segment_appendix(eng, current, cur_asof))
    L.append("")

    # 2. 历史考核
    L.append("## 2. 历史考核与现时回看（窗口均为 d1–d21）")
    L.append("")
    L.append("### 2.1 m1 历史考核（asof=21，按当时口径与材料）")
    L.append("")
    L.extend(minute_table(eng, m1))
    L.append("")
    L.append("要点：d6（第 25 日获知）与 d5（第 25 日获知）当时不可用；d2 仍为唯一适用且 "
             "**unsupported**，故 g3、g6 计“明确不支持”而非待核。g5 的 p1 确认关联当时仍生效，"
             "但其 local/mobile/guidance 凭据 d1 已于第 9 日到期，故 g5 为待核缺口而非覆盖。")
    L.append("")
    L.extend(cell_lines(eng, m1))
    L.append("")
    L.append("### 2.2 m2 现时材料回看同一窗口（asof=26，不覆盖 m1 结论）")
    L.append("")
    L.extend(minute_table(eng, m2))
    L.append("")
    L.append("变化解释：g3、g6 由 unsupported 转为 covered，唯一原因是 d6 于第 25 日到达并"
             "**可追溯订正** d2（覆盖区间 d1–d29）；这是材料获知时点效应，不是展示当时的改善。"
             "g5 原确认关联已被 g9 撤回、由 g10（p2|p3 未决）接管，仍不可判。m1 考核结论按当次"
             "口径与材料保留，m2 只作日常回看，不回写历史考核。")
    L.append("")
    L.extend(cell_lines(eng, m2))
    L.append("")

    # 3. 两期比较
    L.append("## 3. 两期比较（按会前 reference 构成，selected 模式）")
    L.append("")
    L.append("比较只在**相同渠道 × 声称类别 × 时段**且两侧均存在可判定展示的格内进行；"
             "缺同类节目或口径不可比的格列明原因，不以猜测补零。月会实质改善门槛：+5 个百分点。")
    L.append("")
    L.append("### 3.1 v1（asof=23：基期 d1–14 vs 测试期 d15–22）")
    L.append("")
    L.append(f"基期分钟三桶：{eng.bucket_minutes(v1_base)}；测试期三桶：{eng.bucket_minutes(v1_test)}")
    L.append("")
    L.append("- mobile/guidance/evening：**口径切换，不可直接比较**。基期 d7、d11 走 local 口径，"
             "g1 覆盖（15 分钟），g2（45 分钟）与 g10（40 分钟）未决；测试期 d20 的 g8 走 "
             "association 口径且未决，无任何可判定分钟。不做覆盖率相减。")
    L.append("- web/guidance/afternoon：两侧可判定，覆盖率基期 0%（g3 由 d2 明确 unsupported，12 分钟）"
             "→ 测试期 0%（g6 由 d2 明确 unsupported，75 分钟）。**差异 0 个百分点**，"
             "分钟量差异是渠道/节目结构，不是证据改善。")
    L.append("- mobile/consultation/afternoon（参考权重 10%）：仅测试期有 s6（g7 覆盖 10 分钟），"
             "基期无同类节目，**结构缺格，不参与比较**。")
    L.append("- web/consultation/evening：两侧均无节目。")
    L.append("- 结论：v1 无任何达到 +5pp 的实质改善。")
    L.append("")
    L.append("### 3.2 v2（asof=28 口径：基期 d1–14 vs 测试期 d15–28，实际材料截至 d27）")
    L.append("")
    L.append(f"基期分钟三桶：{eng.bucket_minutes(v2_base)}；测试期三桶：{eng.bucket_minutes(v2_test)}")
    L.append("")
    L.append("- mobile/guidance/evening：仍因第 15 日口径切换不可直接比较。测试期未决分段的联合身份"
             "枚举见 3.3；基期 local 段 g1 覆盖 15 分钟，g2（45 分钟）、g10（40 分钟）未决，保持不变。")
    L.append("- web/guidance/afternoon：基期 0%（d2 unsupported）→ 测试期 100%（g6 75 分钟由 d6 覆盖，"
             "g13 54 分钟由 d6 覆盖）。该格两侧覆盖率差为 +100pp，但**全部由 d6 替代 d2 的真实证据"
             "订正解释**（同一主体、同一渠道类别、可追溯生效），且 v1 同窗口当时判定为 0%→0%——"
             "属于材料获知/回执订正效应，按要求单列，不计作运营改善。")
    L.append("- mobile/consultation/afternoon：仅测试期存在（g7 覆盖），结构缺格，不参与比较。")
    L.append("- web/consultation/evening：基期 g4 覆盖（30 分钟，d3 可追溯生效且 d19 获知）；"
             "测试期 g12（p3，26 分钟）无 registry 凭据，为待核缺口，**测试期无可判定覆盖分钟**，"
             "不宣布下降也不猜结果，列入补证（见第 4 节 a4）。")
    L.append("- 结论：v2 不存在可归因于运营改善的 +5pp 变化；唯一的大幅变动是证据订正效应。")
    L.append("")

    # 3.3 联合身份枚举
    rng = joint_identity_range(eng, v2_test, ("mobile", "guidance", "evening"))
    L.append("### 3.3 测试期 mobile/guidance/evening 的联合身份可行性（association 口径）")
    L.append("")
    seg_ids = "、".join(v["segment"].segment for v in v2_test
                        if v["cell"] == ("mobile", "guidance", "evening") and not v["unique"])
    L.append(f"测试期未决分段 {seg_ids} 共 {rng['total_minutes']} 分钟，"
             f"对 {rng['schemes']} 种联合身份分配统一枚举（同一候选人在各分段同时成立，"
             "不逐段择优）：")
    L.append("")
    L.append(f"- 覆盖分钟可行区间：**{rng['min']} – {rng['max']} / {rng['total_minutes']} 分钟**；")
    L.append(f"- 上界方案 {rng['max_scheme']}：g8 取 p1 时无 association 凭据（p1、p3 在该口径下"
             "均无材料），g8 的 6 分钟在任何分配下都是确定缺口；g11 取 p2 时由 d5 覆盖 34 分钟，"
             "取 p1 则无覆盖；")
    L.append("- 基期另有 g10（p2|p3，40 分钟，d11）：当天适用 local 口径，两名候选在该口径下"
             "均无有效凭据（p1 的 d1 已于 d9 到期、p3 无任何材料），身份核实前不可判，"
             "但任何身份结果都不会产生覆盖；")
    L.append("- 基期 local 口径与测试期 association 口径不同，上述区间只用于说明未知归属的影响"
             "范围，不与基期覆盖率相减。")
    L.append("")

    # 4. 抽查与补证
    L.append("## 4. 抽查工作量与补证方案（第 4 周，按可接触资料源给定）")
    L.append("")
    L.append("### 4.1 工时额度与已预约占用")
    L.append("")
    L.append("| 资料源 | 额度(工时) | 已预约请求 | 已占工时 | 剩余 |")
    L.append("| --- | ---: | --- | ---: | ---: |")
    L.append("| issuer | 5 | r1、r2 | 3（a1 一次核实同时服务两请求） | 2 |")
    L.append("| studio | 4 | r3 | 2（a3） | 2 |")
    L.append("| registry | 2 | r4 | 0（r4 可由在库 d4 直接解除，不查档），释放后给 a4 | 2 |")
    L.append("")
    L.append("### 4.2 候选材料的作用分级")
    L.append("")
    L.append("| 候选 | 资料源 | 成本 | 关联对象 | 无论核实结果如何都使关键比较可判定 | 仅补当期局部盲点 |")
    L.append("| --- | --- | ---: | --- | --- | --- |")
    L.append("| a1 | issuer | 3 | d5、d6 | 否 | 是：d6 可同时解除 r1(g3)、r2(g6)；d5 只影响 association 期 g8/g11 |")
    L.append("| a2 | studio | 4 | g2、g11 | **是**：身份任一确定都让对应分钟脱离不可判，v2 的 A 格比较随之可判定 | — |")
    L.append("| a3 | studio | 2 | g5、g9 | **是**：核实撤回链后 g10 缺口定性不再受旧关联干扰 | — |")
    L.append("| a4 | registry | 2 | g12 | **是**：p3 的 registry 证据有无都让 D 格测试期可判定 | — |")
    L.append("")
    L.append("### 4.3 排程建议与规则约束")
    L.append("")
    L.append("- **不重复占用**：r1、r2 已由 web 负责人预约（a1，issuer 源）。d6 虽已于第 25 日到库，"
             "两请求状态仍为 scheduled，须由预约负责人完成一次核实后关闭；同一份核实只解除确实适用的"
             "请求——d6（web/guidance/local）匹配 g3、g6，r1、r2 均可解除；d5 为 mobile/association，"
             "不匹配这两条 web 段，不得据此扩大解除范围。")
    L.append("- **撤回关联不得用于验收**：r3 针对的 g5/p1 关联已被 g9 撤回，即使 d1 类证书到达"
             "也不能据此验收 s4；a3 的产出只用于确认撤回链，r3 应按前提失效关闭，不产生覆盖。")
    L.append("- r4 所期待的 d4 已在库且匹配 g7（mobile/consultation/registry，d12–d23 含 d18），"
             "r4 可直接解除、无需再占 registry 查档；腾出的 2 工时用于 a4，使 D 格测试期可判定。")
    L.append("- studio 剩余 2 工时只够 a3；a2（4 工时）本周额度不足，须追加额度或延至下周，"
             "不得为凑改善而只查可能有利的分段。a2 与 a3 均为身份/关联核实，不涉及无证据承诺的身份联想。")
    L.append("- 上报预计改善时只陈述可判定性变化：a2/a3/a4 无论结果正负都消除不可判；"
             "a1 只补 web/guidance 与 association 期局部盲点，不宣称预计覆盖率提升。")
    L.append("- 所有个人证据（d1–d6 及补证回执）仅用于内部追查，不对外披露个人身份。")
    L.append("")

    # 5. 方法学附注
    L.append("## 5. 口径附注")
    L.append("")
    L.append("1. 主持人（host）不等同出镜人：s1 主持 p3 但出镜分段为 p1、p1|p2，验收只看出镜关联。")
    L.append("2. 机构材料不自动覆盖机构内全部讲师：凭据按 person 精确匹配，无团体推定。")
    L.append("3. 更正不增加时长：g9/g10 替代 g5 后 s4 仍为 40 分钟；d6 替代 d2 后同主体同场景只计一份回执。")
    L.append("4. 左闭右开：所有区间按 [start, end) 处理；d1 在 d9 到期，s4(d11) 不适用。")
    L.append("5. reference 表 target_share 合计为 1，仅用于构成对齐；无事实对应的格不当作零证据分钟。")
    L.append("")
    return "\n".join(L)


def i(v: str) -> int:
    return int(v)


if __name__ == "__main__":
    text = build()
    OUT.write_text(text + "\n", encoding="utf-8")
    print(text)
