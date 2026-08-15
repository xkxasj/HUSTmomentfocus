import { computed, ref } from 'vue'
import { api } from '../api'
import { trackProductEvent } from '../analytics'
import type { ChatMessage, Conversation, Location, Moment, ReplySuggestion, StyleProfile, UserProfile } from '../types'

const selectedId = ref(1)
const composeOpen = ref(false)
const draft = ref('')
const selectedImage = ref<File | null>(null)
const imagePreview = ref('')
const uploadedImageUrl = ref<string | null>(null)
const captionGenerating = ref(false)
const captionSuggestions = ref<string[]>([])
const selectedCaptionIndex = ref<number | null>(null)
const publishing = ref(false)
const toast = ref('')
const conversations = ref<Conversation[]>([])
const activeConversationId = ref<number | null>(null)
const chatMessages = ref<ChatMessage[]>([])
const messageDraft = ref('')
const replySuggestions = ref<ReplySuggestion[]>([])
const replySuggestionsLoading = ref(false)
const replyComposerExpanded = ref(false)
const selectedReplyIndex = ref<number | null>(null)
const selectedReplyText = ref('')
const styleProfile = ref<StyleProfile | null>(null)
const dataLoading = ref(false)
const dataError = ref('')
const authLoading = ref(true)
const authError = ref('')
const currentUser = ref<UserProfile | null>(null)
const locations = ref<Location[]>([])
const moments = ref<Moment[]>([])
let initialized = false
let toastTimer: number | undefined
let positionWatchId: number | undefined
let lastPositionUploadAt = 0

const selected = computed(() => locations.value.find(item => item.id === selectedId.value) ?? locations.value[0])
const placeMoments = computed(() => moments.value.filter(item => item.location_id === selected.value?.id))
const activeConversation = computed(() => conversations.value.find(item => item.id === activeConversationId.value) ?? null)
const todayMomentCount = computed(() => locations.value.reduce((total, item) => total + item.today_count, 0))
const todayInteractionCount = computed(() => locations.value.reduce((total, item) => total + item.today_interaction_count, 0))
const topLocations = computed(() => locations.value.slice(0, 3))
const CAMPUS_BOUNDS = { west: 114.392, east: 114.435, south: 30.498, north: 30.525 }
const isInCampus = (latitude: number, longitude: number) => longitude >= CAMPUS_BOUNDS.west && longitude <= CAMPUS_BOUNDS.east
  && latitude >= CAMPUS_BOUNDS.south && latitude <= CAMPUS_BOUNDS.north

const notify = (message: string) => {
  toast.value = message
  window.clearTimeout(toastTimer)
  toastTimer = window.setTimeout(() => (toast.value = ''), 2200)
}

const selectLocation = (id: number) => { selectedId.value = id }
const retryData = () => { void loadAppData() }

const publish = async () => {
  if ((!draft.value.trim() && !selectedImage.value) || !selected.value || publishing.value) return
  publishing.value = true
  try {
    const privacy = await api.expressionPrompt(selected.value.id, draft.value.trim())
    if (privacy.privacy_note) { notify(`${privacy.privacy_note} 请修改后再发布。`); return }
    const imageUrl = selectedImage.value ? await ensureImageUploaded() : null
    const created = await api.createMoment({ location_id: selected.value.id, content: draft.value.trim(), mood: '此刻', image_url: imageUrl })
    moments.value.unshift(created)
    trackProductEvent('moment_published', '/moments')
    if (selectedCaptionIndex.value !== null) void api.suggestionFeedback('caption', captionSuggestions.value[selectedCaptionIndex.value] || '', draft.value.trim(), selectedCaptionIndex.value + 1)
  } catch (cause) {
    notify(cause instanceof Error ? cause.message : '发布失败')
    return
  } finally {
    publishing.value = false
  }
  draft.value = ''
  clearSelectedImage()
  composeOpen.value = false
  notify('这一刻已经留在校园里')
}

const clearSelectedImage = () => {
  if (imagePreview.value) URL.revokeObjectURL(imagePreview.value)
  selectedImage.value = null
  imagePreview.value = ''
  uploadedImageUrl.value = null
  captionSuggestions.value = []
  selectedCaptionIndex.value = null
}

const selectImage = (event: Event) => {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) { notify('请选择 JPG、PNG 或 WebP 图片'); return }
  if (file.size > 15 * 1024 * 1024) { notify('图片不能超过 15MB'); return }
  clearSelectedImage()
  selectedImage.value = file
  imagePreview.value = URL.createObjectURL(file)
}

const ensureImageUploaded = async () => {
  if (uploadedImageUrl.value) return uploadedImageUrl.value
  if (!selectedImage.value) return null
  const uploaded = await api.uploadImage(selectedImage.value)
  uploadedImageUrl.value = uploaded.image_url
  return uploaded.image_url
}

const generateImageCaption = async () => {
  if (!selectedImage.value || !selected.value || captionGenerating.value) return
  captionGenerating.value = true
  try {
    const imageUrl = await ensureImageUploaded()
    if (!imageUrl) return
    const result = await api.imageCaption(imageUrl, selected.value.id)
    captionSuggestions.value = result.captions
    selectedCaptionIndex.value = 0
    styleProfile.value = result.style_profile
    draft.value = result.caption
    notify(result.vision_used ? '已按你的表达方式生成 3 条文案' : '已按你的标点和句长生成 3 条本地建议')
  } catch (cause) {
    notify(cause instanceof Error ? cause.message : '暂时无法生成文案')
  } finally {
    captionGenerating.value = false
  }
}

const selectCaptionSuggestion = (index: number) => {
  const suggestion = captionSuggestions.value[index]
  if (!suggestion) return
  selectedCaptionIndex.value = index
  draft.value = suggestion
}

const openConversation = async (conversation: Conversation) => {
  activeConversationId.value = conversation.id
  messageDraft.value = ''
  replyComposerExpanded.value = false
  replySuggestions.value = []
  selectedReplyIndex.value = null
  selectedReplyText.value = ''
  try { chatMessages.value = await api.conversationMessages(conversation.id) } catch { chatMessages.value = [] }
}

const loadReplySuggestions = async (force = false) => {
  if (!activeConversation.value || replySuggestionsLoading.value || (replySuggestions.value.length && !force)) return
  replySuggestionsLoading.value = true
  try {
    const result = await api.replySuggestions(activeConversation.value.id)
    replySuggestions.value = result.suggestions
    styleProfile.value = result.style_profile
  } catch (cause) {
    notify(cause instanceof Error ? cause.message : '暂时无法生成回复建议')
  } finally {
    replySuggestionsLoading.value = false
  }
}

const expandReplyComposer = () => {
  replyComposerExpanded.value = true
  void loadReplySuggestions()
}

const selectReplySuggestion = (index: number) => {
  const suggestion = replySuggestions.value[index]
  if (!suggestion) return
  selectedReplyIndex.value = index
  selectedReplyText.value = suggestion.text
  messageDraft.value = suggestion.text
}

const refreshConversations = async () => {
  try {
    const refreshed = await api.conversations()
    conversations.value = refreshed
    if (activeConversationId.value && !refreshed.some(item => item.id === activeConversationId.value)) {
      activeConversationId.value = null
      chatMessages.value = []
    }
  } catch { /* 保留当前会话，下一次自动刷新时重试 */ }
}

const openChatFromMoment = async (moment: Moment) => {
  let conversation = conversations.value.find(item => item.origin_moment_id === moment.id)
  if (!conversation) {
    try { conversation = await api.startConversation(moment.id) }
    catch (cause) { notify(cause instanceof Error ? cause.message : '无法发起回声'); return false }
    conversations.value.unshift(conversation)
    trackProductEvent('conversation_started', '/chat')
  }
  await openConversation(conversation)
  return true
}

const sendChatMessage = async () => {
  const content = messageDraft.value.trim()
  if (!content || !activeConversation.value) return
  let message: ChatMessage
  try { message = await api.sendMessage(activeConversation.value.id, content) }
  catch (cause) { notify(cause instanceof Error ? cause.message : '发送失败'); return }
  chatMessages.value.push(message)
  trackProductEvent('message_sent', '/chat')
  activeConversation.value.last_message = content
  activeConversation.value.updated_at = message.created_at
  if (selectedReplyIndex.value !== null) void api.suggestionFeedback('reply', selectedReplyText.value, content, selectedReplyIndex.value + 1)
  messageDraft.value = ''
  selectedReplyIndex.value = null
  selectedReplyText.value = ''
  replySuggestions.value = []
  replyComposerExpanded.value = false
}

const loadAppData = async () => {
  dataLoading.value = true
  dataError.value = ''
  void api.styleProfile().then(profile => { styleProfile.value = profile }).catch(() => { /* 不影响核心内容加载 */ })
  try {
    const [feedResult, conversationsResult] = await Promise.allSettled([api.feed(), api.conversations()])
    if (feedResult.status === 'fulfilled') {
      locations.value = feedResult.value.locations
      moments.value = feedResult.value.moments
    }
    if (conversationsResult.status === 'fulfilled') {
      conversations.value = conversationsResult.value
    }
    if (feedResult.status === 'rejected' || conversationsResult.status === 'rejected') {
      dataError.value = '部分校园数据加载失败，请检查网络后重试。'
    }
  } finally { dataLoading.value = false }
}

const handleAuthenticated = (user: UserProfile) => {
  currentUser.value = user
  if (user.share_location) startLocationWatch()
  void loadAppData()
}

const logout = () => {
  stopLocationWatch()
  api.logout()
  currentUser.value = null
  conversations.value = []
  moments.value = []
  locations.value = []
}

function stopLocationWatch() {
  if (positionWatchId !== undefined) navigator.geolocation?.clearWatch(positionWatchId)
  positionWatchId = undefined
}

function startLocationWatch() {
  if (!navigator.geolocation || positionWatchId !== undefined) return
  positionWatchId = navigator.geolocation.watchPosition(position => {
    const { latitude, longitude } = position.coords
    if (!currentUser.value?.share_location || !isInCampus(latitude, longitude)) return
    const now = Date.now()
    if (now - lastPositionUploadAt < 15000) return
    lastPositionUploadAt = now
    api.updatePosition(latitude, longitude).catch(() => { /* 下一次定位时重试 */ })
  }, () => { /* 用户可在系统设置中重新授权 */ }, {
    enableHighAccuracy: true,
    timeout: 15000,
    maximumAge: 30000,
  })
}

const updateLocationPrivacy = async () => {
  if (!currentUser.value) return
  if (currentUser.value.share_location) {
    try {
      currentUser.value = await api.updatePrivacy(false)
      stopLocationWatch()
      notify('位置共享已关闭')
    } catch (cause) { notify(cause instanceof Error ? cause.message : '隐私设置更新失败') }
    return
  }
  if (!navigator.geolocation) { notify('当前设备不支持定位，无法开启位置共享'); return }
  notify('正在获取你的位置…')
  try {
    const position = await new Promise<GeolocationPosition>((resolve, reject) => navigator.geolocation.getCurrentPosition(resolve, reject, {
      enableHighAccuracy: true,
      timeout: 12000,
      maximumAge: 30000,
    }))
    const { latitude, longitude } = position.coords
    if (!isInCampus(latitude, longitude)) { notify('你暂时不在主校区，位置共享未开启'); return }
    await api.updatePosition(latitude, longitude)
    currentUser.value = await api.updatePrivacy(true)
    lastPositionUploadAt = Date.now()
    startLocationWatch()
    notify('位置共享已开启，聊天对象现在可以看到你的位置')
  } catch (cause) { notify(cause instanceof Error ? cause.message : '隐私设置更新失败') }
}

const handlePosition = async (position: { latitude: number; longitude: number; inCampus: boolean }) => {
  if (position.inCampus && currentUser.value?.share_location) {
    try { await api.updatePosition(position.latitude, position.longitude) } catch { /* 下次定位时重试 */ }
  }
}

const verifySession = async () => {
  authLoading.value = true
  authError.value = ''
  if (!api.hasToken()) {
    authLoading.value = false
    return
  }
  try {
    currentUser.value = await api.me()
    if (currentUser.value.share_location) startLocationWatch()
    authLoading.value = false
    void loadAppData()
  } catch (cause) {
    currentUser.value = null
    if (api.isUnauthorized(cause)) api.logout()
    else authError.value = cause instanceof Error ? cause.message : '暂时无法连接服务器'
    authLoading.value = false
  }
}

const initialize = () => {
  if (initialized) return
  initialized = true
  void verifySession()
}

const retryAuthentication = () => { void verifySession() }

export const useCampusApp = () => ({
  selectedId, composeOpen, draft, selectedImage, imagePreview, uploadedImageUrl, captionGenerating, captionSuggestions, selectedCaptionIndex, publishing, toast, conversations, activeConversationId,
  chatMessages, messageDraft, replySuggestions, replySuggestionsLoading, replyComposerExpanded, selectedReplyIndex, styleProfile, dataLoading, dataError, authLoading, authError, currentUser,
  locations, moments, selected, placeMoments, activeConversation,
  todayMomentCount, todayInteractionCount, topLocations, notify, selectLocation,
  retryData, publish, selectImage, clearSelectedImage, generateImageCaption, selectCaptionSuggestion, openConversation, refreshConversations, openChatFromMoment, sendChatMessage,
  loadReplySuggestions, expandReplyComposer, selectReplySuggestion,
  loadAppData, handleAuthenticated, logout, updateLocationPrivacy, handlePosition,
  initialize, retryAuthentication,
})
