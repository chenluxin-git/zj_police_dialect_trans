/**
 * 全站单声道播放 store（audioManager）：新播放自动停上一个，play(url) 统一入口
 * Spec §9「全站单声道播放（audioManager，新播放自动停上一个）」
 */
import { defineStore } from "pinia"

export const useAudioStore = defineStore("audio", {
  state: () => ({
    currentUrl: "",
    playing: false,
    el: null as HTMLAudioElement | null,
  }),
  actions: {
    /** 播放指定 URL（先停掉正在播的） */
    play(url: string) {
      this.stop()
      const el = new Audio(url)
      el.onended = () => this.stop()
      el.onerror = () => this.stop()
      this.el = el
      this.currentUrl = url
      this.playing = true
      void el.play().catch(() => this.stop()) // 自动播放受限等异常静默回收
    },
    /** 停止当前播放 */
    stop() {
      if (this.el) {
        this.el.pause()
        this.el.src = ""
        this.el.onended = null
        this.el.onerror = null
      }
      this.el = null
      this.currentUrl = ""
      this.playing = false
    },
    /** 同一 URL 再点 = 停止，否则播放（AudioPlayer 切换钮用） */
    toggle(url: string) {
      if (this.currentUrl === url && this.playing) {
        this.stop()
      } else {
        this.play(url)
      }
    },
  },
})
