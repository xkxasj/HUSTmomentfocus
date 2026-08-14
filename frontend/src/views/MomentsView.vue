<script setup lang="ts">
import { useRouter } from 'vue-router'
import { api } from '../api'
import { useCampusApp } from '../composables/useCampusApp'
import type { Moment } from '../types'

const router = useRouter()
const app = useCampusApp()

const showLocation = (id: number) => {
  app.selectLocation(id)
  void router.push({ name: 'map' })
}

const replyPrivately = async (moment: Moment) => {
  if (await app.openChatFromMoment(moment)) await router.push({ name: 'chat' })
}
</script>

<template>
  <section class="page feed-page">
    <div class="hero-copy">
      <p class="eyebrow">此刻校园</p>
      <h1>先看看校园，<br><em>再决定要不要开口。</em></h1>
      <p>地图不是终点，而是一张有情绪的内容目录。你可以只浏览；当某个片段真的打动你，再留下共鸣或匿名回声。</p>
      <button class="primary-button" @click="router.push({ name: 'map' })">进入校园地图</button>
    </div>
    <div class="pulse-strip">
      <div><strong>{{ app.todayMomentCount.value }}</strong><span>今日新片段</span></div>
      <div><strong>{{ app.locations.value.filter(item => item.today_count).length }}</strong><span>正在发亮</span></div>
      <div><strong>{{ app.todayInteractionCount.value }}</strong><span>次今日互动</span></div>
    </div>
    <section v-if="app.topLocations.value.length" class="today-ranking">
      <div class="section-heading"><div><p class="eyebrow">今日互动顺序</p><h2>校园此刻，哪里最有戏</h2></div><span>按发布、共鸣与回声排序</span></div>
      <button v-for="location in app.topLocations.value" :key="location.id" @click="showLocation(location.id)">
        <b>#{{ location.today_rank }}</b><span><strong>{{ location.short_name }}</strong><small>{{ location.mood }}</small></span><em>{{ location.today_interaction_count }} 次互动</em>
      </button>
    </section>
    <section class="section-block">
      <div class="section-heading"><div><p class="eyebrow">刚刚发生</p><h2>校园里的微小片段</h2></div></div>
      <div class="moment-grid">
        <article v-for="moment in app.moments.value" :key="moment.id" class="moment-card" @click="showLocation(moment.location_id)">
          <span class="place-link">◎ {{ moment.location_name }}</span>
          <img v-if="moment.image_url" class="moment-image" :src="api.mediaUrl(moment.image_url)" alt="校园片段图片" loading="lazy">
          <p v-if="moment.content">{{ moment.content }}</p>
          <footer><span>{{ moment.author_alias }}</span><span class="moment-card-actions"><span>共鸣 {{ moment.resonance_count }}</span><button @click.stop="replyPrivately(moment)">私下回应</button></span></footer>
        </article>
      </div>
    </section>
  </section>
</template>
