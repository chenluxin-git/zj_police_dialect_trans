<script setup lang="ts">
/**
 * 音频上传（dome/admin-audio-upload.html 1:1）：归属区域（super_admin 可指定）
 * + 多文件 dropzone + 状态表（等待中/已入库/失败）。后端单请求逐个转存（UUID 重命名 + ffprobe 时长），
 * 响应回 each 文件 file_name + id/error，据此回填状态。
 */
import { ref } from "vue"
import { ElMessage } from "element-plus"
import type { UploadFile } from "element-plus"
import RegionPicker from "@/components/RegionPicker.vue"
import { uploadAudio } from "@/api/admin/texts"

interface UploadRow {
  uid: number
  raw: File
  name: string
  size: number
  status: "pending" | "done" | "error"
  error?: string
}

const rows = ref<UploadRow[]>([])
const uploading = ref(false)
// 归属区域：区县管理员只读本辖区；市/省级管理员须选定区县（RegionPicker 内部按账号层级推导）
const regionCode = ref("")
let uid = 0

function fmtSize(n: number) {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${Math.round(n / 1024)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

function onFileChange(uploadFile: UploadFile) {
  const raw = uploadFile.raw
  if (!raw) return
  rows.value.push({ uid: uid++, raw, name: raw.name, size: raw.size, status: "pending" })
}

async function startUpload() {
  if (!rows.value.length) {
    ElMessage.warning("请先选择音频文件")
    return
  }
  if (!regionCode.value) {
    ElMessage.warning("请先选择地市并选定归属区县（市/省级归属的音频县级用户无法领取）")
    return
  }
  const form = new FormData()
  rows.value.forEach((r) => form.append("files", r.raw, r.name))
  form.append("region_code", regionCode.value)

  uploading.value = true
  rows.value.forEach((r) => (r.status = "pending"))
  try {
    const data = await uploadAudio(form)
    const map = new Map<string, { id?: number; error?: string }>()
    data.results.forEach((r) => map.set(r.file_name, r))
    rows.value.forEach((r) => {
      const res = map.get(r.name)
      if (res && res.id != null) {
        r.status = "done"
      } else {
        r.status = "error"
        r.error = res?.error || "未返回结果"
      }
    })
    ElMessage.success(`成功入库 ${data.imported} 个文件`)
  } catch {
    rows.value.forEach((r) => {
      if (r.status === "pending") r.status = "error"
    })
  } finally {
    uploading.value = false
  }
}
</script>

<template>
  <div class="zp-content" style="max-width: 880px; padding: 0">
    <div class="zp-page-head">
      <h1>音频上传</h1>
      <span class="sub">上传存量音频作为标注素材，逐个转存入库并自动读取时长</span>
    </div>

    <!-- 上传设置 -->
    <div class="zp-card zp-mb-16">
      <div class="zp-card-head"><h2>上传设置</h2></div>
      <div class="zp-card-body">
        <div class="zp-field" style="margin-bottom: 0">
          <label>归属区域<span class="req">*</span></label>
          <RegionPicker v-model:value="regionCode" mode="required-district" />
          <p class="zp-hint">入库须落区县级：区县管理员默认本辖区；市/省级管理员请选定区县；上传后自动进入该区域标注队列</p>
        </div>
      </div>
    </div>

    <!-- 文件上传 -->
    <div class="zp-card zp-mb-16">
      <div class="zp-card-head">
        <h2>选择文件</h2>
        <span class="zp-card-sub">支持 wav / mp3 / m4a / flac / aac / ogg / webm</span>
      </div>
      <div class="zp-card-body">
        <el-upload
          drag
          multiple
          :auto-upload="false"
          :show-file-list="false"
          :on-change="onFileChange"
          accept=".wav,.mp3,.m4a,.flac,.aac,.ogg,.webm"
        >
          <div class="zp-dropzone zp-mb-16">
            <b>点击选择或拖入音频文件（可多选）</b><br />
            逐个上传转存，UUID 重命名，ffprobe 自动读取时长；单文件不超过 100 MB
          </div>
        </el-upload>

        <div class="zp-table-wrap" v-if="rows.length">
          <table class="zp-table">
            <thead>
              <tr><th>文件名</th><th>大小</th><th>时长</th><th>状态</th><th>说明</th></tr>
            </thead>
            <tbody>
              <tr v-for="row in rows" :key="row.uid">
                <td class="num">{{ row.name }}</td>
                <td class="num">{{ fmtSize(row.size) }}</td>
                <td class="num">—</td>
                <td>
                  <span v-if="row.status === 'done'" class="zp-tag zp-tag--green">已入库</span>
                  <span v-else-if="row.status === 'error'" class="zp-tag zp-tag--danger">失败</span>
                  <span v-else class="zp-tag zp-tag--gray">等待中</span>
                </td>
                <td class="zp-text-3">{{ row.error || "—" }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <button class="zp-btn zp-btn--primary zp-btn--lg zp-mt-16" style="width: 100%" type="button"
          :disabled="uploading || !rows.length" @click="startUpload">
          {{ uploading ? "上传中…" : "开始上传" }}
        </button>
      </div>
    </div>

    <div class="zp-alert zp-alert--info">
      <span>提示：大批量存量音频（数百条以上）建议使用「音频导入」的扫盘方式，从服务器文件夹批量入库。</span>
    </div>
  </div>
</template>

<style scoped>
.zp-dropzone {
  border: 1.5px dashed var(--line-strong);
  border-radius: var(--radius-lg);
  padding: 36px 16px;
  text-align: center;
  color: var(--ink-3);
  font-size: 13px;
}
.zp-dropzone b {
  color: var(--navy-700);
  font-size: 14px;
}
</style>
