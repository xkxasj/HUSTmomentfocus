import type { Activity, AdminMoment, AdminOverview, AdminUser, AuthResponse, ChatMessage, Conversation, FeedData, Location, Moment, ReplySuggestion, StyleProfile, UserProfile } from './types'

const DEFAULT_API_BASE = (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, '') ?? ''
const API_BASE_KEY = 'mouke_api_base'
const currentApiBase = () => (localStorage.getItem(API_BASE_KEY) || DEFAULT_API_BASE).replace(/\/$/, '')
const endpoint = (path: string) => `${currentApiBase()}${path}`
const TOKEN_KEY = 'mouke_access_token'
const DEFAULT_TIMEOUT_MS = 8000

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message)
    this.name = 'ApiError'
  }
}

const fetchWithTimeout = async (input: RequestInfo | URL, init: RequestInit = {}, timeoutMs = DEFAULT_TIMEOUT_MS) => {
  const controller = new AbortController()
  let timedOut = false
  const abortFromCaller = () => controller.abort(init.signal?.reason)
  if (init.signal?.aborted) abortFromCaller()
  else init.signal?.addEventListener('abort', abortFromCaller, { once: true })
  const timer = window.setTimeout(() => {
    timedOut = true
    controller.abort()
  }, timeoutMs)

  try {
    return await fetch(input, { ...init, signal: controller.signal })
  } catch (cause) {
    if (timedOut) throw new Error('连接服务器超时，请检查网络后重试')
    throw cause
  } finally {
    window.clearTimeout(timer)
    init.signal?.removeEventListener('abort', abortFromCaller)
  }
}

const request = (path: string, init: RequestInit = {}, timeoutMs = DEFAULT_TIMEOUT_MS) => {
  const headers = new Headers(init.headers)
  const token = localStorage.getItem(TOKEN_KEY)
  if (token) headers.set('Authorization', `Bearer ${token}`)
  return fetchWithTimeout(endpoint(path), { ...init, headers }, timeoutMs)
}

const json = async <T>(response: Response): Promise<T> => {
  if (!response.ok) {
    const raw = await response.text()
    let message = raw || '请求失败'
    try { message = JSON.parse(raw).detail || message } catch { /* 使用服务端原始文本 */ }
    throw new ApiError(message, response.status)
  }
  return response.json() as Promise<T>
}

export const api = {
  apiBase: currentApiBase,
  setApiBase: (value: string) => localStorage.setItem(API_BASE_KEY, value.trim().replace(/\/$/, '')),
  hasToken: () => Boolean(localStorage.getItem(TOKEN_KEY)),
  setToken: (token: string) => localStorage.setItem(TOKEN_KEY, token),
  logout: () => localStorage.removeItem(TOKEN_KEY),
  isUnauthorized: (cause: unknown) => cause instanceof ApiError && cause.status === 401,
  emailStatus: () => fetchWithTimeout(endpoint('/api/auth/email-status')).then(json<{ configured: boolean; development_mode: boolean }>),
  requestCode: (studentId: string, email: string) => request('/api/auth/request-code', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ student_id: studentId, email }) }).then(json<{ sent: boolean; dev_code: string | null; expires_in: number }>),
  register: (studentId: string, email: string, code: string, password: string) => request('/api/auth/register', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ student_id: studentId, email, code, password }) }).then(json<AuthResponse>),
  login: (studentId: string, password: string) => request('/api/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ student_id: studentId, password }) }).then(json<AuthResponse>),
  me: () => request('/api/auth/me').then(json<UserProfile>),
  updatePrivacy: (shareLocation: boolean) => request('/api/me/privacy', { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ share_location: shareLocation }) }).then(json<UserProfile>),
  updatePosition: (latitude: number, longitude: number) => request('/api/me/position', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ latitude, longitude }) }).then(json<{ updated: boolean; shared: boolean }>),
  feed: () => fetchWithTimeout(endpoint('/api/feed')).then(json<FeedData>),
  locations: () => fetchWithTimeout(endpoint('/api/locations')).then(json<Location[]>),
  moments: (locationId: number) => fetchWithTimeout(endpoint(`/api/locations/${locationId}/moments`)).then(json<Moment[]>),
  activity: () => request('/api/me/activity').then(json<Activity>),
  styleProfile: () => request('/api/me/style-profile').then(json<StyleProfile>),
  mapStyleUrl: () => endpoint('/api/map/style.json'),
  mapTileTemplate: () => endpoint('/api/map/tiles/{z}/{x}/{y}.pbf'),
  mapFontTemplate: () => endpoint('/api/map/fonts/{fontstack}/{range}.pbf'),
  mediaUrl: (path: string | null) => path ? endpoint(path) : '',
  uploadImage: (file: File) => request('/api/uploads/images', { method: 'POST', headers: { 'Content-Type': file.type }, body: file }, 30000).then(json<{ image_url: string; moderation: string }>),
  imageCaption: (imageUrl: string, locationId: number) => request('/api/ai/image-caption', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ image_url: imageUrl, location_id: locationId, tone: '像本人' }) }, 45000).then(json<{ caption: string; captions: string[]; mode: 'vision' | 'template'; vision_used: boolean; style_profile: StyleProfile }>),
  expressionPrompt: (locationId: number, draft: string) => request('/api/ai/expression-prompt', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ location_id: locationId, draft }) }).then(json<{ prompt: string; privacy_note: string | null }>),
  createMoment: (payload: { location_id: number; content: string; mood: string; image_url?: string | null }) => request('/api/moments', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) }).then(json<Moment>),
  conversations: () => request('/api/conversations').then(json<Conversation[]>),
  conversationMessages: (conversationId: number) => request(`/api/conversations/${conversationId}/messages`).then(json<ChatMessage[]>),
  startConversation: (momentId: number) => request('/api/conversations', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ moment_id: momentId }) }).then(json<Conversation>),
  sendMessage: (conversationId: number, content: string) => request(`/api/conversations/${conversationId}/messages`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ content }) }).then(json<ChatMessage>),
  replySuggestions: (conversationId: number) => request('/api/ai/reply-suggestions', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ conversation_id: conversationId }) }, 30000).then(json<{ suggestions: ReplySuggestion[]; style_profile: StyleProfile; ai_used: boolean }>),
  suggestionFeedback: (contextType: 'reply' | 'caption', suggestion: string, finalText: string, selectedRank: number | null) => request('/api/ai/suggestion-feedback', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ context_type: contextType, suggestion, final_text: finalText, selected_rank: selectedRank }) }).then(json<{ recorded: boolean }>),
  trackEvent: (eventName: 'app_open' | 'page_view' | 'session_ping' | 'moment_published' | 'conversation_started' | 'message_sent', sessionId: string, page?: string, durationSeconds?: number, keepalive = false) => request('/api/analytics/events', { method: 'POST', keepalive, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ event_name: eventName, session_id: sessionId, page, duration_seconds: durationSeconds }) }).then(json<{ recorded: boolean }>),
  adminOverview: () => request('/api/admin/overview').then(json<AdminOverview>),
  adminUsers: () => request('/api/admin/users').then(json<AdminUser[]>),
  updateAdminUserStatus: (userId: number, isActive: boolean) => request(`/api/admin/users/${userId}/status`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ is_active: isActive }) }).then(json<{ updated: boolean; is_active: boolean }>),
  adminMoments: () => request('/api/admin/moments').then(json<AdminMoment[]>),
  updateAdminMomentVisibility: (momentId: number, isHidden: boolean) => request(`/api/admin/moments/${momentId}/visibility`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ is_hidden: isHidden }) }).then(json<{ updated: boolean; is_hidden: boolean }>),
}
