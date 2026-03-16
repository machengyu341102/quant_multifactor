import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Card, Tag, Button, Grid, ProgressBar } from 'antd-mobile'
import { LeftOutline } from 'antd-mobile-icons'
import { getSignalDetail } from '../api'
import './SignalDetail.css'

interface SignalDetail {
  id: string
  code: string
  name: string
  strategy: string
  strategies: string[]
  score: number
  price: number
  change_pct: number
  high: number
  low: number
  volume: number
  turnover: number
  buy_price: number
  stop_loss: number
  target_price: number
  risk_reward: number
  timestamp: string
  factor_scores: Record<string, number>
  regime: string
  regime_score: number
}

export default function SignalDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [signal, setSignal] = useState<SignalDetail | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    loadSignal()
  }, [id])

  const loadSignal = async () => {
    try {
      const data = await getSignalDetail(id!)
      setSignal(data)
      setLoading(false)
    } catch (error) {
      console.error('加载信号详情失败:', error)
      setLoading(false)
    }
  }

  if (loading || !signal) {
    return <div className="loading">加载中...</div>
  }

  // 因子分组
  const factorGroups = {
    technical: Object.entries(signal.factor_scores).filter(([k]) =>
      ['s_vol', 's_boll', 's_rsi', 's_ma', 's_momentum', 's_macd'].includes(k)
    ),
    capital: Object.entries(signal.factor_scores).filter(([k]) =>
      ['s_flow_1d', 's_flow_trend', 's_turnover'].includes(k)
    ),
    fundamental: Object.entries(signal.factor_scores).filter(([k]) =>
      ['s_fundamental', 's_chip'].includes(k)
    ),
    crossMarket: Object.entries(signal.factor_scores).filter(([k]) =>
      k.startsWith('ca_')
    ),
  }

  const factorNames: Record<string, string> = {
    s_vol: '量能',
    s_boll: '布林',
    s_rsi: 'RSI',
    s_ma: '均线',
    s_momentum: '动量',
    s_macd: 'MACD',
    s_flow_1d: '单日资金',
    s_flow_trend: '资金趋势',
    s_turnover: '换手率',
    s_fundamental: '基本面',
    s_chip: '筹码',
    ca_us: '美股',
    ca_btc: '币圈',
    ca_a50: 'A50',
  }

  return (
    <div className="signal-detail">
      {/* 顶部导航 */}
      <div className="detail-header">
        <LeftOutline onClick={() => navigate(-1)} />
        <div className="header-title">
          <span className="code">{signal.code}</span>
          <span className="name">{signal.name}</span>
        </div>
        <div></div>
      </div>

      {/* 实时行情 */}
      <Card className="quote-card">
        <div className="quote-price">
          <span className="price">¥{signal.price.toFixed(2)}</span>
          <span className={`change ${signal.change_pct >= 0 ? 'positive' : 'negative'}`}>
            {signal.change_pct >= 0 ? '+' : ''}{signal.change_pct.toFixed(2)}%
          </span>
        </div>
        <Grid columns={4} gap={8} className="quote-stats">
          <Grid.Item>
            <div className="stat-label">今开</div>
            <div className="stat-value">{signal.price.toFixed(2)}</div>
          </Grid.Item>
          <Grid.Item>
            <div className="stat-label">最高</div>
            <div className="stat-value">{signal.high.toFixed(2)}</div>
          </Grid.Item>
          <Grid.Item>
            <div className="stat-label">最低</div>
            <div className="stat-value">{signal.low.toFixed(2)}</div>
          </Grid.Item>
          <Grid.Item>
            <div className="stat-label">换手</div>
            <div className="stat-value">{signal.turnover.toFixed(1)}%</div>
          </Grid.Item>
        </Grid>
      </Card>

      {/* 交易建议 */}
      <Card title="🎯 交易建议" className="trade-card">
        <Grid columns={2} gap={12}>
          <Grid.Item>
            <div className="trade-item">
              <div className="trade-label">买入价</div>
              <div className="trade-value primary">¥{signal.buy_price.toFixed(2)}</div>
              <div className="trade-hint">当前价-0.3%</div>
            </div>
          </Grid.Item>
          <Grid.Item>
            <div className="trade-item">
              <div className="trade-label">止损价</div>
              <div className="trade-value danger">¥{signal.stop_loss.toFixed(2)}</div>
              <div className="trade-hint">
                {((signal.stop_loss / signal.price - 1) * 100).toFixed(1)}%
              </div>
            </div>
          </Grid.Item>
          <Grid.Item>
            <div className="trade-item">
              <div className="trade-label">目标价</div>
              <div className="trade-value success">¥{signal.target_price.toFixed(2)}</div>
              <div className="trade-hint">
                +{((signal.target_price / signal.price - 1) * 100).toFixed(1)}%
              </div>
            </div>
          </Grid.Item>
          <Grid.Item>
            <div className="trade-item">
              <div className="trade-label">盈亏比</div>
              <div className="trade-value highlight">{signal.risk_reward.toFixed(1)}:1</div>
              <div className="trade-hint">
                {signal.risk_reward >= 2 ? '⭐⭐⭐' : signal.risk_reward >= 1.5 ? '⭐⭐' : '⭐'}
              </div>
            </div>
          </Grid.Item>
        </Grid>

        <div className="position-suggest">
          <div className="suggest-label">建议仓位: 10% (¥10,000)</div>
          <div className="suggest-detail">
            预期收益: +¥{((signal.target_price - signal.price) * 1000).toFixed(0)} |
            最大风险: -¥{((signal.price - signal.stop_loss) * 1000).toFixed(0)}
          </div>
        </div>
      </Card>

      {/* AI分析 */}
      <Card title="🧠 AI分析" className="analysis-card">
        <div className="score-header">
          <span>综合得分</span>
          <span className="score-value">{signal.score.toFixed(2)} / 1.00</span>
        </div>
        <ProgressBar percent={signal.score * 100} />

        {signal.strategies.length > 1 && (
          <div className="consensus-section">
            <div className="section-title">
              🔥 {signal.strategies.length}个策略共识 (强信号)
            </div>
            {signal.strategies.map(s => (
              <Tag key={s} color="primary" style={{ margin: '4px' }}>{s}</Tag>
            ))}
          </div>
        )}

        {/* 因子得分 */}
        <div className="factors-section">
          <div className="section-title">📊 因子得分明细</div>

          {factorGroups.technical.length > 0 && (
            <div className="factor-group">
              <div className="group-title">技术面 (60%)</div>
              {factorGroups.technical.map(([key, value]) => (
                <div key={key} className="factor-item">
                  <span className="factor-name">{factorNames[key] || key}</span>
                  <div className="factor-bar">
                    <div
                      className="factor-fill"
                      style={{ width: `${value * 100}%` }}
                    ></div>
                  </div>
                  <span className="factor-value">{value.toFixed(2)}</span>
                </div>
              ))}
            </div>
          )}

          {factorGroups.capital.length > 0 && (
            <div className="factor-group">
              <div className="group-title">资金面 (25%)</div>
              {factorGroups.capital.map(([key, value]) => (
                <div key={key} className="factor-item">
                  <span className="factor-name">{factorNames[key] || key}</span>
                  <div className="factor-bar">
                    <div
                      className="factor-fill"
                      style={{ width: `${value * 100}%` }}
                    ></div>
                  </div>
                  <span className="factor-value">{value.toFixed(2)}</span>
                </div>
              ))}
            </div>
          )}

          {factorGroups.crossMarket.length > 0 && (
            <div className="factor-group">
              <div className="group-title">跨市场 (5%)</div>
              {factorGroups.crossMarket.map(([key, value]) => (
                <div key={key} className="factor-item">
                  <span className="factor-name">{factorNames[key] || key}</span>
                  <div className="factor-bar">
                    <div
                      className="factor-fill"
                      style={{ width: `${value * 100}%` }}
                    ></div>
                  </div>
                  <span className="factor-value">{value.toFixed(2)}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </Card>

      {/* 市场环境 */}
      <Card title="🌍 市场环境" className="regime-card">
        <div className="regime-item">
          <span>Regime识别</span>
          <Tag color="primary">{signal.regime}</Tag>
        </div>
        <div className="regime-item">
          <span>适配度</span>
          <span className="regime-score">{(signal.regime_score * 100).toFixed(0)}%</span>
        </div>
        <div className="regime-item">
          <span>环境评估</span>
          <Tag color={signal.regime_score >= 0.7 ? 'success' : 'warning'}>
            {signal.regime_score >= 0.7 ? '✅ 适合交易' : '⚠️ 谨慎交易'}
          </Tag>
        </div>
      </Card>

      {/* 底部操作 */}
      <div className="detail-actions">
        <Button block color="primary" size="large">
          加入自选
        </Button>
      </div>
    </div>
  )
}
