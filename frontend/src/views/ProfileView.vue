<script setup lang="ts">
import { computed } from 'vue'
import { useCampusApp } from '../composables/useCampusApp'
import { maskEmail, maskStudentId } from '../utils/privacy'

const app = useCampusApp()
const safeStudentId = computed(() => app.currentUser.value ? maskStudentId(app.currentUser.value.student_id) : '')
const safeEmail = computed(() => app.currentUser.value ? maskEmail(app.currentUser.value.email) : '')
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
      <div><p class="eyebrow">回声位置隐私</p><h2>让聊天对象在地图上看到你</h2><p>仅对与你聊天的人显示；开启时会请求定位权限，位置超过 30 分钟自动失效。默认关闭。</p></div>
      <button class="privacy-toggle" :class="{ active: app.currentUser.value?.share_location }" @click="app.updateLocationPrivacy"><i></i>{{ app.currentUser.value?.share_location ? '已开启' : '已关闭' }}</button>
    </section>
    <div class="memory-card"><span>四年以后</span><h2>这张地图，会记得你曾怎样经过校园。</h2><p>个人时间线、毕业声音地图与年度回顾，会在真实使用数据验证后逐步开放。</p></div>
  </section>
</template>
