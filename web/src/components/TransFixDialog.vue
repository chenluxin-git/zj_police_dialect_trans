<script setup lang="ts">
/**
 * 转译修正弹窗（工作台/历史共用）：编辑识别结果并保存
 * - 预填 displayText（人工修正优先）；「改回原文 = 撤销修正」为后端定稿语义
 * - 保存成功 emit saved(item)，调用方原位替换该行
 */
import { ref, watch } from "vue"
import { ElMessage } from "element-plus"
import type { TranscriptionItem } from "@/api/trans"
import { fixTranscription } from "@/api/trans"
import { displayText } from "@/constants/trans"

const props = defineProps<{
  modelValue: boolean
  /** 只用 id + 文件名/时长 + 原文/修正文本（displayText），结构化放宽以兼容管理端行（created_at 可空） */
  item: { id: number; file_name: string; duration: number; text_raw: string; text_fixed: string } | null
}>()

const emit = defineEmits<{
  (e: "update:modelValue", v: boolean): void
  (e: "saved", item: TranscriptionItem): void
}>()

const visible = ref(props.modelValue)
watch(() => props.modelValue, (v) => (visible.value = v))
watch(visible, (v) => emit("update:modelValue", v))

const text = ref("")
const saving = ref(false)

watch(() => props.modelValue, (open) => {
  if (open && props.item) text.value = displayText(props.item)
})

async function save() {
  if (!props.item) return
  if (!text.value.trim()) {
    ElMessage.warning("修正文本不能为空")
    return
  }
  saving.value = true
  try {
    const item = await fixTranscription(props.item.id, text.value)
    ElMessage.success(item.corrected ? "修正已保存" : "已改回原文，撤销修正")
    visible.value = false
    emit("saved", item)
  } catch {
    /* http 层已 toast */
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <el-dialog v-model="visible" width="560px">
    <template #header>
      <h3 style="font-size: 16px; font-weight: 600">修正识别结果</h3>
      <p v-if="item" class="zp-text-3" style="margin-top: 2px">
        原文件：{{ item.file_name }}（{{ Math.round(item.duration) }}s）
      </p>
    </template>
    <div class="zp-dialog-body">
      <p v-if="item" class="zp-text-3" style="margin-bottom: 8px">
        原始识别：<span style="color: var(--ink)">{{ item.text_raw || "（空）" }}</span>
      </p>
      <textarea
        v-model="text"
        class="zp-textarea"
        rows="5"
        placeholder="请输入修正后的文本"
      ></textarea>
      <p class="zp-text-3" style="margin-top: 8px">
        提示：改回与原始识别一致即视为撤销修正（去掉「已修正」标记）。
      </p>
    </div>
    <template #footer>
      <button class="zp-btn zp-btn--primary" type="button" :disabled="saving" @click="save">
        {{ saving ? "保存中…" : "保存" }}
      </button>
    </template>
  </el-dialog>
</template>
