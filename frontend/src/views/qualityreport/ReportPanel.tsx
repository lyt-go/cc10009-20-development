import type { Dashboard } from './types'

type Props = {
  dashboard: Dashboard
  selectedSnapshot: string
  onSelectSnapshot: (snapshotId: string) => void
  onClearSnapshot: () => void
}

function formatRate(value: number | null | undefined): string {
  if (value === null || value === undefined) return '不可计算'
  return `${value}%`
}

function formatCell(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  return String(value)
}

export default function ReportPanel({ dashboard, selectedSnapshot, onSelectSnapshot, onClearSnapshot }: Props) {
  return (
    <section className="panel" data-testid="quality-dashboard">
      <header className="panel-head">
        <h3>
          质量报告视图 · {dashboard.作业编号}
          {dashboard.作业名称 ? ` ${dashboard.作业名称}` : ''}
        </h3>
        <span className="panel-hint">
          呈现口径：{dashboard.呈现口径}
          {dashboard.snapshot_id ? ` · 快照 ${dashboard.snapshot_id}` : ''}
        </span>
      </header>

      <div className="report-meta">
        <span>结论等级：<strong>{dashboard.结论等级}</strong></span>
        <span>提取版本：{dashboard.提取版本 || '—'}（批次 {dashboard.批次}）</span>
        <span>URL计数校验：{formatCell(dashboard.URL计数校验.校验)}</span>
        <span>
          快照校验和：<code className="mono">{dashboard.快照校验和 ? dashboard.快照校验和.slice(0, 16) : '—'}</code>
        </span>
        <span>覆盖口径：{dashboard.覆盖口径}</span>
      </div>

      <p className="conclusion">{dashboard.结论摘要}</p>

      <div className="metric-grid">
        {dashboard.指标概览.map((item) => (
          <article key={item.label} className="metric-card">
            <span className="stat-label">{item.label}</span>
            <strong className="stat-value">
              {item.value === null ? '不可计算' : `${item.value}${item.unit}`}
            </strong>
          </article>
        ))}
      </div>

      <div className="boundary-list">
        {dashboard.边界明细.length === 0 && <span className="tag ok">无边界异常</span>}
        {dashboard.边界明细.map((item) => (
          <span key={item.code} className="tag warn" title={item.说明}>
            {item.label} · {item.code}
          </span>
        ))}
      </div>
      {dashboard.边界说明.length > 0 && (
        <ul className="boundary-notes">
          {dashboard.边界说明.map((note) => <li key={note}>{note}</li>)}
        </ul>
      )}

      <div className="split">
        <section>
          <h4>字段覆盖分布</h4>
          <table className="data-table">
            <thead>
              <tr>
                <th>字段名</th>
                <th>应填URL数</th>
                <th>有值URL数</th>
                <th>缺失URL数</th>
                <th>完整率</th>
              </tr>
            </thead>
            <tbody>
              {dashboard.字段覆盖分布.map((item) => (
                <tr key={item.字段名}>
                  <td>{item.字段名}</td>
                  <td>{item.应填URL数}</td>
                  <td>{item.有值URL数}</td>
                  <td>
                    {item.缺失URL数}
                    {item.缺失URL.length > 0 && (
                      <span className="mono inline-hint">（{item.缺失URL.join('，')}）</span>
                    )}
                  </td>
                  <td>{formatRate(item.完整率)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        <section>
          <h4>失败URL对照</h4>
          <table className="data-table">
            <thead>
              <tr>
                <th>URL</th>
                <th>失败原因码</th>
                <th>失败原因</th>
                <th>计入方式</th>
              </tr>
            </thead>
            <tbody>
              {dashboard.失败URL对照.map((item) => (
                <tr key={item.URL}>
                  <td className="mono">{item.URL}</td>
                  <td>{item.失败原因码}</td>
                  <td>{item.失败原因}</td>
                  <td>{item.计入方式}</td>
                </tr>
              ))}
              {dashboard.失败URL对照.length === 0 && (
                <tr>
                  <td className="empty-state" colSpan={4}>本次没有失败URL</td>
                </tr>
              )}
            </tbody>
          </table>
        </section>
      </div>

      <section>
        <h4>字段核验核对</h4>
        <div className="report-meta">
          <span>字段核验版本：{formatCell(dashboard.字段核验核对.提取版本)}</span>
          <span>申报完整率：{formatRate(dashboard.字段核验核对.申报完整率 as number | null)}</span>
          <span>重算完整率：{formatRate(dashboard.字段核验核对.计算完整率 as number | null)}</span>
          <span>核对结果：{formatCell(dashboard.字段核验核对.核对结果)}</span>
        </div>
        <p className="panel-hint">{dashboard.字段完整率口径}</p>
      </section>

      <section>
        <h4>已确认指标核对（读取已确认快照，不随重算漂移）</h4>
        <table className="data-table">
          <thead>
            <tr>
              <th>指标</th>
              <th>已确认值</th>
              <th>当前源数据重算值</th>
              <th>是否一致</th>
            </tr>
          </thead>
          <tbody>
            {dashboard.已确认指标核对.map((item) => (
              <tr key={item.指标}>
                <td>{item.指标}</td>
                <td>{formatCell(item.已确认值)}</td>
                <td>{formatCell(item.当前值)}</td>
                <td>
                  <span className={item.是否一致 ? 'tag ok' : 'tag bad'}>
                    {item.是否一致 ? '一致' : '已漂移'}
                  </span>
                </td>
              </tr>
            ))}
            {dashboard.已确认指标核对.length === 0 && (
              <tr>
                <td className="empty-state" colSpan={4}>该作业还没有已确认快照，当前呈现为实时计算</td>
              </tr>
            )}
          </tbody>
        </table>
      </section>

      <section>
        <h4>URL结果追溯</h4>
        <table className="data-table">
          <thead>
            <tr>
              <th>URL</th>
              <th>状态</th>
              <th>完整字段数</th>
              <th>缺失字段</th>
              <th>提取版本</th>
            </tr>
          </thead>
          <tbody>
            {dashboard.URL结果.map((item) => (
              <tr key={`${item.URL}-${item.提取版本}`}>
                <td className="mono">{item.URL}</td>
                <td>{item.状态}</td>
                <td>{item.完整字段数}</td>
                <td>{item.缺失字段.length > 0 ? item.缺失字段.join('、') : '—'}</td>
                <td>{item.提取版本}</td>
              </tr>
            ))}
            {dashboard.URL结果.length === 0 && (
              <tr>
                <td className="empty-state" colSpan={5}>该作业没有URL结果（零URL边界）</td>
              </tr>
            )}
          </tbody>
        </table>
      </section>

      <section>
        <h4>版本历史（重算生成新版本，历史只读）</h4>
        <table className="data-table">
          <thead>
            <tr>
              <th>结论编号</th>
              <th>版本</th>
              <th>状态</th>
              <th>结论等级</th>
              <th>提取版本</th>
              <th>批次</th>
              <th>快照</th>
              <th>生成时间</th>
              <th>追溯</th>
            </tr>
          </thead>
          <tbody>
            {dashboard.版本历史.map((item) => (
              <tr key={item.结论编号} className={selectedSnapshot === item.snapshot_id ? 'row-active' : ''}>
                <td>{item.结论编号}</td>
                <td>v{item.版本号}</td>
                <td>{item.状态}</td>
                <td>{item.结论等级}</td>
                <td>{item.提取版本}</td>
                <td>{item.批次}</td>
                <td className="mono">{item.snapshot_id}</td>
                <td>{item.生成时间}</td>
                <td>
                  {item.状态 === '已确认' ? (
                    <button
                      className="link"
                      type="button"
                      onClick={() => onSelectSnapshot(item.snapshot_id)}
                    >
                      读取该快照
                    </button>
                  ) : item.状态 === '已取代' ? (
                    <span className="inline-hint">历史版本，快照只读</span>
                  ) : item.可确认 ? (
                    <span className="inline-hint">待确认，未对外呈现</span>
                  ) : (
                    <span className="inline-hint">不可确认</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {selectedSnapshot && (
          <button className="btn ghost" type="button" onClick={onClearSnapshot}>
            回到已确认快照
          </button>
        )}
      </section>
    </section>
  )
}
