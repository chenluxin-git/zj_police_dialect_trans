<script setup lang="ts">
/**
 * 质检详情弹窗（民警端/管理端共用）：展示录音原文与历次质检比对流水
 * - 原文 vs 方言转译文本 vs 相似度（failed/passed），接口异常行显示 error_message
 * - props {fetchQc} 注入取数函数（民警端/管理端各传各的 API，组件零 API 耦合）
 * - 弹窗骨架照 admin/TextImportManageView：el-dialog + zp-dialog-body + zp-btn footer
 */
import { ref, watch } from "vue"
import type { QcDetail } from "@/api/recordings"
import { qcLabel, qcTagClass } from "@/constants/qc"

const props = defineProps<{
  modelValue: boolean
  recordingId: number | null
  fetchQc: (id: number) => Promise<QcDetail>
  subtitle?: string
}>()

const emit = defineEmits<{ (e: "update:modelValue", v: boolean): void }>()

const visible = ref(props.modelValue)
watch(() => props.modelValue, (v) => (visible.value = v))
watch(visible, (v) => emit("update:modelValue", v))

const loading = ref(false)
const detail = ref<QcDetail | null>(null)

watch(() => props.modelValue, async (open) => {
  if (!open || props.recordingId == null) return
  loading.value = true
  detail.value = null
  try {
    detail.value = await props.fetchQc(props.recordingId)
  } catch {
    detail.value = null // http 层已 toast，留空态即可
  } finally {
    loading.value = false
  }
})

function simLabel(v: number | null) {
  return v == null ? "—" : `${Math.round(v * 100)}%`
}

function fmtDateTime(iso: string | null) {
  if (!iso) return "—"
  const d = new Date(iso)
  const mm = String(d.getMonth() + 1).padStart(2, "0")
  const dd = String(d.getDate()).padStart(2, "0")
  const hh = String(d.getHours()).padStart(2, "0")
  const mi = String(d.getMinutes()).padStart(2, "0")
  return `${mm}-${dd} ${hh}:${mi}`
}
</script>

<template>
  <el-dialog v-model="visible" width="640px">
    <template #header>
      <h3 style="font-size: 16px; font-weight: 600">质检详情</h3>
      <p v-if="subtitle" class="zp-text-3" style="margin-top: 2px">{{ subtitle }}</p>
    </template>
    <div class="zp-dialog-body" style="padding: 0">
      <p v-if="loading" class="zp-text-3">加载中…</p>
      <template v-else-if="detail">
        <p class="zp-text-3" style="margin-bottom: 12px">
          录音原文：<span style="color: var(--ink)">{{ detail.text_content }}</span>
        </p>
        <div v-for="it in detail.items" :key="it.id" class="zp-qc-item">
          <div class="zp-flex zp-qc-head">
            <span class="zp-tag" :class="qcTagClass(it.result)">{{ qcLabel(it.result) }}</span>
            <span class="zp-text-3">相似度 {{ simLabel(it.similarity) }} · {{ fmtDateTime(it.created_at) }}</span>
          </div>
          <p v-if="it.result !== 'error'" class="zp-qc-asr">{{ it.asr_text || "（转译为空）" }}</p>
          <p v-else class="zp-qc-asr zp-qc-asr--err">{{ it.error_message || "（异常信息为空）" }}</p>
        </div>
        <p v-if="detail.items.length === 0" class="zp-text-3">暂无质检记录（待质检或质检停用时不产生流水）</p>
      </template>
      <p v-else class="zp-text-3">加载失败，请重试</p>
    </div>
    <template #footer>
      <button class="zp-btn zp-btn--primary" type="button" @click="visible = false">关闭</button>
    </template>
  </el-dialog>
</template>

<style scoped>
.zp-qc-item {
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 10px 12px;
  margin-bottom: 10px;
}
.zp-qc-head {
  margin-bottom: 8px;
}
.zp-qc-asr {
  margin: 0;
  font-size: 13px;
  line-height: 1.6;
  color: var(--ink);
}
.zp-qc-asr--err {
  color: var(--danger);
}
</style>
