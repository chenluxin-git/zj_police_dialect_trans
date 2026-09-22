<script setup lang="ts">
/**
 * 标注管理（dome/admin-annotations.html 1:1）：译文关键词筛选 + 表格
 * + 播放（/api/audio/files/{id}/file）+ 删除（音频回待标注队列）（已取消是否方言判定）
 */
import { onMounted, onUnmounted, ref } from "vue"
import { ElMessage, ElMessageBox } from "element-plus"
import { useAudioStore } from "@/stores/audio"
import {
  deleteAnnotation,
  fetchAudioBlob,
  listAdminAnnotations,
  type AdminAnnotation,
} from "@/api/admin/export"

const audio = useAudioStore()
const items = ref<AdminAnnotation[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const keyword = ref("")
const loading = ref(false)

let listenUrl = ""

function fmtDateTime(iso: string | null) {
  if (!iso) return "—"
  const d = new Date(iso)
  const p = (n: number) => String(n).padStart(2, "0")
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

async function load() {
  loading.value = true
  try {
    const data = await listAdminAnnotations({
      q: keyword.value || undefined,
      page: page.value,
      page_size: pageSize,
    })
    items.value = data.items
    total.value = data.total
  } finally {
    loading.value = false
  }
}

function search() {
  page.value = 1
  void load()
}
function reset() {
  keyword.value = ""
  page.value = 1
  void load()
}

async function listen(row: AdminAnnotation) {
  const blob = await fetchAudioBlob(`/api/audio/files/${row.file_id}/file`)
  const url = URL.createObjectURL(blob)
  audio.play(url)
  if (listenUrl) URL.revokeObjectURL(listenUrl)
  listenUrl = url
}

async function remove(row: AdminAnnotation) {
  await ElMessageBox.confirm(
    `确定删除这条标注吗？删除后标注人任务进度相应扣减，该音频重新进入待标注队列。\n${row.translation || row.file_name}`,
    "删除标注",
    { confirmButtonText: "确认删除", cancelButtonText: "取消", type: "warning" },
  )
  await deleteAnnotation(row.id)
  ElMessage.success("已删除，音频已回到待标注队列")
  void load()
}

onMounted(() => void load())
onUnmounted(() => {
  if (listenUrl) URL.revokeObjectURL(listenUrl)
})
</script>

<template>
  <div class="zp-content" style="padding: 0">
    <div class="zp-page-head">
      <h1>标注管理</h1>
      <span class="sub">辖区全部标注记录 · 删除后该音频重新进入待标注队列</span>
    </div>

    <!-- 筛选栏 -->
    <div class="zp-filter">
      <input class="zp-input" v-model="keyword" placeholder="普通话翻译关键词" aria-label="普通话翻译关键词" @keyup.enter="search" />
      <button class="zp-btn zp-btn--primary" type="button" @click="search">查询</button>
      <button class="zp-btn zp-btn--ghost" type="button" @click="reset">重置</button>
    </div>

    <!-- 列表 -->
    <div class="zp-card">
      <div class="zp-table-wrap">
        <table class="zp-table">
          <thead>
            <tr>
              <th>标注人</th>
              <th>音频文件</th>
              <th style="width: 44%">普通话翻译</th>
              <th>标注时间</th>
              <th class="zp-text-right">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in items" :key="row.id">
              <td><b>{{ row.annotator_name }}</b></td>
              <td class="num">{{ row.file_name }}</td>
              <td>
                <span v-if="row.translation">{{ row.translation }}</span>
                <span v-else class="zp-text-3">—</span>
              </td>
              <td class="num">{{ fmtDateTime(row.created_at) }}</td>
              <td class="zp-text-right">
                <button class="zp-btn zp-btn--text" type="button" @click="listen(row)">播放</button>
                <button class="zp-btn zp-btn--text is-danger" type="button" @click="remove(row)">删除</button>
              </td>
            </tr>
            <tr v-if="!loading && items.length === 0">
              <td colspan="5" style="color: var(--ink-3); padding: 32px; text-align: center">暂无标注记录</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div style="padding: 14px 20px; display: flex; justify-content: space-between; align-items: center">
        <span class="total" style="font-size: 13px; color: var(--ink-2)">
          共 {{ total }} 条
        </span>
        <el-pagination
          background
          layout="prev, pager, next"
          :total="total"
          :page-size="pageSize"
          :current-page="page"
          @current-change="(p: number) => { page = p; load() }"
        />
      </div>
    </div>
  </div>
</template>
