<script setup lang="ts">
/**
 * 用户管理（T33 / dome/admin-users.html 1:1）
 * 筛选 + 表格（角色 tag / 录音数 / 有效标注 / 任务进度）+ 新增/编辑 + 重置密码 + 删除（400 有录音禁删透传）
 * + 批量导入（模板下载 / el-upload / 轮询明细）+ 导出 blob。
 * 角色选项按 /auth/me role：super_admin 可选 super_admin，admin 仅 user/admin。
 */
import { computed, onMounted, reactive, ref } from "vue"
import { ElMessage, type UploadFile } from "element-plus"
import { useUserStore } from "@/stores/user"
import { api } from "@/api/http"
import {
  createUser,
  deleteUser,
  downloadImportTemplate,
  exportUsers,
  getImportStatus,
  importUsers,
  listUsers,
  updateUser,
} from "@/api/admin/users"
import type { ImportDetailRow, UserItem } from "@/api/admin/users"

interface RegionNode {
  code: string
  name: string
  level: string
  children: RegionNode[]
}

interface Station {
  code: string
  name: string
  region_code: string
  sort_order: number
}

const ROLE_LABEL: Record<string, string> = { user: "民警", admin: "管理员", super_admin: "超级管理员" }
const ROLE_TAG: Record<string, string> = { user: "zp-tag--gray", admin: "zp-tag--blue", super_admin: "zp-tag--gold" }
const TYPE_LABEL: Record<string, string> = { recording: "录音", annotation: "标注" }

function formatDate(iso: string | null): string {
  if (!iso) return "—"
  return iso.slice(5, 10)
}

const userStore = useUserStore()
const isSuper = computed(() => userStore.user?.role === "super_admin")

const roleOptions = computed(() => {
  const opts = [
    { value: "user", label: "民警" },
    { value: "admin", label: "管理员" },
  ]
  if (isSuper.value) opts.push({ value: "super_admin", label: "超级管理员" })
  return opts
})

// ---------- 列表 ----------
const loading = ref(false)
const filters = reactive({ real_name: "", phone: "", role: "", station: "" })
const items = ref<UserItem[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 20

const regionTree = ref<RegionNode[]>([])
const allStations = ref<Station[]>([])

// 区域筛选：地市 + 区县两级下拉，地市选定后区县才可选（市码展开整域、区县码精确）
const filterCity = ref("")
const filterDistrict = ref("")
const filterRegionCode = computed(() => filterDistrict.value || filterCity.value)

const cityOptions = computed<RegionNode[]>(() =>
  regionTree.value.flatMap((r) => (r.level === "province" ? r.children : [r])))

const filterDistrictOptions = computed<RegionNode[]>(() =>
  filterCity.value
    ? cityOptions.value.find((c) => c.code === filterCity.value)?.children ?? []
    : [])

function onFilterCityChange() {
  filterDistrict.value = ""
}

async function load() {
  loading.value = true
  try {
    const data = await listUsers({
      real_name: filters.real_name || undefined,
      phone: filters.phone || undefined,
      role: filters.role || undefined,
      region_code: filterRegionCode.value || undefined,
      station: filters.station || undefined,
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
  filters.phone = ""
  filters.role = ""
  filters.station = ""
  filterCity.value = ""
  filterDistrict.value = ""
  search()
}

function onPageChange(p: number) {
  page.value = p
  void load()
}

async function loadBase() {
  const [tree, stations] = await Promise.all([
    api.get<RegionNode[]>("/regions/tree"),
    api.get<Station[]>("/police_stations"),
  ])
  regionTree.value = tree
  allStations.value = stations
}

// ---------- 新增 / 编辑 ----------
const dlgUser = reactive({
  visible: false,
  editing: false,
  id: 0,
  phone: "",
  real_name: "",
  regionCode: "",
  policeStation: "",
  role: "user",
  password: "",
})
// 弹窗区域：地市 + 区县两级下拉（区县可不选 = 市本级账号；派出所随区县加载）
const dlgCity = ref("")
const dlgDistrict = ref("")
const formStations = ref<Station[]>([])

const dlgDistrictOptions = computed<RegionNode[]>(() =>
  dlgCity.value
    ? cityOptions.value.find((c) => c.code === dlgCity.value)?.children ?? []
    : [])

function syncDlgRegion() {
  dlgUser.regionCode = dlgDistrict.value || dlgCity.value
}

function onDlgCityChange() {
  dlgDistrict.value = ""
  formStations.value = []
  syncDlgRegion()
}

function onDlgDistrictChange() {
  formStations.value = []
  syncDlgRegion()
  if (dlgDistrict.value) void loadFormStations(dlgDistrict.value)
}

/** 编辑回填：区县码 → 市+县；市码 → 仅市（市级账号） */
function fillDlgRegion(code: string) {
  dlgCity.value = ""
  dlgDistrict.value = ""
  if (code) {
    const city = cityOptions.value.find(
      (c) => c.code === code || c.children.some((d) => d.code === code),
    )
    if (city) {
      dlgCity.value = city.code
      if (code !== city.code) dlgDistrict.value = code
    }
  }
  syncDlgRegion()
}

function openCreate() {
  Object.assign(dlgUser, {
    visible: true, editing: false, id: 0, phone: "", real_name: "",
    regionCode: "", policeStation: "", role: "user", password: "",
  })
  fillDlgRegion("")
  formStations.value = []
}

function openEdit(u: UserItem) {
  Object.assign(dlgUser, {
    visible: true, editing: true, id: u.id, phone: u.phone, real_name: u.real_name,
    regionCode: u.region_code, policeStation: u.police_station, role: u.role, password: "",
  })
  fillDlgRegion(u.region_code)
  formStations.value = []
  if (u.region_code) void loadFormStations(u.region_code)
}

async function loadFormStations(regionCode: string) {
  formStations.value = await api.get<Station[]>(`/police_stations/by-region/${regionCode}`)
}

async function submitUser() {
  if (!dlgUser.phone) {
    ElMessage.warning("请输入手机号")
    return
  }
  if (!dlgUser.real_name) {
    ElMessage.warning("请输入姓名")
    return
  }
  if (!dlgUser.regionCode) {
    ElMessage.warning("请选择区域")
    return
  }
  if (dlgUser.editing) {
    await updateUser(dlgUser.id, {
      real_name: dlgUser.real_name,
      region_code: dlgUser.regionCode,
      police_station: dlgUser.policeStation,
      role: dlgUser.role,
      password: dlgUser.password || undefined,
    })
    ElMessage.success("用户信息已保存")
  } else {
    await createUser({
      phone: dlgUser.phone,
      real_name: dlgUser.real_name,
      region_code: dlgUser.regionCode,
      police_station: dlgUser.policeStation,
      role: dlgUser.role,
    })
    ElMessage.success("用户已创建")
  }
  dlgUser.visible = false
  void load()
}

// ---------- 重置密码 ----------
const dlgPwd = reactive({ visible: false, id: 0, phone: "", title: "" })

function openPwd(u: UserItem) {
  dlgPwd.id = u.id
  dlgPwd.phone = u.phone
  dlgPwd.title = `${u.real_name}（${u.phone}）`
  dlgPwd.visible = true
}

async function submitPwd() {
  await updateUser(dlgPwd.id, { password: dlgPwd.phone.slice(-6) })
  ElMessage.success("密码已重置为手机号后 6 位")
  dlgPwd.visible = false
}

// ---------- 删除 ----------
const dlgDel = reactive({ visible: false, id: 0, title: "" })

function openDel(u: UserItem) {
  dlgDel.id = u.id
  dlgDel.title = `${u.real_name}（${u.phone}）`
  dlgDel.visible = true
}

async function submitDel() {
  await deleteUser(dlgDel.id)
  ElMessage.success("用户已删除")
  dlgDel.visible = false
  void load()
}

// ---------- 导出 ----------
function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement("a")
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

async function doExport() {
  const blob = await exportUsers({
    real_name: filters.real_name || undefined,
    phone: filters.phone || undefined,
    role: filters.role || undefined,
    region_code: filterRegionCode.value || undefined,
    station: filters.station || undefined,
  })
  saveBlob(blob, "users_export.xlsx")
}

// ---------- 批量导入 ----------
const dlgImport = reactive({
  visible: false,
  batchId: 0,
  status: "",
  total: 0,
  success: 0,
  fail: 0,
  detail: [] as ImportDetailRow[],
})
const importPolling = ref(false)
const importTimer = ref<number | null>(null)

function openImport() {
  Object.assign(dlgImport, { visible: true, batchId: 0, status: "", total: 0, success: 0, fail: 0, detail: [] })
}

function closeImport() {
  stopPolling()
  dlgImport.visible = false
}

function stopPolling() {
  if (importTimer.value !== null) {
    clearInterval(importTimer.value)
    importTimer.value = null
  }
  importPolling.value = false
}

function pollImport() {
  stopPolling()
  importPolling.value = true
  importTimer.value = window.setInterval(() => {
    void getImportStatus(dlgImport.batchId)
      .then((st) => {
        dlgImport.status = st.status
        dlgImport.total = st.total
        dlgImport.success = st.success
        dlgImport.fail = st.fail
        dlgImport.detail = st.detail
        if (st.status === "completed") stopPolling()
      })
      .catch(() => stopPolling())
  }, 1000)
}

async function onUploadChange(file: UploadFile) {
  const raw = file.raw
  if (!raw) return
  try {
    const data = await importUsers(raw)
    dlgImport.batchId = data.batch_id
    dlgImport.status = "processing"
    dlgImport.detail = []
    pollImport()
  } catch {
    /* 拦截器已提示 */
  }
}

async function downloadTemplate() {
  const blob = await downloadImportTemplate()
  saveBlob(blob, "users_import_template.xlsx")
}

onMounted(() => {
  void loadBase()
  void load()
})
</script>

<template>
  <div v-loading="loading">
    <div class="zp-page-head">
      <h1>用户管理</h1>
      <span class="sub">辖区用户台账 · 数据范围随层级自动限定</span>
      <div class="zp-head-actions">
        <button class="zp-btn zp-btn--ghost" type="button" @click="doExport">导出 Excel</button>
        <button class="zp-btn zp-btn--gold" type="button" @click="openImport">批量导入</button>
        <button class="zp-btn zp-btn--primary" type="button" @click="openCreate">新增用户</button>
      </div>
    </div>

    <!-- 筛选栏 -->
    <div class="zp-filter">
      <el-select v-model="filters.role" placeholder="全部角色" clearable style="width: 130px">
        <el-option label="民警" value="user" />
        <el-option label="管理员" value="admin" />
        <el-option label="超级管理员" value="super_admin" />
      </el-select>
      <el-select
        v-model="filterCity"
        placeholder="全部地市"
        clearable
        style="width: 140px"
        @change="onFilterCityChange"
      >
        <el-option v-for="c in cityOptions" :key="c.code" :label="c.name" :value="c.code" />
      </el-select>
      <el-select
        v-model="filterDistrict"
        placeholder="全部区县"
        clearable
        :disabled="!filterCity"
        style="width: 140px"
      >
        <el-option v-for="d in filterDistrictOptions" :key="d.code" :label="d.name" :value="d.code" />
      </el-select>
      <el-select v-model="filters.station" placeholder="全部单位" clearable filterable style="width: 180px">
        <el-option v-for="s in allStations" :key="s.code" :label="s.name" :value="s.name" />
      </el-select>
      <el-input v-model="filters.real_name" placeholder="姓名 / 手机号" clearable style="width: 180px" />
      <button class="zp-btn zp-btn--primary" type="button" @click="search">查询</button>
      <button class="zp-btn zp-btn--ghost" type="button" @click="reset">重置</button>
    </div>

    <!-- 用户列表 -->
    <div class="zp-card">
      <div class="zp-table-wrap">
        <table class="zp-table">
          <thead>
            <tr>
              <th>姓名</th><th>手机号</th><th>角色</th><th>区域</th><th>单位</th>
              <th>录音数</th><th>有效标注</th><th>任务进度</th><th>注册时间</th><th class="zp-text-right">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="u in items" :key="u.id" :style="u.role === 'super_admin' && !isSuper ? 'opacity:.7' : ''">
              <td><b>{{ u.real_name }}</b></td>
              <td class="num">{{ u.phone }}</td>
              <td><span class="zp-tag" :class="ROLE_TAG[u.role] || 'zp-tag--gray'">{{ ROLE_LABEL[u.role] || u.role }}</span></td>
              <td>{{ u.region_name }}</td>
              <td>{{ u.police_station || "—" }}</td>
              <td class="num">{{ u.recording_count }}</td>
              <td class="num">{{ u.annotation_count }}</td>
              <td>
                <span v-if="u.task_progress">{{ TYPE_LABEL[u.task_progress.type] || u.task_progress.type }} {{ u.task_progress.done }}/{{ u.task_progress.target_count }}</span>
                <span v-else class="zp-text-3">—</span>
              </td>
              <td class="num">{{ formatDate(u.created_at) }}</td>
              <td class="zp-text-right">
                <template v-if="u.role !== 'super_admin' || isSuper">
                  <button class="zp-btn zp-btn--text" type="button" @click="openEdit(u)">编辑</button>
                  <button class="zp-btn zp-btn--text" type="button" @click="openPwd(u)">重置密码</button>
                  <button class="zp-btn zp-btn--text is-danger" type="button" @click="openDel(u)">删除</button>
                </template>
                <span v-else class="zp-text-3">上级管辖，仅可见</span>
              </td>
            </tr>
            <tr v-if="!items.length"><td colspan="10" class="zp-center"><div class="zp-empty"><p>暂无用户</p></div></td></tr>
          </tbody>
        </table>
      </div>
      <div class="zp-pagination" style="padding: 14px 20px">
        <span class="total">辖区共 {{ total }} 人</span>
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
      <span>说明：有录音的用户不可删除；区县管理员仅可管理本辖区用户，超级管理员可管理全省并创建各级管理员。</span>
    </div>

    <!-- 新增 / 编辑用户 -->
    <el-dialog v-model="dlgUser.visible" :title="dlgUser.editing ? '编辑用户' : '新增用户'" width="560px">
      <div class="zp-form-row">
        <div class="zp-field">
          <label>手机号<span class="req">*</span></label>
          <el-input v-model="dlgUser.phone" :disabled="dlgUser.editing" />
        </div>
        <div class="zp-field">
          <label>姓名<span class="req">*</span></label>
          <el-input v-model="dlgUser.real_name" />
        </div>
      </div>
      <div class="zp-form-row">
        <div class="zp-field">
          <label>区域<span class="req">*</span></label>
          <div class="zp-flex" style="gap: 8px">
            <el-select
              v-model="dlgCity"
              placeholder="选择地市"
              clearable
              style="flex: 1"
              @change="onDlgCityChange"
            >
              <el-option v-for="c in cityOptions" :key="c.code" :label="c.name" :value="c.code" />
            </el-select>
            <el-select
              v-model="dlgDistrict"
              placeholder="区县（可不选）"
              clearable
              :disabled="!dlgCity"
              style="flex: 1"
              @change="onDlgDistrictChange"
            >
              <el-option v-for="d in dlgDistrictOptions" :key="d.code" :label="d.name" :value="d.code" />
            </el-select>
          </div>
        </div>
        <div class="zp-field">
          <label>所属派出所</label>
          <el-select v-model="dlgUser.policeStation" filterable allow-create default-first-option placeholder="选择或输入" style="width: 100%">
            <el-option v-for="s in formStations" :key="s.code" :label="s.name" :value="s.name" />
          </el-select>
        </div>
      </div>
      <div class="zp-form-row">
        <div class="zp-field">
          <label>角色<span class="req">*</span></label>
          <el-select v-model="dlgUser.role" style="width: 100%">
            <el-option v-for="o in roleOptions" :key="o.value" :label="o.label" :value="o.value" />
          </el-select>
        </div>
        <div class="zp-field" v-if="dlgUser.editing">
          <label>重置密码</label>
          <el-input v-model="dlgUser.password" type="password" placeholder="留空表示不修改" show-password />
        </div>
      </div>
      <template #footer>
        <button class="zp-btn zp-btn--ghost" type="button" @click="dlgUser.visible = false">取消</button>
        <button class="zp-btn zp-btn--primary" type="button" @click="submitUser">保存</button>
      </template>
    </el-dialog>

    <!-- 重置密码 -->
    <el-dialog v-model="dlgPwd.visible" title="重置密码" width="460px">
      <p>确定将 <b>{{ dlgPwd.title }}</b> 的密码重置为初始密码（手机号后 6 位）吗？</p>
      <template #footer>
        <button class="zp-btn zp-btn--ghost" type="button" @click="dlgPwd.visible = false">取消</button>
        <button class="zp-btn zp-btn--primary" type="button" @click="submitPwd">确认重置</button>
      </template>
    </el-dialog>

    <!-- 删除用户 -->
    <el-dialog v-model="dlgDel.visible" title="删除用户" width="460px">
      <p>确定删除 <b>{{ dlgDel.title }}</b> 吗？此操作不可恢复（有录音的用户将无法删除）。</p>
      <template #footer>
        <button class="zp-btn zp-btn--ghost" type="button" @click="dlgDel.visible = false">取消</button>
        <button class="zp-btn zp-btn--danger" type="button" @click="submitDel">确认删除</button>
      </template>
    </el-dialog>

    <!-- 批量导入 -->
    <el-dialog v-model="dlgImport.visible" title="批量导入用户" width="560px" @close="closeImport">
      <p class="zp-hint" style="margin-bottom: 12px">
        第一步：下载
        <a href="javascript:void(0)" @click="downloadTemplate">Excel 模板</a>
        （手机号 / 姓名 / 区域码 / 单位 / 角色）
      </p>
      <el-upload
        :show-file-list="false"
        :auto-upload="false"
        accept=".xlsx"
        :on-change="onUploadChange"
      >
        <div class="zp-dropzone zp-mb-16">
          <b>点击选择或拖入 .xlsx 文件</b><br>
          第二步：上传名单，逐行校验后导入；初始密码为手机号后 6 位
        </div>
      </el-upload>

      <div v-if="dlgImport.batchId">
        <div class="zp-alert" :class="dlgImport.status === 'completed' ? 'zp-alert--ok' : 'zp-alert--info'">
          <span v-if="dlgImport.status === 'completed'">导入完成：新增 {{ dlgImport.success }} 人 · 失败 {{ dlgImport.fail }} 人</span>
          <span v-else>导入中，请稍候…（已处理 {{ dlgImport.detail.length }} / {{ dlgImport.total || '—' }}）</span>
        </div>
        <div v-if="dlgImport.detail.length" class="zp-table-wrap" style="margin-top: 12px">
          <table class="zp-table">
            <thead><tr><th>手机号</th><th>结果</th><th>说明</th></tr></thead>
            <tbody>
              <tr v-for="(d, i) in dlgImport.detail" :key="i">
                <td class="num">{{ d.phone }}</td>
                <td><span class="zp-tag" :class="d.ok ? 'zp-tag--green' : 'zp-tag--danger'">{{ d.ok ? "成功" : "失败" }}</span></td>
                <td>{{ d.msg }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
      <template #footer>
        <button class="zp-btn zp-btn--ghost" type="button" @click="closeImport">关闭</button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.zp-dropzone {
  border: 1.5px dashed var(--line-strong);
  border-radius: var(--radius-lg);
  padding: 28px 16px;
  text-align: center;
  color: var(--ink-3);
  font-size: 13px;
  cursor: pointer;
}
.zp-dropzone b {
  color: var(--navy-700);
}
</style>
