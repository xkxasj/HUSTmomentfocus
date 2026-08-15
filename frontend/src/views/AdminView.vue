<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'
import { useCampusApp } from '../composables/useCampusApp'
import type { AdminMoment, AdminOverview, AdminUser } from '../types'
import { maskEmail, maskStudentId } from '../utils/privacy'

const app = useCampusApp()
const tab = ref<'overview' | 'users' | 'moments'>('overview')
const overview = ref<AdminOverview | null>(null)
const users = ref<AdminUser[]>([])
const moments = ref<AdminMoment[]>([])
const loading = ref(true)
const error = ref('')

const maxDaily = computed(() => Math.max(1, ...(overview.value?.daily.flatMap(day => [day.active_users, day.messages]) ?? [1])))
const displayRate = (value: number | null) => value === null ? '暂无数据' : `${value}%`
const displayMinutes = (value: number | null) => value === null ? '暂无数据' : `${value} 分钟`
const displayDate = (value: string | null) => value ? new Date(value).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '尚无记录'

const load = async () => {
  if (!app.currentUser.value?.is_admin) { loading.value = false; error.value = '当前账号没有管理员权限'; return }
  loading.value = true
  error.value = ''
  try {
    const [overviewResult, usersResult, momentsResult] = await Promise.all([api.adminOverview(), api.adminUsers(), api.adminMoments()])
    overview.value = overviewResult
    users.value = usersResult
    moments.value = momentsResult
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '管理数据加载失败'
  } finally { loading.value = false }
}

const toggleUser = async (user: AdminUser) => {
  if (user.id === app.currentUser.value?.id) return
  try {
    const result = await api.updateAdminUserStatus(user.id, !user.is_active)
    user.is_active = result.is_active
  } catch (cause) { app.notify(cause instanceof Error ? cause.message : '用户状态更新失败') }
}

const toggleMoment = async (moment: AdminMoment) => {
  try {
    const result = await api.updateAdminMomentVisibility(moment.id, !moment.is_hidden)
    moment.is_hidden = result.is_hidden
  } catch (cause) { app.notify(cause instanceof Error ? cause.message : '内容状态更新失败') }
}

onMounted(load)
</script>

<template>
  <section class="admin-page">
    <header class="admin-hero">
      <div><p class="eyebrow">MOMENT CONTROL</p><h1>某刻管理后台</h1><p>只看运营所需的汇总数据，不展示私人聊天正文。</p></div>
      <button class="ghost-button" @click="$router.push({ name: 'profile' })">返回普通页面</button>
    </header>

    <div v-if="loading" class="admin-state">正在整理运营数据…</div>
    <div v-else-if="error" class="admin-state error"><p>{{ error }}</p><button class="primary-button" @click="load">重新加载</button></div>
    <template v-else-if="overview">
      <nav class="admin-tabs">
        <button :class="{ active: tab === 'overview' }" @click="tab = 'overview'">数据概览</button>
        <button :class="{ active: tab === 'users' }" @click="tab = 'users'">用户管理</button>
        <button :class="{ active: tab === 'moments' }" @click="tab = 'moments'">内容管理</button>
      </nav>

      <div v-if="tab === 'overview'" class="admin-stack">
        <section class="admin-metric-grid">
          <article><span>今日活跃</span><strong>{{ overview.users.dau }}</strong><small>WAU {{ overview.users.wau }} · MAU {{ overview.users.mau }}</small></article>
          <article><span>总用户</span><strong>{{ overview.users.total }}</strong><small>今日新增 {{ overview.users.new_today }}</small></article>
          <article><span>今日聊天消息</span><strong>{{ overview.content.messages_today }}</strong><small>活跃会话 {{ overview.content.conversations_today }}</small></article>
          <article><span>使用时长中位数</span><strong>{{ displayMinutes(overview.sessions.median_minutes) }}</strong><small>近 30 日 {{ overview.sessions.count_30d }} 次会话</small></article>
        </section>

        <section class="admin-panel">
          <div class="panel-title"><div><p class="eyebrow">近 14 日趋势</p><h2>活跃与聊天</h2></div><span><i class="active-dot"></i>活跃用户　<i class="message-dot"></i>消息</span></div>
          <div class="admin-chart">
            <div v-for="day in overview.daily" :key="day.date" class="chart-day" :title="`${day.date}：活跃 ${day.active_users}，消息 ${day.messages}`">
              <div class="bar-pair"><i class="active-bar" :style="{ height: `${Math.max(3, day.active_users / maxDaily * 100)}%` }"></i><i class="message-bar" :style="{ height: `${Math.max(3, day.messages / maxDaily * 100)}%` }"></i></div>
              <small>{{ day.date.slice(5) }}</small>
            </div>
          </div>
        </section>

        <div class="admin-two-column">
          <section class="admin-panel">
            <p class="eyebrow">用户留存</p><h2>注册后是否回来</h2>
            <div class="retention-list"><div v-for="item in overview.retention" :key="item.days"><span>第 {{ item.days }} 天</span><strong>{{ displayRate(item.rate) }}</strong><small>{{ item.retained }} / {{ item.eligible }} 人</small></div></div>
            <p class="metric-note">留存按注册日后的对应自然日发生有效行为计算；新上线初期样本不足时显示暂无数据。</p>
          </section>
          <section class="admin-panel">
            <p class="eyebrow">聊天健康度 · 近 30 日</p><h2>是否形成真实回应</h2>
            <div class="chat-health"><div><span>发起会话</span><strong>{{ overview.chat.conversations_30d }}</strong></div><div><span>获得双方回应</span><strong>{{ displayRate(overview.chat.reply_rate) }}</strong></div><div><span>首次回复中位数</span><strong>{{ displayMinutes(overview.chat.median_first_reply_minutes) }}</strong></div></div>
          </section>
        </div>
      </div>

      <section v-else-if="tab === 'users'" class="admin-panel admin-table-panel">
        <div class="panel-title"><div><p class="eyebrow">最多显示 500 人</p><h2>用户管理</h2></div><span>学号和邮箱默认脱敏</span></div>
        <div class="admin-table-wrap"><table><thead><tr><th>用户</th><th>账号</th><th>加入时间</th><th>最后活跃</th><th>动态 / 消息</th><th>状态</th></tr></thead><tbody>
          <tr v-for="user in users" :key="user.id"><td><strong>{{ user.alias }}</strong><small v-if="user.is_admin">管理员</small></td><td>{{ maskStudentId(user.student_id) }}<small>{{ maskEmail(user.email) }}</small></td><td>{{ displayDate(user.created_at) }}</td><td>{{ displayDate(user.last_seen_at) }}</td><td>{{ user.moment_count }} / {{ user.message_count }}</td><td><button class="status-button" :class="{ danger: user.is_active }" :disabled="user.id === app.currentUser.value?.id" @click="toggleUser(user)">{{ user.is_active ? '停用' : '恢复' }}</button></td></tr>
        </tbody></table></div>
      </section>

      <section v-else class="admin-panel admin-table-panel">
        <div class="panel-title"><div><p class="eyebrow">最近 500 条</p><h2>公开内容管理</h2></div><span>隐藏后普通用户不可见，可随时恢复</span></div>
        <div class="moment-admin-list"><article v-for="moment in moments" :key="moment.id" :class="{ hidden: moment.is_hidden }"><div><span>{{ moment.location_name }} · {{ moment.author_alias }}</span><p>{{ moment.content || '［仅图片］' }}</p><small>{{ displayDate(moment.created_at) }}</small></div><img v-if="moment.image_url" :src="api.mediaUrl(moment.image_url)" alt="内容图片"><button class="status-button" :class="{ danger: !moment.is_hidden }" @click="toggleMoment(moment)">{{ moment.is_hidden ? '恢复' : '隐藏' }}</button></article></div>
      </section>
    </template>
  </section>
</template>
