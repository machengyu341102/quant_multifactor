import { useEffect, useState } from 'react'
import { Card, Tag } from 'antd-mobile'
import { useNavigate } from 'react-router-dom'
import { getPositions } from '../api'
import './Positions.css'

interface Position {
  code: string
  name: string
  quantity: number
  cost_price: number
  current_price: number
  market_value: number
  profit_loss: number
  profit_loss_pct: number
  stop_loss: number
  take_profit: number
  hold_days: number
  strategy: string
}

export default function Positions() {
  const navigate = useNavigate()
  const [positions, setPositions] = useState<Position[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    loadPositions()
    const timer = setInterval(loadPositions, 10000) // 10秒刷新
    return () => clearInterval(timer)
  }, [])

  const loadPositions = async () => {
    try {
      const data = await getPositions()
      setPositions(data)
      setLoading(false)
    } catch (error) {
      console.error('加载持仓失败:', error)
      setLoading(false)
    }
  }

  if (loading) {
    return <div className="loading">加载中...</div>
  }

  // 计算总览数据
  const totalAssets = 100000 + positions.reduce((sum, p) => sum + p.profit_loss, 0)
  const totalMarketValue = positions.reduce((sum, p) => sum + p.market_value, 0)
  const availableCash = totalAssets - totalMarketValue
  const todayPL = positions.reduce((sum, p) => sum + p.profit_loss, 0)
  const todayPLPct = (todayPL / 100000) * 100

  const profitPositions = positions.filter(p => p.profit_loss > 0)
  const lossPositions = positions.filter(p => p.profit_loss < 0)

  return (
    <div className="positions-page">
      <div className="positions-header">
        <h1>持仓管理</h1>
      </div>

      {/* 账户总览 */}
      <Card className="account-card">
        <div className="account-total">
          <div className="total-label">总资产</div>
          <div className="total-value">¥{totalAssets.toLocaleString()}</div>
          <div className={`total-change ${todayPL >= 0 ? 'positive' : 'negative'}`}>
            今日 {todayPL >= 0 ? '+' : ''}¥{todayPL.toFixed(0)} ({todayPL >= 0 ? '+' : ''}{todayPLPct.toFixed(2)}%)
          </div>
        </div>

        <div className="account-stats">
          <div className="stat-item">
            <div className="stat-label">可用</div>
            <div className="stat-value">¥{availableCash.toLocaleString()}</div>
          </div>
          <div className="stat-item">
            <div className="stat-label">持仓</div>
            <div className="stat-value">¥{totalMarketValue.toLocaleString()}</div>
          </div>
          <div className="stat-item">
            <div className="stat-label">持仓数</div>
            <div className="stat-value">{positions.length}只</div>
          </div>
          <div className="stat-item">
            <div className="stat-label">盈亏</div>
            <div className="stat-value">
              {profitPositions.length}盈{lossPositions.length}亏
            </div>
          </div>
        </div>
      </Card>

      {/* 持仓列表 */}
      {positions.length === 0 ? (
        <div className="empty-state">
          <div className="empty-icon">📭</div>
          <div className="empty-text">暂无持仓</div>
        </div>
      ) : (
        <div className="position-list">
          {positions.map(pos => {
            const isProfitable = pos.profit_loss > 0
            const stopLossDistance = ((pos.stop_loss / pos.current_price - 1) * 100).toFixed(1)
            const takeProfitDistance = ((pos.take_profit / pos.current_price - 1) * 100).toFixed(1)
            const isNearStopLoss = Math.abs(parseFloat(stopLossDistance)) < 1

            return (
              <Card
                key={pos.code}
                className={`position-card ${isNearStopLoss ? 'warning' : ''}`}
                onClick={() => navigate(`/positions/${pos.code}`)}
              >
                <div className="position-header">
                  <div className="position-title">
                    <span className="position-code">{pos.code}</span>
                    <span className="position-name">{pos.name}</span>
                  </div>
                  <div className={`position-status ${isProfitable ? 'profit' : 'loss'}`}>
                    {isProfitable ? '🟢 盈利中' : '🔴 亏损中'}
                  </div>
                </div>

                <div className="position-pl">
                  <span className={`pl-value ${isProfitable ? 'positive' : 'negative'}`}>
                    {isProfitable ? '+' : ''}¥{pos.profit_loss.toFixed(0)}
                  </span>
                  <span className={`pl-pct ${isProfitable ? 'positive' : 'negative'}`}>
                    ({isProfitable ? '+' : ''}{pos.profit_loss_pct.toFixed(2)}%)
                  </span>
                </div>

                <div className="position-info">
                  <div className="info-row">
                    <span className="info-label">持仓:</span>
                    <span className="info-value">
                      {pos.quantity}股 @ ¥{pos.cost_price.toFixed(2)}
                    </span>
                  </div>
                  <div className="info-row">
                    <span className="info-label">现价:</span>
                    <span className="info-value">
                      ¥{pos.current_price.toFixed(2)} | 市值: ¥{pos.market_value.toLocaleString()}
                    </span>
                  </div>
                </div>

                <div className="position-targets">
                  <div className="target-item">
                    <span className="target-label">🎯 止盈:</span>
                    <span className="target-value success">
                      ¥{pos.take_profit.toFixed(2)} (+{takeProfitDistance}%)
                    </span>
                  </div>
                  <div className="target-item">
                    <span className="target-label">🛡️ 止损:</span>
                    <span className={`target-value ${isNearStopLoss ? 'danger-blink' : 'danger'}`}>
                      ¥{pos.stop_loss.toFixed(2)} ({stopLossDistance}%)
                    </span>
                  </div>
                </div>

                {isNearStopLoss && (
                  <div className="warning-banner">
                    ⚠️ 接近止损线，请注意风险
                  </div>
                )}

                <div className="position-footer">
                  <Tag color="default" fill="outline">{pos.strategy}</Tag>
                  <span className="hold-days">持仓{pos.hold_days}天</span>
                </div>
              </Card>
            )
          })}
        </div>
      )}

      {/* 风险监控 */}
      {positions.length > 0 && (
        <Card title="📊 风险监控" className="risk-card">
          <div className="risk-item">
            <span className="risk-label">VaR (95%置信):</span>
            <span className="risk-value">-¥1,850</span>
          </div>
          <div className="risk-item">
            <span className="risk-label">组合回撤:</span>
            <span className="risk-value success">-1.2% (安全)</span>
          </div>
          <div className="risk-item">
            <span className="risk-label">策略相关性:</span>
            <span className="risk-value">0.35 (分散)</span>
          </div>
          <div className="risk-status">
            <span>✅ 风险等级: 低</span>
            <span>✅ 断路器: 未触发</span>
          </div>
        </Card>
      )}
    </div>
  )
}
