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
  peer_presence: { label: string; updated_at: string } | null
}

export type UserProfile = {
  id: number
  student_id: string
  email: string
  alias: string
  share_location: boolean
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
