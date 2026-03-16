import { useCallback, useEffect, useMemo, useState } from 'react'
import { Card, ProgressBar, Tag } from 'antd-mobile'
import { RightOutline } from 'antd-mobile-icons'
import { useNavigate } from 'react-router-dom'
import { getSystemStatus, getStrategies } from '../api'
import { useWebSocket } from '../hooks/useWebSocket'
import './Dashboard.css'

interface SystemStatus {
  status: string
  uptime_hours: number
  health_score: number
  today_signals: number
  active_strategies: number
  ooda_cycles: number
  decision_accuracy: number
}

interface Strategy {
  id: string
  name: string
  status: string
  win_rate: number
  avg_return: number
  signal_count: number
}

export default function Dashboard() {
  const navigate = useNavigate()
  const [system, setSystem] = useState<SystemStatus | null>(null)
  const [strategies, setStrategies] = useState<Strategy[]>([])
  const [loading, setLoading] = useState(true)

  const refreshData = useCallback(async () => {
    try {
      const [sysData, stratData] = await Promise.all([
        getSystemStatus(),
        getStrategies(),
      ])
      setSystem(sysData)
      setStrategies(stratData.slice(0, 5))
      setLoading(false)
    } catch (error) {
      console.error('加载数据失败:', error)
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    refreshData()
    const timer = setInterval(refreshData, 30000)
    return () => clearInterval(timer)
  }, [refreshData])

  const handleSystemUpdate = useCallback((data: any) => {
    setSystem(prev => (prev ? { ...prev, ...data } : prev))
  }, [])

  const handleSignalPush = useCallback((data: any) => {
    if ('Notification' in window && Notification.permission === 'granted') {
      new Notification('新信号推送', {
        body: `${data.code} ${data.name} - ${data.strategy}`,
        icon: '/pwa-192x192.png',
      })
    }
    setSystem(prev => (prev ? { ...prev, today_signals: prev.today_signals + 1 } : prev))
  }, [])

  useWebSocket('system_update', handleSystemUpdate)
  useWebSocket('new_signal', handleSignalPush)

  const statusSummary = useMemo(() => {
    if (!system) return []
    return [
      { label: '持续运行', value: `${system.uptime_hours.toFixed(1)} 小时` },
      { label: 'OODA 轮次', value: `${system.ooda_cycles} 轮` },
      { label: '系统状态', value: system.status },
    ]
  }, [system])

  const snapshotCards = useMemo(() => {
    if (!system) return []
    return [
      { title: '健康度', value: `${system.health_score}%`, detail: 'Guardrail · SLA 监控' },
      { title: '今日信号', value: `${system.today_signals} 条`, detail: '信号采集 → 评分 → 过滤' },
      { title: '决策准确率', value: `${(system.decision_accuracy * 100).toFixed(1)}%`, detail: 'Rolling 7 天' },
      { title: '活跃策略', value: `${system.active_strategies}`, detail: '可部署 / 运行中' },
    ]
  }, [system])

  const strategyProfiles = useMemo(() => {
    return strategies.reduce(
      (acc, curr) => {
        if (curr.status === 'active') acc.active += 1
        else if (curr.status === 'paused') acc.paused += 1
        else acc.disabled += 1
        return acc
      },
      { active: 0, paused: 0, disabled: 0 }
    )
  }, [strategies])

  const bestStrategy = useMemo(() => {
    return strategies.reduce<Strategy | null>((prev, curr) => {
      if (!prev) return curr
      return curr.avg_return > prev.avg_return ? curr : prev
    }, null)
  }, [strategies])

  const pipelineSteps = useMemo(() => {
    if (!system) return []
    return [
      { title: '信号采集', value: `${system.today_signals} 条`, detail: '跨市场因子 + 事件' },
      { title: '策略评审', value: `${system.active_strategies} 套`, detail: '覆盖成长/价值/事件' },
      { title: '模型自检', value: `${system.health_score}%`, detail: 'Guardrail + 回撤监测' },
      { title: '执行推送', value: `${system.ooda_cycles} 次`, detail: '多通道通知 + WebSocket' },
    ]
  }, [system])

  const actions = useMemo(
    () => [
      { label: '信号中心', detail: '多策略共识', route: '/signals' },
      { label: '持仓管理', detail: '风险控制与止盈', route: '/positions' },
      { label: '学习轨迹', detail: '因子进化与命中率', route: '/learning' },
      { label: '个人设置', detail: '提醒、推送与 Guardrails', route: '/profile' },
    ],
    []
  )

  if (loading || !system) {
    return <div className="loading">加载中...</div>
  }

  return (
    <div className="dashboard">
      <section className="dashboard-hero">
        <div className="hero-copy">
          <p className="hero-eyebrow">Alpha AI / 智库中枢</p>
          <h1>用 AI 交易系统替代人工跑腿</h1>
          <p className="hero-tagline">
            将信号、事件、策略与记忆串成透明可审计的决策链，让投资人随时看到推荐的因果。
          </p>
          <div className="badge-row">
            {statusSummary.map(item => (
              <div key={item.label} className="badge-pill">
                <span className="badge-label">{item.label}</span>
                <span className="badge-value">{item.value}</span>
              </div>
            ))}
          </div>
        </div>
        <div className="hero-card">
          <div className="hero-card-title">系统健康</div>
          <div className="hero-card-score">{system.health_score}%</div>
          <ProgressBar className="hero-card-bar" percent={system.health_score} />
          <div className="hero-card-foot">
            <span>今日信号 {system.today_signals}</span>
            <span>策略 {system.active_strategies}</span>
          </div>
        </div>
      </section>

      <section className="snapshot-grid">
        {snapshotCards.map(card => (
          <Card key={card.title} className="snapshot-card">
            <p className="snapshot-title">{card.title}</p>
            <p className="snapshot-value">{card.value}</p>
            <p className="snapshot-detail">{card.detail}</p>
          </Card>
        ))}
      </section>

      <Card title="信号处理管线" className="pipeline-card">
        <div className="pipeline-grid">
          {pipelineSteps.map(step => (
            <div key={step.title} className="pipeline-step">
              <p className="pipeline-title">{step.title}</p>
              <p className="pipeline-value">{step.value}</p>
              <p className="pipeline-detail">{step.detail}</p>
            </div>
          ))}
        </div>
      </Card>

      <Card title="策略智库" extra={<RightOutline onClick={() => navigate('/strategies')} />} className="strategy-card">
        <div className="strategy-meta">
          <div>
            <p className="strategy-meta-label">策略状态</p>
            <p className="strategy-meta-value">
              {strategyProfiles.active} 运行 · {strategyProfiles.paused} 暂停 · {strategyProfiles.disabled} 关闭
            </p>
          </div>
          {bestStrategy && (
            <div className="strategy-highlight">
              <p className="strategy-highlight-label">旗舰策略</p>
              <p className="strategy-highlight-name">{bestStrategy.name}</p>
              <p className="strategy-highlight-stats">
                胜率 {(bestStrategy.win_rate * 100).toFixed(1)}% · 平均收益 {bestStrategy.avg_return.toFixed(2)}%
              </p>
            </div>
          )}
        </div>
        <div className="strategy-list">
          {strategies.map(s => (
            <div key={s.id} className="strategy-row">
              <div>
                <p className="strategy-name">{s.name}</p>
                <p className="strategy-detail">{s.signal_count} 条信号 · 胜率 {(s.win_rate * 100).toFixed(1)}%</p>
              </div>
              <Tag
                color={s.status === 'active' ? 'success' : s.status === 'paused' ? 'warning' : 'default'}
              >
                {s.status === 'active' ? '运行中' : s.status === 'paused' ? '已暂停' : '已禁用'}
              </Tag>
              <span className={`strategy-return ${s.avg_return >= 0 ? 'positive' : 'negative'}`}>
                {s.avg_return >= 0 ? '+' : ''}{s.avg_return.toFixed(2)}%
              </span>
            </div>
          ))}
        </div>
      </Card>

      <Card title="行动准备" className="action-card">
        <div className="action-grid">
          {actions.map(action => (
            <div key={action.label} className="action-tile" onClick={() => navigate(action.route)}>
              <p className="action-label">{action.label}</p>
              <p className="action-detail">{action.detail}</p>
            </div>
          ))}
        </div>
      </Card>
    </div>
  )
}
