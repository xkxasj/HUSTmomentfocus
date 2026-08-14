<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { ComponentPublicInstance } from 'vue'
import { AttributionControl, Map as MapLibreMap, Marker, NavigationControl } from 'maplibre-gl'
import type { StyleSpecification } from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { api } from '../api'
import type { Location } from '../types'

const props = defineProps<{ locations: Location[]; selectedId?: number }>()
const emit = defineEmits<{
  select: [location: Location]
  position: [position: { latitude: number; longitude: number; inCampus: boolean }]
}>()

const CAMPUS_CENTER: [number, number] = [114.4162, 30.5134]
const CAMPUS_BOUNDS = { west: 114.392, east: 114.435, south: 30.498, north: 30.525 }
const markerById = new Map<number, Marker>()
let mapContainer: HTMLDivElement | null = null
let map: MapLibreMap | null = null
let userMarker: Marker | null = null
let mapErrorShown = false
const locating = ref(false)
const locationMessage = ref('')
const mapMode = ref('真实地图正在加载')
const diningShortNames = new Set(['韵苑', '百景园', '百惠园', '西一', '西二', '西园', '集贤楼', '喻园', '集锦园', '东一', '东三', '东四', '学一', '学二', '东教工', '东园', '东篱', '百盛园'])
const isDiningLocation = (location: Location) => location.category === 'dining' || diningShortNames.has(location.short_name)

const baseStyle: StyleSpecification = {
  version: 8,
  glyphs: api.mapFontTemplate(),
  sources: {},
  layers: [{ id: 'canvas', type: 'background', paint: { 'background-color': '#edf1e8' } }],
}

const addRealMapLayers = () => {
  if (!map || map.getSource('openmaptiles')) return
  map.addSource('openmaptiles', {
    type: 'vector',
    tiles: [api.mapTileTemplate()],
    minzoom: 0,
    maxzoom: 14,
    attribution: '© OpenStreetMap contributors · OpenFreeMap',
  })
  map.addLayer({ id: 'landcover', type: 'fill', source: 'openmaptiles', 'source-layer': 'landcover', paint: { 'fill-color': ['match', ['get', 'class'], 'wood', '#c8ddbd', 'grass', '#d9e7c7', '#e7eadf'], 'fill-opacity': 0.72 } })
  map.addLayer({ id: 'landuse', type: 'fill', source: 'openmaptiles', 'source-layer': 'landuse', paint: { 'fill-color': ['match', ['get', 'class'], 'park', '#cce3c3', 'school', '#eee4c9', 'hospital', '#f1d8d2', '#e6e6d8'], 'fill-opacity': 0.62 } })
  map.addLayer({ id: 'park', type: 'fill', source: 'openmaptiles', 'source-layer': 'park', paint: { 'fill-color': '#c6dfbb', 'fill-opacity': 0.72 } })
  map.addLayer({ id: 'water', type: 'fill', source: 'openmaptiles', 'source-layer': 'water', paint: { 'fill-color': '#9fd3df', 'fill-opacity': 0.88 } })
  map.addLayer({ id: 'buildings', type: 'fill', source: 'openmaptiles', 'source-layer': 'building', minzoom: 13, paint: { 'fill-color': '#e2c69e', 'fill-outline-color': '#b98d67', 'fill-opacity': 0.88 } })
  map.addLayer({ id: 'roads-casing', type: 'line', source: 'openmaptiles', 'source-layer': 'transportation', minzoom: 12, paint: { 'line-color': '#b8aa91', 'line-width': ['interpolate', ['linear'], ['zoom'], 12, 1.2, 18, 8] } })
  map.addLayer({ id: 'roads', type: 'line', source: 'openmaptiles', 'source-layer': 'transportation', minzoom: 12, paint: { 'line-color': '#fffaf0', 'line-width': ['interpolate', ['linear'], ['zoom'], 12, 0.7, 18, 5.5] } })
  map.addLayer({
    id: 'road-labels', type: 'symbol', source: 'openmaptiles', 'source-layer': 'transportation_name', minzoom: 13,
    layout: {
      'symbol-placement': 'line',
      'text-field': ['coalesce', ['get', 'name:zh-Hans'], ['get', 'name:zh'], ['get', 'name']],
      'text-font': ['Noto Sans Regular'],
      'text-size': ['interpolate', ['linear'], ['zoom'], 13, 9, 18, 13],
      'text-letter-spacing': 0.04,
    },
    paint: { 'text-color': '#59655f', 'text-halo-color': 'rgba(249,248,240,.95)', 'text-halo-width': 1.5 },
  })
  map.addLayer({
    id: 'campus-poi-labels', type: 'symbol', source: 'openmaptiles', 'source-layer': 'poi', minzoom: 14,
    filter: ['has', 'name'],
    layout: {
      'text-field': ['coalesce', ['get', 'name:zh-Hans'], ['get', 'name:zh'], ['get', 'name']],
      'text-font': ['Noto Sans Regular'],
      'text-size': ['interpolate', ['linear'], ['zoom'], 14, 9, 18, 12],
      'text-offset': [0, 0.7],
      'text-anchor': 'top',
      'text-max-width': 8,
    },
    paint: { 'text-color': '#40584e', 'text-halo-color': 'rgba(249,248,240,.96)', 'text-halo-width': 1.5 },
  })
}

const locateMe = () => {
  if (!navigator.geolocation || locating.value) {
    if (!navigator.geolocation) locationMessage.value = '当前设备不支持定位'
    return
  }
  locating.value = true
  locationMessage.value = ''
  navigator.geolocation.getCurrentPosition(
    position => {
      locating.value = false
      const { latitude, longitude } = position.coords
      const inCampus = longitude >= CAMPUS_BOUNDS.west && longitude <= CAMPUS_BOUNDS.east
        && latitude >= CAMPUS_BOUNDS.south && latitude <= CAMPUS_BOUNDS.north
      emit('position', { latitude, longitude, inCampus })
      if (!inCampus) {
        locationMessage.value = '你暂时不在主校区，地图继续留在校园范围内'
        window.setTimeout(() => (locationMessage.value = ''), 4200)
        return
      }
      if (!map) return
      const element = document.createElement('span')
      element.className = 'campus-user-dot'
      userMarker?.remove()
      userMarker = new Marker({ element }).setLngLat([longitude, latitude]).addTo(map)
      map.flyTo({ center: [longitude, latitude], zoom: 17.2, essential: true })
      locationMessage.value = '已在校园地图上找到你'
      window.setTimeout(() => (locationMessage.value = ''), 2600)
    },
    error => {
      locating.value = false
      locationMessage.value = error.code === 1 ? '请在手机设置中允许定位权限' : '暂时没找到你，请稍后再试'
    },
    { enableHighAccuracy: true, timeout: 12000, maximumAge: 30000 },
  )
}

const createMarkerElement = (location: Location) => {
  const button = document.createElement('button')
  button.type = 'button'
  button.className = 'geo-marker'
  const dining = isDiningLocation(location)
  button.classList.add(dining ? 'dining-marker' : 'landmark-marker')
  button.style.setProperty('--accent', location.accent)
  button.setAttribute('aria-label', `${location.name}，今天 ${location.today_count} 条`)
  const count = document.createElement('span')
  count.textContent = dining ? '饭' : String(location.today_count)
  const label = document.createElement('strong')
  label.textContent = location.short_name
  button.append(count, label)
  button.addEventListener('click', event => {
    event.stopPropagation()
    emit('select', location)
  })
  return button
}

const syncMarkers = () => {
  if (!map) return
  markerById.forEach(marker => marker.remove())
  markerById.clear()
  props.locations.forEach(location => {
    if (!Number.isFinite(location.longitude) || !Number.isFinite(location.latitude)) return
    const element = createMarkerElement(location)
    element.classList.toggle('active', props.selectedId === location.id)
    markerById.set(location.id, new Marker({ element, anchor: 'bottom' })
      .setLngLat([location.longitude, location.latitude]).addTo(map!))
  })
}

const fitCampusLocations = () => {
  if (!map) return
  const points = props.locations.filter(location => Number.isFinite(location.longitude) && Number.isFinite(location.latitude))
  if (points.length < 2) return
  const longitudes = points.map(location => location.longitude)
  const latitudes = points.map(location => location.latitude)
  map.fitBounds(
    [[Math.min(...longitudes), Math.min(...latitudes)], [Math.max(...longitudes), Math.max(...latitudes)]],
    { padding: window.innerWidth <= 800 ? { top: 52, right: 52, bottom: 125, left: 52 } : { top: 70, right: 88, bottom: 110, left: 88 }, maxZoom: 15.8, duration: 0 },
  )
}

const syncSelectedMarker = (selectedId?: number) => {
  markerById.forEach((marker, id) => marker.getElement().classList.toggle('active', id === selectedId))
}

const syncZoomDetails = () => {
  if (!map || !mapContainer) return
  mapContainer.closest('.real-map-shell')?.classList.toggle('show-dining-labels', map.getZoom() >= 14.25)
}

const setMapContainer = (element: Element | ComponentPublicInstance | null) => {
  mapContainer = element instanceof HTMLDivElement ? element : null
}

onMounted(() => {
  if (!mapContainer) return
  try {
    map = new MapLibreMap({
      container: mapContainer,
      center: CAMPUS_CENTER,
      zoom: 15.7,
      minZoom: 13,
      maxZoom: 19,
      maxBounds: [[114.382, 30.488], [114.447, 30.537]],
      attributionControl: false,
      style: baseStyle,
      fadeDuration: 0,
      renderWorldCopies: false,
      refreshExpiredTiles: false,
      maxTileCacheSize: 42,
    })
  } catch (cause) {
    mapMode.value = '当前设备无法启动地图'
    locationMessage.value = cause instanceof Error ? cause.message : '地图初始化失败，请重新打开此页'
    return
  }
  map.addControl(new NavigationControl({ showCompass: true }), 'top-right')
  map.addControl(new AttributionControl({ compact: true }), 'bottom-right')
  map.on('load', () => {
    map?.resize()
    addRealMapLayers()
    syncMarkers()
    window.requestAnimationFrame(fitCampusLocations)
    map?.once('idle', fitCampusLocations)
    syncZoomDetails()
  })
  map.on('zoom', syncZoomDetails)
  map.on('sourcedata', event => {
    if (event.sourceId === 'openmaptiles' && event.isSourceLoaded) mapMode.value = '真实道路 · 建筑 · 水域'
  })
  map.on('error', event => {
    if (mapErrorShown) return
    mapErrorShown = true
    mapMode.value = '真实地图连接异常'
    locationMessage.value = event.error?.message
      ? `地图错误：${event.error.message}`
      : '请确认手机能访问当前电脑后端，再点开地图重试'
  })
})

watch(() => props.locations, () => {
  syncMarkers()
  fitCampusLocations()
}, { deep: true })
watch(() => props.selectedId, syncSelectedMarker)

onBeforeUnmount(() => {
  markerById.clear()
  userMarker?.remove()
  userMarker = null
  map?.remove()
  map = null
})
</script>

<template>
  <div class="real-map-shell">
    <div :ref="setMapContainer" class="real-map" role="application" aria-label="华中科技大学真实地图"></div>
    <div class="map-status"><strong>{{ mapMode }}</strong><span>MapLibre · WGS-84</span></div>
    <button class="campus-locate" :class="{ locating }" type="button" @click="locateMe">
      <span>●</span>{{ locating ? '定位中' : '找我' }}
    </button>
    <div v-if="locationMessage" class="campus-location-message">{{ locationMessage }}</div>
  </div>
</template>
