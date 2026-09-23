<script setup lang="ts">
/**
 * 任务管理（T32 / dome/admin-tasks.html 1:1）
 * 筛选 + 行内进度条（超额金色 / 未启动 warn / 取消置灰）+ 四弹窗（单人/批量/调整/取消）+ 规则说明。
 */
import { computed, onMounted, reactive, ref, watch } from "vue"
import { ElMessage } from "element-plus"
import { assignTask, assignTaskBatch, listTasks, updateTask } from "@/api/admin/tasks"
import type { TaskItem } from "@/api/admin/tasks"
import { listUsers } from "@/api/admin/users"
import type { UserItem } from "@/api/admin/users"
import RegionPicker from "@/components/RegionPicker.vue"

const TYPE_LABEL: Record<string, string> = { recording: "录音", annotation: "标注" }

function formatDate(iso: string | null): string {
  if (!iso) return "—"
  return iso.slice(5, 16).replace("T", " ")
}

function barWidth(t: TaskItem): number {
  if (!t.target_count) return 0
  return Math.min(100, Math.round((t.done / t.target_count) * 100))
}

function donePct(t: TaskItem): number {
  if (!t.target_count) return 0
  return Math.round((t.done / t.target_count) * 100)
}

function fillClass(t: TaskItem): string {
  if (t.status === "cancelled") return ""
  if (t.target_count > 0 && t.done >= t.target_count) return t.done > t.target_count ? "is-over" : "is-done"
  return ""
}

function numStyle(t: TaskItem): string {
  if (t.status === "cancelled") return ""
  if (t.target_count > 0 && t.done > t.target_count) return "color:var(--gold-500)"
  if (t.target_count > 0 && t.done >= t.target_count) return "color:var(--ok)"
  return ""
}

function statusOf(t: TaskItem): { label: string; cls: string } {
  if (t.status === "cancelled") return { label: "已取消", cls: "zp-tag--gray" }
  if (t.done <= 0) return { label: "未启动", cls: "zp-tag--warn" }
  if (t.done >= t.target_count) return { label: "已完成", cls: "zp-tag--green" }
  return { label: "进行中", cls: "zp-tag--navy" }
}

const loading = ref(false)
const filters = reactive({ real_name: "", type: "", status: "" })
const items = ref<TaskItem[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 20

async function load() {
  loading.value = true
  try {
    const data = await listTasks({
      real_name: filters.real_name || undefined,
      type: filters.type || undefined,
      status: filters.status || undefined,
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
  filters.real_name = ""
  filters.type = ""
  filters.status = ""
  search()
}

function onPageChange(p: number) {
  page.value = p
  void load()
}

// ---------- 单人下达 ----------
const dlgAssign = reactive({ visible: false, userId: null as number | null, type: "recording", target: 100, note: "" })
const assignUserOptions = ref<{ value: number; label: string }[]>([])
const assignSearchLoading = ref(false)

async function searchUsers(q: string) {
  assignSearchLoading.value = true
  try {
    const data = await listUsers({ real_name: q || undefined, page: 1, page_size: 20 })
    assignUserOptions.value = data.items.map((u) => ({
      value: u.id,
      label: `${u.real_name} · ${u.phone} · ${u.police_station || "—"}`,
    }))
  } finally {
    assignSearchLoading.value = false
  }
}

function openAssign() {
  dlgAssign.userId = null
  dlgAssign.type = "recording"
  dlgAssign.target = 100
  dlgAssign.note = ""
  dlgAssign.visible = true
  void searchUsers("")
}

async function submitAssign() {
  if (dlgAssign.userId == null) {
    ElMessage.warning("请选择民警")
    return
  }
  await assignTask({
    user_id: dlgAssign.userId,
    type: dlgAssign.type,
    target_count: dlgAssign.target,
    note: dlgAssign.note || undefined,
  })
  ElMessage.success("任务已下达")
  dlgAssign.visible = false
  void load()
}

// ---------- 批量下达 ----------
const dlgBatch = reactive({ visible: false, type: "recording", target: 50, note: "" })
const batchUsers = ref<UserItem[]>([])
const batchSelected = ref<number[]>([])
// 区域筛选（RegionPicker 统一维护，仅超管渲染选择器；市/县管后端自动限辖区）
// + 是否含管理员（默认只列民警）+ 组内搜索
const batchRegionCode = ref("")
const batchIncludeAdmins = ref(false)
const batchKeyword = ref("")
const batchLoading = ref(false)
let batchLoadSeq = 0 // 连续切换区域时丢弃过期响应

async function loadBatchUsers() {
  const seq = ++batchLoadSeq
  batchLoading.value = true
  try {
    const base = {
      page_size: 100,
      role: batchIncludeAdmins.value ? undefined : "user",
      region_code: batchRegionCode.value || undefined,
    }
    const first = await listUsers({ ...base, page: 1 })
    if (seq !== batchLoadSeq) return
    const items = [...first.items]
    // 后端 page_size 上限 100，按 total 翻页拉全（全省 282 账号 = 3 页）
    for (let p = 2; p <= Math.ceil(first.total / first.page_size); p++) {
      items.push(...(await listUsers({ ...base, page: p })).items)
    }
    if (seq !== batchLoadSeq) return
    batchUsers.value = items
    batchSelected.value = [] // 换区域/换口径清空选择，避免跨区域残留
  } finally {
    if (seq === batchLoadSeq) batchLoading.value = false
  }
}

// 组内搜索：只过滤展示层，已选但被过滤掉的人保持选中
const batchShown = computed(() => {
  const kw = batchKeyword.value.trim()
  if (!kw) return batchUsers.value
  return batchUsers.value.filter((u) => u.real_name.includes(kw) || u.phone.includes(kw))
})

// 全选作用于当前可见集（含搜索过滤），用 Set 合并不干扰其他区域已选
const batchAllChecked = computed({
  get: () => batchShown.value.length > 0 && batchShown.value.every((u) => batchSelected.value.includes(u.id)),
  set: (v: boolean) => {
    const ids = new Set(batchSelected.value)
    for (const u of batchShown.value) {
      if (v) ids.add(u.id)
      else ids.delete(u.id)
    }
    batchSelected.value = [...ids]
  },
})

const batchAllIndeterminate = computed(() => {
  const n = batchShown.value.filter((u) => batchSelected.value.includes(u.id)).length
  return n > 0 && n < batchShown.value.length
})

async function openBatch() {
  // 先复位（此时弹窗未开，watcher 不触发），再开窗取数
  dlgBatch.type = "recording"
  dlgBatch.target = 50
  dlgBatch.note = ""
  batchRegionCode.value = ""
  batchIncludeAdmins.value = false
  batchKeyword.value = ""
  dlgBatch.visible = true
  await loadBatchUsers()
}

// 弹窗开着时切换区域/口径 → 重拉（换区域选择清空在 loadBatchUsers 内）
watch([batchRegionCode, batchIncludeAdmins], () => {
  if (dlgBatch.visible) void loadBatchUsers()
})

async function submitBatch() {
  if (!batchSelected.value.length) {
    ElMessage.warning("请选择民警")
    return
  }
  await assignTaskBatch({
    user_ids: batchSelected.value,
    type: dlgBatch.type,
    target_count: dlgBatch.target,
    note: dlgBatch.note || undefined,
  })
  ElMessage.success(`已批量下达 ${batchSelected.value.length} 人`)
  dlgBatch.visible = false
  void load()
}

// ---------- 调整 ----------
const dlgAdjust = reactive({ visible: false, taskId: 0, target: 0, note: "", title: "" })

function openAdjust(t: TaskItem) {
  dlgAdjust.taskId = t.id
  dlgAdjust.target = t.target_count
  dlgAdjust.note = t.note
  dlgAdjust.title = `${t.real_name} · ${TYPE_LABEL[t.type] || t.type}任务 · 当前 ${t.done} / ${t.target_count}`
  dlgAdjust.visible = true
}

async function submitAdjust() {
  await updateTask(dlgAdjust.taskId, {
    target_count: dlgAdjust.target,
    note: dlgAdjust.note || undefined,
  })
  ElMessage.success("指标已调整")
  dlgAdjust.visible = false
  void load()
}

// ---------- 取消 ----------
const dlgCancel = reactive({ visible: false, taskId: 0, title: "" })

function openCancel(t: TaskItem) {
  dlgCancel.taskId = t.id
  dlgCancel.title = `${t.real_name} · ${TYPE_LABEL[t.type] || t.type}任务（${t.done} / ${t.target_count}）`
  dlgCancel.visible = true
}

async function submitCancel() {
  await updateTask(dlgCancel.taskId, { status: "cancelled" })
  ElMessage.success("任务已取消")
  dlgCancel.visible = false
  void load()
}

onMounted(() => void load())
</script>

<template>
  <div v-loading="loading">
    <div class="zp-page-head">
      <h1>任务管理</h1>
      <span class="sub">给辖区民警下达录音 / 标注数量指标，进度实时统计</span>
      <div class="zp-head-actions">
        <button class="zp-btn zp-btn--gold" type="button" @click="openBatch">批量下达</button>
        <button class="zp-btn zp-btn--primary" type="button" @click="openAssign">下达任务</button>
      </div>
    </div>

    <!-- 筛选栏 -->
    <div class="zp-filter">
      <el-select v-model="filters.type" placeholder="全部类型" clearable style="width: 130px">
        <el-option label="录音任务" value="recording" />
        <el-option label="标注任务" value="annotation" />
      </el-select>
      <el-select v-model="filters.status" placeholder="全部状态" clearable style="width: 130px">
        <el-option label="进行中" value="active" />
        <el-option label="已取消" value="cancelled" />
      </el-select>
      <el-input v-model="filters.real_name" placeholder="姓名 / 手机号" clearable style="width: 180px" />
      <button class="zp-btn zp-btn--primary" type="button" @click="search">查询</button>
      <button class="zp-btn zp-btn--ghost" type="button" @click="reset">重置</button>
    </div>

    <!-- 任务列表 -->
    <div class="zp-card">
      <div class="zp-table-wrap">
        <table class="zp-table">
          <thead>
            <tr>
              <th>民警</th><th>单位</th><th>类型</th><th>目标</th><th>已完成</th>
              <th style="width: 180px">进度</th><th>状态</th><th>下达时间</th><th class="zp-text-right">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="t in items" :key="t.id" :style="t.status === 'cancelled' ? 'opacity:.62' : ''">
              <td><b>{{ t.real_name }}</b><br><span class="zp-text-3">{{ t.police_station || "—" }}</span></td>
              <td>{{ t.police_station || "—" }}</td>
              <td>
                <span class="zp-tag" :class="t.type === 'recording' ? 'zp-tag--blue' : 'zp-tag--green'">
                  {{ TYPE_LABEL[t.type] || t.type }}
                </span>
              </td>
              <td class="num">{{ t.target_count }}</td>
              <td class="num">{{ t.done }}</td>
              <td>
                <div class="zp-task-progress">
                  <div class="track"><div class="fill" :class="fillClass(t)" :style="{ width: barWidth(t) + '%' }"></div></div>
                  <span class="num" :style="numStyle(t)">{{ donePct(t) }}%</span>
                </div>
              </td>
              <td><span class="zp-tag" :class="statusOf(t).cls">{{ statusOf(t).label }}</span></td>
              <td class="num">{{ formatDate(t.created_at) }}</td>
              <td class="zp-text-right">
                <template v-if="t.status === 'active'">
                  <button class="zp-btn zp-btn--text" type="button" @click="openAdjust(t)">调整</button>
                  <button class="zp-btn zp-btn--text is-danger" type="button" @click="openCancel(t)">取消</button>
                </template>
                <span v-else class="zp-text-3">—</span>
              </td>
            </tr>
            <tr v-if="!items.length"><td colspan="9" class="zp-center"><div class="zp-empty"><p>暂无任务</p></div></td></tr>
          </tbody>
        </table>
      </div>
      <div class="zp-pagination" style="padding: 14px 20px">
        <span class="total">辖区共 {{ total }} 条任务</span>
        <el-pagination
          background
          layout="prev, pager, next"
          :total="total"
          :page-size="pageSize"
          :current-page="page"
          @current-change="onPageChange"
        />
      </div>
    </div>

    <div class="zp-alert zp-alert--info zp-mt-16">
      <span>规则说明：进度 = 下达后的有效新增数（删除自动扣减）；同一民警同一类型仅一条进行中任务，重复下达即调整指标；任务下达与调整会自动向本人发送站内消息。</span>
    </div>

    <!-- 单人下达 -->
    <el-dialog v-model="dlgAssign.visible" title="下达任务" width="520px">
      <div class="zp-field">
        <label>选择民警<span class="req">*</span></label>
        <el-select
          v-model="dlgAssign.userId"
          filterable
          remote
          :remote-method="searchUsers"
          :loading="assignSearchLoading"
          placeholder="请搜索姓名 / 手机号"
          style="width: 100%"
        >
          <el-option v-for="o in assignUserOptions" :key="o.value" :label="o.label" :value="o.value" />
        </el-select>
      </div>
      <div class="zp-field">
        <label>任务类型<span class="req">*</span></label>
        <el-radio-group v-model="dlgAssign.type">
          <el-radio-button value="recording">录音任务</el-radio-button>
          <el-radio-button value="annotation">标注任务</el-radio-button>
        </el-radio-group>
      </div>
      <div class="zp-form-row">
        <div class="zp-field">
          <label>目标数量（条）<span class="req">*</span></label>
          <el-input-number v-model="dlgAssign.target" :min="1" style="width: 100%" />
        </div>
        <div class="zp-field">
          <label>备注</label>
          <el-input v-model="dlgAssign.note" placeholder="如：优先警情类文本" />
        </div>
      </div>
      <p class="zp-hint">该民警已有进行中的同类型任务时，本次下达将<b>调整其指标</b>，已完成数继续有效。</p>
      <template #footer>
        <button class="zp-btn zp-btn--ghost" type="button" @click="dlgAssign.visible = false">取消</button>
        <button class="zp-btn zp-btn--primary" type="button" @click="submitAssign">确认下达</button>
      </template>
    </el-dialog>

    <!-- 批量下达 -->
    <el-dialog v-model="dlgBatch.visible" title="批量下达" width="560px">
      <div class="zp-field">
        <label>任务类型<span class="req">*</span></label>
        <el-radio-group v-model="dlgBatch.type">
          <el-radio-button value="recording">录音任务</el-radio-button>
          <el-radio-button value="annotation">标注任务</el-radio-button>
        </el-radio-group>
      </div>
      <div class="zp-form-row">
        <div class="zp-field">
          <label>目标数量（条）<span class="req">*</span></label>
          <el-input-number v-model="dlgBatch.target" :min="1" style="width: 100%" />
        </div>
        <div class="zp-field">
          <label>备注</label>
          <el-input v-model="dlgBatch.note" placeholder="选填" />
        </div>
      </div>
      <div class="zp-field">
        <label>选择民警（已选 {{ batchSelected.length }} 人）<span class="req">*</span></label>
        <div class="zp-batch-toolbar">
          <RegionPicker
            v-model:value="batchRegionCode"
            mode="filter"
            super-only
            city-placeholder="全部地市"
            district-placeholder="全部区县"
            style="width: 290px"
          />
          <el-checkbox v-model="batchAllChecked" :indeterminate="batchAllIndeterminate" :disabled="!batchShown.length">
            全选{{ batchKeyword.trim() ? "（筛选结果）" : "" }}
          </el-checkbox>
          <el-switch v-model="batchIncludeAdmins" active-text="含管理员" />
        </div>
        <el-input
          v-model="batchKeyword"
          placeholder="搜索姓名 / 手机号"
          clearable
          style="width: 100%; margin-bottom: 8px"
        />
        <div class="zp-batch-pick" v-loading="batchLoading">
          <el-checkbox-group v-model="batchSelected">
            <el-checkbox v-for="u in batchShown" :key="u.id" :value="u.id" style="display: block; height: 30px">
              {{ u.real_name }} · {{ u.police_station || "—" }}（{{ u.phone }}）
              <span v-if="u.role !== 'user'" class="zp-tag zp-tag--warn" style="margin-left: 4px">
                {{ u.role === "super_admin" ? "超管" : "管理员" }}
              </span>
            </el-checkbox>
          </el-checkbox-group>
          <div v-if="!batchLoading && !batchShown.length" class="zp-empty"><p>该区域暂无民警</p></div>
        </div>
      </div>
      <p class="zp-hint">已有同类型进行中任务的民警，指标将被调整；其余民警新建任务，并逐一发送站内消息通知。</p>
      <template #footer>
        <button class="zp-btn zp-btn--ghost" type="button" @click="dlgBatch.visible = false">取消</button>
        <button class="zp-btn zp-btn--primary" type="button" @click="submitBatch">批量下达</button>
      </template>
    </el-dialog>

    <!-- 调整任务 -->
    <el-dialog v-model="dlgAdjust.visible" title="调整任务" width="520px">
      <p class="zp-text-3" style="margin-bottom: 14px">{{ dlgAdjust.title }}</p>
      <div class="zp-form-row">
        <div class="zp-field">
          <label>调整目标（条）<span class="req">*</span></label>
          <el-input-number v-model="dlgAdjust.target" :min="1" style="width: 100%" />
        </div>
        <div class="zp-field">
          <label>备注</label>
          <el-input v-model="dlgAdjust.note" placeholder="选填" />
        </div>
      </div>
      <p class="zp-hint">调整后基线不变、已完成数继续有效，本人将收到指标调整消息。</p>
      <template #footer>
        <button class="zp-btn zp-btn--ghost" type="button" @click="dlgAdjust.visible = false">取消</button>
        <button class="zp-btn zp-btn--primary" type="button" @click="submitAdjust">保存调整</button>
      </template>
    </el-dialog>

    <!-- 取消任务 -->
    <el-dialog v-model="dlgCancel.visible" title="取消任务" width="460px">
      <p>确定取消 <b>{{ dlgCancel.title }}</b> 吗？取消后进度不再统计，可随时重新下达。</p>
      <template #footer>
        <button class="zp-btn zp-btn--ghost" type="button" @click="dlgCancel.visible = false">取消</button>
        <button class="zp-btn zp-btn--danger" type="button" @click="submitCancel">确认取消任务</button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.zp-task-progress {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 150px;
}
.zp-task-progress .track {
  flex: 1;
  height: 6px;
  border-radius: 99px;
  background: #e8edf5;
  overflow: hidden;
}
.zp-task-progress .fill {
  height: 100%;
  background: var(--navy-700);
}
.zp-task-progress .fill.is-done {
  background: var(--ok);
}
.zp-task-progress .fill.is-over {
  background: var(--gold-500);
}
.zp-task-progress .num {
  font-size: 12px;
  color: var(--ink-2);
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}
.zp-batch-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 8px;
}
.zp-batch-pick {
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 6px 12px;
  max-height: 160px;
  overflow-y: auto;
}
</style>
