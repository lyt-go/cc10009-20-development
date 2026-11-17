"""采集质量业务规则：读源数据算结论、固化快照、单版本确认与字段核验回写。

约束都在这一层兑现：
- 指标只从 URL 抓取结果与字段核验清单计算，不接受人工填写；
- 成功URL数 + 失败URL数必须等于总URL数；
- 同一作业任意时刻至多一个「已确认」版本；
- 同一份输入（同一提取版本、同一批URL结果与核验记录）连续或并发提交只生效一次；
- 重算只新增版本，历史结论与快照内容不改写。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.quality_store import FIELD_SCOPE, quality_store
from app.services.qualitycore import (
    BOUNDARY_LABELS,
    BOUNDARY_NOTES,
    COVERAGE_SCOPE,
    UNCONFIRMABLE_BOUNDARIES,
    build_snapshot,
    compare_metrics,
    compute_digest,
    compute_quality,
    snapshot_checksum,
)
from app.store import store

MODULE = "qualityreport"
CONCLUSION_PENDING = "待确认"
CONCLUSION_CONFIRMED = "已确认"
CONCLUSION_SUPERSEDED = "已取代"
CONCLUSION_ARCHIVED = "已归档"


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


class QualityreportService:
    # -- 质量报告清单（由结论同步而来，作为「另一业务清单」）-------------
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = [dict(row) for row in store.rows(MODULE)]
        if keyword:
            rows = [
                row for row in rows
                if keyword in str(row.get("报告编号", ""))
                or keyword in str(row.get("作业编号", ""))
            ]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        rows.sort(key=lambda row: (str(row.get("作业编号", "")), -int(row.get("版本号", 0) or 0)))
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def archive(self, entry_id: int) -> tuple[dict[str, Any] | None, str]:
        entry = self.get_entry(entry_id)
        if entry is None:
            return None, f"质量报告 {entry_id} 不存在或已归档"
        with quality_store.lock():
            conclusion = quality_store.raw_conclusion(str(entry.get("结论编号") or ""))
            if conclusion is None:
                return None, "该质量报告未绑定质量结论，无法归档"
            status = conclusion["状态"]
            if status == CONCLUSION_ARCHIVED:
                return None, f"结论 {conclusion['结论编号']} 已归档，无需重复归档"
            if status == CONCLUSION_PENDING:
                return None, "待确认版本不能归档，请先确认或由新版本取代"
            if status == CONCLUSION_CONFIRMED:
                return None, (
                    f"结论 {conclusion['结论编号']} 是当前对外口径，不能直接归档；"
                    "请先生成并确认新版本，本版本被取代后再归档"
                )
            conclusion["状态"] = CONCLUSION_ARCHIVED
            self._sync_report_rows()
            archived = quality_store.find_conclusion(conclusion["结论编号"])
        refreshed = self.get_entry(entry_id)
        if refreshed is None:
            return archived, "质量报告已归档，快照内容保持只读"
        return refreshed, "质量报告已归档，快照内容保持只读"

    # -- 源数据 ----------------------------------------------------------
    def list_sources(self) -> list[dict[str, Any]]:
        """给前端选择作业用：把URL结果、字段核验与已确认版本并列展示。"""
        sources: list[dict[str, Any]] = []
        for record in quality_store.list_url_results():
            job = record["作业编号"]
            urls = record.get("URL结果") or []
            success = sum(1 for row in urls if row.get("状态") == "成功")
            verification = quality_store.get_field_verification(job)
            confirmed = quality_store.confirmed_conclusion(job)
            sources.append({
                "作业编号": job,
                "作业名称": record.get("作业名称"),
                "目标站点": record.get("目标站点"),
                "提取版本": record.get("提取版本"),
                "结果批次": record.get("结果批次"),
                "抓取时间": record.get("抓取时间"),
                "总URL数": len(urls),
                "成功URL数": success,
                "失败URL数": len(urls) - success,
                "字段核验版本": None if verification is None else verification.get("提取版本"),
                "结构化字段完整率": None if verification is None else verification.get("结构化字段完整率"),
                "字段核验状态": None if verification is None else verification.get("核验状态"),
                "已确认版本": None if confirmed is None else confirmed["版本号"],
                "已确认结论": None if confirmed is None else confirmed["结论等级"],
                "已确认快照": None if confirmed is None else confirmed["snapshot_id"],
            })
        return sources

    # -- 生成结论 --------------------------------------------------------
    def generate(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str, bool]:
        job = str(values.get("作业编号") or "").strip()
        if not job:
            return None, "缺少必填字段：作业编号", False
        record = quality_store.get_url_results(job)
        if record is None:
            return None, f"尚未读取到作业 {job} 的URL抓取结果，无法计算质量结论", False
        extraction_version = str(values.get("提取版本") or record.get("提取版本") or "").strip()
        if not extraction_version:
            return None, "缺少提取版本，无法把结论写入结构化提取批次", False

        verification = quality_store.get_field_verification(job)
        urls = record.get("URL结果") or []
        result = compute_quality(job, extraction_version, urls, verification)
        digest = compute_digest(job, extraction_version, urls, verification)
        request_id = str(values.get("请求编号") or "").strip()
        # 幂等以输入摘要为准：同一份URL结果与字段核验，无论请求编号是否相同都只生成一个版本。
        key = f"digest:{job}:{digest}"
        request_key = f"request:{job}:{request_id}" if request_id else None

        with quality_store.lock():
            existing_id = quality_store.lookup_idempotency(key)
            if request_key:
                existing_id = existing_id or quality_store.lookup_idempotency(request_key)
            if existing_id:
                existing = quality_store.find_conclusion(existing_id)
                if existing is not None:
                    return existing, (
                        f"同一份URL结果与字段核验已生成过结论（{existing_id}），"
                        "本次提交未重复生效"
                    ), True

            version_no = quality_store.latest_version(job) + 1
            sequence = quality_store.next_sequence()
            conclusion_id = f"QCON-{sequence:04d}"
            snapshot_id = f"QSNP-{sequence:04d}"
            created_at = _now()
            snapshot = build_snapshot(
                snapshot_id=snapshot_id,
                conclusion_id=conclusion_id,
                result=result,
                created_at=created_at,
                version_no=version_no,
            )
            confirmable = not any(code in UNCONFIRMABLE_BOUNDARIES for code in result["边界标记"])
            conclusion = {
                "结论编号": conclusion_id,
                "作业编号": job,
                "版本号": version_no,
                "提取版本": extraction_version,
                "批次": result["批次"],
                "snapshot_id": snapshot_id,
                "版本分布": dict(result["版本分布"]),
                "指标": dict(result["指标"]),
                "URL计数校验": dict(result["URL计数校验"]),
                "字段覆盖分布": [dict(item) for item in result["字段覆盖分布"]],
                "失败URL对照": [dict(item) for item in result["失败URL对照"]],
                "URL结果": [dict(item) for item in result["URL结果"]],
                "边界标记": list(result["边界标记"]),
                "边界说明": list(result["边界说明"]),
                "结论等级": result["结论等级"],
                "结论摘要": result["结论摘要"],
                "字段核验核对": dict(result["字段核验核对"]),
                "版本一致": result["版本一致"],
                "可确认": confirmable,
                "不可确认原因": (
                    "" if confirmable
                    else "；".join(
                        BOUNDARY_NOTES[code] for code in result["边界标记"] if code in UNCONFIRMABLE_BOUNDARIES
                    )
                ),
                "状态": CONCLUSION_PENDING,
                "输入摘要": digest,
                "请求编号": request_id or None,
                "生成时间": created_at,
                "确认时间": None,
                "确认人": None,
            }
            quality_store.add_snapshot(snapshot)
            quality_store.add_conclusion(conclusion)
            quality_store.bind_idempotency(key, conclusion_id)
            if request_key:
                quality_store.bind_idempotency(request_key, conclusion_id)
            self._sync_report_rows()

            message = f"已生成质量结论 {conclusion_id}（版本 v{version_no}，批次 {result['批次']}）"
            if not confirmable:
                message += "，存在不可确认边界，需先处理边界"
            return quality_store.find_conclusion(conclusion_id), message, False

    # -- 确认结论 --------------------------------------------------------
    def confirm(self, conclusion_id: str, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str, bool]:
        conclusion_id = str(conclusion_id or "").strip()
        operator = str(values.get("操作人") or "值班管理员").strip() or "值班管理员"
        request_id = str(values.get("请求编号") or "").strip()
        key = f"confirm:{conclusion_id}:{request_id}" if request_id else None

        with quality_store.lock():
            conclusion = quality_store.raw_conclusion(conclusion_id)
            if conclusion is None:
                return None, f"质量结论 {conclusion_id} 不存在", False
            if key:
                existing_id = quality_store.lookup_idempotency(key)
                if existing_id:
                    return quality_store.find_conclusion(existing_id), "同一确认请求已生效，本次未重复回写", True
            if conclusion["状态"] == CONCLUSION_CONFIRMED:
                return quality_store.find_conclusion(conclusion_id), (
                    f"结论 {conclusion_id} 已是已确认版本，本次提交未重复生效"
                ), True
            if conclusion["状态"] == CONCLUSION_SUPERSEDED:
                latest = quality_store.latest_version(conclusion["作业编号"])
                return None, f"结论 {conclusion_id} 已被 v{latest} 取代，历史版本不可再确认", False
            if conclusion["状态"] == CONCLUSION_ARCHIVED:
                return None, f"结论 {conclusion_id} 已归档，不可再确认", False
            if not conclusion["可确认"]:
                return None, f"结论 {conclusion_id} 存在不可确认边界：{conclusion['不可确认原因']}", False

            latest = quality_store.latest_version(conclusion["作业编号"])
            if int(conclusion["版本号"]) != latest:
                return None, (
                    f"结论 {conclusion_id} 不是最新版本（当前最新 v{latest}），"
                    "请确认最新版本，避免同一作业出现两个已确认口径"
                ), False

            snapshot = quality_store.find_snapshot(conclusion["snapshot_id"])
            if snapshot is None:
                return None, f"结论 {conclusion_id} 的报告快照缺失，无法确认", False
            if snapshot["批次"] != conclusion["批次"]:
                return None, "结论与报告快照批次不一致，拒绝确认", False
            if snapshot_checksum(snapshot) != snapshot["校验和"]:
                return None, "报告快照校验和不一致，快照可能被改写，拒绝确认", False

            # 同一作业只保留一个已确认版本，其余已确认结论降为已取代；历史快照保持只读。
            for other in quality_store.list_conclusions(conclusion["作业编号"]):
                if other["结论编号"] != conclusion_id and other["状态"] == CONCLUSION_CONFIRMED:
                    other_row = quality_store.raw_conclusion(other["结论编号"])
                    if other_row is not None:
                        other_row["状态"] = CONCLUSION_SUPERSEDED

            confirmed_at = _now()
            conclusion["状态"] = CONCLUSION_CONFIRMED
            conclusion["确认时间"] = confirmed_at
            conclusion["确认人"] = operator
            self._write_back(job=conclusion["作业编号"], conclusion=conclusion, snapshot=snapshot,
                             operator=operator, confirmed_at=confirmed_at)
            self._sync_report_rows()
            if key:
                quality_store.bind_idempotency(key, conclusion_id)
            return quality_store.find_conclusion(conclusion_id), (
                f"结论 {conclusion_id}（v{conclusion['版本号']}）已确认，"
                f"快照 {snapshot['snapshot_id']} 已回写字段核验清单"
            ), False

    # -- 对外呈现 --------------------------------------------------------
    def dashboard(self, job: str, snapshot_id: str | None = None) -> dict[str, Any] | None:
        sources = {item["作业编号"]: item for item in self.list_sources()}
        if job not in sources:
            return None
        confirmed = quality_store.confirmed_conclusion(job)
        snapshot = quality_store.find_snapshot(snapshot_id) if snapshot_id else None
        if snapshot is not None and snapshot["作业编号"] != job:
            return None
        if snapshot is not None:
            # 只有曾经确认过的快照可以对外呈现；待确认草稿不能当口径。
            candidate = quality_store.find_conclusion(snapshot["结论编号"])
            if candidate is None or candidate["状态"] not in {
                CONCLUSION_CONFIRMED, CONCLUSION_SUPERSEDED, CONCLUSION_ARCHIVED,
            }:
                return None
        if snapshot is None and confirmed is not None:
            snapshot = quality_store.find_snapshot(confirmed["snapshot_id"])

        current_record = quality_store.get_url_results(job)
        current_verification = quality_store.get_field_verification(job)
        current = compute_quality(
            job,
            snapshot["提取版本"] if snapshot else (current_record or {}).get("提取版本", ""),
            (current_record or {}).get("URL结果") or [],
            current_verification,
        )
        if snapshot is not None:
            comparison = compare_metrics(snapshot["指标"], current["指标"])
            metrics = snapshot["指标"]
            view_source = (
                "已确认快照"
                if confirmed and snapshot["snapshot_id"] == confirmed["snapshot_id"]
                else "历史已确认快照（已取代）"
            )
        else:
            comparison = []
            metrics = current["指标"]
            view_source = "未确认的实时计算"
        confirmed_copy = None if confirmed is None else {
            "结论编号": confirmed["结论编号"],
            "版本号": confirmed["版本号"],
            "提取版本": confirmed["提取版本"],
            "批次": confirmed["批次"],
            "snapshot_id": confirmed["snapshot_id"],
            "结论等级": confirmed["结论等级"],
            "确认时间": confirmed["确认时间"],
            "确认人": confirmed["确认人"],
        }
        history = [
            {
                "结论编号": item["结论编号"],
                "版本号": item["版本号"],
                "状态": item["状态"],
                "结论等级": item["结论等级"],
                "可确认": item["可确认"],
                "提取版本": item["提取版本"],
                "批次": item["批次"],
                "snapshot_id": item["snapshot_id"],
                "生成时间": item["生成时间"],
            }
            for item in quality_store.list_conclusions(job)
        ]
        return {
            "作业编号": job,
            "作业名称": sources[job].get("作业名称"),
            "目标站点": sources[job].get("目标站点"),
            "呈现口径": view_source,
            "提取版本": snapshot["提取版本"] if snapshot else current["提取版本"],
            "批次": snapshot["批次"] if snapshot else current["批次"],
            "snapshot_id": snapshot["snapshot_id"] if snapshot else None,
            "快照生成时间": snapshot["生成时间"] if snapshot else None,
            "快照校验和": snapshot["校验和"] if snapshot else None,
            "已确认": confirmed_copy,
            "指标": metrics,
            "指标概览": [
                {"label": "总URL数", "value": metrics["总URL数"], "unit": "个"},
                {"label": "成功URL数", "value": metrics["成功URL数"], "unit": "个"},
                {"label": "失败URL数", "value": metrics["失败URL数"], "unit": "个"},
                {"label": "成功率", "value": metrics["成功率"], "unit": "%"},
                {"label": "内容完整率", "value": metrics["内容完整率"], "unit": "%"},
                {"label": "字段覆盖率", "value": metrics["字段覆盖率"], "unit": "%"},
                {"label": "成功页完整率", "value": metrics["成功页完整率"], "unit": "%"},
            ],
            "URL计数校验": dict(snapshot["URL计数校验"]) if snapshot else current["URL计数校验"],
            "字段覆盖分布": list(snapshot["字段覆盖分布"]) if snapshot else current["字段覆盖分布"],
            "失败URL对照": list(snapshot["失败URL对照"]) if snapshot else current["失败URL对照"],
            "URL结果": list(snapshot["URL结果"]) if snapshot else current["URL结果"],
            "边界标记": list(snapshot["边界标记"]) if snapshot else current["边界标记"],
            "边界明细": [
                {
                    "code": code,
                    "label": BOUNDARY_LABELS.get(code, code),
                    "说明": BOUNDARY_NOTES.get(code, ""),
                }
                for code in (snapshot["边界标记"] if snapshot else current["边界标记"])
            ],
            "边界说明": [BOUNDARY_NOTES[code] for code in (snapshot["边界标记"] if snapshot else current["边界标记"])
                     if code in BOUNDARY_NOTES],
            "结论等级": snapshot["结论等级"] if snapshot else current["结论等级"],
            "结论摘要": snapshot["结论摘要"] if snapshot else current["结论摘要"],
            "字段核验核对": dict(snapshot["字段核验核对"]) if snapshot else current["字段核验核对"],
            "已确认指标核对": comparison,
            "版本历史": history,
            "覆盖口径": COVERAGE_SCOPE,
            "字段完整率口径": FIELD_SCOPE,
            # 当前源数据能否生成可确认的新版本（历史快照本身仍可读）。
            "当前数据可确认": not any(
                code in UNCONFIRMABLE_BOUNDARIES for code in current["边界标记"]
            ),
        }

    def list_conclusions(self, job: str | None = None) -> list[dict[str, Any]]:
        return quality_store.list_conclusions(job)

    def get_conclusion(self, conclusion_id: str) -> dict[str, Any] | None:
        return quality_store.find_conclusion(conclusion_id)

    def list_snapshots(self, job: str | None = None) -> list[dict[str, Any]]:
        summaries: list[dict[str, Any]] = []
        for snapshot in quality_store.list_snapshots(job):
            summaries.append({
                "snapshot_id": snapshot["snapshot_id"],
                "结论编号": snapshot["结论编号"],
                "作业编号": snapshot["作业编号"],
                "版本号": snapshot["版本号"],
                "提取版本": snapshot["提取版本"],
                "批次": snapshot["批次"],
                "结论等级": snapshot["结论等级"],
                "指标": dict(snapshot["指标"]),
                "校验和": snapshot["校验和"],
                "生成时间": snapshot["生成时间"],
            })
        return summaries

    def get_snapshot(self, snapshot_id: str) -> dict[str, Any] | None:
        snapshot = quality_store.find_snapshot(snapshot_id)
        if snapshot is None:
            return None
        snapshot["校验有效"] = snapshot_checksum(snapshot) == snapshot["校验和"]
        return snapshot

    # -- 内部：回写与清单同步 -------------------------------------------
    def _write_back(
        self,
        *,
        job: str,
        conclusion: dict[str, Any],
        snapshot: dict[str, Any],
        operator: str,
        confirmed_at: str,
    ) -> None:
        patch = {
            "回写结论编号": conclusion["结论编号"],
            "回写快照编号": snapshot["snapshot_id"],
            "最近回写时间": confirmed_at,
            "回写人": operator,
            "质量结论等级": conclusion["结论等级"],
            "质量结论摘要": conclusion["结论摘要"],
            "回写批次": snapshot["批次"],
            "回写版本号": conclusion["版本号"],
            "回写状态": "已回写质量结论",
        }
        quality_store.write_back_field_verification(job, patch)

    def _sync_report_rows(self) -> None:
        """质量报告清单跟随结论状态同步：生成、确认、取代、归档都会反映到这里。"""
        existing = {str(row.get("结论编号")): row for row in store.rows(MODULE)}
        next_id = max((int(row.get("id", 0) or 0) for row in existing.values()), default=0) + 1
        rows: list[dict[str, Any]] = []
        status_map = {
            CONCLUSION_PENDING: "待确认",
            CONCLUSION_CONFIRMED: "已确认",
            CONCLUSION_SUPERSEDED: "已取代",
            CONCLUSION_ARCHIVED: "已归档",
        }
        for conclusion in sorted(
            quality_store.list_conclusions(),
            key=lambda item: (item["作业编号"], item["版本号"]),
        ):
            rows_version = conclusion["状态"]
            status = status_map.get(rows_version, rows_version)
            if conclusion["状态"] == CONCLUSION_PENDING and not conclusion["可确认"]:
                status = "不可确认"
            row = existing.get(conclusion["结论编号"])
            if row and row.get("id"):
                entry_id = int(row["id"])
            else:
                entry_id = next_id
                next_id += 1
            metrics = conclusion["指标"]
            rows.append({
                "id": entry_id,
                "报告编号": conclusion["结论编号"].replace("QCON-", "QUAL-"),
                "结论编号": conclusion["结论编号"],
                "作业编号": conclusion["作业编号"],
                "提取版本": conclusion["提取版本"],
                "批次": conclusion["批次"],
                "总URL数": metrics["总URL数"],
                "成功URL数": metrics["成功URL数"],
                "失败URL数": metrics["失败URL数"],
                "成功率": metrics["成功率"],
                "内容完整率": metrics["内容完整率"],
                "字段覆盖率": metrics["字段覆盖率"],
                "结论等级": conclusion["结论等级"],
                "版本号": conclusion["版本号"],
                "快照编号": conclusion["snapshot_id"],
                "覆盖口径": metrics["覆盖口径"],
                "报告生成时间": conclusion["生成时间"],
                "确认时间": conclusion["确认时间"],
                "status": status,
                "pending": status in {"待确认", "不可确认"},
                "abnormal": status in {"不可确认", "已取代"},
            })
        store.rows(MODULE).clear()
        store.rows(MODULE).extend(rows)

    def ready(self) -> None:
        """把示例源数据算一遍：CRAW-0001 直接给出已确认版本，其余保留待确认边界。

        幂等：重复调用（启动钩子 + 首次请求）只会补算尚无结论的作业。
        """
        for source in self.list_sources():
            job = source["作业编号"]
            if quality_store.list_conclusions(job):
                continue
            generated, _, _ = self.generate({
                "作业编号": job,
                "提取版本": source["提取版本"],
                "请求编号": f"bootstrap-{job}",
            })
            if generated is None:
                continue
            if job == "CRAW-0001" and generated["可确认"]:
                self.confirm(generated["结论编号"], {
                    "操作人": "质量平台初始化",
                    "请求编号": f"bootstrap-confirm-{job}",
                })


service = QualityreportService()
# 导入即就绪：直接跑服务、跑接口测试都能看到同一份示例结论。
service.ready()
