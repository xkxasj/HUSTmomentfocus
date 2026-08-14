<script setup lang="ts">
import RealCampusMap from '../components/RealCampusMap.vue'
import { api } from '../api'
import { useCampusApp } from '../composables/useCampusApp'

const app = useCampusApp()
</script>

<template>
  <section class="map-page">
    <div class="map-toolbar">
      <div><p class="eyebrow">华中科技大学 · 主校区</p><h1>一张会呼吸的校园地图</h1><p>道路和地标按现实关系绘制，动态圆点代表正在发生的内容。</p></div>
      <div class="map-key"><span><i class="live-dot"></i>内容热点</span><span><i class="place-dot"></i>校园地标</span><span><i class="food-dot"></i>食堂</span></div>
    </div>

    <RealCampusMap :locations="app.locations.value" :selected-id="app.selected.value?.id" @select="app.selectLocation($event.id)" @position="app.handlePosition" />

    <aside v-if="app.selected.value" class="place-sheet">
      <div class="place-title"><span class="place-swatch" :style="{ background: app.selected.value.accent }"></span><div><p class="eyebrow">{{ app.selected.value.mood }} · 今天 {{ app.selected.value.today_count }} 条</p><h2>{{ app.selected.value.name }}</h2><p>{{ app.selected.value.description }}</p></div></div>
      <button class="primary-button" @click="app.composeOpen.value = true">＋ 留下某刻</button>
      <div v-if="app.placeMoments.value.length" class="place-moments">
        <article v-for="moment in app.placeMoments.value" :key="moment.id"><img v-if="moment.image_url" class="place-moment-image" :src="api.mediaUrl(moment.image_url)" alt="校园片段图片" loading="lazy"><p v-if="moment.content">{{ moment.content }}</p><span>{{ moment.author_alias }} · 共鸣 {{ moment.resonance_count }}</span></article>
      </div>
      <div v-else class="quiet-place"><strong>这里暂时很安静</strong><span>{{ app.selected.value.prompt }}</span></div>
    </aside>
  </section>
</template>
