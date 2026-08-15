import { api } from './api'

export const analyticsSessionId = typeof crypto !== 'undefined' && crypto.randomUUID
  ? crypto.randomUUID()
  : `session-${Date.now()}-${Math.random().toString(36).slice(2)}`

export type ProductEvent = 'app_open' | 'page_view' | 'session_ping' | 'moment_published' | 'conversation_started' | 'message_sent'

export const trackProductEvent = (eventName: ProductEvent, page?: string, durationSeconds?: number, keepalive = false) => {
  void api.trackEvent(eventName, analyticsSessionId, page, durationSeconds, keepalive).catch(() => {
    // 统计失败不能影响用户的正常操作。
  })
}
