import { useEffect } from 'react'
import { wsManager } from '../api/websocket'

export function useWebSocket(event: string, callback: Function) {
  useEffect(() => {
    wsManager.on(event, callback)
    return () => {
      wsManager.off(event, callback)
    }
  }, [event, callback])
}
