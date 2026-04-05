// WebSocket管理器
class WebSocketManager {
  private ws: WebSocket | null = null
  private reconnectTimer: NodeJS.Timeout | null = null
  private listeners: Map<string, Set<Function>> = new Map()

  connect(url: string) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      return
    }

    this.ws = new WebSocket(url)

    this.ws.onopen = () => {
      console.log('WebSocket连接成功')
      if (this.reconnectTimer) {
        clearTimeout(this.reconnectTimer)
        this.reconnectTimer = null
      }
    }

    this.ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        this.emit(data.type, data.payload)
      } catch (error) {
        console.error('WebSocket消息解析失败:', error)
      }
    }

    this.ws.onerror = (error) => {
      console.error('WebSocket错误:', error)
    }

    this.ws.onclose = () => {
      console.log('WebSocket连接关闭，5秒后重连...')
      this.reconnectTimer = setTimeout(() => {
        this.connect(url)
      }, 5000)
    }
  }

  disconnect() {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
    if (this.ws) {
      this.ws.close()
      this.ws = null
    }
  }

  on(event: string, callback: Function) {
    if (!this.listeners.has(event)) {
      this.listeners.set(event, new Set())
    }
    this.listeners.get(event)!.add(callback)
  }

  off(event: string, callback: Function) {
    const listeners = this.listeners.get(event)
    if (listeners) {
      listeners.delete(callback)
    }
  }

  private emit(event: string, data: any) {
    const listeners = this.listeners.get(event)
    if (listeners) {
      listeners.forEach(callback => callback(data))
    }
  }
}

export const wsManager = new WebSocketManager()

// 在应用启动时连接
const WS_URL = import.meta.env.DEV
  ? (window.location.hostname === 'localhost'
      ? 'ws://localhost:18000/ws'
      : `ws://${window.location.hostname}:18000/ws`)
  : `wss://${window.location.host}/ws`

wsManager.connect(WS_URL)
