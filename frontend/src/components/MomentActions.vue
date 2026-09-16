<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'
import { useCampusApp } from '../composables/useCampusApp'
import type { Interactions, Moment, ReportTarget } from '../types'
import ReportDialog from './ReportDialog.vue'

const props = defineProps<{ moment: Moment }>()
const app = useCampusApp()
const router = useRouter()
const expanded = ref(false)
const data = ref<Interactions | null>(null)
const busy = ref(false)
const error = ref('')
const draft = ref('')
const reportTarget = ref<{ type: ReportTarget; id: number } | null>(null)
const load = async () => {
  error.value = ''
  try {
    data.value = await api.interactions(props.moment.id)
    app.syncMomentCounts(props.moment.id, data.value.resonance_count, data.value.echoes.length)
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '互动加载失败' }
}
const toggle = async () => { expanded.value = !expanded.value; if (expanded.value) await load() }
const resonate = async (kind: string) => {
  if (busy.value || !data.value) return
  busy.value = true
  try {
    const result = data.value.my_resonance === kind ? await api.removeResonance(props.moment.id) : await api.resonate(props.moment.id, kind)
    data.value.my_resonance = result.my_resonance
    data.value.resonance_count = result.resonance_count
    app.syncMomentCounts(props.moment.id, result.resonance_count, data.value.echoes.length)
    void app.refreshLocations()
  } catch (cause) { app.notify(cause instanceof Error ? cause.message : '共鸣失败') }
  finally { busy.value = false }
}
const send = async () => {
  if (busy.value || !draft.value.trim()) return
  busy.value = true
  try { await api.echo(props.moment.id, draft.value.trim()); draft.value = ''; await load(); void app.refreshLocations() }
  catch (cause) { app.notify(cause instanceof Error ? cause.message : '回声发送失败') }
  finally { busy.value = false }
}
const chat = async () => { if (await app.openChatFromMoment(props.moment)) await router.push({ name: 'chat' }) }
</script>

<template>
  <div class="moment-interactions" @click.stop>
    <div class="social-actions">
      <button :aria-expanded="expanded" @click="toggle">共鸣 {{ moment.resonance_count }} · 回声 {{ moment.echo_count }}</button>
      <button @click="chat">私下回应</button>
      <button @click="reportTarget = { type: 'moment', id: moment.id }">举报</button>
    </div>
    <section v-if="expanded" class="echo-panel">
      <p v-if="error" role="alert">{{ error }} <button @click="load">重试</button></p>
      <p v-else-if="!data">正在加载回声…</p>
      <template v-if="data">
        <div class="social-actions"><button v-for="kind in ['我也这样', '抱抱你', '我曾经也是']" :key="kind" :aria-pressed="data.my_resonance === kind" :class="{ selected: data.my_resonance === kind }" :disabled="busy" @click="resonate(kind)">{{ kind }}</button></div>
        <p v-if="!data.echoes.length">还没有公开回声，留下一句善意吧。</p>
        <div v-for="echo in data.echoes" :key="echo.id" class="echo-row"><div><small>{{ echo.author_alias }}</small><p>{{ echo.content }}</p></div><button @click="reportTarget = { type: 'echo', id: echo.id }">举报</button></div>
        <form class="echo-form" @submit.prevent="send"><input v-model="draft" aria-label="公开回声" maxlength="30" placeholder="公开回声，最多 30 字"><button :disabled="busy || !draft.trim()">发送</button></form>
      </template>
    </section>
    <ReportDialog v-if="reportTarget" :target-type="reportTarget.type" :target-id="reportTarget.id" @close="reportTarget = null" @submitted="app.notify('举报已提交，管理员会核查处理')" />
  </div>
</template>
