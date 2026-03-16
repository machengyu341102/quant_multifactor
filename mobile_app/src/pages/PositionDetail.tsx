import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Card, Button, Dialog } from 'antd-mobile'
import { LeftOutline } from 'antd-mobile-icons'
import ReactECharts from 'echarts-for-react'
import { getPositionDetail } from '../api'
import './PositionDetail.css'

interface PositionDetail {
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
  buy_time: string
  high_price: number
  low_price: number
  trailing_stop: boolean
  trailing_trigger_price: number
  trades: Array<{
    time: string
    type: string
    price: number
    quantity: number
    reason: string
  }>
}

export default function PositionDetail() {
  const { code } = useParams()
  const navigate = useNavigate()
  const [position, setPosition] = useState<PositionDetail | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    loadPosition()
    const timer = setInterval(loadPosition, 5000) // 5秒刷新
    return () => clearInterval(timer)
  }, [code])

  const loadPosition = async () => {
    try {
      const data = await getPositionDetail(code!)
      setPosition(data)
      setLoading(false)
    } catch (error) {
      console.error('加载持仓详情失败:', error)
      setLoading(false)
    }
  }

  const handleClosePosition = () => {
    Dialog.confirm({
      content: '确认平仓？',
      onConfirm: async () => {
        // TODO: 调用平仓API
        console.log('平仓:', code)
      },
    })
  }

  const handleAdjustStopLoss = () => {
    Dialog.confirm({
      content: '调整止损价？',
      onConfirm: async () => {
        // TODO: 调用调整止损API
        console.log('调整止损:', code)
      },
    })
  }

  if (loading || !position) {
    return <div className="loading">加载中...</div>
  }

  const isProfitable = position.profit_loss > 0
  const stopLossDistance = ((position.stop_loss / position.current_price - 1) * 100).toFixed(1)
  const takeProfitDistance = ((position.take_profit / position.current_price - 1) * 100).toFixed(1)
  const isNearStopLoss = Math.abs(parseFloat(stopLossDistance)) < 1

  // 分时图配置
  const chartOption = {
    grid: {
      left: 10,
      right: 10,
      top: 30,
      bottom: 30,
    },
    xAxis: {
      type: 'category',
      data: ['09:30', '10:00', '10:30', '11:00', '11:30', '13:00', '13:30', '14:00', '14:30', '15:00'],
      axisLabel: { fontSize: 10 },
    },
    yAxis: {
      type: 'value',
      scale: true,
      axisLabel: { fontSize: 10 },
    },
    series: [
      {
        name: '价格',
        type: 'line',
        data: [
          position.cost_price,
          position.cost_price * 1.01,
          position.cost_price * 1.02,
          position.cost_price * 1.015,
          position.cost_price * 1.03,
          position.cost_price * 1.025,
          position.cost_price * 1.04,
          position.cost_price * 1.035,
          position.cost_price * 1.045,
          position.current_price,
        ],
        smooth: true,
        lineStyle: { color: isProfitable ? '#ff4d4f' : '#52c41a', width: 2 },
        areaStyle: {
          color: {
            type: 'linear',
            x: 0,
            y: 0,
            x2: 0,
            y2: 1,
            colorStops: [
              { offset: 0, color: isProfitable ? 'rgba(255, 77, 79, 0.3)' : 'rgba(82, 196, 26, 0.3)' },
              { offset: 1, color: isProfitable ? 'rgba(255, 77, 79, 0.05)' : 'rgba(82, 196, 26, 0.05)' },
            ],
          },
        },
      },
    ],
    visualMap: {
      show: false,
      pieces: [
        { gt: position.cost_price, color: '#ff4d4f' },
        { lte: position.cost_price, color: '#52c41a' },
      ],
    },
    markLine: {
      symbol: 'none',
      data: [
        {
          name: '成本价',
          yAxis: position.cost_price,
          lineStyle: { color: '#999', type: 'solid', width: 1 },
          label: { formatter: '成本 {c}', fontSize: 10 },
        },
        {
          name: '止盈',
          yAxis: position.take_profit,
          lineStyle: { color: '#52c41a', type: 'dashed', width: 1 },
          label: { formatter: '止盈 {c}', fontSize: 10 },
        },
        {
          name: '止损',
          yAxis: position.stop_loss,
          lineStyle: { color: '#ff4d4f', type: 'dashed', width: 1 },
          label: { formatter: '止损 {c}', fontSize: 10 },
        },
      ],
    },
  }

  return (
    <div className="position-detail">
      {/* 顶部导航 */}
      <div className="detail-header">
        <LeftOutline onClick={() => navigate(-1)} />
        <div className="header-title">
          <span className="code">{position.code}</span>
          <span className="name">{position.name}</span>
        </div>
        <div></div>
      </div>

      {/* 盈亏概览 */}
      <Card className="pl-overview-card">
        <div className="pl-display">
          <div className={`pl-value ${isProfitable ? 'positive' : 'negative'}`}>
            {isProfitable ? '+' : ''}¥{position.profit_loss.toFixed(0)}
          </div>
          <div className={`pl-pct ${isProfitable ? 'positive' : 'negative'}`}>
            ({isProfitable ? '+' : ''}{position.profit_loss_pct.toFixed(2)}%)
          </div>
        </div>
        <div className="pl-status">
          {isProfitable ? '🟢 盈利中' : '🔴 亏损中'}
        </div>
      </Card>

      {/* 分时图 */}
      <Card title="📈 分时走势" className="chart-card">
        <ReactECharts option={chartOption} style={{ height: '250px' }} />
        {isNearStopLoss && (
          <div className="warning-banner">
            ⚠️ 接近止损价 ({stopLossDistance}%)，请注意风险！
          </div>
        )}
      </Card>

      {/* 持仓信息 */}
      <Card title="📊 持仓信息" className="info-card">
        <div className="info-grid">
          <div className="info-item">
            <span className="info-label">持仓数量</span>
            <span className="info-value">{position.quantity}股</span>
          </div>
          <div className="info-item">
            <span className="info-label">成本价</span>
            <span className="info-value">¥{position.cost_price.toFixed(2)}</span>
          </div>
          <div className="info-item">
            <span className="info-label">现价</span>
            <span className="info-value">¥{position.current_price.toFixed(2)}</span>
          </div>
          <div className="info-item">
            <span className="info-label">市值</span>
            <span className="info-value">¥{position.market_value.toLocaleString()}</span>
          </div>
          <div className="info-item">
            <span className="info-label">最高价</span>
            <span className="info-value">¥{position.high_price.toFixed(2)}</span>
          </div>
          <div className="info-item">
            <span className="info-label">最低价</span>
            <span className="info-value">¥{position.low_price.toFixed(2)}</span>
          </div>
          <div className="info-item">
            <span className="info-label">持仓天数</span>
            <span className="info-value">{position.hold_days}天</span>
          </div>
          <div className="info-item">
            <span className="info-label">买入策略</span>
            <span className="info-value">{position.strategy}</span>
          </div>
        </div>
      </Card>

      {/* 止损止盈 */}
      <Card title="🎯 止损止盈" className="target-card">
        <div className="target-grid">
          <div className="target-item">
            <div className="target-header">
              <span className="target-label">🛡️ 止损价</span>
              <Button size="small" fill="none" onClick={handleAdjustStopLoss}>
                调整
              </Button>
            </div>
            <div className="target-value danger">¥{position.stop_loss.toFixed(2)}</div>
            <div className="target-distance">
              距离: {stopLossDistance}%
            </div>
          </div>
          <div className="target-item">
            <div className="target-header">
              <span className="target-label">🎯 止盈价</span>
            </div>
            <div className="target-value success">¥{position.take_profit.toFixed(2)}</div>
            <div className="target-distance">
              距离: +{takeProfitDistance}%
            </div>
          </div>
        </div>

        {position.trailing_stop && (
          <div className="trailing-info">
            <div className="trailing-badge">🔄 追踪止盈已激活</div>
            <div className="trailing-detail">
              触发价: ¥{position.trailing_trigger_price.toFixed(2)} | 回撤30%触发平仓
            </div>
          </div>
        )}
      </Card>

      {/* 交易记录 */}
      <Card title="📝 交易记录" className="trades-card">
        <div className="timeline">
          {position.trades.map((trade, index) => (
            <div key={index} className="timeline-item">
              <div className={`timeline-dot ${trade.type === 'buy' ? 'buy' : 'sell'}`}></div>
              <div className="timeline-content">
                <div className="timeline-header">
                  <span className="timeline-type">
                    {trade.type === 'buy' ? '📥 买入' : '📤 卖出'}
                  </span>
                  <span className="timeline-time">{trade.time}</span>
                </div>
                <div className="timeline-detail">
                  ¥{trade.price.toFixed(2)} × {trade.quantity}股
                </div>
                <div className="timeline-reason">{trade.reason}</div>
              </div>
            </div>
          ))}
        </div>
      </Card>

      {/* 底部操作按钮 */}
      <div className="action-buttons">
        <Button block color="danger" onClick={handleClosePosition}>
          平仓
        </Button>
      </div>
    </div>
  )
}
