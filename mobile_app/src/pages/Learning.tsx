import { useEffect, useState } from 'react'
import { Card, ProgressBar, Tag } from 'antd-mobile'
import { getLearningProgress } from '../api'
import './Learning.css'

interface LearningProgress {
  today_cycles: number
  factor_adjustments: number
  online_updates: number
  experiments_running: number
  new_factors_deployed: number
  decision_accuracy: number
}

export default function Learning() {
  const [progress, setProgress] = useState<LearningProgress | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    loadProgress()
    const timer = setInterval(loadProgress, 60000) // 1分钟刷新
    return () => clearInterval(timer)
  }, [])

  const loadProgress = async () => {
    try {
      const data = await getLearningProgress()
      setProgress(data)
      setLoading(false)
    } catch (error) {
      console.error('加载学习进度失败:', error)
      setLoading(false)
    }
  }

  if (loading || !progress) {
    return <div className="loading">加载中...</div>
  }

  return (
    <div className="learning-page">
      <div className="learning-header">
        <h1>学习进度</h1>
      </div>

      {/* 今日学习概览 */}
      <Card title="📊 今日学习概览" className="overview-card">
        <div className="learning-stats">
          <div className="stat-item">
            <div className="stat-icon">🔄</div>
            <div className="stat-content">
              <div className="stat-value">{progress.today_cycles}</div>
              <div className="stat-label">学习周期</div>
            </div>
          </div>
          <div className="stat-item">
            <div className="stat-icon">⚖️</div>
            <div className="stat-content">
              <div className="stat-value">{progress.factor_adjustments}</div>
              <div className="stat-label">因子调权</div>
            </div>
          </div>
          <div className="stat-item">
            <div className="stat-icon">📈</div>
            <div className="stat-content">
              <div className="stat-value">{progress.online_updates}</div>
              <div className="stat-label">在线更新</div>
            </div>
          </div>
          <div className="stat-item">
            <div className="stat-icon">🧪</div>
            <div className="stat-content">
              <div className="stat-value">{progress.experiments_running}</div>
              <div className="stat-label">实验进行中</div>
            </div>
          </div>
        </div>
      </Card>

      {/* 决策准确率 */}
      <Card title="🎯 决策准确率" className="accuracy-card">
        <div className="accuracy-display">
          <div className="accuracy-value">
            {(progress.decision_accuracy * 100).toFixed(1)}%
          </div>
          <div className="accuracy-trend">
            {progress.decision_accuracy >= 0.65 ? '↑ 表现良好' : '↓ 需要改进'}
          </div>
        </div>
        <ProgressBar percent={progress.decision_accuracy * 100} />
        <div className="accuracy-hint">
          近30天决策验证结果，准确率 ≥65% 为优秀
        </div>
      </Card>

      {/* 因子进化 */}
      <Card title="🧬 因子进化" className="factor-card">
        <div className="factor-stats">
          <div className="factor-item">
            <span className="factor-label">活跃因子</span>
            <span className="factor-value">71 个</span>
          </div>
          <div className="factor-item">
            <span className="factor-label">今日调权</span>
            <span className="factor-value highlight">{progress.factor_adjustments} 次</span>
          </div>
          <div className="factor-item">
            <span className="factor-label">新部署</span>
            <span className="factor-value success">{progress.new_factors_deployed} 个</span>
          </div>
        </div>

        {progress.new_factors_deployed > 0 && (
          <div className="new-factors">
            <Tag color="success">s_forge_kdj_cross 新部署</Tag>
            <Tag color="success">s_forge_cci_trend 新部署</Tag>
          </div>
        )}
      </Card>

      {/* 实验室 */}
      <Card title="🔬 实验室" className="lab-card">
        {progress.experiments_running > 0 ? (
          <div className="experiments">
            <div className="experiment-item">
              <div className="experiment-header">
                <span className="experiment-name">隔夜策略权重优化</span>
                <Tag color="primary">进行中</Tag>
              </div>
              <div className="experiment-detail">
                <span>s_vol +10% → 预期收益 +0.5%</span>
              </div>
              <div className="experiment-progress">
                <span className="progress-label">回测进度</span>
                <ProgressBar percent={65} />
                <span className="progress-value">65%</span>
              </div>
            </div>

            <div className="experiment-item">
              <div className="experiment-header">
                <span className="experiment-name">集合竞价止损优化</span>
                <Tag color="primary">进行中</Tag>
              </div>
              <div className="experiment-detail">
                <span>ATR倍数 2.5 → 3.0</span>
              </div>
              <div className="experiment-progress">
                <span className="progress-label">回测进度</span>
                <ProgressBar percent={40} />
                <span className="progress-value">40%</span>
              </div>
            </div>
          </div>
        ) : (
          <div className="empty-lab">
            <div className="empty-icon">🧪</div>
            <div className="empty-text">当前无实验运行</div>
          </div>
        )}
      </Card>

      {/* 学习时间线 */}
      <Card title="⏱️ 学习时间线" className="timeline-card">
        <div className="timeline">
          <div className="timeline-item">
            <div className="timeline-dot active"></div>
            <div className="timeline-content">
              <div className="timeline-time">12:30</div>
              <div className="timeline-title">午盘学习</div>
              <div className="timeline-desc">信号验证 + 健康快检</div>
            </div>
          </div>
          <div className="timeline-item">
            <div className="timeline-dot"></div>
            <div className="timeline-content">
              <div className="timeline-time">17:30</div>
              <div className="timeline-title">日终学习</div>
              <div className="timeline-desc">因子分析 + 权重调整</div>
            </div>
          </div>
          <div className="timeline-item">
            <div className="timeline-dot"></div>
            <div className="timeline-content">
              <div className="timeline-time">22:30</div>
              <div className="timeline-title">夜班深度学习</div>
              <div className="timeline-desc">全量分析 + 策略优化</div>
            </div>
          </div>
        </div>
      </Card>

      {/* 学习模式 */}
      <Card title="🎓 学习模式" className="mode-card">
        <div className="mode-list">
          <div className="mode-item">
            <div className="mode-icon">⚡</div>
            <div className="mode-content">
              <div className="mode-name">在线学习</div>
              <div className="mode-desc">T+1验证后实时EMA微调 (±0.01限幅)</div>
              <Tag color="success">已启用</Tag>
            </div>
          </div>
          <div className="mode-item">
            <div className="mode-icon">🔄</div>
            <div className="mode-content">
              <div className="mode-name">批量学习</div>
              <div className="mode-desc">每日3轮全量分析 (±0.03调权)</div>
              <Tag color="success">已启用</Tag>
            </div>
          </div>
          <div className="mode-item">
            <div className="mode-icon">🧪</div>
            <div className="mode-content">
              <div className="mode-name">实验学习</div>
              <div className="mode-desc">自主设计实验 + 回测验证</div>
              <Tag color="success">已启用</Tag>
            </div>
          </div>
        </div>
      </Card>
    </div>
  )
}
