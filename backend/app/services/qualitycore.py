"""采集质量计算内核：口径、校验、结论边界与快照摘要。

这里只放纯函数，不依赖内存仓库，示例数据与业务服务都复用同一套规则，
保证「种子快照」和「运行时生成的快照」算法完全一致。
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable

# 结构化抽取版本固定要求核验的字段集合。
REQUIRED_FIELDS = ["标题", "发布时间", "作者", "正文", "来源"]

# 字段核验侧对外展示的口径说明，与计算内核共用同一套字段集合。
FIELD_SCOPE = "结构化字段完整率 = 成功页面已填字段数 / (成功URL数 × 结构化字段数)"

SUCCESS_STATUS = "成功"
FAILURE_STATUS = "失败"
VALID_STATUSES = {SUCCESS_STATUS, FAILURE_STATUS}

# 失败覆盖口径只允许一个，写死在核心里并进入快照，避免同一作业因口径漂移得出不同结论。
COVERAGE_SCOPE = "全量URL计入分母，失败URL按零覆盖计"

BOUNDARY_LABELS: dict[str, str] = {
    "ZERO_URL": "零URL",
    "ALL_FAILED": "全部失败",
    "PARTIAL_FAILURE": "部分失败",
    "FIELD_MISSING": "字段缺失",
    "VERSION_CONFLICT": "提取版本冲突",
    "FIELD_VERIFICATION_MISSING": "字段核验缺失",
    "RATE_MISMATCH": "完整率核对不一致",
    "COUNT_MISMATCH": "URL计数不一致",
    "UNKNOWN_STATUS": "URL状态无法识别",
}

BOUNDARY_NOTES: dict[str, str] = {
    "ZERO_URL": "作业没有可评估的URL结果，按零URL边界记为不可评估，补齐结果后重算生成新版本。",
    "ALL_FAILED": "全部URL均失败，成功页完整率无处计算，作业质量判为不合格。",
    "PARTIAL_FAILURE": "部分URL失败，失败URL按零覆盖计入全量分母，结论同时保留成功页完整率用于核对。",
    "FIELD_MISSING": "成功页面存在结构化字段缺失，内容完整率未达满分，字段覆盖分布会列出缺失URL。",
    "VERSION_CONFLICT": "URL结果的提取版本与字段核验的提取版本不一致，结论落入各自批次且不可确认。",
    "FIELD_VERIFICATION_MISSING": "缺少对应提取版本的字段核验记录，无法取得结构化字段完整率，结论不可评估。",
    "RATE_MISMATCH": "字段核验侧申报的结构化字段完整率与URL结果重算值不一致，需要先对齐再确认。",
    "COUNT_MISMATCH": "成功URL数与失败URL数之和与总URL数不一致，指标不可计算。",
    "UNKNOWN_STATUS": "存在无法识别的URL状态，已按失败计入并标记边界。",
}

# 这些边界让指标本身算不出来，结论只能记为不可评估。
UNEVALUABLE_BOUNDARIES = {"ZERO_URL", "VERSION_CONFLICT", "FIELD_VERIFICATION_MISSING"}

# 这些边界让结论失去确认资格：要么不可评估，要么源数据自相矛盾。
UNCONFIRMABLE_BOUNDARIES = UNEVALUABLE_BOUNDARIES | {"RATE_MISMATCH"}

CONCLUSION_LEVELS = ["优秀", "良好", "合格", "不合格", "不可评估"]


def canonical_json(value: Any) -> str:
    """稳定序列化：同一份输入永远得到同一段字符串，幂等摘要依赖它。"""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _field_present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict, tuple, set)):
        return len(value) > 0
    return True


def _percent(numerator: float, denominator: float) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator * 100, 2)


def normalize_url_rows(urls: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """把URL结果拍平成可序列化的结构，供摘要、快照和追溯列表共用。"""
    normalized: list[dict[str, Any]] = []
    for row in urls:
        fields = row.get("字段") or row.get("fields") or {}
        normalized.append({
            "URL": str(row.get("URL") or row.get("url") or ""),
            "提取版本": str(row.get("提取版本") or row.get("extraction_version") or ""),
            "状态": str(row.get("状态") or row.get("status") or ""),
            "失败原因码": str(row.get("失败原因码") or row.get("reason_code") or ""),
            "失败原因": str(row.get("失败原因") or row.get("reason") or ""),
            "字段": {str(key): fields[key] for key in fields},
        })
    return normalized


def compute_digest(
    job: str,
    extraction_version: str,
    urls: Iterable[dict[str, Any]],
    field_record: dict[str, Any] | None,
) -> str:
    """输入摘要：同一作业、同一提取版本、同一批URL结果与字段核验只允许生效一次。"""
    normalized = normalize_url_rows(urls)
    normalized.sort(key=lambda item: (item["提取版本"], item["URL"], item["状态"]))
    payload = {
        "作业编号": job,
        "提取版本": extraction_version,
        "覆盖口径": COVERAGE_SCOPE,
        "字段集合": REQUIRED_FIELDS,
        "URL结果": [
            {
                "URL": row["URL"],
                "提取版本": row["提取版本"],
                "状态": row["状态"],
                "失败原因码": row["失败原因码"],
                "失败原因": row["失败原因"],
                "字段": row["字段"],
            }
            for row in normalized
        ],
        "字段核验": None if field_record is None else {
            "提取版本": str(field_record.get("提取版本") or ""),
            "结构化字段数": field_record.get("结构化字段数"),
            "完整字段数": field_record.get("完整字段数"),
            "结构化字段完整率": field_record.get("结构化字段完整率"),
            "抽检URL数": field_record.get("抽检URL数"),
        },
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def snapshot_checksum(snapshot: dict[str, Any]) -> str:
    payload = {key: value for key, value in snapshot.items() if key != "校验和"}
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _conclusion_level(
    boundaries: list[str],
    success_rate: float | None,
    content_rate: float | None,
) -> str:
    if any(code in UNEVALUABLE_BOUNDARIES for code in boundaries):
        return "不可评估"
    if success_rate is None or content_rate is None:
        return "不可评估"
    if success_rate == 0:
        return "不合格"
    if success_rate >= 99 and content_rate >= 98:
        return "优秀"
    if success_rate >= 95 and content_rate >= 90:
        return "良好"
    if success_rate >= 80 and content_rate >= 70:
        return "合格"
    return "不合格"


def _summary(
    *,
    level: str,
    total: int,
    success: int,
    failure: int,
    success_rate: float | None,
    content_rate: float | None,
    success_completeness: float | None,
    field_coverage: float | None,
    boundaries: list[str],
    extraction_version: str,
    field_version: str | None,
    version_distribution: dict[str, int],
) -> str:
    if "ZERO_URL" in boundaries:
        return "零URL：作业没有可评估的URL结果，结论记为不可评估；补齐结果后重算会生成新版本，历史快照不改写。"
    if "VERSION_CONFLICT" in boundaries:
        return (
            f"版本冲突：URL结果提取版本 {version_distribution or '未标注'}，"
            f"字段核验提取版本 {field_version or '未标注'}，结论落入各自批次且不可确认；"
            "需对齐提取版本后重新生成。"
        )
    if "FIELD_VERIFICATION_MISSING" in boundaries:
        return f"字段核验缺失：没有提取版本 {extraction_version or '未标注'} 的核验记录，结构化字段完整率不可得，结论不可评估。"
    failure_rate_part = f"失败 {failure} 个（按零覆盖计入全量分母）"
    return (
        f"共 {total} 个URL：成功 {success} 个、失败 {failure} 个，"
        f"成功+失败={success + failure}，与总URL数一致；{failure_rate_part}；"
        f"成功率 {success_rate}%，内容完整率（全量口径）{content_rate}%，"
        f"{'成功页完整率 ' + str(success_completeness) + '%' if success_completeness is not None else '成功页完整率不可计算'}，"
        f"{'字段覆盖率 ' + str(field_coverage) + '%' if field_coverage is not None else '字段覆盖率不可计算'}；"
        f"结论：{level}。"
    )


def compute_quality(
    job: str,
    extraction_version: str,
    urls: Iterable[dict[str, Any]],
    field_record: dict[str, Any] | None,
) -> dict[str, Any]:
    """按固定口径汇总URL结果，产出指标、字段分布、失败对照与结论边界。"""
    job_urls = normalize_url_rows(urls)
    version_distribution: dict[str, int] = {}
    for row in job_urls:
        version = row["提取版本"] or "未标注"
        version_distribution[version] = version_distribution.get(version, 0) + 1

    field_record_version = None if field_record is None else str(field_record.get("提取版本") or "")
    version_mismatch = len(job_urls) > 0 and any(
        row["提取版本"] != extraction_version for row in job_urls
    )
    if version_mismatch:
        # 版本冲突时不能悄悄按单一版本切片，否则总URL数会与原始结果不一致；
        # 全量参与计数并标记冲突，结论不可确认、不可当成对外口径。
        compatible = list(job_urls)
    else:
        compatible = [row for row in job_urls if row["提取版本"] == extraction_version]
    boundaries: list[str] = []

    if not job_urls:
        boundaries.append("ZERO_URL")
    elif version_mismatch:
        boundaries.append("VERSION_CONFLICT")
    if field_record is None:
        boundaries.append("FIELD_VERIFICATION_MISSING")
    elif field_record_version != extraction_version:
        if "VERSION_CONFLICT" not in boundaries:
            boundaries.append("VERSION_CONFLICT")

    total = len(compatible)
    success_rows = [row for row in compatible if row["状态"] == SUCCESS_STATUS]
    unknown_rows = [row for row in compatible if row["状态"] not in VALID_STATUSES]
    success = len(success_rows)
    failure = total - success
    if unknown_rows:
        boundaries.append("UNKNOWN_STATUS")
    # 成功 + 失败必须恒等于总URL数；这里显式校验，任何不一致都要让结论失效。
    if success + failure != total:
        boundaries.append("COUNT_MISMATCH")
    if total and failure and success:
        boundaries.append("PARTIAL_FAILURE")
    elif total and success == 0:
        boundaries.append("ALL_FAILED")

    field_count = len(REQUIRED_FIELDS)
    complete_cells = 0
    field_present: dict[str, int] = {field: 0 for field in REQUIRED_FIELDS}
    url_details: list[dict[str, Any]] = []
    failure_rows: list[dict[str, Any]] = []

    for row in compatible:
        fields = row["字段"]
        missing = [field for field in REQUIRED_FIELDS if not _field_present(fields.get(field))]
        is_success = row["状态"] == SUCCESS_STATUS
        if is_success:
            complete_cells += field_count - len(missing)
            for field in REQUIRED_FIELDS:
                if field not in missing:
                    field_present[field] += 1
        else:
            failure_rows.append({
                "URL": row["URL"],
                "失败原因码": row["失败原因码"] or "UNKNOWN",
                "失败原因": row["失败原因"] or "未提供失败原因",
                "计入方式": "按零覆盖计入全量完整率",
                "缺失字段": missing,
                "提取版本": row["提取版本"],
            })
        url_details.append({
            "URL": row["URL"],
            "状态": row["状态"] or "未标注",
            "失败原因码": row["失败原因码"],
            "失败原因": row["失败原因"],
            "缺失字段": missing,
            "完整字段数": field_count - len(missing),
            "提取版本": row["提取版本"],
        })

    required_cells = total * field_count
    content_rate = _percent(complete_cells, required_cells)
    success_completeness = _percent(complete_cells, success * field_count)
    success_rate = _percent(success, total)
    covered_fields = sum(1 for field in REQUIRED_FIELDS if field_present[field] > 0)
    # 没有成功页面时字段覆盖率无从谈起，按不可计算处理，不能写成 0% 误导质量人员。
    field_coverage = _percent(covered_fields, field_count) if success else None

    if success and complete_cells < success * field_count:
        boundaries.append("FIELD_MISSING")

    declared_rate = None if field_record is None else field_record.get("结构化字段完整率")
    rate_matches: bool | None = None
    if declared_rate is not None and success_completeness is not None:
        rate_matches = abs(float(declared_rate) - success_completeness) <= 0.01
        if not rate_matches:
            boundaries.append("RATE_MISMATCH")

    level = _conclusion_level(boundaries, success_rate, content_rate)

    field_distribution = []
    for field in REQUIRED_FIELDS:
        present = field_present[field]
        missing_urls = [
            detail["URL"] for detail in url_details
            if detail["状态"] == SUCCESS_STATUS and field in detail["缺失字段"]
        ]
        field_distribution.append({
            "字段名": field,
            "应填URL数": success,
            "有值URL数": present,
            "缺失URL数": success - present,
            "完整率": _percent(present, success),
            "缺失URL": missing_urls,
        })

    field_check = {
        "提取版本": None if field_record is None else str(field_record.get("提取版本") or ""),
        "申报完整率": declared_rate,
        "计算完整率": success_completeness,
        "核对结果": (
            "一致" if rate_matches
            else "不一致" if rate_matches is False
            else "无法核对"
        ),
        "申报抽检URL数": None if field_record is None else field_record.get("抽检URL数"),
        "申报完整字段数": None if field_record is None else field_record.get("完整字段数"),
    }

    metrics = {
        "总URL数": total,
        "成功URL数": success,
        "失败URL数": failure,
        "成功率": success_rate,
        "内容完整率": content_rate,
        "成功页完整率": success_completeness,
        "字段覆盖率": field_coverage,
        "结构化字段数": field_count,
        "完整字段数": complete_cells,
        "应填字段数": required_cells,
        "覆盖口径": COVERAGE_SCOPE,
    }

    summary = _summary(
        level=level,
        total=total,
        success=success,
        failure=failure,
        success_rate=success_rate,
        content_rate=content_rate,
        success_completeness=success_completeness,
        field_coverage=field_coverage,
        boundaries=boundaries,
        extraction_version=extraction_version,
        field_version=field_check["提取版本"],
        version_distribution=version_distribution,
    )

    batch_version = extraction_version or "未指定"
    return {
        "作业编号": job,
        "提取版本": extraction_version,
        "批次": f"BATCH-{batch_version}",
        "版本分布": version_distribution,
        "指标": metrics,
        "URL计数校验": {
            "总URL数": total,
            "成功URL数": success,
            "失败URL数": failure,
            "校验": "通过" if success + failure == total else "不通过",
        },
        "字段覆盖分布": field_distribution,
        "失败URL对照": failure_rows,
        "URL结果": url_details,
        "边界标记": boundaries,
        "边界说明": [BOUNDARY_NOTES[code] for code in boundaries if code in BOUNDARY_NOTES],
        "结论等级": level,
        "结论摘要": summary,
        "字段核验核对": field_check,
        "版本一致": "VERSION_CONFLICT" not in boundaries,
    }


def build_snapshot(
    *,
    snapshot_id: str,
    conclusion_id: str,
    result: dict[str, Any],
    created_at: str,
    version_no: int,
) -> dict[str, Any]:
    """把一次计算结果固化成不可变快照；快照一旦生成只读不写。"""
    snapshot: dict[str, Any] = {
        "snapshot_id": snapshot_id,
        "结论编号": conclusion_id,
        "版本号": version_no,
        "作业编号": result["作业编号"],
        "提取版本": result["提取版本"],
        "批次": result["批次"],
        "结论等级": result["结论等级"],
        "结论摘要": result["结论摘要"],
        "边界标记": list(result["边界标记"]),
        "指标": dict(result["指标"]),
        "URL计数校验": dict(result["URL计数校验"]),
        "字段覆盖分布": [dict(item, 缺失URL=list(item["缺失URL"])) for item in result["字段覆盖分布"]],
        "失败URL对照": [dict(item, 缺失字段=list(item["缺失字段"])) for item in result["失败URL对照"]],
        "URL结果": [dict(item, 缺失字段=list(item["缺失字段"])) for item in result["URL结果"]],
        "字段核验核对": dict(result["字段核验核对"]),
        "版本分布": dict(result["版本分布"]),
        "覆盖口径": COVERAGE_SCOPE,
        "生成时间": created_at,
    }
    snapshot["校验和"] = snapshot_checksum(snapshot)
    return snapshot


def compare_metrics(
    confirmed: dict[str, Any],
    current: dict[str, Any],
) -> list[dict[str, Any]]:
    """已确认指标与当前源数据重算值的逐项核对，漂移只展示、不回写历史。"""
    keys = ["总URL数", "成功URL数", "失败URL数", "成功率", "内容完整率", "字段覆盖率", "成功页完整率"]
    rows: list[dict[str, Any]] = []
    for key in keys:
        left = confirmed.get(key)
        right = current.get(key)
        if isinstance(left, (int, float)) and isinstance(right, (int, float)):
            same = abs(float(left) - float(right)) <= 0.01
        else:
            same = left == right
        rows.append({
            "指标": key,
            "已确认值": left,
            "当前值": right,
            "是否一致": same,
        })
    return rows
