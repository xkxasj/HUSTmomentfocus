import type { Activity, AuthResponse, ChatMessage, Conversation, FeedData, Location, Moment, UserProfile } from './types'

const DEFAULT_API_BASE = (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, '') ?? ''
const API_BASE_KEY = 'mouke_api_base'
const currentApiBase = () => (localStorage.getItem(API_BASE_KEY) || DEFAULT_API_BASE).replace(/\/$/, '')
const endpoint = (path: string) => `${currentApiBase()}${path}`
const TOKEN_KEY = 'mouke_access_token'

const request = (path: string, init: RequestInit = {}) => {
  const headers = new Headers(init.headers)
  const token = localStorage.getItem(TOKEN_KEY)
  if (token) headers.set('Authorization', `Bearer ${token}`)
  return fetch(endpoint(path), { ...init, headers })
}

const json = async <T>(response: Response): Promise<T> => {
  if (!response.ok) {
    const raw = await response.text()
    try { throw new Error(JSON.parse(raw).detail || '请求失败') } catch (error) { if (error instanceof SyntaxError) throw new Error(raw || '请求失败'); throw error }
  }
  return response.json() as Promise<T>
}

export const api = {
  apiBase: currentApiBase,
  setApiBase: (value: string) => localStorage.setItem(API_BASE_KEY, value.trim().replace(/\/$/, '')),
  hasToken: () => Boolean(localStorage.getItem(TOKEN_KEY)),
  setToken: (token: string) => localStorage.setItem(TOKEN_KEY, token),
  logout: () => localStorage.removeItem(TOKEN_KEY),
  emailStatus: () => fetch(endpoint('/api/auth/email-status')).then(json<{ configured: boolean; development_mode: boolean }>),
  requestCode: (studentId: string, email: string) => request('/api/auth/request-code', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ student_id: studentId, email }) }).then(json<{ sent: boolean; dev_code: string | null; expires_in: number }>),
  register: (studentId: string, email: string, code: string, password: string) => request('/api/auth/register', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ student_id: studentId, email, code, password }) }).then(json<AuthResponse>),
  login: (studentId: string, password: string) => request('/api/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ student_id: studentId, password }) }).then(json<AuthResponse>),
  me: () => request('/api/auth/me').then(json<UserProfile>),
  updatePrivacy: (shareLocation: boolean) => request('/api/me/privacy', { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ share_location: shareLocation }) }).then(json<UserProfile>),
  updatePosition: (latitude: number, longitude: number) => request('/api/me/position', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ latitude, longitude }) }).then(json<{ updated: boolean; shared: boolean }>),
  feed: () => fetch(endpoint('/api/feed')).then(json<FeedData>),
  locations: () => fetch(endpoint('/api/locations')).then(json<Location[]>),
  moments: (locationId: number) => fetch(endpoint(`/api/locations/${locationId}/moments`)).then(json<Moment[]>),
  activity: () => request('/api/me/activity').then(json<Activity>),
  mapStyleUrl: () => endpoint('/api/map/style.json'),
  mapTileTemplate: () => endpoint('/api/map/tiles/{z}/{x}/{y}.pbf'),
  mapFontTemplate: () => endpoint('/api/map/fonts/{fontstack}/{range}.pbf'),
  mediaUrl: (path: string | null) => path ? endpoint(path) : '',
  uploadImage: (file: File) => request('/api/uploads/images', { method: 'POST', headers: { 'Content-Type': file.type }, body: file }).then(json<{ image_url: string; moderation: string }>),
  imageCaption: (imageUrl: string, locationId: number) => request('/api/ai/image-caption', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ image_url: imageUrl, location_id: locationId, tone: '轻松自然' }) }).then(json<{ caption: string; mode: 'vision' | 'template'; vision_used: boolean }>),
  expressionPrompt: (locationId: number, draft: string) => request('/api/ai/expression-prompt', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ location_id: locationId, draft }) }).then(json<{ prompt: string; privacy_note: string | null }>),
  createMoment: (payload: { location_id: number; content: string; mood: string; image_url?: string | null }) => request('/api/moments', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) }).then(json<Moment>),
  conversations: () => request('/api/conversations').then(json<Conversation[]>),
  conversationMessages: (conversationId: number) => request(`/api/conversations/${conversationId}/messages`).then(json<ChatMessage[]>),
  startConversation: (momentId: number) => request('/api/conversations', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ moment_id: momentId }) }).then(json<Conversation>),
  sendMessage: (conversationId: number, content: string) => request(`/api/conversations/${conversationId}/messages`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ content }) }).then(json<ChatMessage>),
}
