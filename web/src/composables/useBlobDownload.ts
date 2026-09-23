/**
 * Blob 下载 / 播放（P0 公用件）
 *
 * 抽掉原本散落在 5 个页面里的 `URL.createObjectURL` + 合成 <a> 标签：
 * - ExportView.doDownload        导出 ZIP
 * - RecordingsView.download      录音下载
 * - TextImportView.downloadTemplate  模板下载
 * - UsersView.saveBlob           用户 Excel 导出
 * - (AnnotationsView/RecordingsView 试听走 playBlob)
 *
 * 统一在这里 revokeObjectURL，避免各自漏回收。
 */
import { onUnmounted } from "vue"
import { useAudioStore } from "@/stores/audio"

/** 触发浏览器下载，用完即回收 objectURL */
export function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement("a")
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

/**
 * 全站单声道播放一个 Blob：新播放自动停上一个，并回收上一次的 objectURL。
 * 组件卸载时自动停播并回收，避免音频在页面切走后继续响。
 */
export function useBlobPlayer() {
  const audio = useAudioStore()
  let lastUrl = ""

  function play(blob: Blob) {
    const url = URL.createObjectURL(blob)
    audio.play(url)
    if (lastUrl) URL.revokeObjectURL(lastUrl)
    lastUrl = url
  }

  function stop() {
    audio.stop()
    if (lastUrl) {
      URL.revokeObjectURL(lastUrl)
      lastUrl = ""
    }
  }

  onUnmounted(stop)

  return { play, stop }
}
