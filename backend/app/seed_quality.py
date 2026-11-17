"""采集质量示例源数据：URL抓取结果与字段核验清单。

URL结果、字段核验、提取版本三者都齐备，质量结论才能计算；
示例里特意覆盖了部分失败、零URL、版本冲突、全部失败、字段核验缺失几种边界。
"""
from __future__ import annotations

from typing import Any

from app.services.qualitycore import FIELD_SCOPE, REQUIRED_FIELDS

__all__ = ["FIELD_SCOPE", "REQUIRED_FIELDS", "SEED_FIELD_VERIFICATIONS", "SEED_URL_RESULTS"]


def _fields(
    title: str | None,
    published_at: str | None,
    author: str | None,
    body: str | None,
    source: str | None,
) -> dict[str, Any]:
    return {
        "标题": title,
        "发布时间": published_at,
        "作者": author,
        "正文": body,
        "来源": source,
    }


def _url(
    url: str,
    version: str,
    status: str,
    fields: dict[str, Any] | None = None,
    reason_code: str = "",
    reason: str = "",
) -> dict[str, Any]:
    return {
        "URL": url,
        "提取版本": version,
        "状态": status,
        "失败原因码": reason_code,
        "失败原因": reason,
        "字段": fields or {},
    }


SEED_URL_RESULTS: list[dict[str, Any]] = [
    {
        "作业编号": "CRAW-0001",
        "作业名称": "行业资讯日更",
        "目标站点": "news.example.com",
        "提取版本": "CONT-0001",
        "结果批次": "RUN-20260901-01",
        "抓取时间": "2026-09-01T08:30:00+08:00",
        "URL结果": [
            _url(
                "https://news.example.com/a/1001", "CONT-0001", "成功",
                _fields("算力中心扩容", "2026-09-01", "王琳", "算力中心完成二期扩容……", "行业观察"),
            ),
            _url(
                "https://news.example.com/a/1002", "CONT-0001", "成功",
                _fields("边缘节点落地", "2026-09-01", "陈默", "边缘节点在一线城市完成部署……", "行业观察"),
            ),
            _url(
                "https://news.example.com/a/1003", "CONT-0001", "成功",
                _fields("采集框架对比", "2026-09-01", "李响", "三款采集框架的吞吐与召回对比……", "技术周刊"),
            ),
            _url(
                "https://news.example.com/a/1004", "CONT-0001", "成功",
                _fields("调度队列优化", "2026-09-01", None, "调度队列引入分级重试……", "技术周刊"),
            ),
            _url(
                "https://news.example.com/a/1005", "CONT-0001", "成功",
                _fields("反爬策略复盘", "2026-09-01", None, "反爬策略按月复盘……", None),
            ),
            _url(
                "https://news.example.com/a/1006", "CONT-0001", "失败",
                reason_code="HTTP_504", reason="网关超时，重试 2 次仍未成功",
            ),
        ],
    },
    {
        "作业编号": "CRAW-0002",
        "作业名称": "竞品价格巡检",
        "目标站点": "price.example.com",
        "提取版本": "CONT-0002",
        "结果批次": "RUN-20260902-01",
        "抓取时间": "2026-09-02T09:00:00+08:00",
        "URL结果": [],
    },
    {
        "作业编号": "CRAW-0003",
        "作业名称": "政策法规订阅",
        "目标站点": "policy.example.com",
        "提取版本": "CONT-0003",
        "结果批次": "RUN-20260903-01",
        "抓取时间": "2026-09-03T07:45:00+08:00",
        "URL结果": [
            _url(
                "https://policy.example.com/notice/2001", "CONT-0003", "成功",
                _fields("数据出境新规", "2026-09-03", "政策研究室", "数据出境安全评估办法更新……", "官方公报"),
            ),
            _url(
                "https://policy.example.com/notice/2002", "CONT-0003", "成功",
                _fields("采集合规指引", "2026-09-03", "政策研究室", "采集合规操作指引发布……", "官方公报"),
            ),
            # 同一次运行里混入了旧提取版本，结论会落进 BATCH-CONT-0003 之外的另一批次。
            _url(
                "https://policy.example.com/notice/2003", "CONT-0002", "成功",
                _fields("爬虫备案口径", "2026-09-03", "政策研究室", "爬虫备案口径补充说明……", "官方公报"),
            ),
        ],
    },
    {
        "作业编号": "CRAW-0004",
        "作业名称": "展会日历同步",
        "目标站点": "expo.example.com",
        "提取版本": "CONT-0001",
        "结果批次": "RUN-20260904-01",
        "抓取时间": "2026-09-04T10:20:00+08:00",
        "URL结果": [
            _url(
                "https://expo.example.com/2026/spring", "CONT-0001", "失败",
                reason_code="DNS_FAIL", reason="域名解析失败，连续 3 次超时",
            ),
            _url(
                "https://expo.example.com/2026/autumn", "CONT-0001", "失败",
                reason_code="HTTP_403", reason="目标站点拒绝访问，命中反爬",
            ),
        ],
    },
    {
        "作业编号": "CRAW-0006",
        "作业名称": "舆情快照抽取",
        "目标站点": "opinion.example.com",
        "提取版本": "CONT-0006",
        "结果批次": "RUN-20260906-01",
        "抓取时间": "2026-09-06T08:50:00+08:00",
        "URL结果": [
            _url(
                "https://opinion.example.com/post/3001", "CONT-0006", "成功",
                _fields("首条舆情", "2026-09-06", "监测组", "首条舆情摘要……", "舆情系统"),
            ),
            _url(
                "https://opinion.example.com/post/3002", "CONT-0006", "成功",
                _fields("第二条舆情", "2026-09-06", None, "第二条舆情摘要……", "舆情系统"),
            ),
        ],
    },
    {
        "作业编号": "CRAW-0005",
        "作业名称": "开源仓库追踪",
        "目标站点": "repo.example.com",
        "提取版本": "CONT-0009",
        "结果批次": "RUN-20260905-01",
        "抓取时间": "2026-09-05T11:10:00+08:00",
        "URL结果": [
            _url(
                "https://repo.example.com/projects/alpha", "CONT-0009", "成功",
                _fields("alpha 项目", "2026-09-05", "社区维护组", "alpha 项目发布 2.0……", "代码托管"),
            ),
            _url(
                "https://repo.example.com/projects/beta", "CONT-0009", "成功",
                _fields("beta 项目", "2026-09-05", "社区维护组", "beta 项目补齐文档……", "代码托管"),
            ),
            _url(
                "https://repo.example.com/projects/gamma", "CONT-0009", "成功",
                _fields("gamma 项目", "2026-09-05", "社区维护组", "gamma 项目迁移仓库……", "代码托管"),
            ),
        ],
    },
]


SEED_FIELD_VERIFICATIONS: list[dict[str, Any]] = [
    {
        "作业编号": "CRAW-0001",
        "提取版本": "CONT-0001",
        "核验清单编号": "FV-0001",
        "结构化字段数": 5,
        "抽检URL数": 5,
        "完整字段数": 22,
        "结构化字段完整率": 88.0,
        "核验状态": "已核验",
        "核验时间": "2026-09-01T09:10:00+08:00",
        "回写结论编号": None,
        "回写快照编号": None,
        "最近回写时间": None,
        "回写人": None,
    },
    {
        "作业编号": "CRAW-0002",
        "提取版本": "CONT-0002",
        "核验清单编号": "FV-0002",
        "结构化字段数": 5,
        "抽检URL数": 0,
        "完整字段数": 0,
        "结构化字段完整率": None,
        "核验状态": "待核验",
        "核验时间": "2026-09-02T09:30:00+08:00",
        "回写结论编号": None,
        "回写快照编号": None,
        "最近回写时间": None,
        "回写人": None,
    },
    {
        "作业编号": "CRAW-0003",
        "提取版本": "CONT-0003",
        "核验清单编号": "FV-0003",
        "结构化字段数": 5,
        "抽检URL数": 3,
        "完整字段数": 15,
        "结构化字段完整率": 100.0,
        "核验状态": "已核验",
        "核验时间": "2026-09-03T08:20:00+08:00",
        "回写结论编号": None,
        "回写快照编号": None,
        "最近回写时间": None,
        "回写人": None,
    },
    {
        "作业编号": "CRAW-0004",
        "提取版本": "CONT-0001",
        "核验清单编号": "FV-0004",
        "结构化字段数": 5,
        "抽检URL数": 0,
        "完整字段数": 0,
        "结构化字段完整率": None,
        "核验状态": "无可核验页面",
        "核验时间": "2026-09-04T10:50:00+08:00",
        "回写结论编号": None,
        "回写快照编号": None,
        "最近回写时间": None,
        "回写人": None,
    },
    {
        "作业编号": "CRAW-0006",
        "提取版本": "CONT-0006",
        "核验清单编号": "FV-0006",
        "结构化字段数": 5,
        "抽检URL数": 2,
        "完整字段数": 10,
        "结构化字段完整率": 100.0,
        "核验状态": "已核验",
        "核验时间": "2026-09-06T09:00:00+08:00",
        "回写结论编号": None,
        "回写快照编号": None,
        "最近回写时间": None,
        "回写人": None,
    },
    # CRAW-0005 没有 CONT-0009 的核验记录：字段核验缺失边界。
]
