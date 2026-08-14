import { computed, ref } from 'vue'
import { api } from '../api'
import type { ChatMessage, Conversation, Location, Moment, UserProfile } from '../types'

const selectedId = ref(1)
const composeOpen = ref(false)
const draft = ref('')
const selectedImage = ref<File | null>(null)
const imagePreview = ref('')
const uploadedImageUrl = ref<string | null>(null)
const captionGenerating = ref(false)
const publishing = ref(false)
const toast = ref('')
const conversations = ref<Conversation[]>([])
const activeConversationId = ref<number | null>(null)
const chatMessages = ref<ChatMessage[]>([])
const messageDraft = ref('')
const dataLoading = ref(false)
const dataError = ref('')
const authLoading = ref(true)
const currentUser = ref<UserProfile | null>(null)
const locations = ref<Location[]>([])
const moments = ref<Moment[]>([])
let initialized = false
let toastTimer: number | undefined

const selected = computed(() => locations.value.find(item => item.id === selectedId.value) ?? locations.value[0])
const placeMoments = computed(() => moments.value.filter(item => item.location_id === selected.value?.id))
const activeConversation = computed(() => conversations.value.find(item => item.id === activeConversationId.value) ?? null)
const todayMomentCount = computed(() => locations.value.reduce((total, item) => total + item.today_count, 0))
const todayInteractionCount = computed(() => locations.value.reduce((total, item) => total + item.today_interaction_count, 0))
const topLocations = computed(() => locations.value.slice(0, 3))

const notify = (message: string) => {
  toast.value = message
  window.clearTimeout(toastTimer)
  toastTimer = window.setTimeout(() => (toast.value = ''), 2200)
}

const selectLocation = (id: number) => { selectedId.value = id }
const retryData = () => window.location.reload()

const publish = async () => {
  if ((!draft.value.trim() && !selectedImage.value) || !selected.value || publishing.value) return
  publishing.value = true
  try {
    const privacy = await api.expressionPrompt(selected.value.id, draft.value.trim())
    if (privacy.privacy_note) { notify(`${privacy.privacy_note} 请修改后再发布。`); return }
    const imageUrl = selectedImage.value ? await ensureImageUploaded() : null
    const created = await api.createMoment({ location_id: selected.value.id, content: draft.value.trim(), mood: '此刻', image_url: imageUrl })
    moments.value.unshift(created)
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
    draft.value = result.caption
    notify(result.vision_used ? '已根据图片生成文案' : 'AI 尚未配置，先给你一句地点灵感')
  } catch (cause) {
    notify(cause instanceof Error ? cause.message : '暂时无法生成文案')
  } finally {
    captionGenerating.value = false
  }
}

const openConversation = async (conversation: Conversation) => {
  activeConversationId.value = conversation.id
  try { chatMessages.value = await api.conversationMessages(conversation.id) } catch { chatMessages.value = [] }
}

const openChatFromMoment = async (moment: Moment) => {
  let conversation = conversations.value.find(item => item.origin_moment_id === moment.id)
  if (!conversation) {
    try { conversation = await api.startConversation(moment.id) }
    catch (cause) { notify(cause instanceof Error ? cause.message : '无法发起回声'); return false }
    conversations.value.unshift(conversation)
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
  activeConversation.value.last_message = content
  activeConversation.value.updated_at = message.created_at
  messageDraft.value = ''
}

const loadAppData = async () => {
  dataLoading.value = true
  try {
    const data = await api.feed()
    locations.value = data.locations
    moments.value = data.moments
    conversations.value = await api.conversations()
    if (conversations.value.length) await openConversation(conversations.value[0])
    dataError.value = ''
  } catch {
    dataError.value = '数据服务尚未连接。地图仍可浏览，但发布、私聊和内容列表需要后端服务。'
  } finally { dataLoading.value = false }
}

const handleAuthenticated = async (user: UserProfile) => {
  currentUser.value = user
  await loadAppData()
}

const logout = () => {
  api.logout()
  currentUser.value = null
  conversations.value = []
  moments.value = []
  locations.value = []
}

const updateLocationPrivacy = async () => {
  if (!currentUser.value) return
  try { currentUser.value = await api.updatePrivacy(!currentUser.value.share_location) }
  catch (cause) { notify(cause instanceof Error ? cause.message : '隐私设置更新失败') }
}

const handlePosition = async (position: { latitude: number; longitude: number; inCampus: boolean }) => {
  if (position.inCampus && currentUser.value?.share_location) {
    try { await api.updatePosition(position.latitude, position.longitude) } catch { /* 下次定位时重试 */ }
  }
}

const initialize = async () => {
  if (initialized) return
  initialized = true
  if (api.hasToken()) {
    try { currentUser.value = await api.me(); await loadAppData() }
    catch { api.logout(); currentUser.value = null }
  }
  authLoading.value = false
}

export const useCampusApp = () => ({
  selectedId, composeOpen, draft, selectedImage, imagePreview, uploadedImageUrl, captionGenerating, publishing, toast, conversations, activeConversationId,
  chatMessages, messageDraft, dataLoading, dataError, authLoading, currentUser,
  locations, moments, selected, placeMoments, activeConversation,
  todayMomentCount, todayInteractionCount, topLocations, notify, selectLocation,
  retryData, publish, selectImage, clearSelectedImage, generateImageCaption, openConversation, openChatFromMoment, sendChatMessage,
  loadAppData, handleAuthenticated, logout, updateLocationPrivacy, handlePosition,
  initialize,
})
