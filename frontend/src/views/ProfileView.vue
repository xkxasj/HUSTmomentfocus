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
    <section class="privacy-card">
      <div><p class="eyebrow">回声位置隐私</p><h2>让对方知道你在哪一片校园</h2><p>仅显示“某地点附近”，不展示坐标；位置超过 30 分钟自动失效。默认关闭。</p></div>
      <button class="privacy-toggle" :class="{ active: app.currentUser.value?.share_location }" @click="app.updateLocationPrivacy"><i></i>{{ app.currentUser.value?.share_location ? '已开启' : '已关闭' }}</button>
    </section>
    <div class="memory-card"><span>四年以后</span><h2>这张地图，会记得你曾怎样经过校园。</h2><p>个人时间线、毕业声音地图与年度回顾，会在真实使用数据验证后逐步开放。</p></div>
  </section>
</template>
