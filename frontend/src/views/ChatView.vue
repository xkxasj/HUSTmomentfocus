<script setup lang="ts">
import { onBeforeUnmount, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import PeerLocationMap from '../components/PeerLocationMap.vue'
import { useCampusApp } from '../composables/useCampusApp'

const router = useRouter()
const app = useCampusApp()
let presenceTimer: number | undefined

onMounted(async () => {
  if (!app.conversations.value.length) await app.refreshConversations()
  if (!app.activeConversation.value && app.conversations.value[0]) await app.openConversation(app.conversations.value[0])
  presenceTimer = window.setInterval(app.refreshConversations, 30000)
})
onBeforeUnmount(() => window.clearInterval(presenceTimer))
</script>

<template>
  <section class="chat-page">
    <header class="chat-hero">
      <div><p class="eyebrow">匿名回声</p><h1>从一句真话，<br><em>开始一段对话。</em></h1><p>只能从公开片段发起。没有搜索陌生人，也不显示真实身份。</p></div>
      <div class="chat-safety"><span>私密</span><strong>你可以随时结束、屏蔽或举报会话</strong></div>
    </header>
    <div class="chat-layout">
      <aside class="conversation-list">
        <div class="conversation-heading"><strong>回声盒</strong><span>{{ app.conversations.value.length }} 段对话</span></div>
        <button v-for="conversation in app.conversations.value" :key="conversation.id" :class="{ active: app.activeConversationId.value === conversation.id }" @click="app.openConversation(conversation)">
          <span class="chat-avatar">{{ conversation.peer_alias.slice(-1) }}</span>
          <span class="conversation-copy"><strong>{{ conversation.peer_alias }}</strong><small>{{ conversation.peer_presence?.label || `来自 ${conversation.location_name}` }}</small><span>{{ conversation.last_message }}</span></span>
          <i v-if="conversation.unread_count">{{ conversation.unread_count }}</i>
        </button>
      </aside>
      <section v-if="app.activeConversation.value" class="message-panel">
        <header class="message-head">
          <span class="chat-avatar large">{{ app.activeConversation.value.peer_alias.slice(-1) }}</span>
          <div><strong>{{ app.activeConversation.value.peer_alias }}</strong><small>因 {{ app.activeConversation.value.location_name }} 的一个片段相遇</small><span v-if="app.activeConversation.value.peer_presence" class="peer-presence">◎ {{ app.activeConversation.value.peer_presence.label }} · 已允许分享</span></div>
          <button aria-label="会话设置">•••</button>
        </header>
        <div class="conversation-context">
          <blockquote class="origin-card"><span>对话起点 · {{ app.activeConversation.value.location_name }}</span><p>{{ app.activeConversation.value.origin_excerpt }}</p></blockquote>
          <PeerLocationMap
            v-if="app.activeConversation.value.peer_presence"
            :latitude="app.activeConversation.value.peer_presence.latitude"
            :longitude="app.activeConversation.value.peer_presence.longitude"
            :label="app.activeConversation.value.peer_presence.label"
            :updated-at="app.activeConversation.value.peer_presence.updated_at"
          />
        </div>
        <div class="message-stream">
          <div v-for="message in app.chatMessages.value" :key="message.id" class="message-bubble" :class="message.sender">
            <p>{{ message.content }}</p><time>{{ new Date(message.created_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) }}</time>
          </div>
        </div>
        <button v-if="!app.replyComposerExpanded.value" class="reply-composer-collapsed" @click="app.expandReplyComposer">
          <span>回应这一刻……</span><i>AI 可帮你想，也可以自己写</i>
        </button>
        <section v-else class="reply-assistant">
          <header><div><strong>猜你会这样回</strong><small>点一下填入，可修改后发送</small></div><button :disabled="app.replySuggestionsLoading.value" @click="app.loadReplySuggestions(true)">换一组</button></header>
          <template v-if="app.replySuggestionsLoading.value && !app.replySuggestions.value.length">
            <div v-for="index in 3" :key="index" class="reply-option loading-option"><span></span></div>
          </template>
          <button
            v-for="(suggestion, index) in app.replySuggestions.value"
            :key="`${suggestion.intent}-${suggestion.text}`"
            class="reply-option"
            :class="{ selected: app.selectedReplyIndex.value === index }"
            @click="app.selectReplySuggestion(index)"
          >
            <span>{{ suggestion.label }}</span><p>{{ suggestion.text }}</p><i>↗</i>
          </button>
          <form class="reply-option own-reply" @submit.prevent="app.sendChatMessage">
            <span>自己说</span>
            <textarea v-model="app.messageDraft.value" maxlength="500" rows="1" autofocus placeholder="写下你真正想说的……"></textarea>
            <button class="send-button" :disabled="!app.messageDraft.value.trim()">发送</button>
          </form>
          <p class="reply-ai-note">AI 只提供草稿，不会替你自动发送。</p>
        </section>
      </section>
      <section v-else class="no-conversation"><strong>还没有匿名回声</strong><p>从一条真正打动你的校园片段开始。</p><button class="primary-button" @click="router.push({ name: 'moments' })">去看看此刻</button></section>
    </div>
  </section>
</template>
