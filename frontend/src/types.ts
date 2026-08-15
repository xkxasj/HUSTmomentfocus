export type Location = {
  id: number
  name: string
  short_name: string
  description: string
  prompt: string
  mood: string
  accent: string
  category?: 'landmark' | 'dining'
  x: number
  y: number
  latitude: number
  longitude: number
  moment_count: number
  today_count: number
  today_interaction_count: number
  today_rank: number
}

export type Moment = {
  id: number
  location_id: number
  location_name: string
  author_alias: string
  content: string
  image_url: string | null
  mood: string
  created_at: string
  resonance_count: number
  echo_count: number
  is_official: boolean
}

export type FeedData = {
  greeting: string
  campus_pulse: string
  locations: Location[]
  moments: Moment[]
}

export type Activity = {
  alias: string
  posted_count: number
  resonance_given: number
  echoes_sent: number
  received_resonance: number
  moments: Moment[]
}

export type Conversation = {
  id: number
  peer_alias: string
  origin_moment_id: number | null
  origin_excerpt: string
  location_name: string
  last_message: string
  updated_at: string
  unread_count: number
  peer_presence: {
    label: string
    updated_at: string
    latitude: number
    longitude: number
  } | null
}

export type UserProfile = {
  id: number
  student_id: string
  email: string
  alias: string
  share_location: boolean
  is_admin: boolean
}

export type AdminOverview = {
  generated_at: string
  users: { total: number; new_today: number; dau: number; wau: number; mau: number }
  content: { moments_today: number; messages_today: number; conversations_today: number }
  sessions: { count_30d: number; average_minutes: number | null; median_minutes: number | null }
  retention: { days: number; eligible: number; retained: number; rate: number | null }[]
  chat: { conversations_30d: number; replied_conversations_30d: number; reply_rate: number | null; median_first_reply_minutes: number | null }
  daily: { date: string; new_users: number; active_users: number; messages: number }[]
}

export type AdminUser = UserProfile & {
  is_active: boolean
  created_at: string
  last_seen_at: string | null
  moment_count: number
  message_count: number
}

export type AdminMoment = {
  id: number
  author_alias: string
  content: string
  image_url: string | null
  location_name: string
  created_at: string
  is_hidden: boolean
}

export type AuthResponse = {
  access_token: string
  token_type: 'bearer'
  user: UserProfile
}

export type ChatMessage = {
  id: number
  conversation_id: number
  sender: 'me' | 'peer'
  content: string
  created_at: string
}

export type StyleProfile = {
  sample_count: number
  ready: boolean
  confidence: '稳定' | '正在了解' | '尚未开始'
  average_length: number
  preferred_ending: string
  habits: string[]
  summary: string
  representative_samples: string[]
}

export type ReplySuggestion = {
  label: string
  intent: 'natural' | 'continue' | 'gentle'
  text: string
}
