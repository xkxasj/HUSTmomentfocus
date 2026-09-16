<script setup lang="ts">
import { ref } from 'vue'
import { api } from '../api'
import type { ReportTarget } from '../types'

const props = defineProps<{ targetType: ReportTarget; targetId: number }>()
const emit = defineEmits<{ close: []; submitted: [] }>()
const reason = ref('')
const busy = ref(false)
const error = ref('')
const submit = async () => {
  if (busy.value || reason.value.trim().length < 2) return
  busy.value = true
  error.value = ''
  try { await api.report(props.targetType, props.targetId, reason.value.trim()); emit('submitted'); emit('close') }
  catch (cause) { error.value = cause instanceof Error ? cause.message : '举报提交失败' }
  finally { busy.value = false }
}
</script>

<template>
  <Teleport to="body">
    <div class="modal-backdrop" @click.self="!busy && emit('close')" @keydown.esc="!busy && emit('close')">
      <form class="modal" role="dialog" aria-modal="true" aria-label="举报内容" @submit.prevent="submit">
        <button type="button" class="modal-close" aria-label="关闭举报" :disabled="busy" @click="emit('close')">×</button>
        <h2>举报这段内容</h2>
        <p v-if="targetType === 'conversation'">提交后，管理员可查看此会话最近 20 条消息作为处理依据。</p>
        <p v-else>请说明骚扰、隐私泄露或其他不当内容，管理员会核查处理。</p>
        <label>举报原因<textarea v-model="reason" maxlength="300" minlength="2" required autofocus placeholder="请描述具体问题（至少 2 字）"></textarea></label>
        <p v-if="error" class="auth-error" role="alert">{{ error }}</p>
        <button class="primary-button" :disabled="busy || reason.trim().length < 2">{{ busy ? '正在提交…' : '提交举报' }}</button>
      </form>
    </div>
  </Teleport>
</template>
