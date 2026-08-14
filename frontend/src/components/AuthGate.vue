<script setup lang="ts">
import { computed, ref } from 'vue'
import { api } from '../api'
import type { UserProfile } from '../types'

const emit = defineEmits<{ authenticated: [user: UserProfile] }>()
const mode = ref<'login' | 'register'>('login')
const studentId = ref('')
const password = ref('')
const code = ref('')
const devCode = ref('')
const loading = ref(false)
const error = ref('')
const emailStatus = ref<{ configured: boolean; development_mode: boolean } | null>(null)
const showServerSetup = ref(false)
const serverUrl = ref(api.apiBase())
const normalizedStudentId = computed(() => studentId.value.trim().toUpperCase())
const email = computed(() => normalizedStudentId.value ? `${normalizedStudentId.value.toLowerCase()}@hust.edu.cn` : '学号@hust.edu.cn')

api.emailStatus().then(status => (emailStatus.value = status)).catch(() => undefined)

const saveServerUrl = async () => {
  if (!/^https?:\/\/[^\s]+$/i.test(serverUrl.value)) { error.value = '请输入完整服务器地址，例如 http://电脑IP:8000'; return }
  api.setApiBase(serverUrl.value)
  error.value = ''
  try { emailStatus.value = await api.emailStatus(); showServerSetup.value = false }
  catch { error.value = '仍无法连接服务器，请确认电脑和手机在同一网络' }
}

const finish = (token: string, user: UserProfile) => {
  api.setToken(token)
  emit('authenticated', user)
}

const requestCode = async () => {
  if (!/^[A-Za-z0-9]{6,20}$/.test(studentId.value)) { error.value = '请输入 6–20 位字母或数字组成的学号'; return }
  loading.value = true; error.value = ''
  try {
    const result = await api.requestCode(normalizedStudentId.value, email.value)
    devCode.value = result.dev_code ?? ''
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '验证码发送失败' }
  finally { loading.value = false }
}

const submit = async () => {
  loading.value = true; error.value = ''
  try {
    const result = mode.value === 'login'
      ? await api.login(normalizedStudentId.value, password.value)
      : await api.register(normalizedStudentId.value, email.value, code.value, password.value)
    finish(result.access_token, result.user)
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '操作失败' }
  finally { loading.value = false }
}
</script>

<template>
  <main class="auth-page">
    <section class="auth-story">
      <span class="auth-logo">刻</span>
      <p class="eyebrow">MOMENT · HUST</p>
      <h1>校园很大，<br><em>先确认是你。</em></h1>
      <p>学号只用于校内身份验证。公开内容仍使用随机匿名昵称，不向其他同学展示学号和邮箱。</p>
      <div class="auth-trust"><span>✓ 教育邮箱验证</span><span>✓ 默认匿名发布</span><span>✓ 位置共享默认关闭</span></div>
    </section>
    <section class="auth-card">
      <div class="auth-tabs"><button :class="{ active: mode === 'login' }" @click="mode = 'login'">登录</button><button :class="{ active: mode === 'register' }" @click="mode = 'register'">注册</button></div>
      <form @submit.prevent="submit">
        <label>学号<input v-model.trim="studentId" autocapitalize="characters" autocomplete="username" placeholder="请输入完整校园学号" maxlength="20"></label>
        <p v-if="mode === 'register' && emailStatus && !emailStatus.configured" class="email-warning">当前服务器未配置发件邮箱，暂时不能发送真实验证码。</p>
        <label v-if="mode === 'register'">教育邮箱<input :value="email" disabled></label>
        <label v-if="mode === 'register'">邮箱验证码<span class="code-row"><input v-model.trim="code" inputmode="numeric" maxlength="6" placeholder="6 位验证码"><button type="button" :disabled="loading" @click="requestCode">获取验证码</button></span></label>
        <p v-if="devCode" class="dev-code">仅限本机开发测试，邮件并未发送：<strong>{{ devCode }}</strong></p>
        <label>密码<input v-model="password" type="password" :autocomplete="mode === 'login' ? 'current-password' : 'new-password'" minlength="8" maxlength="128" placeholder="至少 8 位"></label>
        <p v-if="error" class="auth-error">{{ error }}</p>
        <button class="primary-button full" :disabled="loading || !studentId || password.length < 8 || (mode === 'register' && code.length !== 6)">{{ loading ? '请稍候…' : mode === 'login' ? '进入某刻' : '完成注册' }}</button>
      </form>
      <small>注册即表示你确认使用本人教育邮箱。密码只保存安全哈希，不保存明文。</small>
      <button class="server-setup-link" type="button" @click="showServerSetup = !showServerSetup">{{ showServerSetup ? '收起连接设置' : '无法连接？设置服务器地址' }}</button>
      <div v-if="showServerSetup" class="server-setup"><input v-model.trim="serverUrl" inputmode="url" placeholder="http://电脑IP:8000"><button type="button" @click="saveServerUrl">保存并测试</button></div>
    </section>
  </main>
</template>
