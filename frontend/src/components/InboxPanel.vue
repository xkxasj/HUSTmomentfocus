<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'
import type { InboxNotice, MyReport } from '../types'
const notices = ref<InboxNotice[]>([])
const reports = ref<MyReport[]>([])
const unread = ref(0)
const moreNotices = ref(false)
const moreReports = ref(false)
const busy = ref(false)
const error = ref('')
const load = async (part: 'all' | 'notices' | 'reports' = 'all') => {
  if (busy.value) return
  busy.value = true; error.value = ''
  try {
    if (part !== 'reports') {
      const result = await api.notifications(part === 'notices' ? notices.value.at(-1)?.id : undefined)
      notices.value = part === 'notices' ? [...notices.value, ...result.items] : result.items
      unread.value = result.unread_count; moreNotices.value = result.has_more
    }
    if (part !== 'notices') {
      const result = await api.myReports(part === 'reports' ? reports.value.at(-1)?.id : undefined)
      reports.value = part === 'reports' ? [...reports.value, ...result.items] : result.items
      moreReports.value = result.has_more
    }
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '加载失败' }
  finally { busy.value = false }
}
const read = async (notice: InboxNotice) => {
  try { await api.readNotification(notice.id); if (!notice.is_read) unread.value = Math.max(0, unread.value - 1); notice.is_read = true }
  catch (cause) { error.value = cause instanceof Error ? cause.message : '标记失败' }
}
const statuses: Record<string, string> = { pending: '待处理', resolved: '已处理', dismissed: '未认定违规' }
const targets: Record<string, string> = { moment: '片段', echo: '回声', conversation: '会话' }
onMounted(() => load())
</script>
<template>
  <section class="section-block inbox-panel">
    <div class="social-actions"><h2>互动通知 · {{ unread }} 条未读</h2><button :disabled="busy" @click="load()">刷新</button></div>
    <p v-if="busy" role="status">正在加载…</p><p v-if="error" class="auth-error" role="alert">{{ error }}</p>
    <p v-if="!busy && !notices.length">还没有通知，新收到的共鸣、回声与举报处理结果会出现在这里。</p>
    <article v-for="notice in notices" :key="notice.id" class="echo-row"><div><small>{{ new Date(notice.created_at).toLocaleString('zh-CN') }} · {{ notice.is_read ? '已读' : '未读' }}</small><p>{{ notice.text }}</p></div><button v-if="!notice.is_read" @click="read(notice)">标为已读</button></article>
    <div class="social-actions"><button v-if="moreNotices" :disabled="busy" @click="load('notices')">更多通知</button></div>
    <h2>我的举报</h2><p v-if="!busy && !reports.length">还没有举报记录。</p>
    <article v-for="report in reports" :key="report.id" class="report-row"><small>#{{ report.id }} · {{ targets[report.target_type] }} · {{ statuses[report.status] }} · {{ new Date(report.created_at).toLocaleString('zh-CN') }}</small><p>{{ report.reason }}</p><p v-if="report.status === 'pending'">已提交，等待管理员核查。</p><small v-if="report.resolved_at">处理时间：{{ new Date(report.resolved_at).toLocaleString('zh-CN') }}</small></article>
    <div class="social-actions"><button v-if="moreReports" :disabled="busy" @click="load('reports')">更多举报记录</button></div>
  </section>
</template>

<style scoped>
.inbox-panel { background: #f7faf6; border-radius: 20px; padding: 24px; }
</style>
