export type Source = {
  作业编号: string
  作业名称?: string
  目标站点?: string
  提取版本?: string
  总URL数: number
  成功URL数: number
  失败URL数: number
  字段核验版本?: string | null
  结构化字段完整率?: number | null
  字段核验状态?: string | null
  已确认版本?: number | null
  已确认结论?: string | null
}

export type MetricItem = { label: string; value: number | null; unit: string }

export type FieldRow = {
  字段名: string
  应填URL数: number
  有值URL数: number
  缺失URL数: number
  完整率: number | null
  缺失URL: string[]
}

export type FailureRow = {
  URL: string
  失败原因码: string
  失败原因: string
  计入方式: string
  缺失字段: string[]
  提取版本: string
}

export type UrlRow = {
  URL: string
  状态: string
  失败原因码: string
  失败原因: string
  缺失字段: string[]
  完整字段数: number
  提取版本: string
}

export type ComparisonRow = {
  指标: string
  已确认值: number | null
  当前值: number | null
  是否一致: boolean
}

export type VersionRow = {
  结论编号: string
  版本号: number
  状态: string
  结论等级: string
  可确认: boolean
  提取版本: string
  批次: string
  snapshot_id: string
  生成时间: string
}

export type Dashboard = {
  作业编号: string
  作业名称?: string
  目标站点?: string
  呈现口径: string
  提取版本: string
  批次: string
  snapshot_id: string | null
  快照生成时间: string | null
  快照校验和: string | null
  已确认: {
    结论编号: string
    版本号: number
    提取版本: string
    批次: string
    snapshot_id: string
    结论等级: string
    确认时间: string | null
    确认人: string | null
  } | null
  指标: Record<string, number | null>
  指标概览: MetricItem[]
  URL计数校验: Record<string, string | number>
  字段覆盖分布: FieldRow[]
  失败URL对照: FailureRow[]
  URL结果: UrlRow[]
  边界标记: string[]
  边界说明: string[]
  边界明细: { code: string; label: string; 说明: string }[]
  结论等级: string
  结论摘要: string
  字段核验核对: Record<string, string | number | null>
  已确认指标核对: ComparisonRow[]
  版本历史: VersionRow[]
  覆盖口径: string
  字段完整率口径: string
}

export type Verification = {
  作业编号: string
  核验清单编号?: string
  提取版本?: string
  结构化字段数?: number
  抽检URL数?: number
  完整字段数?: number
  结构化字段完整率?: number | null
  核验状态?: string
  回写结论编号?: string | null
  回写快照编号?: string | null
  回写版本号?: number | null
  最近回写时间?: string | null
  回写人?: string | null
  质量结论等级?: string | null
  回写批次?: string | null
}
