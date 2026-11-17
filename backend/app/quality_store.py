"""采集质量扩展仓库：URL结果、字段核验清单、质量结论与报告快照。

与 app.store 一样是进程内实现，但这里额外保存了「已确认」这一层：
快照一经确认就只读，后续重算写新版本，不会覆盖历史。
"""
from __future__ import annotations

import copy
import threading
from typing import Any

from app.seed_quality import (
    FIELD_SCOPE,
    REQUIRED_FIELDS,
    SEED_FIELD_VERIFICATIONS,
    SEED_URL_RESULTS,
)


class QualityStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.url_results: dict[str, dict[str, Any]] = {
            str(item["作业编号"]): self._copy(item) for item in SEED_URL_RESULTS
        }
        self.field_verifications: dict[str, dict[str, Any]] = {
            str(item["作业编号"]): self._copy(item) for item in SEED_FIELD_VERIFICATIONS
        }
        self.conclusions: list[dict[str, Any]] = []
        self.snapshots: list[dict[str, Any]] = []
        # 幂等键 -> 已执行的结论编号；重复提交直接返回同一结果。
        self.idempotency: dict[str, str] = {}
        self._sequence = 0

    @staticmethod
    def _copy(value: dict[str, Any]) -> dict[str, Any]:
        """深拷贝：调用方拿到的永远是副本，改不动仓库里的快照。"""
        return copy.deepcopy(value)

    # -- 读 -------------------------------------------------------------
    def get_url_results(self, job: str) -> dict[str, Any] | None:
        with self._lock:
            row = self.url_results.get(job)
            return self._copy(row) if row is not None else None

    def list_url_results(self) -> list[dict[str, Any]]:
        with self._lock:
            return [self._copy(row) for row in self.url_results.values()]

    def get_field_verification(self, job: str) -> dict[str, Any] | None:
        with self._lock:
            row = self.field_verifications.get(job)
            return self._copy(row) if row is not None else None

    def list_field_verifications(self) -> list[dict[str, Any]]:
        with self._lock:
            return [self._copy(row) for row in self.field_verifications.values()]

    def find_conclusion(self, conclusion_id: str) -> dict[str, Any] | None:
        with self._lock:
            for row in self.conclusions:
                if row["结论编号"] == conclusion_id:
                    return self._deep_copy(row)
            return None

    def list_conclusions(self, job: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            rows = [
                self._deep_copy(row) for row in self.conclusions
                if job is None or row["作业编号"] == job
            ]
        return sorted(rows, key=lambda row: (row["作业编号"], row["版本号"], row["生成时间"]))

    def confirmed_conclusion(self, job: str) -> dict[str, Any] | None:
        with self._lock:
            candidates = [
                row for row in self.conclusions
                if row["作业编号"] == job and row["状态"] == "已确认"
            ]
        if not candidates:
            return None
        # 每个作业至多一个已确认版本；若出现多个说明历史数据被污染，取版本号最大者并暴露出来。
        return self._deep_copy(max(candidates, key=lambda row: row["版本号"]))

    def list_snapshots(self, job: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            rows = [
                self._deep_copy(row) for row in self.snapshots
                if job is None or row["作业编号"] == job
            ]
        return sorted(rows, key=lambda row: (row["作业编号"], row["版本号"]))

    def find_snapshot(self, snapshot_id: str) -> dict[str, Any] | None:
        with self._lock:
            for row in self.snapshots:
                if row["snapshot_id"] == snapshot_id:
                    return self._deep_copy(row)
            return None

    # -- 写（全部在锁内完成）-------------------------------------------
    @staticmethod
    def _deep_copy(value: dict[str, Any]) -> dict[str, Any]:
        return copy.deepcopy(value)

    def raw_conclusion(self, conclusion_id: str) -> dict[str, Any] | None:
        """只给业务层在持锁状态下改状态用；路由与展示一律走 find_conclusion 拿副本。"""
        with self._lock:
            for row in self.conclusions:
                if row["结论编号"] == conclusion_id:
                    return row
            return None

    def next_sequence(self) -> int:
        with self._lock:
            self._sequence += 1
            return self._sequence

    def latest_version(self, job: str) -> int:
        with self._lock:
            return max(
                (int(row.get("版本号", 0)) for row in self.conclusions if row["作业编号"] == job),
                default=0,
            )

    def lock(self) -> threading.RLock:
        return self._lock

    def add_conclusion(self, conclusion: dict[str, Any]) -> None:
        with self._lock:
            self.conclusions.append(conclusion)

    def add_snapshot(self, snapshot: dict[str, Any]) -> None:
        with self._lock:
            self.snapshots.append(snapshot)

    def bind_idempotency(self, key: str, conclusion_id: str) -> None:
        with self._lock:
            self.idempotency[key] = conclusion_id

    def lookup_idempotency(self, key: str) -> str | None:
        with self._lock:
            return self.idempotency.get(key)

    def write_back_field_verification(self, job: str, patch: dict[str, Any]) -> dict[str, Any] | None:
        with self._lock:
            row = self.field_verifications.get(job)
            if row is None:
                return None
            row.update(patch)
            return self._copy(row)

    def replace_url_results(self, job: str, record: dict[str, Any]) -> dict[str, Any] | None:
        """重新读取抓取结果：只改源数据，已生成的结论与快照一律不动。"""
        with self._lock:
            if job not in self.url_results:
                return None
            self.url_results[job] = self._copy({**record, "作业编号": job})
            return self._copy(self.url_results[job])

    def replace_field_verification(self, job: str, record: dict[str, Any]) -> dict[str, Any] | None:
        with self._lock:
            if job not in self.field_verifications:
                return None
            self.field_verifications[job] = self._copy({**record, "作业编号": job})
            return self._copy(self.field_verifications[job])


quality_store = QualityStore()

__all__ = [
    "FIELD_SCOPE",
    "REQUIRED_FIELDS",
    "QualityStore",
    "quality_store",
]
