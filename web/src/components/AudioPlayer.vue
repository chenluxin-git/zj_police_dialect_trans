<script setup lang="ts">
/**
 * 音频播放组件（dome/annotation.html 1:1）：72px 播放钮 + 静态波形 + 当前/总时长
 * props {src}：音频流 URL（/api/... 全路径）；内部带 token 转 Blob 后走 useAudioStore 单声道播放
 */
import { computed, onUnmounted, ref } from "vue"
import { useAudioStore } from "@/stores/audio"
import { fetchAudioBlob } from "@/api/annotations"

const props = defineProps<{ src: string }>()

const audio = useAudioStore()
const current = ref(0)
const total = ref(0)
let blobUrl = ""

const playing = computed(() => audio.playing && audio.currentUrl === blobUrl)

async function toggle() {
  if (playing.value) {
    audio.stop()
    return
  }
  const blob = await fetchAudioBlob(props.src)
  if (blobUrl) URL.revokeObjectURL(blobUrl)
  blobUrl = URL.createObjectURL(blob)
  audio.play(blobUrl)
  const el = audio.el
  if (el) {
    el.addEventListener("loadedmetadata", () => {
      total.value = el.duration || 0
    })
    el.addEventListener("timeupdate", () => {
      current.value = el.currentTime || 0
    })
    el.addEventListener("ended", () => {
      current.value = 0
    })
  }
}

function format(s: number) {
  if (!Number.isFinite(s)) return "00:00"
  const m = Math.floor(s / 60)
  const ss = Math.floor(s % 60)
  return `${String(m).padStart(2, "0")}:${String(ss).padStart(2, "0")}`
}

onUnmounted(() => {
  if (blobUrl) URL.revokeObjectURL(blobUrl)
})
</script>

<template>
  <div class="zp-center" style="padding: 24px 20px">
    <div class="zp-flex" style="justify-content: center">
      <button
        class="zp-record"
        style="width: 72px; height: 72px"
        type="button"
        :aria-label="playing ? '停止播放' : '播放'"
        @click="toggle"
      >
        <span class="core" style="width: 50px; height: 50px">
          <span style="font-size: 18px; color: var(--navy-700)">{{ playing ? "■" : "▶" }}</span>
        </span>
      </button>
    </div>
    <div class="zp-wave zp-wave--static zp-mt-16" aria-hidden="true">
      <span v-for="n in 40" :key="n"></span>
    </div>
    <p class="zp-text-3 zp-mt-8">{{ format(current) }} / {{ format(total) }}</p>
  </div>
</template>
