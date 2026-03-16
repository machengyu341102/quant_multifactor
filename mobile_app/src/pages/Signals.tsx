import { useEffect, useState } from 'react'
import { Card, Tag, Tabs } from 'antd-mobile'
import { useNavigate } from 'react-router-dom'
import { getSignals } from '../api'
import './Signals.css'

interface Signal {
  id: string
  code: string
  name: string
  strategy: string
  score: number
  price: number
  change_pct: number
  buy_price: number
  stop_loss: number
  target_price: number
  risk_reward: number
  timestamp: string
  consensus_count: number
}

export default function Signals() {
  const navigate = useNavigate()
  const [signals, setSignals] = useState<Signal[]>([])
  const [activeTab, setActiveTab] = useState('today')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    loadSignals()
  }, [activeTab])

  const loadSignals = async () => {
    try {
      setLoading(true)
      const data = await getSignals({
        date: activeTab === 'today' ? new Date().toISOString().split('T')[0] : undefined
      })
      setSignals(data)
      setLoading(false)
    } catch (error) {
      console.error('加载信号失败:', error)
      setLoading(false)
    }
  }

  const strongSignals = signals.filter(s => s.consensus_count >= 2)
  const normalSignals = signals.filter(s => s.consensus_count < 2)

  return (
    <div className="signals-page">
      <div className="signals-header">
        <h1>信号中心</h1>
      </div>

      <Tabs activeKey={activeTab} onChange={setActiveTab}>
        <Tabs.Tab title="今日" key="today" />
        <Tabs.Tab title="近7天" key="week" />
        <Tabs.Tab title="近30天" key="month" />
      </Tabs>

      {/* 今日概览 */}
      {activeTab === 'today' && (
        <Card className="overview-card">
          <div className="overview-stats">
            <div className="stat-item">
              <div className="stat-value">{signals.length}</div>
              <div className="stat-label">总信号</div>
            </div>
            <div className="stat-item">
              <div className="stat-value highlight">{strongSignals.length}</div>
              <div className="stat-label">强信号</div>
            </div>
            <div className="stat-item">
              <div className="stat-value">{signals.filter(s => s.code.startsWith('6')).length}</div>
              <div className="stat-label">股票</div>
            </div>
            <div className="stat-item">
              <div className="stat-value">{signals.filter(s => !s.code.startsWith('6')).length}</div>
              <div className="stat-label">期货</div>
            </div>
          </div>
        </Card>
      )}

      {/* 强信号 */}
      {strongSignals.length > 0 && (
        <div className="signal-section">
          <div className="section-title">🔥 强信号 (多策略共识)</div>
          {strongSignals.map(signal => (
            <Card
              key={signal.id}
              className="signal-card strong"
              onClick={() => navigate(`/signals/${signal.id}`)}
            >
              <div className="signal-header">
                <div className="signal-title">
                  <span className="signal-code">{signal.code}</span>
                  <span className="signal-name">{signal.name}</span>
                </div>
                <div className="signal-stars">
                  {'⭐'.repeat(Math.min(signal.consensus_count, 3))}
                </div>
              </div>

              <div className="signal-price">
                <span className="price">¥{signal.price.toFixed(2)}</span>
                <span className={`change ${signal.change_pct >= 0 ? 'positive' : 'negative'}`}>
                  {signal.change_pct >= 0 ? '+' : ''}{signal.change_pct.toFixed(2)}%
                </span>
              </div>

              <div className="signal-consensus">
                <Tag color="primary">{signal.consensus_count}个策略共识</Tag>
                <span className="score">得分 {signal.score.toFixed(2)}</span>
              </div>

              <div className="signal-trade">
                <div className="trade-item">
                  <span className="label">买入</span>
                  <span className="value">¥{signal.buy_price.toFixed(2)}</span>
                </div>
                <div className="trade-item">
                  <span className="label">止损</span>
                  <span className="value">¥{signal.stop_loss.toFixed(2)}</span>
                </div>
                <div className="trade-item">
                  <span className="label">目标</span>
                  <span className="value">¥{signal.target_price.toFixed(2)}</span>
                </div>
                <div className="trade-item">
                  <span className="label">盈亏比</span>
                  <span className="value highlight">{signal.risk_reward.toFixed(1)}</span>
                </div>
              </div>

              <div className="signal-time">
                {new Date(signal.timestamp).toLocaleTimeString('zh-CN', {
                  hour: '2-digit',
                  minute: '2-digit'
                })} 推送
              </div>
            </Card>
          ))}
        </div>
      )}

      {/* 普通信号 */}
      {normalSignals.length > 0 && (
        <div className="signal-section">
          <div className="section-title">📡 最新信号</div>
          {normalSignals.map(signal => (
            <Card
              key={signal.id}
              className="signal-card"
              onClick={() => navigate(`/signals/${signal.id}`)}
            >
              <div className="signal-header">
                <div className="signal-title">
                  <span className="signal-code">{signal.code}</span>
                  <span className="signal-name">{signal.name}</span>
                </div>
                <div className="signal-stars">
                  {'⭐'.repeat(Math.min(Math.floor(signal.score * 3), 3))}
                </div>
              </div>

              <div className="signal-price">
                <span className="price">¥{signal.price.toFixed(2)}</span>
                <span className={`change ${signal.change_pct >= 0 ? 'positive' : 'negative'}`}>
                  {signal.change_pct >= 0 ? '+' : ''}{signal.change_pct.toFixed(2)}%
                </span>
              </div>

              <div className="signal-meta">
                <Tag color="default">{signal.strategy}</Tag>
                <span className="score">得分 {signal.score.toFixed(2)}</span>
              </div>

              <div className="signal-trade compact">
                <span>买入 ¥{signal.buy_price.toFixed(2)}</span>
                <span>止损 ¥{signal.stop_loss.toFixed(2)}</span>
                <span>目标 ¥{signal.target_price.toFixed(2)}</span>
              </div>

              <div className="signal-time">
                {new Date(signal.timestamp).toLocaleTimeString('zh-CN', {
                  hour: '2-digit',
                  minute: '2-digit'
                })}
              </div>
            </Card>
          ))}
        </div>
      )}

      {!loading && signals.length === 0 && (
        <div className="empty-state">
          <div className="empty-icon">📭</div>
          <div className="empty-text">暂无信号</div>
        </div>
      )}
    </div>
  )
}
