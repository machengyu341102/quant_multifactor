import axios from 'axios'

// 自动检测：如果是手机访问，使用当前host的IP
const API_BASE = import.meta.env.DEV
  ? (window.location.hostname === 'localhost'
      ? ''
      : `http://${window.location.hostname}:8000`)
  : ''

const api = axios.create({
  baseURL: API_BASE,
  timeout: 10000,
})

// 系统状态
export const getSystemStatus = () =>
  api.get('/api/system').then(res => res.data)

// 策略列表
export const getStrategies = () =>
  api.get('/api/strategies').then(res => res.data)

// 信号列表
export const getSignals = (params?: { date?: string; strategy?: string }) =>
  api.get('/api/signals', { params }).then(res => res.data)

// 信号详情
export const getSignalDetail = (id: string) =>
  api.get(`/api/signals/${id}`).then(res => res.data)

// 持仓列表
export const getPositions = () =>
  api.get('/api/positions').then(res => res.data)

// 持仓详情
export const getPositionDetail = (code: string) =>
  api.get(`/api/positions/${code}`).then(res => res.data)

// 学习进度
export const getLearningProgress = () =>
  api.get('/api/learning').then(res => res.data)

export default api
