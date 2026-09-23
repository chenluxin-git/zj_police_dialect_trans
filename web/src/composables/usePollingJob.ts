/**
 * 后台任务轮询（P0 公用件）
 *
 * 抽掉原本散落在 4 个页面里的各自 setInterval：
 * - AudioImportView.pollTask    1200ms
 * - TextImportView.pollTask     1200ms
 * - ExportView.pollTask         1500ms
 * - UsersView.pollImport        1000ms
 *
 * 语义：调用 poll() 一次；返回 true 表示任务结束（停止轮询）。
 * poll() 抛错同样停止轮询，避免后台任务挂掉后页面无限重试。
 * 组件卸载时自动停表。
 */
import { onUnmounted, ref } from "vue"

export interface PollingJobOptions {
  /** 轮询间隔毫秒 */
  interval: number
  /** 是否立即执行一次（默认 false，首次等待一个间隔） */
  immediate?: boolean
}

export function usePollingJob(options: PollingJobOptions) {
  const running = ref(false)
  let timer: ReturnType<typeof setInterval> | null = null

  /** 停表。可重复调用。 */
  function stop() {
    if (timer !== null) {
      clearInterval(timer)
      timer = null
    }
    running.value = false
  }

  /**
   * 启动轮询。会先停掉上一轮，所以重复调用是安全的。
   * @param poll 每次轮询执行；返回 true 表示结束
   * @param onError 轮询抛错时回调（错误通常已由 http 拦截器提示）
   */
  function start(
    poll: () => Promise<boolean>,
    onError?: (e: unknown) => void,
  ) {
    stop()
    running.value = true

    const tick = async () => {
      try {
        if (await poll()) stop()
      } catch (e) {
        onError?.(e)
        stop()
      }
    }

    if (options.immediate) void tick()
    timer = setInterval(() => void tick(), options.interval)
  }

  onUnmounted(stop)

  return { running, start, stop }
}
