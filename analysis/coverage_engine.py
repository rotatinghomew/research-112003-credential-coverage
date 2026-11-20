"""宣传资质证据覆盖核验引擎。

口径要点（与 README 及业务约定一致）：
- 凭据仅在主体、类别、渠道、日期区间均匹配时覆盖；适用材料类型取展示当日生效的口径。
- 左闭右开：凭据/口径区间 [start, end)；更正凭据可追溯生效，以 start 表示，known 为获知日。
- 被 replaces 订正的旧回执，在获知替代回执之后不再用于判断；unsupported 是明确不支持。
- 分段更正链：state=withdrawn 的分段自其 known 日起失效；同一 ref 链上的最新分段接管，时长不重复计。
- 三桶分别统计：covered（唯一适用证据）/ unsupported（明确不支持）/ pending（资料待核不可判）。
- 出镜人无法唯一确定（candidates 多人或 state=uncertain）时，分段结论为候选条件判断，不武断归人。
- 所有判断都带 asof 日期：只使用 known <= asof 的资料，历史考核按当时口径与材料找回。
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data"


def load(table: str) -> list[dict]:
    with (DATA / f"{table}.csv").open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def i(value: str) -> int:
    return int(value) if value not in ("", None) else None


# ---------------------------------------------------------------- 资料装载

@dataclass
class Show:
    show: str
    channel: str
    category: str
    day: int
    minutes: int
    host: str


@dataclass
class Segment:
    segment: str
    show: str
    start: int
    end: int
    candidates: tuple[str, ...]
    known: int
    ref: str
    state: str

    @property
    def minutes(self) -> int:
        return self.end - self.start

    @property
    def chain(self) -> str:
        return self.ref or self.segment


@dataclass
class Credential:
    doc: str
    person: str
    kind: str
    channel: str
    category: str
    start: int
    end: int
    known: int
    state: str
    replaces: str


@dataclass
class Cell:
    channel: str
    category: str
    slot: str


class Engine:
    def __init__(self) -> None:
        self.shows = {
            r["show"]: Show(r["show"], r["channel"], r["category"], i(r["day"]),
                            i(r["minutes"]), r["host"])
            for r in load("shows")
        }
        self.segments = [
            Segment(r["segment"], r["show"], i(r["start"]), i(r["end"]),
                    tuple(r["candidates"].split("|")) if r["candidates"] else (),
                    i(r["known"]), r["ref"], r["state"])
            for r in load("segments")
        ]
        self.policy = [
            dict(channel=r["channel"], category=r["category"], start=i(r["start"]),
                 end=i(r["end"]), evidence_kind=r["evidence_kind"])
            for r in load("policy")
        ]
        self.credentials = [
            Credential(r["doc"], r["person"], r["kind"], r["channel"], r["category"],
                       i(r["start"]), i(r["end"]), i(r["known"]), r["state"], r["replaces"])
            for r in load("credentials")
        ]
        self.slots = {r["show"]: r["slot"] for r in load("show_slots")}
        self.reference = [
            dict(channel=r["channel"], category=r["category"], slot=r["slot"],
                 target_share=float(r["target_share"]))
            for r in load("reference")
        ]
        self.requests = load("requests")
        self.options = load("verification_options")
        self.budget = load("verification_budget")

    # ---------------------------------------------------------------- 口径与证据

    def evidence_kind_on(self, channel: str, category: str, day: int) -> str:
        hits = [p for p in self.policy
                if p["channel"] == channel and p["category"] == category
                and p["start"] <= day < p["end"]]
        if len(hits) != 1:
            raise ValueError(f"口径不唯一: {channel}/{category}/day{day} -> {hits}")
        return hits[0]["evidence_kind"]

    def active_credentials(self, asof: int) -> list[Credential]:
        """asof 时点可见且未被已知替代回执取代的凭据。"""
        replaced = {c.replaces for c in self.credentials if c.known <= asof and c.replaces}
        return [c for c in self.credentials if c.known <= asof and c.doc not in replaced]

    def person_doc(self, person: str, channel: str, category: str, day: int,
                   asof: int) -> Credential | None:
        """返回该主体在该展示场景下唯一适用的凭据；无则 None。"""
        kind = self.evidence_kind_on(channel, category, day)
        hits = [c for c in self.active_credentials(asof)
                if c.person == person and c.kind == kind
                and c.channel == channel and c.category == category
                and c.start <= day < c.end]
        if len(hits) > 1:
            raise ValueError(f"适用凭据不唯一: {person} {channel}/{category} day{day}")
        return hits[0] if hits else None

    # ---------------------------------------------------------------- 分段有效性

    def active_segments(self, asof: int) -> list[Segment]:
        """asof 时点生效的分段：撤回分段失效，同一更正链只保留最新一条。"""
        known_segments = [s for s in self.segments if s.known <= asof]
        latest: dict[str, Segment] = {}
        for s in known_segments:
            cur = latest.get(s.chain)
            if cur is None or s.known > cur.known:
                latest[s.chain] = s
        return [s for s in latest.values() if s.state != "withdrawn"]

    def segment_verdict(self, seg: Segment, asof: int) -> dict:
        """对单个分段逐候选人判定，返回条件结论与分段级三桶。"""
        show = self.shows[seg.show]
        per_person = {}
        for person in seg.candidates:
            doc = self.person_doc(person, show.channel, show.category, show.day, asof)
            if doc is None:
                per_person[person] = "no_material"
            elif doc.state == "supported":
                per_person[person] = f"covered:{doc.doc}"
            elif doc.state == "unsupported":
                per_person[person] = f"unsupported:{doc.doc}"
            else:
                raise ValueError(f"未知凭据状态 {doc.state}")
        unique = len(seg.candidates) == 1 and seg.state == "confirmed"
        if unique:
            label = next(iter(per_person.values()))
            bucket = ("covered" if label.startswith("covered")
                      else "unsupported" if label.startswith("unsupported")
                      else "pending")
        else:
            # 身份不可唯一确定：任何结论都是条件性的，分段整体不可判
            bucket = "pending"
        return {"segment": seg, "show": show, "per_person": per_person,
                "unique": unique, "bucket": bucket,
                "minutes": seg.minutes,
                "cell": (show.channel, show.category, self.slots[seg.show])}

    def evaluate_window(self, lo: int, hi: int, asof: int) -> list[dict]:
        """评估 day 落在 [lo, hi] 的展示（比较端点均含）。"""
        out = []
        for seg in self.active_segments(asof):
            show = self.shows[seg.show]
            if lo <= show.day <= hi:
                out.append(self.segment_verdict(seg, asof))
        return out

    # ---------------------------------------------------------------- 汇总

    @staticmethod
    def bucket_minutes(verdicts: list[dict]) -> dict[str, int]:
        agg = {"covered": 0, "unsupported": 0, "pending": 0}
        for v in verdicts:
            agg[v["bucket"]] += v["minutes"]
        return agg

    def cells(self, verdicts: list[dict]) -> dict[tuple, list[dict]]:
        grouped: dict[tuple, list[dict]] = {}
        for v in verdicts:
            grouped.setdefault(v["cell"], []).append(v)
        return grouped

    def cell_person_view(self, verdicts: list[dict]) -> dict[tuple, dict]:
        """每格的独立出镜人：确认覆盖 / 确认缺口 / 同人混合 / 仅候选未决，分列。

        同一人在同一格内可能一段覆盖、另一段缺口（凭据到期等），单列混合，
        不把此人同时塞进覆盖与缺口两个集合。
        """
        view = {}
        for cell, items in self.cells(verdicts).items():
            covered, gap, mixed, unresolved = set(), set(), set(), set()
            status: dict[str, set[str]] = {}
            for v in items:
                if v["unique"]:
                    person = v["segment"].candidates[0]
                    status.setdefault(person, set()).add(v["bucket"])
                else:
                    unresolved.update(v["segment"].candidates)
            for person, buckets in status.items():
                if buckets == {"covered"}:
                    covered.add(person)
                elif buckets == {"pending"} or buckets == {"unsupported"}:
                    gap.add(person)
                else:
                    mixed.add(person)
            # 已在本格确认过的人不再算“未决”
            unresolved -= covered | gap | mixed
            view[cell] = {"covered": sorted(covered), "gap": sorted(gap),
                          "mixed": sorted(mixed), "unresolved": sorted(unresolved)}
        return view

    def unknown_attribution(self, verdicts: list[dict]) -> dict:
        """未知归属对分钟口径与人户口径的影响范围。"""
        minutes = sum(v["minutes"] for v in verdicts if not v["unique"])
        people = set()
        for v in verdicts:
            if not v["unique"]:
                people.update(v["segment"].candidates)
        return {"uncertain_minutes": minutes, "uncertain_candidates": sorted(people)}

    def decidable_rates(self, verdicts: list[dict]) -> dict[tuple, dict | None]:
        """每格只在可判定分钟上计算覆盖率；无可判定分钟返回 None。"""
        rates = {}
        for cell, items in self.cells(verdicts).items():
            decidable = [v for v in items if v["bucket"] in ("covered", "unsupported")]
            if not decidable:
                rates[cell] = None
            else:
                covered = sum(v["minutes"] for v in decidable if v["bucket"] == "covered")
                total = sum(v["minutes"] for v in decidable)
                rates[cell] = {"rate": covered / total, "covered": covered,
                               "decidable": total,
                               "all_minutes": sum(v["minutes"] for v in items)}
        return rates
