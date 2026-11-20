"""核验引擎的业务结论测试：锁定三桶、口径切换、撤回链、更正链与比较规则。"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analysis"))

from coverage_engine import Engine  # noqa: E402


class CoverageTests(unittest.TestCase):
    def setUp(self):
        self.eng = Engine()

    def bucket(self, lo, hi, asof):
        return self.eng.bucket_minutes(self.eng.evaluate_window(lo, hi, asof))

    def seg_bucket(self, verdicts, seg_id):
        return next(v["bucket"] for v in verdicts if v["segment"].segment == seg_id)

    def test_policy_switch_left_closed_right_open(self):
        # d14 仍是 local，d15 起 association，d32 已无口径
        self.assertEqual(self.eng.evidence_kind_on("mobile", "guidance", 14), "local")
        self.assertEqual(self.eng.evidence_kind_on("mobile", "guidance", 15), "association")
        with self.assertRaises(ValueError):
            self.eng.evidence_kind_on("mobile", "guidance", 32)

    def test_current_three_buckets(self):
        verdicts = self.eng.evaluate_window(1, 31, 27)
        self.assertEqual(self.eng.bucket_minutes(verdicts),
                         {"covered": 196, "unsupported": 0, "pending": 151})
        # 三桶之和等于全部生效分段分钟（撤回链不重复计时长）
        self.assertEqual(sum(self.eng.bucket_minutes(verdicts).values()), 347)

    def test_expired_credential_is_pending_not_covered(self):
        # d1 区间 d1–d9，g1(d7) 覆盖；s4(d11) 的任何关联都不能再用 d1
        verdicts = self.eng.evaluate_window(1, 31, 27)
        self.assertEqual(self.seg_bucket(verdicts, "g1"), "covered")

    def test_withdrawn_link_takes_latest_segment(self):
        # asof=21：g5 确认关联仍生效；asof=22 撤回后失效，asof=23 由 g10 接管
        early = self.eng.evaluate_window(1, 21, 21)
        self.assertEqual(self.seg_bucket(early, "g5"), "pending")
        with self.assertRaises(StopIteration):
            self.seg_bucket(self.eng.evaluate_window(1, 31, 22), "g5")
        later = self.eng.evaluate_window(1, 31, 23)
        self.assertEqual(self.seg_bucket(later, "g10"), "pending")
        # 同一更正链任一时点只计一次 40 分钟
        self.assertEqual(
            sum(v["minutes"] for v in later if v["segment"].show == "s4"), 40)

    def test_unsupported_then_retroactive_correction(self):
        # asof=21：d2 是唯一适用且 unsupported；asof=25 后 d6 可追溯订正
        old = self.eng.evaluate_window(1, 21, 21)
        self.assertEqual(self.seg_bucket(old, "g3"), "unsupported")
        self.assertEqual(self.seg_bucket(old, "g6"), "unsupported")
        new = self.eng.evaluate_window(1, 21, 26)
        self.assertEqual(self.seg_bucket(new, "g3"), "covered")
        self.assertEqual(self.seg_bucket(new, "g6"), "covered")
        # d2 在 d6 获知后不再参与判断
        self.assertNotIn("d2", {c.doc for c in self.eng.active_credentials(26)})

    def test_uncertain_identity_is_pending_even_if_one_candidate_covered(self):
        # g11：p2 有 d5 覆盖、p1 无材料；身份未决 => 分段整体不可判
        verdicts = self.eng.evaluate_window(15, 28, 28)
        self.assertEqual(self.seg_bucket(verdicts, "g11"), "pending")
        v11 = next(v for v in verdicts if v["segment"].segment == "g11")
        self.assertEqual(v11["per_person"]["p2"], "covered:d5")
        self.assertEqual(v11["per_person"]["p1"], "no_material")

    def test_kind_mismatch_not_coverage(self):
        # g10(d11) 走 local：d5 虽为 association 且日期覆盖 d11，种类不符不可用
        verdicts = self.eng.evaluate_window(1, 31, 27)
        v10 = next(v for v in verdicts if v["segment"].segment == "g10")
        self.assertEqual(set(v10["per_person"].values()), {"no_material"})

    def test_historical_assessment_vs_current_review(self):
        self.assertEqual(self.bucket(1, 21, 21),
                         {"covered": 55, "unsupported": 87, "pending": 91})
        self.assertEqual(self.bucket(1, 21, 26),
                         {"covered": 142, "unsupported": 0, "pending": 91})

    def test_person_not_double_counted_across_channels_or_shows(self):
        verdicts = self.eng.evaluate_window(1, 31, 27)
        view = self.eng.cell_person_view(verdicts)
        # p2 在 web/guidance 两个长场次出镜，人户口径只记一人
        self.assertEqual(view[("web", "guidance", "afternoon")]["covered"], ["p2"])
        # 跨渠道各自成格，不相加
        self.assertEqual(view[("mobile", "consultation", "afternoon")]["covered"], ["p2"])

    def test_mixed_status_person_listed_separately(self):
        # m1 中 p1 在 mobile/guidance：g1 覆盖、g5 缺口 => 混合列
        view = self.eng.cell_person_view(self.eng.evaluate_window(1, 21, 21))
        cell = view[("mobile", "guidance", "evening")]
        self.assertEqual(cell["mixed"], ["p1"])
        self.assertNotIn("p1", cell["covered"])
        self.assertNotIn("p1", cell["gap"])

    def test_joint_identity_enumeration(self):
        from build_report import joint_identity_range
        verdicts = self.eng.evaluate_window(15, 28, 28)
        rng = joint_identity_range(
            self.eng, verdicts, ("mobile", "guidance", "evening"))
        # g8(6) 与 g11(34)，2x2=4 种联合方案；可行覆盖 0–34 分钟
        self.assertEqual(rng["schemes"], 4)
        self.assertEqual((rng["min"], rng["max"], rng["total_minutes"]), (0, 34, 40))

    def test_decidable_rate_excludes_pending(self):
        rates = self.eng.decidable_rates(self.eng.evaluate_window(1, 31, 27))
        # mobile/guidance/evening：仅 g1 的 15 分钟可判定且覆盖
        r = rates[("mobile", "guidance", "evening")]
        self.assertEqual((r["covered"], r["decidable"], r["all_minutes"]), (15, 15, 140))
        self.assertEqual(r["rate"], 1.0)

    def test_host_is_not_on_screen_identity(self):
        # s1 主持 p3，但出镜分段不含确认的 p3
        verdicts = self.eng.evaluate_window(7, 7, 27)
        confirmed = {p for v in verdicts if v["unique"]
                     for p in v["segment"].candidates}
        self.assertEqual(confirmed, {"p1"})


if __name__ == "__main__":
    unittest.main()
