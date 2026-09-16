<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useCampusApp } from '../composables/useCampusApp'
import { maskEmail, maskStudentId } from '../utils/privacy'
import { api } from '../api'
import type { BlockedUser } from '../types'
import MomentActions from '../components/MomentActions.vue'

const app = useCampusApp()
const safeStudentId = computed(() => app.currentUser.value ? maskStudentId(app.currentUser.value.student_id) : '')
const safeEmail = computed(() => app.currentUser.value ? maskEmail(app.currentUser.value.email) : '')
const blocks = ref<BlockedUser[]>([])
const loading = ref(false)
const error = ref('')
const load = async () => {
  loading.value = true
  error.value = ''
  try { const [, result] = await Promise.all([app.refreshActivity(), api.blocks()]); blocks.value = result }
  catch (cause) { error.value = cause instanceof Error ? cause.message : '活动加载失败' }
  finally { loading.value = false }
}
const unblock = async (id: number) => {
  try { await api.unblock(id); blocks.value = blocks.value.filter(b => b.id !== id); app.notify('已解除屏蔽，结束的会话不会自动恢复'); await app.refreshConversations() }
  catch (cause) { app.notify(cause instanceof Error ? cause.message : '解除屏蔽失败') }
}
onMounted(load)
</script>

<template>
  <section class="page me-page">
    <p class="eyebrow">我的校园足迹</p><h1>你不是在经营人设，<br><em>只是在收藏经过。</em></h1>
    <section class="account-card">
      <div><p class="eyebrow">校园账号</p><h2>{{ app.currentUser.value?.alias }}</h2><span>{{ safeStudentId }} · {{ safeEmail }}</span></div>
      <button class="ghost-button" @click="app.logout">退出登录</button>
    </section>
    <section v-if="app.currentUser.value?.is_admin" class="admin-entry-card">
      <div><p class="eyebrow">管理员权限</p><h2>查看运营数据与管理内容</h2><p>管理页面与普通用户页面共用同一套应用，但由服务端权限严格隔离。</p></div>
      <button class="primary-button" @click="$router.push({ name: 'admin' })">进入管理后台</button>
    </section>
    <section class="ai-style-card">
      <div class="ai-style-heading"><div><p class="eyebrow">我的表达档案</p><h2>AI {{ app.styleProfile.value?.confidence || '正在了解' }}你的说话方式</h2></div><strong>{{ app.styleProfile.value?.sample_count || 0 }} 条样本</strong></div>
      <p>所有人共用同一个基础模型；生成时只加载你自己的表达习惯和少量代表句，所以每个人得到的建议不同。</p>
      <div v-if="app.styleProfile.value?.habits.length" class="style-habits"><span v-for="habit in app.styleProfile.value.habits" :key="habit">{{ habit }}</span></div>
      <small>只分析句长、标点、换行和常用语气词，不推断性格或身份。你最终发送的文字会让建议逐渐更像你。</small>
    </section>
    <section class="privacy-card">
      <div><p class="eyebrow">回声位置隐私</p><h2>让聊天对象在地图上看到你</h2><p>仅在双方接受且未到期的会话中显示；开启时会请求定位权限，位置超过 30 分钟自动失效。默认关闭。</p></div>
      <button class="privacy-toggle" :class="{ active: app.currentUser.value?.share_location }" @click="app.updateLocationPrivacy"><i></i>{{ app.currentUser.value?.share_location ? '已开启' : '已关闭' }}</button>
    </section>
    <p v-if="loading">正在加载你的活动…</p>
    <p v-if="error" class="auth-error" role="alert">{{ error }} <button @click="load">重试</button></p>
    <section v-if="app.activity.value" class="section-block">
      <h2>我的活动</h2>
      <div class="activity-stats"><span>发布 <strong>{{ app.activity.value.posted_count }}</strong></span><span>送出共鸣 <strong>{{ app.activity.value.resonance_given }}</strong></span><span>公开回声 <strong>{{ app.activity.value.echoes_sent }}</strong></span><span>收到共鸣 <strong>{{ app.activity.value.received_resonance }}</strong></span></div>
      <p v-if="!app.activity.value.moments.length">还没有发布片段，从地图上选一个地点开始吧。</p>
      <div class="moment-grid"><article v-for="moment in app.activity.value.moments" :key="moment.id" class="moment-card"><small>{{ moment.location_name }} · {{ new Date(moment.created_at).toLocaleString('zh-CN') }}</small><img v-if="moment.image_url" class="moment-image" :src="api.mediaUrl(moment.image_url)" alt="我的片段图片" loading="lazy"><p>{{ moment.content }}</p><MomentActions :moment="moment" /></article></div>
    </section>
    <section class="privacy-card"><div><h2>屏蔽名单</h2><p v-if="!blocks.length">你还没有屏蔽任何人。</p><div v-for="block in blocks" :key="block.id" class="echo-row"><span>{{ block.alias }}</span><button @click="unblock(block.id)">解除屏蔽</button></div></div></section>
  </section>
</template>
