"""采集质量接口：读取抓取结果、生成质量结论与报告快照、确认/归档、回写字段核验清单。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.quality_store import quality_store
from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.qualityreport import service
from app.services.qualitycore import BOUNDARY_LABELS, COVERAGE_SCOPE

router = APIRouter(prefix="/api/qualityreport", tags=["采集质量"])

STATUSES = ["待确认", "不可确认", "已确认", "已取代", "已归档"]
ACTIONS = ["归档报告"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按报告编号或作业编号检索"),
    status: str | None = Query(default=None, description="待确认、不可确认、已确认、已取代、已归档"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按报告编号与状态过滤采集质量列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/meta")
def meta() -> dict[str, Any]:
    """把状态、边界、口径与可执行动作一次给前端，避免页面写死文案。"""
    return {
        "statuses": STATUSES,
        "actions": ACTIONS,
        "boundaries": [{"code": code, "label": label} for code, label in BOUNDARY_LABELS.items()],
        "coverage_scope": COVERAGE_SCOPE,
        "id_semantics": "报告编号由结论编号派生，同一作业的不同版本共用作业编号、各自独立报告编号",
    }


@router.get("/sources")
def list_sources() -> dict[str, Any]:
    """读取抓取URL结果与结构化字段核验清单，供生成结论前核对。"""
    items = service.list_sources()
    return {"total": len(items), "items": items}


@router.get("/field-verifications")
def list_field_verifications() -> dict[str, Any]:
    """字段核验侧清单：包含结构化字段完整率与最近一次质量结论回写。"""
    items = quality_store.list_field_verifications()
    return {"total": len(items), "items": items}


@router.post("/sources/{job}/url-results", response_model=ActionResult)
def refresh_url_results(job: str, payload: EntryPayload) -> ActionResult:
    """重新读取某个作业的抓取URL结果；只更新源数据，历史结论与快照不改写。"""
    record = payload.values.get("record")
    if not isinstance(record, dict):
        return ActionResult(ok=False, message="缺少 record：需要提供本次读取到的URL结果")
    updated = quality_store.replace_url_results(job, record)
    if updated is None:
        return ActionResult(ok=False, message=f"作业 {job} 不在URL结果清单里，请先登记来源")
    return ActionResult(ok=True, message="URL结果已更新，请重新生成质量结论以产生新版本", entry=updated)


@router.post("/sources/{job}/field-verification", response_model=ActionResult)
def refresh_field_verification(job: str, payload: EntryPayload) -> ActionResult:
    """重新读取字段核验记录（含结构化字段完整率申报值）。"""
    record = payload.values.get("record")
    if not isinstance(record, dict):
        return ActionResult(ok=False, message="缺少 record：需要提供字段核验清单内容")
    updated = quality_store.replace_field_verification(job, record)
    if updated is None:
        return ActionResult(ok=False, message=f"作业 {job} 没有字段核验清单记录")
    return ActionResult(ok=True, message="字段核验记录已更新，重算后会写入新的质量结论", entry=updated)


@router.get("/dashboard")
def dashboard(
    job: str = Query(..., description="作业编号"),
    snapshot_id: str | None = Query(default=None, description="指定快照；缺省读取已确认快照"),
) -> dict[str, Any]:
    """质量报告视图：指标概览、字段覆盖分布、失败URL对照与已确认指标核对。"""
    payload = service.dashboard(job, snapshot_id)
    if payload is None:
        raise HTTPException(status_code=404, detail=f"作业 {job} 没有可呈现的质量报告")
    return payload


@router.get("/conclusions")
def list_conclusions(job: str | None = Query(default=None)) -> dict[str, Any]:
    """质量结论版本列表：同一作业按版本号排序，历史版本只读。"""
    items = service.list_conclusions(job)
    return {"total": len(items), "items": items}


@router.get("/conclusions/{conclusion_id}")
def get_conclusion(conclusion_id: str) -> dict[str, Any]:
    payload = service.get_conclusion(conclusion_id)
    if payload is None:
        raise HTTPException(status_code=404, detail=f"质量结论 {conclusion_id} 不存在")
    return payload


@router.post("/generate", response_model=ActionResult)
def generate(payload: EntryPayload) -> ActionResult:
    """读取URL结果与字段核验，计算指标并固化报告快照；同一份输入只生效一次。"""
    entry, message, reused = service.generate(payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=not reused, message=message, entry=entry)


@router.post("/conclusions/{conclusion_id}/confirm", response_model=ActionResult)
def confirm(conclusion_id: str, payload: EntryPayload) -> ActionResult:
    """确认质量结论：同一作业只保留一个已确认版本，快照回写字段核验清单。"""
    entry, message, reused = service.confirm(conclusion_id, payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=not reused, message=message, entry=entry)


@router.get("/snapshots")
def list_snapshots(job: str | None = Query(default=None)) -> dict[str, Any]:
    items = service.list_snapshots(job)
    return {"total": len(items), "items": items}


@router.get("/snapshots/{snapshot_id}")
def get_snapshot(snapshot_id: str) -> dict[str, Any]:
    payload = service.get_snapshot(snapshot_id)
    if payload is None:
        raise HTTPException(status_code=404, detail=f"报告快照 {snapshot_id} 不存在")
    return payload


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出采集质量清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "qualityreport", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条质量报告明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"质量报告 {entry_id} 不存在或已归档")
    return entry


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条质量报告执行归档；归档不改变快照内容，只改状态。"""
    action = str(payload.values.get("action") or "").strip()
    if action != "归档报告":
        return ActionResult(ok=False, message=f"动作「{action}」不属于采集质量可执行范围")
    entry, message = service.archive(entry_id)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
