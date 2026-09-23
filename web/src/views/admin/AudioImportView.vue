<script setup lang="ts">
/**
 * 音频导入（扫盘）（dome/admin-audio-import.html 1:1）：服务器路径 + 递归开关 + 归属区域
 * + 后台扫描任务轮询 + 4 统计格（已发现/新入库/跳过/失败）
 */
import { onUnmounted, ref } from "vue"
import { ElMessage } from "element-plus"
import RegionPicker from "@/components/RegionPicker.vue"
import { usePollingJob } from "@/composables/usePollingJob"
import {
  pollAudioScan,
  startAudioScan,
  type AudioScanPoll,
} from "@/api/admin/texts"

const serverPath = ref("")
const recursive = ref(true)

// 归属区域：区县管理员只读本辖区；市/省级管理员须选定区县（RegionPicker 内部按账号层级推导）
const regionCode = ref("")

const scanning = ref(false)
const task = ref<AudioScanPoll | null>(null)

const STATUS_TAG: Record<string, { label: string; cls: string }> = {
  pending: { label: "排队中", cls: "zp-tag--gray" },
  processing: { label: "进行中", cls: "zp-tag--warn" },
  completed: { label: "完成", cls: "zp-tag--green" },
  failed: { label: "失败", cls: "zp-tag--danger" },
}

const scanJob = usePollingJob({ interval: 1200 })

function pollTask(taskId: number) {
  scanJob.start(async () => {
    const t = await pollAudioScan(taskId)
    task.value = t
    if (t.status === "completed") {
      scanning.value = false
      ElMessage.success(`扫描完成：新入库 ${t.imported} 个文件`)
      return true
    }
    if (t.status === "failed") {
      scanning.value = false
      ElMessage.error(t.error_message || "扫描失败")
      return true
    }
    return false
  }, () => {
    scanning.value = false
    task.value = null
  })
}

async function startScan() {
  if (!serverPath.value.trim()) {
    ElMessage.warning("请输入服务器文件夹路径")
    return
  }
  if (!regionCode.value) {
    ElMessage.warning("请先选择地市并选定归属区县（市/省级归属的音频县级用户无法领取）")
    return
  }
  scanning.value = true
  task.value = null
  try {
    const data = await startAudioScan({
      server_path: serverPath.value.trim(),
      recursive: recursive.value,
      region_code: regionCode.value,
    })
    pollTask(data.task_id)
  } catch {
    scanning.value = false
  }
}

onUnmounted(() => scanJob.stop())
</script>

<template>
  <div class="zp-content" style="max-width: 880px; padding: 0">
    <div class="zp-page-head">
      <h1>音频导入（扫盘）</h1>
      <span class="sub">扫描服务器本地文件夹，批量将存量音频入库为标注素材</span>
    </div>

    <!-- 扫描设置 -->
    <div class="zp-card zp-mb-16">
      <div class="zp-card-head"><h2>扫描设置</h2></div>
      <div class="zp-card-body">
        <div class="zp-field">
          <label>服务器文件夹路径<span class="req">*</span></label>
          <input class="zp-input" v-model="serverPath" placeholder="如 /data/audio_batch_0921" />
          <p class="zp-hint zp-hint--warn">仅支持服务器本地路径（容器内路径），不支持网络位置</p>
        </div>
        <div class="zp-form-row" style="align-items: center">
          <label class="zp-flex" style="gap: 8px; font-size: 14px; flex: 1">
            <input type="checkbox" v-model="recursive" style="width: 16px; height: 16px; accent-color: var(--navy-700)" />
            包含子目录（递归扫描）
          </label>
          <div style="flex: 1">
            <label style="display: block; font-size: 13px; color: var(--ink-2); margin-bottom: 6px">归属区域<span class="req">*</span></label>
            <RegionPicker v-model:value="regionCode" mode="required-district" />
          </div>
        </div>
        <button class="zp-btn zp-btn--primary zp-btn--lg zp-mt-16" style="width: 100%" type="button"
          :disabled="scanning" @click="startScan">
          {{ scanning ? "扫描中…" : "开始扫描导入" }}
        </button>
      </div>
    </div>

    <!-- 扫描进度 -->
    <div class="zp-card zp-mb-16" v-if="task || scanning">
      <div class="zp-card-head">
        <h2>扫描进度</h2>
        <span v-if="task" class="zp-tag" :class="STATUS_TAG[task.status]?.cls || 'zp-tag--gray'">
          {{ STATUS_TAG[task.status]?.label || task.status }}
        </span>
        <span v-else class="zp-tag zp-tag--warn">进行中</span>
        <span v-if="task" class="zp-card-sub" style="margin-left: auto">任务 #{{ task.task_id }}</span>
      </div>
      <div class="zp-card-body">
        <div class="zp-grid-4">
          <div class="zp-stat"><div class="label">已发现</div><div class="value" style="font-size: 24px">{{ task?.found || 0 }}</div></div>
          <div class="zp-stat zp-stat--ok"><div class="label">新入库</div><div class="value" style="font-size: 24px">{{ task?.imported || 0 }}</div></div>
          <div class="zp-stat"><div class="label">跳过（路径重复）</div><div class="value" style="font-size: 24px">{{ task?.skipped || 0 }}</div></div>
          <div class="zp-stat zp-stat--gold"><div class="label">失败</div><div class="value" style="font-size: 24px">{{ task?.failed?.length || 0 }}</div></div>
        </div>
        <div v-if="task?.failed?.length" class="zp-alert zp-alert--warn zp-mt-16">
          <span>部分文件读取失败：{{ task.failed.slice(0, 5).map((f) => f.path).join("、") }}{{ task.failed.length > 5 ? "…" : "" }}</span>
        </div>
      </div>
    </div>

    <div class="zp-alert zp-alert--info">
      <span>说明：同一文件路径只入库一次（重复扫描自动跳过）；每 100 条自动提交一次，中断后可重新扫描续入；导入完成后音频立即进入本区域标注队列。</span>
    </div>
  </div>
</template>
