<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterView, useRoute, useRouter } from 'vue-router'
import AuthGate from './components/AuthGate.vue'
import { useCampusApp } from './composables/useCampusApp'
import { STARTUP_MESSAGES } from './content/startupMessages'
import { trackProductEvent } from './analytics'

const route = useRoute()
const router = useRouter()
const app = useCampusApp()
const startupMessageIndex = ref(0)
let startupMessageTimer: number | undefined
let analyticsTimer: number | undefined
let activeSeconds = 0
const isAdminRoute = computed(() => route.name === 'admin')

const stopStartupMessages = () => {
  window.clearInterval(startupMessageTimer)
  startupMessageTimer = undefined
}

watch(() => app.authLoading.value, loading => {
  stopStartupMessages()
  if (!loading) return
  startupMessageIndex.value = 0
  startupMessageTimer = window.setInterval(() => {
    startupMessageIndex.value = (startupMessageIndex.value + 1) % STARTUP_MESSAGES.length
  }, 4000)
}, { immediate: true })

const openCompose = () => {
  if (!app.selected.value) {
    app.notify('请先在地图中选择一个地点')
    void router.push({ name: 'map' })
    return
  }
  app.composeOpen.value = true
}

const trackCurrentPage = () => {
  if (app.currentUser.value && !app.currentUser.value.is_admin) trackProductEvent('page_view', route.path)
}

onMounted(() => {
  app.initialize()
  analyticsTimer = window.setInterval(() => {
    if (!app.currentUser.value || app.currentUser.value.is_admin || document.visibilityState !== 'visible') return
    activeSeconds += 30
    trackProductEvent('session_ping', route.path, activeSeconds)
  }, 30000)
})
watch(() => app.currentUser.value?.id, (id, previousId) => {
  if (!id || id === previousId || app.currentUser.value?.is_admin) return
  activeSeconds = 0
  trackProductEvent('app_open', route.path)
  trackCurrentPage()
})
watch(() => route.fullPath, trackCurrentPage)
onBeforeUnmount(() => {
  stopStartupMessages()
  window.clearInterval(analyticsTimer)
  if (app.currentUser.value && !app.currentUser.value.is_admin && activeSeconds) trackProductEvent('session_ping', route.path, activeSeconds, true)
})
</script>

<template>
  <div v-if="app.authLoading.value" class="auth-splash">
    <span>刻</span>
    <div class="startup-message-space" aria-live="polite"><p :key="startupMessageIndex">{{ STARTUP_MESSAGES[startupMessageIndex] }}</p></div>
  </div>
  <div v-else-if="app.authError.value" class="auth-startup-error">
    <span class="brand-mark">刻</span><h2>暂时没能连接校园</h2><p>{{ app.authError.value }}</p>
    <button class="primary-button" @click="app.retryAuthentication">重新连接</button>
  </div>
  <AuthGate v-else-if="!app.currentUser.value" @authenticated="app.handleAuthenticated" />
  <div v-else class="app-shell">
    <header class="topbar">
      <button class="brand" @click="router.push({ name: 'moments' })">
        <span class="brand-mark">刻</span>
        <span><strong>某刻</strong><small>MOMENT · HUST</small></span>
      </button>
      <div class="campus-chip"><i></i> {{ isAdminRoute ? '管理员控制台' : '华科主校区 · 今晚' }}</div>
      <button class="avatar" @click="router.push({ name: 'profile' })">{{ app.currentUser.value?.alias.slice(-1) }}</button>
    </header>

    <main>
      <div v-if="app.dataLoading.value" class="service-banner loading">正在连接校园数据…</div>
      <button v-else-if="app.dataError.value" class="service-banner error" @click="app.retryData">{{ app.dataError.value }} · 点击重试</button>
      <RouterView />
    </main>

    <nav v-if="!isAdminRoute" class="bottom-nav">
      <button :class="{ active: route.name === 'moments' }" @click="router.push({ name: 'moments' })"><span>◌</span>此刻</button>
      <button :class="{ active: route.name === 'map' }" @click="router.push({ name: 'map' })"><span>⌖</span>地图</button>
      <button class="compose-fab" @click="openCompose">＋</button>
      <button :class="{ active: route.name === 'chat' }" @click="router.push({ name: 'chat' })"><span>↝</span>回声<i v-if="app.conversations.value.some(item => item.unread_count)"></i></button>
      <button :class="{ active: route.name === 'profile' }" @click="router.push({ name: 'profile' })"><span>◉</span>我的</button>
    </nav>

    <div v-if="!isAdminRoute && app.composeOpen.value" class="modal-backdrop" @click.self="app.composeOpen.value = false">
      <section class="modal">
        <button class="modal-close" @click="app.composeOpen.value = false">×</button>
        <p class="eyebrow">留在 {{ app.selected.value?.short_name }}</p><h2>这一刻，不需要写得很好</h2>
        <button class="ai-question" @click="app.draft.value = app.selected.value?.prompt ?? ''">✦ {{ app.selected.value?.prompt }}</button>
        <textarea v-model="app.draft.value" maxlength="280" placeholder="写下一句话，或者点击上面的问题开始……"></textarea>
        <div v-if="app.imagePreview.value" class="compose-image-preview"><img :src="app.imagePreview.value" alt="待发布图片预览"><button @click="app.clearSelectedImage">移除</button></div>
        <button v-if="app.selectedImage.value" class="ai-question" :disabled="app.captionGenerating.value" @click="app.generateImageCaption">✨ {{ app.captionGenerating.value ? '正在读图…' : '根据图片一键生成文案' }}</button>
        <div v-if="app.captionSuggestions.value.length" class="caption-options">
          <button v-for="(caption, index) in app.captionSuggestions.value" :key="caption" :class="{ selected: app.selectedCaptionIndex.value === index }" @click="app.selectCaptionSuggestion(index)"><span>{{ ['最像我', '稍微润色', '换个感觉'][index] }}</span><p>{{ caption }}</p></button>
        </div>
        <label class="image-picker"><input type="file" accept="image/jpeg,image/png,image/webp" @change="app.selectImage"><span>▧ 添加一张图片</span><small>JPG / PNG / WebP，最大 15MB</small></label>
        <p class="privacy-note">默认匿名 · 只显示模糊地点 · 发布前自动提醒隐私信息</p>
        <button class="primary-button full" :disabled="app.publishing.value || (!app.draft.value.trim() && !app.selectedImage.value)" @click="app.publish">{{ app.publishing.value ? '正在发布…' : '把这一刻留在这里' }}</button>
      </section>
    </div>
    <div v-if="app.toast.value" class="toast">{{ app.toast.value }}</div>
  </div>
</template>
