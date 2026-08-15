<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { AttributionControl, Map as MapLibreMap, Marker } from 'maplibre-gl'
import type { StyleSpecification } from 'maplibre-gl'
import { api } from '../api'

const props = defineProps<{
  latitude: number
  longitude: number
  label: string
  updatedAt: string
}>()

const container = ref<HTMLDivElement | null>(null)
let map: MapLibreMap | null = null
let peerMarker: Marker | null = null
let ownMarker: Marker | null = null
const ownPosition = ref<{ latitude: number; longitude: number } | null>(null)
const locationHint = ref('正在定位自己…')
const CAMPUS_BOUNDS = { west: 114.392, east: 114.435, south: 30.498, north: 30.525 }

const style: StyleSpecification = {
  version: 8,
  glyphs: api.mapFontTemplate(),
  sources: {
    campus: {
      type: 'vector',
      tiles: [api.mapTileTemplate()],
      minzoom: 0,
      maxzoom: 14,
      attribution: '© OpenStreetMap contributors · OpenFreeMap',
    },
  },
  layers: [
    { id: 'background', type: 'background', paint: { 'background-color': '#e9eee5' } },
    { id: 'landcover', type: 'fill', source: 'campus', 'source-layer': 'landcover', paint: { 'fill-color': '#dce8d4', 'fill-opacity': 0.72 } },
    { id: 'water', type: 'fill', source: 'campus', 'source-layer': 'water', paint: { 'fill-color': '#a9d5dc' } },
    { id: 'buildings', type: 'fill', source: 'campus', 'source-layer': 'building', paint: { 'fill-color': '#dfc8a5', 'fill-outline-color': '#c3a37e' } },
    { id: 'roads', type: 'line', source: 'campus', 'source-layer': 'transportation', paint: { 'line-color': '#fffaf0', 'line-width': ['interpolate', ['linear'], ['zoom'], 13, 1, 18, 6] } },
  ],
}

const syncPosition = () => {
  if (!map) return
  const coordinates: [number, number] = [props.longitude, props.latitude]
  peerMarker?.setLngLat(coordinates)
  showBothPositions()
}

const showBothPositions = () => {
  if (!map) return
  const peerCoordinates: [number, number] = [props.longitude, props.latitude]
  if (!ownPosition.value) {
    map.easeTo({ center: peerCoordinates, zoom: 17, duration: 450 })
    return
  }
  const ownCoordinates: [number, number] = [ownPosition.value.longitude, ownPosition.value.latitude]
  map.fitBounds([peerCoordinates, ownCoordinates], { padding: 54, maxZoom: 17, duration: 450 })
}

const locateMe = () => {
  if (!navigator.geolocation) {
    locationHint.value = '设备不支持定位 · 红点是对方'
    return
  }
  navigator.geolocation.getCurrentPosition(position => {
    const { latitude, longitude } = position.coords
    const inCampus = longitude >= CAMPUS_BOUNDS.west && longitude <= CAMPUS_BOUNDS.east
      && latitude >= CAMPUS_BOUNDS.south && latitude <= CAMPUS_BOUNDS.north
    if (!inCampus) {
      locationHint.value = '你当前不在校园内 · 红点是对方'
      return
    }
    ownPosition.value = { latitude, longitude }
    const pin = document.createElement('span')
    pin.className = 'own-location-pin'
    pin.setAttribute('aria-label', '蓝点，你的位置')
    ownMarker?.remove()
    ownMarker = new Marker({ element: pin }).setLngLat([longitude, latitude]).addTo(map!)
    locationHint.value = '蓝点是你 · 红点是对方'
    showBothPositions()
  }, error => {
    locationHint.value = error.code === 1 ? '请允许定位 · 红点是对方' : '暂时无法定位 · 红点是对方'
  }, { enableHighAccuracy: true, timeout: 12000, maximumAge: 30000 })
}

onMounted(() => {
  if (!container.value) return
  map = new MapLibreMap({
    container: container.value,
    style,
    center: [props.longitude, props.latitude],
    zoom: 17,
    minZoom: 14,
    maxZoom: 19,
    attributionControl: false,
  })
  map.addControl(new AttributionControl({ compact: true }), 'bottom-right')
  const pin = document.createElement('span')
  pin.className = 'peer-location-pin'
  pin.setAttribute('aria-label', `红点，${props.label}，聊天对象的位置`)
  peerMarker = new Marker({ element: pin }).setLngLat([props.longitude, props.latitude]).addTo(map)
  locateMe()
})

watch(() => [props.latitude, props.longitude], syncPosition)

onBeforeUnmount(() => {
  peerMarker?.remove()
  ownMarker?.remove()
  map?.remove()
  peerMarker = null
  ownMarker = null
  map = null
})
</script>

<template>
  <section class="peer-location-card" aria-label="聊天对象共享的位置">
    <div class="peer-location-copy">
      <span>共享位置 · 30 分钟内有效</span>
      <strong>{{ label }}</strong>
      <time>{{ new Date(updatedAt).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) }} 更新</time>
    </div>
    <div class="peer-location-legend" aria-live="polite">{{ locationHint }}</div>
    <div ref="container" class="peer-location-map"></div>
  </section>
</template>
