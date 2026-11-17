import { useCallback, useEffect, useMemo, useState } from 'react'

import { request } from '@/api/client'

import ReportPanel from './ReportPanel'
import type { Dashboard, Source, Verification } from './types'

const ENDPOINT = '/api/qualityreport'

const columns = [
  '报告编号',
  '作业编号',
  '总URL数',
  '成功URL数',
  '失败URL数',
  '内容完整率',
  '字段覆盖率',
  '报告生成时间',
]

const statuses = ['待确认', '不可确认', '已确认', '已取代', '已归档']

const statusLabels = ['质量报告总数', '已确认版本', '待确认版本', '不可确认版本']

type Row = Record<string, string | number | null>

function formatRate(value: number | null | undefined): string {
  if (value === null || value === undefined) return '不可计算'
  return `${value}%`
}

function formatCell(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  return String(value)
}

export default function QualityreportView() {
  const [rows, setRows] = useState<Row[]>([])
  const [total, setTotal] = useState(0)
  const [sources, setSources] = useState<Source[]>([])
  const [verifications, setVerifications] = useState<Verification[]>([])
  const [selectedJob, setSelectedJob] = useState('')
  const [dashboard, setDashboard] = useState<Dashboard | null>(null)
  const [selectedSnapshot, setSelectedSnapshot] = useState('')
  const [errorMessage, setErrorMessage] = useState('')
  const [notice, setNotice] = useState('')
  const [filters, setFilters] = useState<Record<string, string>>({})

  const filterFields = useMemo(() => columns.slice(0, 2), [])

  const loadSources = useCallback(async () => {
    const response = await request(`${ENDPOINT}/sources`)
    if (!response.ok) throw new Error('抓取URL结果读取失败')
    const payload = await response.json()
    const items: Source[] = payload.items ?? []
    setSources(items)
    if (!selectedJob && items.length > 0) setSelectedJob(items[0].作业编号)
  }, [selectedJob])

  const loadVerifications = useCallback(async () => {
    const response = await request(`${ENDPOINT}/field-verifications`)
    if (!response.ok) throw new Error('字段核验清单读取失败')
    const payload = await response.json()
    setVerifications(payload.items ?? [])
  }, [])

  const reload = useCallback(async () => {
    setErrorMessage('')
    const query = new URLSearchParams(filters).toString()
    try {
      const response = await request(`${ENDPOINT}?${query}`)
      if (!response.ok) throw new Error('质量报告列表读取失败')
      const payload = await response.json()
      setRows(payload.items ?? [])
      setTotal(payload.total ?? 0)
      await loadSources()
      await loadVerifications()
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '采集质量列表读取失败')
    }
  }, [filters, loadSources, loadVerifications])

  const loadDashboard = useCallback(async (job: string, snapshotId?: string) => {
    if (!job) {
      setDashboard(null)
      return
    }
    try {
      const query = new URLSearchParams({ job })
      if (snapshotId) query.set('snapshot_id', snapshotId)
      const response = await request(`${ENDPOINT}/dashboard?${query.toString()}`)
      if (!response.ok) throw new Error('质量报告视图读取失败')
      setDashboard(await response.json())
    } catch (error) {
      setDashboard(null)
      setErrorMessage(error instanceof Error ? error.message : '质量报告视图读取失败')
    }
  }, [])

  useEffect(() => {
    void reload()
  }, [reload])

  useEffect(() => {
    void loadDashboard(selectedJob, selectedSnapshot || undefined)
  }, [selectedJob, selectedSnapshot, loadDashboard])

  async function postAction(path: string, values: Record<string, unknown>): Promise<boolean> {
    setErrorMessage('')
    setNotice('')
    try {
      const response = await request(path, {
        method: 'POST',
        body: JSON.stringify({ values }),
      })
      const payload = await response.json().catch(() => ({}))
      if (!response.ok || payload.ok === false) {
        throw new Error(payload.message ?? payload.detail ?? '动作未生效')
      }
      setNotice(payload.message ?? '动作已生效')
      await reload()
      await loadDashboard(selectedJob, selectedSnapshot || undefined)
      return true
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '采集质量操作失败')
      return false
    }
  }

  async function generate() {
    if (!selectedJob) {
      setErrorMessage('请先选择要生成质量结论的作业')
      return
    }
    await postAction(`${ENDPOINT}/generate`, { 作业编号: selectedJob, 请求编号: crypto.randomUUID?.() })
  }

  async function confirmLatest() {
    const latest = dashboard?.版本历史[dashboard.版本历史.length - 1]
    if (!latest) return
    await postAction(`${ENDPOINT}/conclusions/${latest.结论编号}/confirm`, {
      操作人: '值班管理员',
      请求编号: crypto.randomUUID?.(),
    })
  }

  async function archive(row: Row) {
    setErrorMessage('')
    setNotice('')
    try {
      const response = await request(`${ENDPOINT}/${row.id}/actions`, {
        method: 'POST',
        body: JSON.stringify({ values: { action: '归档报告' } }),
      })
      const payload = await response.json().catch(() => ({}))
      if (!response.ok || payload.ok === false) {
        throw new Error(payload.message ?? '归档未生效')
      }
      setNotice(payload.message ?? '已归档')
      await reload()
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '归档失败')
    }
  }

  const stats = useMemo(() => {
    const confirmed = new Set(rows.filter((row) => row.status === '已确认').map((row) => row['作业编号']))
    const pending = rows.filter((row) => row.status === '待确认').length
    const blocked = rows.filter((row) => row.status === '不可确认').length
    return [
      { label: statusLabels[0], value: total },
      { label: statusLabels[1], value: confirmed.size },
      { label: statusLabels[2], value: pending },
      { label: statusLabels[3], value: blocked },
    ]
  }, [rows, total])

  const latestVersion = dashboard?.版本历史[dashboard.版本历史.length - 1]

  return (
    <section className="page" data-module="qualityreport">
      <header className="page-head">
        <div>
          <h2>采集质量管理</h2>
          <p className="page-desc">
            读取抓取URL结果与字段核验清单，汇总成功失败数量并校验字段覆盖，生成可核对的质量结论与报告快照。
          </p>
        </div>
        <div className="page-actions">
          <button className="btn primary" type="button" onClick={() => void generate()}>
            生成质量结论
          </button>
          <button
            className="btn"
            type="button"
            disabled={!latestVersion || !latestVersion.可确认 || latestVersion.状态 === '已确认'}
            onClick={() => void confirmLatest()}
          >
            确认最新版本
          </button>
          <button className="btn" type="button" onClick={() => window.open(`${ENDPOINT}/export`, '_blank')}>
            导出采集质量清单
          </button>
        </div>
      </header>

      <div className="stat-row">
        {stats.map((item) => (
          <article key={item.label} className="stat-card">
            <span className="stat-label">{item.label}</span>
            <strong className="stat-value">{item.value}</strong>
          </article>
        ))}
      </div>

      <section className="panel">
        <header className="panel-head">
          <h3>抓取结果与字段核验来源</h3>
          <span className="panel-hint">URL计数校验：成功URL数 + 失败URL数 = 总URL数</span>
        </header>
        <table className="data-table">
          <thead>
            <tr>
              <th>选取</th>
              <th>作业编号</th>
              <th>作业名称</th>
              <th>总URL数</th>
              <th>成功/失败</th>
              <th>URL提取版本</th>
              <th>字段核验版本</th>
              <th>结构化字段完整率</th>
              <th>已确认版本</th>
            </tr>
          </thead>
          <tbody>
            {sources.map((item) => {
              const addUp = item.成功URL数 + item.失败URL数 === item.总URL数
              return (
                <tr key={item.作业编号} className={selectedJob === item.作业编号 ? 'row-active' : ''}>
                  <td>
                    <input
                      type="radio"
                      name="quality-job"
                      checked={selectedJob === item.作业编号}
                      onChange={() => {
                        setSelectedJob(item.作业编号)
                        setSelectedSnapshot('')
                      }}
                    />
                  </td>
                  <td>{item.作业编号}</td>
                  <td>{item.作业名称 ?? '—'}</td>
                  <td>{item.总URL数}</td>
                  <td>
                    {item.成功URL数} / {item.失败URL数}{' '}
                    <span className={addUp ? 'tag ok' : 'tag bad'}>{addUp ? '合计一致' : '合计不一致'}</span>
                  </td>
                  <td>{formatCell(item.提取版本)}</td>
                  <td>{formatCell(item.字段核验版本)}</td>
                  <td>{formatRate(item.结构化字段完整率)}</td>
                  <td>{item.已确认版本 ? `v${item.已确认版本} ${item.已确认结论 ?? ''}` : '暂无'}</td>
                </tr>
              )
            })}
            {sources.length === 0 && (
              <tr>
                <td className="empty-state" colSpan={9}>尚未读取到抓取URL结果</td>
              </tr>
            )}
          </tbody>
        </table>
      </section>

      {dashboard && (
        <ReportPanel
          dashboard={dashboard}
          selectedSnapshot={selectedSnapshot}
          onSelectSnapshot={setSelectedSnapshot}
          onClearSnapshot={() => setSelectedSnapshot('')}
        />
      )}

      <section className="panel">
        <header className="panel-head">
          <h3>字段核验侧清单（质量结论已回写）</h3>
          <span className="panel-hint">{dashboard?.字段完整率口径 ?? '结构化字段完整率按成功页面统计'}</span>
        </header>
        <table className="data-table">
          <thead>
            <tr>
              <th>作业编号</th>
              <th>核验清单</th>
              <th>提取版本</th>
              <th>核验状态</th>
              <th>抽检URL数</th>
              <th>结构化字段完整率</th>
              <th>回写结论</th>
              <th>回写快照</th>
              <th>回写版本</th>
              <th>回写时间</th>
            </tr>
          </thead>
          <tbody>
            {verifications.map((item) => (
              <tr key={item.作业编号}>
                <td>{item.作业编号}</td>
                <td>{formatCell(item.核验清单编号)}</td>
                <td>{formatCell(item.提取版本)}</td>
                <td>{formatCell(item.核验状态)}</td>
                <td>{formatCell(item.抽检URL数)}</td>
                <td>{formatRate(item.结构化字段完整率)}</td>
                <td>{formatCell(item.回写结论编号)}</td>
                <td className="mono">{formatCell(item.回写快照编号)}</td>
                <td>{item.回写版本号 ? `v${item.回写版本号}` : '—'}</td>
                <td>{formatCell(item.最近回写时间)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="panel">
        <header className="panel-head">
          <h3>质量报告清单</h3>
          <span className="panel-hint">指标由URL结果计算，不接受人工填写</span>
        </header>

        <form className="filter-bar" onSubmit={(event) => { event.preventDefault(); void reload() }}>
          {filterFields.map((field) => (
            <label key={field} className="filter-item">
              <span>{field}</span>
              <input
                value={filters[field] ?? ''}
                placeholder={`按${field}检索`}
                onChange={(event) => setFilters((prev) => ({ ...prev, [field]: event.target.value }))}
              />
            </label>
          ))}
          <label className="filter-item">
            <span>状态</span>
            <select
              value={filters.status ?? ''}
              onChange={(event) => setFilters((prev) => ({ ...prev, status: event.target.value }))}
            >
              <option value="">全部状态</option>
              {statuses.map((status) => (
                <option key={status} value={status}>{status}</option>
              ))}
            </select>
          </label>
          <button className="btn" type="submit">查询</button>
          <button className="btn ghost" type="button" onClick={() => setFilters({})}>重置条件</button>
        </form>

        <table className="data-table">
          <thead>
            <tr>
              {columns.map((column) => <th key={column}>{column}</th>)}
              <th>状态</th>
              <th>结论等级</th>
              <th>版本</th>
              <th>可执行动作</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={String(row.id)}>
                {columns.map((column) => (
                  <td key={column}>
                    {column.endsWith('率') ? formatRate(row[column] as number | null) : formatCell(row[column])}
                  </td>
                ))}
                <td>{formatCell(row.status)}</td>
                <td>{formatCell(row['结论等级'])}</td>
                <td>v{formatCell(row['版本号'])}</td>
                <td className="row-actions">
                  <button
                    className="link"
                    type="button"
                    onClick={() => {
                      setSelectedJob(String(row['作业编号']))
                      setSelectedSnapshot('')
                    }}
                  >
                    查看报告
                  </button>
                  <button
                    className="link"
                    type="button"
                    disabled={row.status === '待确认'}
                    onClick={() => void archive(row)}
                  >
                    归档报告
                  </button>
                </td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr>
                <td className="empty-state" colSpan={columns.length + 4}>暂无质量报告，先选择作业生成质量结论</td>
              </tr>
            )}
          </tbody>
        </table>

        <footer className="page-foot">
          <span>共 {total} 条质量报告记录</span>
          {notice && <span className="notice-text">{notice}</span>}
          {errorMessage && <span className="error-text">{errorMessage}</span>}
        </footer>
      </section>
    </section>
  )
}
