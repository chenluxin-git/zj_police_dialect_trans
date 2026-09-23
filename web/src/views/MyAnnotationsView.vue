<script setup lang="ts">
/**
 * 我的标注（dome/my-annotations.html 1:1）：表格 + 文件名筛选（后端无筛选参数，前端过滤）
 * + 修改 dialog（AudioPlayer 重听 + 回填）+ 删除确认（提示进度扣减）（已取消是否方言判定）
 */
import { computed, onMounted, onUnmounted, ref } from "vue"
import { ElMessage, ElMessageBox } from "element-plus"
import { useAudioStore } from "@/stores/audio"
import {
  audioFileUrl,
  deleteAnnotation,
  myAnnotations,
  updateAnnotation,
  type AnnotationItem,
} from "@/api/annotations"
import AudioPlayer from "@/components/AudioPlayer.vue"

const audio = useAudioStore()
const all = ref<AnnotationItem[]>([])
const keyword = ref("")
const page = ref(1)
const pageSize = 20

const editVisible = ref(false)
const editItem = ref<AnnotationItem | null>(null)
const editTranslation = ref("")

const filtered = computed(() =>
  all.value.filter((a) => {
    if (keyword.value && !a.file_name.includes(keyword.value.trim())) return false
    return true
  }),
)
const total = computed(() => filtered.value.length)
const pageItems = computed(() =>
  filtered.value.slice((page.value - 1) * pageSize, page.value * pageSize),
)

function fmtDateTime(iso: string) {
  const d = new Date(iso)
  const mm = String(d.getMonth() + 1).padStart(2, "0")
  const dd = String(d.getDate()).padStart(2, "0")
  const hh = String(d.getHours()).padStart(2, "0")
  const mi = String(d.getMinutes()).padStart(2, "0")
  return `${mm}-${dd} ${hh}:${mi}`
}

async function loadAll() {
  const data = await myAnnotations({ page: 1, page_size: 10000 })
  all.value = data.items
}

function search() {
  page.value = 1
}
function reset() {
  keyword.value = ""
  page.value = 1
}
function onPageChange(p: number) {
  page.value = p
}

function openEdit(row: AnnotationItem) {
  editItem.value = row
  editTranslation.value = row.translation
  editVisible.value = true
}
function closeEdit() {
  audio.stop()
  editVisible.value = false
  editItem.value = null
}
async function saveEdit() {
  if (!editItem.value) return
  if (!editTranslation.value.trim()) {
    ElMessage.warning("请填写普通话翻译")
    return
  }
  await updateAnnotation(editItem.value.id, {
    file_id: editItem.value.file_id,
    translation: editTranslation.value.trim(),
  })
  ElMessage.success("标注已更新")
  closeEdit()
  await loadAll()
}

async function remove(row: AnnotationItem) {
  await ElMessageBox.confirm(
    "确定删除这条标注吗？删除后任务进度将相应扣减，且该音频将重新进入待标注队列。",
    "删除标注",
    { confirmButtonText: "确认删除", cancelButtonText: "取消", type: "warning" },
  )
  await deleteAnnotation(row.id)
  ElMessage.success("已删除")
  await loadAll()
}

onMounted(() => void loadAll())
onUnmounted(() => audio.stop())
</script>

<template>
  <div class="zp-page-head">
    <h1>历史标注</h1>
    <span class="sub">共 {{ all.length }} 条</span>
    <div class="zp-head-actions">
      <router-link class="zp-btn zp-btn--ghost" to="/annotation/work">← 返回开始标注</router-link>
    </div>
  </div>

  <!-- 筛选栏 -->
  <div class="zp-filter">
    <input
      class="zp-input"
      v-model="keyword"
      placeholder="搜索音频文件名"
      aria-label="搜索音频文件名"
      @keyup.enter="search"
    />
    <button class="zp-btn zp-btn--primary" type="button" @click="search">查询</button>
    <button class="zp-btn zp-btn--ghost" type="button" @click="reset">重置</button>
  </div>

  <!-- 列表 -->
  <div class="zp-card">
    <div class="zp-table-wrap">
      <table class="zp-table">
        <thead>
          <tr>
            <th>音频文件</th>
            <th style="width: 46%">普通话翻译</th>
            <th>标注时间</th>
            <th class="zp-text-right">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in pageItems" :key="row.id">
            <td class="num">{{ row.file_name }}</td>
            <td>{{ row.translation }}</td>
            <td class="num">{{ fmtDateTime(row.created_at) }}</td>
            <td class="zp-text-right">
              <button class="zp-btn zp-btn--text" type="button" @click="openEdit(row)">修改</button>
              <button class="zp-btn zp-btn--text is-danger" type="button" @click="remove(row)">删除</button>
            </td>
          </tr>
          <tr v-if="pageItems.length === 0">
            <td colspan="4" class="zp-center" style="color: var(--ink-3); padding: 32px">暂无标注记录</td>
          </tr>
        </tbody>
      </table>
    </div>
    <div style="padding: 14px 20px; display: flex; justify-content: flex-end">
      <el-pagination
        background
        layout="total, prev, pager, next"
        :total="total"
        :page-size="pageSize"
        :current-page="page"
        @current-change="onPageChange"
      />
    </div>
  </div>

  <!-- 修改标注 -->
  <div v-if="editVisible" class="zp-dialog-mask is-open">
    <div class="zp-dialog" role="dialog" aria-label="修改标注" style="max-width: 560px">
      <div class="zp-dialog-head">
        <h3>修改标注</h3>
        <button class="zp-x" type="button" aria-label="关闭" @click="closeEdit">×</button>
      </div>
      <div class="zp-dialog-body">
        <AudioPlayer v-if="editItem" :src="audioFileUrl(editItem.file_id)" />
        <div class="zp-field">
          <label>普通话翻译<span class="req">*</span></label>
          <textarea v-model="editTranslation" class="zp-textarea" placeholder="请输入这段音频对应的普通话意思"></textarea>
        </div>
      </div>
      <div class="zp-dialog-foot">
        <button class="zp-btn zp-btn--ghost" type="button" @click="closeEdit">取消</button>
        <button class="zp-btn zp-btn--primary" type="button" @click="saveEdit">保存修改</button>
      </div>
    </div>
  </div>
</template>
