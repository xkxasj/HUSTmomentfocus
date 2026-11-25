<script setup lang="ts">
import { ref } from 'vue'
import { api } from '../api'
const props = defineProps<{ kind: 'moments' | 'echoes'; id: number; content: string }>()
const emit = defineEmits<{ changed: []; deleted: [] }>()
const editing = ref(false)
const confirming = ref(false)
const draft = ref('')
const busy = ref(false)
const error = ref('')
const save = async (remove = false) => {
  if (busy.value) return
  busy.value = true; error.value = ''
  try {
    if (remove) { await api.deleteContent(props.kind, props.id); emit('deleted') }
    else { await api.editContent(props.kind, props.id, draft.value); emit('changed') }
    editing.value = false; confirming.value = false
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '操作失败' }
  finally { busy.value = false }
}
</script>
<template>
  <div class="content-editor" @click.stop>
    <div class="social-actions"><button :disabled="busy" @click="draft = content; editing = !editing; confirming = false">编辑文字</button><button :disabled="busy" @click="confirming = !confirming; editing = false">删除</button></div>
    <form v-if="editing" @submit.prevent="save()"><textarea v-model="draft" aria-label="编辑内容" :maxlength="kind === 'moments' ? 280 : 30" rows="3" /><div class="social-actions"><button :disabled="busy">保存</button><button type="button" :disabled="busy" @click="editing = false">取消</button></div></form>
    <div v-if="confirming"><p>确定删除？此操作不可撤销。举报证据与已有聊天记录仍会保留。</p><div class="social-actions"><button :disabled="busy" @click="save(true)">确认删除</button><button :disabled="busy" @click="confirming = false">取消</button></div></div>
    <p v-if="error" class="auth-error" role="alert">{{ error }}</p>
  </div>
</template>
