"""采集质量的约束测试：口径、版本、幂等与回写。

运行：cd backend && .venv/bin/python -m pytest tests -q
没有 pytest 时也可以直接 .venv/bin/python tests/test_quality.py。
"""
from __future__ import annotations

import importlib
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def fresh_app():
    """每个用例重建仓库模块，避免示例引导数据互相影响。"""
    for name in [
        "app.quality_store",
        "app.services.qualitycore",
        "app.services.qualityreport",
        "app.routers.qualityreport",
        "app.routers",
        "app.main",
        "app.store",
    ]:
        sys.modules.pop(name, None)
    import app.main as main

    return importlib.reload(main)


class QualityTest(unittest.TestCase):
    def setUp(self) -> None:
        main = fresh_app()
        from fastapi.testclient import TestClient

        self.client = TestClient(main.app)
        from app.services.qualityreport import service

        self.service = service

    def test_counts_always_add_up(self) -> None:
        for item in self.service.list_sources():
            payload = self.client.get(
                "/api/qualityreport/dashboard", params={"job": item["作业编号"]}
            ).json()
            counts = payload["URL计数校验"]
            self.assertEqual(
                counts["成功URL数"] + counts["失败URL数"],
                counts["总URL数"],
                item["作业编号"],
            )
            self.assertEqual(counts["校验"], "通过")

    def test_partial_failure_uses_failure_zero_coverage(self) -> None:
        payload = self.client.get(
            "/api/qualityreport/dashboard", params={"job": "CRAW-0001"}
        ).json()
        metrics = payload["指标"]
        self.assertEqual(metrics["总URL数"], 6)
        self.assertEqual(metrics["成功URL数"], 5)
        self.assertEqual(metrics["失败URL数"], 1)
        self.assertEqual(metrics["内容完整率"], 73.33)  # 22 / 30
        self.assertEqual(metrics["成功页完整率"], 88.0)  # 22 / 25
        self.assertEqual(metrics["覆盖口径"], "全量URL计入分母，失败URL按零覆盖计")
        self.assertIn("部分URL失败", " ".join(payload["边界说明"]))
        self.assertIn("PARTIAL_FAILURE", payload["边界标记"])

    def test_zero_url_is_unevaluable(self) -> None:
        conclusion = [
            item for item in self.service.list_conclusions("CRAW-0002")
        ][0]
        self.assertEqual(conclusion["结论等级"], "不可评估")
        self.assertIn("ZERO_URL", conclusion["边界标记"])
        self.assertFalse(conclusion["可确认"])

    def test_version_conflict_blocks_confirm(self) -> None:
        conclusion = self.service.list_conclusions("CRAW-0003")[0]
        self.assertIn("VERSION_CONFLICT", conclusion["边界标记"])
        self.assertFalse(conclusion["可确认"])
        entry, message, _ = self.service.confirm(conclusion["结论编号"], {})
        self.assertIsNone(entry)
        self.assertIn("不可确认边界", message)
        # 冲突不影响URL计数：三行都计入总数。
        self.assertEqual(conclusion["指标"]["总URL数"], 3)
        self.assertEqual(conclusion["指标"]["成功URL数"], 3)

    def test_generate_is_idempotent(self) -> None:
        # 示例数据在导入时已经生成过一次结论；同一份输入再提交不应产生新版本。
        before = len(self.service.list_conclusions("CRAW-0001"))
        seed = self.service.list_conclusions("CRAW-0001")[0]
        again, message, reused = self.service.generate({"作业编号": "CRAW-0001"})
        self.assertEqual(len(self.service.list_conclusions("CRAW-0001")), before)
        self.assertEqual(again["结论编号"], seed["结论编号"])
        self.assertTrue(reused)
        self.assertIn("未重复生效", message)
        # 换一个请求编号重放，仍然命中同一份输入摘要。
        replayed, _, reused_again = self.service.generate(
            {"作业编号": "CRAW-0001", "请求编号": "REQ-OTHER"}
        )
        self.assertTrue(reused_again)
        self.assertEqual(replayed["结论编号"], seed["结论编号"])

    def test_concurrent_generate_creates_one_version(self) -> None:
        before = len(self.service.list_conclusions("CRAW-0004"))
        results: list[str] = []
        lock = threading.Lock()

        def worker() -> None:
            entry, _, _ = self.service.generate({"作业编号": "CRAW-0004"})
            with lock:
                results.append(entry["结论编号"])

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(set(results)), 1)
        self.assertEqual(len(self.service.list_conclusions("CRAW-0004")), before)

    def test_concurrent_generate_after_change_writes_one_version(self) -> None:
        """源数据变化后并发重算：只允许落一个版本，不能出现两条 v2。"""
        from app.quality_store import quality_store

        record = {
            "作业名称": "展会日历同步",
            "目标站点": "expo.example.com",
            "提取版本": "CONT-0001",
            "结果批次": "RUN-20260904-02",
            "抓取时间": "2026-09-04T20:00:00+08:00",
            "URL结果": [
                {
                    "URL": "https://expo.example.com/2026/spring",
                    "提取版本": "CONT-0001",
                    "状态": "成功",
                    "字段": {
                        "标题": "春季展会",
                        "发布时间": "2026-09-04",
                        "作者": "会展组",
                        "正文": "春季展会排期……",
                        "来源": "会展官网",
                    },
                }
            ],
        }
        quality_store.replace_url_results("CRAW-0004", record)
        quality_store.replace_field_verification(
            "CRAW-0004",
            {
                "提取版本": "CONT-0001",
                "核验清单编号": "FV-0004",
                "结构化字段数": 5,
                "抽检URL数": 1,
                "完整字段数": 5,
                "结构化字段完整率": 100.0,
                "核验状态": "已核验",
                "核验时间": "2026-09-04T20:10:00+08:00",
            },
        )
        before = len(self.service.list_conclusions("CRAW-0004"))
        results: list[str] = []
        lock = threading.Lock()

        def worker() -> None:
            entry, _, _ = self.service.generate({"作业编号": "CRAW-0004"})
            with lock:
                results.append(entry["结论编号"])

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(set(results)), 1, results)
        self.assertEqual(len(self.service.list_conclusions("CRAW-0004")), before + 1)

    def test_recompute_new_version_keeps_history(self) -> None:
        old = self.service.get_conclusion(
            self.service.list_conclusions("CRAW-0001")[0]["结论编号"]
        )
        old_snapshot = self.service.get_snapshot(old["snapshot_id"])
        record = {
            "作业名称": "行业资讯日更",
            "目标站点": "news.example.com",
            "提取版本": "CONT-0001",
            "结果批次": "RUN-20260901-02",
            "抓取时间": "2026-09-01T18:30:00+08:00",
            "URL结果": [
                {
                    "URL": "https://news.example.com/a/1001",
                    "提取版本": "CONT-0001",
                    "状态": "成功",
                    "字段": {
                        "标题": "算力中心扩容",
                        "发布时间": "2026-09-01",
                        "作者": "王琳",
                        "正文": "算力中心完成二期扩容……",
                        "来源": "行业观察",
                    },
                }
            ],
        }
        self.service_url_update(record)
        self.service_field_update(
            "CRAW-0001",
            {
                "提取版本": "CONT-0001",
                "核验清单编号": "FV-0001",
                "结构化字段数": 5,
                "抽检URL数": 1,
                "完整字段数": 5,
                "结构化字段完整率": 100.0,
                "核验状态": "已核验",
                "核验时间": "2026-09-01T18:40:00+08:00",
            },
        )
        new, message, _ = self.service.generate({"作业编号": "CRAW-0001"})
        self.assertNotEqual(new["结论编号"], old["结论编号"])
        self.assertEqual(new["版本号"], old["版本号"] + 1)
        # 历史快照逐字节不变，校验和仍然有效。
        self.assertEqual(self.service.get_snapshot(old["snapshot_id"]), old_snapshot)
        self.assertTrue(self.service.get_snapshot(old["snapshot_id"])["校验有效"])
        self.assertEqual(
            self.service.get_conclusion(old["结论编号"])["状态"],
            "已确认",
            "历史已确认版本不应被重算改写",
        )
        # 确认新版本后，旧版本降为已取代，但快照仍然只读可追溯。
        confirmed, _, _ = self.service.confirm(new["结论编号"], {"操作人": "质量甲"})
        self.assertIsNotNone(confirmed)
        self.assertEqual(
            self.service.get_conclusion(old["结论编号"])["状态"], "已取代"
        )
        self.assertEqual(
            self.service.get_snapshot(old["snapshot_id"])["指标"], old_snapshot["指标"]
        )

    def service_url_update(self, record: dict) -> None:
        from app.quality_store import quality_store

        updated = quality_store.replace_url_results("CRAW-0001", record)
        self.assertIsNotNone(updated)

    def service_field_update(self, job: str, record: dict) -> None:
        from app.quality_store import quality_store

        self.assertIsNotNone(quality_store.replace_field_verification(job, record))

    def test_confirm_idempotent_and_writeback(self) -> None:
        conclusion = [
            item for item in self.service.list_conclusions("CRAW-0004")
        ][0]
        first, message, reused = self.service.confirm(
            conclusion["结论编号"], {"请求编号": "REQ-1", "操作人": "质量乙"}
        )
        self.assertIsNotNone(first)
        self.assertFalse(reused)
        second, message2, reused2 = self.service.confirm(
            conclusion["结论编号"], {"请求编号": "REQ-1", "操作人": "质量乙"}
        )
        self.assertTrue(reused2)
        self.assertEqual(second["结论编号"], first["结论编号"])
        self.assertIn("未重复", message2)

        from app.quality_store import quality_store

        verification = quality_store.get_field_verification("CRAW-0004")
        self.assertEqual(verification["回写结论编号"], conclusion["结论编号"])
        self.assertEqual(verification["回写快照编号"], conclusion["snapshot_id"])
        self.assertEqual(verification["回写版本号"], conclusion["版本号"])

        # 另一业务清单（质量报告清单）同步出现已确认状态。
        rows, _ = self.service.list_entries()
        matched = [row for row in rows if row["结论编号"] == conclusion["结论编号"]]
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0]["status"], "已确认")
        self.assertEqual(matched[0]["总URL数"], matched[0]["成功URL数"] + matched[0]["失败URL数"])

    def test_only_one_confirmed_version_per_job(self) -> None:
        record = {
            "作业名称": "行业资讯日更",
            "目标站点": "news.example.com",
            "提取版本": "CONT-0001",
            "结果批次": "RUN-20260901-03",
            "抓取时间": "2026-09-01T20:00:00+08:00",
            "URL结果": [],
        }
        self.service_url_update(record)
        pending, _, _ = self.service.generate({"作业编号": "CRAW-0001"})
        # 新版本是零URL，不可确认，原已确认版本继续生效。
        self.assertFalse(pending["可确认"])
        rejected, message, _ = self.service.confirm(pending["结论编号"], {})
        self.assertIsNone(rejected)
        self.assertIn("不可确认边界", message)
        confirmed = [
            item
            for item in self.service.list_conclusions("CRAW-0001")
            if item["状态"] == "已确认"
        ]
        self.assertEqual(len(confirmed), 1)

    def test_concurrent_confirm_keeps_single_confirmed_version(self) -> None:
        """两个版本同时发起确认：无论先后，同一作业最终只保留一个已确认版本。"""
        from app.quality_store import quality_store

        quality_store.replace_url_results(
            "CRAW-0006",
            {
                "作业名称": "舆情快照抽取",
                "目标站点": "opinion.example.com",
                "提取版本": "CONT-0006",
                "结果批次": "RUN-20260906-02",
                "抓取时间": "2026-09-06T18:50:00+08:00",
                "URL结果": [
                    {
                        "URL": "https://opinion.example.com/post/3001",
                        "提取版本": "CONT-0006",
                        "状态": "成功",
                        "字段": {
                            "标题": "首条舆情",
                            "发布时间": "2026-09-06",
                            "作者": "监测组",
                            "正文": "首条舆情摘要……",
                            "来源": "舆情系统",
                        },
                    }
                ],
            },
        )
        quality_store.replace_field_verification(
            "CRAW-0006",
            {
                "提取版本": "CONT-0006",
                "核验清单编号": "FV-0006",
                "结构化字段数": 5,
                "抽检URL数": 1,
                "完整字段数": 5,
                "结构化字段完整率": 100.0,
                "核验状态": "已核验",
                "核验时间": "2026-09-06T19:00:00+08:00",
            },
        )
        versions = [item for item in self.service.list_conclusions("CRAW-0006")]
        v2, _, _ = self.service.generate({"作业编号": "CRAW-0006"})
        self.assertTrue(v2["可确认"])
        targets = [v2["结论编号"]]

        results: list[tuple[str, str]] = []
        lock = threading.Lock()

        def worker(conclusion_id: str) -> None:
            entry, message, _ = self.service.confirm(conclusion_id, {})
            with lock:
                results.append((conclusion_id, "ok" if entry else message))

        threads = [threading.Thread(target=worker, args=(cid,)) for cid in targets * 4]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertTrue(all(state == "ok" for _, state in results), results)
        confirmed = [
            item for item in self.service.list_conclusions("CRAW-0006")
            if item["状态"] == "已确认"
        ]
        self.assertEqual(len(confirmed), 1)
        self.assertEqual(confirmed[0]["结论编号"], v2["结论编号"])
        self.assertEqual(len(versions) + 1, len(self.service.list_conclusions("CRAW-0006")))

    def test_stale_version_cannot_be_confirmed(self) -> None:
        # CRAW-0003 的 v1 不可确认；换一份完整数据再生成 v2，v1 仍不可确认。
        old = self.service.list_conclusions("CRAW-0003")[0]
        self.service_url_update_for(
            "CRAW-0003",
            {
                "作业名称": "政策法规订阅",
                "目标站点": "policy.example.com",
                "提取版本": "CONT-0003",
                "结果批次": "RUN-20260903-02",
                "抓取时间": "2026-09-03T18:00:00+08:00",
                "URL结果": [
                    {
                        "URL": "https://policy.example.com/notice/2001",
                        "提取版本": "CONT-0003",
                        "状态": "成功",
                        "字段": {
                            "标题": "数据出境新规",
                            "发布时间": "2026-09-03",
                            "作者": "政策研究室",
                            "正文": "数据出境安全评估办法更新……",
                            "来源": "官方公报",
                        },
                    }
                ],
            },
        )
        new, _, _ = self.service.generate({"作业编号": "CRAW-0003"})
        self.assertEqual(new["版本号"], old["版本号"] + 1)
        self.assertTrue(new["可确认"])
        rejected, message, _ = self.service.confirm(old["结论编号"], {})
        self.assertIsNone(rejected)
        self.assertTrue(
            "不可确认边界" in message or "取代" in message,
            message,
        )

    def test_archive_rules(self) -> None:
        rows, _ = self.service.list_entries()
        confirmed = next(row for row in rows if row["status"] == "已确认")
        blocked, message = self.service.archive(int(confirmed["id"]))
        self.assertIsNone(blocked)
        self.assertIn("对外口径", message)

        blocked_pending, message_pending = self.service.archive(
            int(next(row for row in rows if row["status"] == "待确认")["id"])
        )
        self.assertIsNone(blocked_pending)
        self.assertIn("待确认", message_pending)

        superseded = [row for row in self.service.list_entries(page=1, size=100)[0] if row["status"] == "已取代"]
        if superseded:
            archived, message_archived = self.service.archive(int(superseded[0]["id"]))
            self.assertIsNotNone(archived)
            self.assertEqual(archived["status"], "已归档")
            again, message_again = self.service.archive(int(superseded[0]["id"]))
            self.assertIsNone(again)
            self.assertIn("无需重复归档", message_again)

    def test_export_and_list_contract(self) -> None:
        response = self.client.get("/api/qualityreport", params={"size": 10})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(set(payload), {"items", "total", "page", "size"})
        exported = self.client.get("/api/qualityreport/export").json()
        self.assertEqual(exported["total"], payload["total"])

    def test_unknown_action_rejected(self) -> None:
        entry_id = self.client.get("/api/qualityreport").json()["items"][0]["id"]
        response = self.client.post(
            f"/api/qualityreport/{entry_id}/actions", json={"values": {"action": "生成报告"}}
        ).json()
        self.assertFalse(response["ok"])
        self.assertIn("不属于", response["message"])

    def service_url_update_for(self, job: str, record: dict) -> None:
        from app.quality_store import quality_store

        self.assertIsNotNone(quality_store.replace_url_results(job, record))


if __name__ == "__main__":
    unittest.main()
