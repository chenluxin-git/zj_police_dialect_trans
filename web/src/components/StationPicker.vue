<script lang="ts">
export interface StationPickItem {
  code: string
  name: string
  region_code: string
}
</script>

<script setup lang="ts">
/**
 * 单位选择器（RegionPicker 的下一级）：地市/区县 → 单位
 *
 * 两种形态：
 * - standalone：内嵌 RegionPicker(required-district) + 单位下拉（消息发送·按单位）
 * - linked：外部传 regionCode（省/市/县码均可），只渲染单位下拉（用户管理筛选行，
 *   避免出现第二个区域下拉）；regionCode 为空时市/县管回退自身辖区，省/超管禁用待选
 *
 * 值语义：单选=单位名（与 User.police_station / listUsers station 参数同口径）；
 * 多选=单位 code 数组（同名单位跨区县重名不碰撞），change 回传完整项供提交携带区县。
 * 多选可跨区县累积：切区域后已选项保留，置底「已选（跨区县）」组保证 tag 显示名。
 * 数据：全量单位（696 条）+ 区域（102 条）各拉一次，模块级缓存多实例共享。
 */
import { computed, onMounted, ref, watch } from "vue"
import RegionPicker from "@/components/RegionPicker.vue"
import { useUserStore } from "@/stores/user"
import { api } from "@/api/http"
import { listRegions, type RegionItem } from "@/api/admin/texts"

interface Station {
  code: string
  name: string
  region_code: string
  sort_order: number
}

// 模块级缓存：两个实例（消息发送 + 用户管理筛选行）共享一次请求
let stationsCache: Promise<Station[]> | null = null
let regionsCache: Promise<RegionItem[]> | null = null

function loadStations() {
  if (!stationsCache) {
    stationsCache = api.get<Station[]>("/police_stations").catch((e) => {
      stationsCache = null
      throw e
    })
  }
  return stationsCache
}

function loadRegions() {
  if (!regionsCache) {
    regionsCache = listRegions().catch((e) => {
      regionsCache = null
      throw e
    })
  }
  return regionsCache
}

const props = withDefaults(
  defineProps<{
    /** 单选=单位名（""=未选）；多选=单位 code 数组 */
    value?: string | string[]
    multiple?: boolean
    /** linked 模式：外部区域码（省/市/县码均可，内部展开到后代区县集） */
    regionCode?: string
    /** true 时内嵌 RegionPicker(required-district)，false 时只渲染单位下拉 */
    standalone?: boolean
    clearable?: boolean
    filterable?: boolean
    placeholder?: string
    disabled?: boolean
  }>(),
  {
    value: "",
    multiple: false,
    regionCode: "",
    standalone: false,
    clearable: false,
    filterable: true,
    placeholder: "选择单位",
    disabled: false,
  },
)

const emit = defineEmits<{
  (e: "update:value", v: string | string[]): void
  /** 完整选中项（含 code/name/region_code），供提交携带区县约束 */
  (e: "change", items: StationPickItem[]): void
}>()

const userStore = useUserStore()
const stations = ref<Station[]>([])
const flatRegions = ref<RegionItem[]>([])
const loaded = ref(false)
// standalone 模式 RegionPicker 发出的码（区县优先，否则地市码）
const innerRegion = ref("")

async function load() {
  try {
    const [st, rg] = await Promise.all([loadStations(), loadRegions()])
    stations.value = st
    flatRegions.value = rg
  } catch {
    /* 错误已由 http 拦截器提示 */
  }
  loaded.value = true
}

async function reload() {
  stationsCache = null
  regionsCache = null
  await load()
}

const ownRegion = computed(() =>
  flatRegions.value.find((r) => r.code === userStore.user?.region_code),
)
/** 省/超管：不回退自身辖区，linked 未传区域时禁用待选 */
const isPrivileged = computed(
  () => userStore.user?.role === "super_admin" || ownRegion.value?.level === "province",
)

const effectiveRegion = computed(() => {
  if (props.standalone) {
    if (innerRegion.value) return innerRegion.value
    // 县管：RegionPicker 只读不发码，直接用自身区县
    return ownRegion.value?.level === "district" ? ownRegion.value.code : ""
  }
  if (props.regionCode) return props.regionCode
  if (isPrivileged.value) return ""
  return userStore.user?.region_code || ""
})

/** 生效区域 + 全部后代（单位只挂区县级，市/省码留在集合里无碍） */
const districtSet = computed(() => {
  const code = effectiveRegion.value
  if (!code) return new Set<string>()
  const byParent = new Map<string, string[]>()
  for (const r of flatRegions.value) {
    if (!r.parent_code) continue
    const arr = byParent.get(r.parent_code)
    if (arr) arr.push(r.code)
    else byParent.set(r.parent_code, [r.code])
  }
  const result = new Set<string>([code])
  const queue = [code]
  while (queue.length) {
    const c = queue.shift() as string
    for (const child of byParent.get(c) || []) {
      if (!result.has(child)) {
        result.add(child)
        queue.push(child)
      }
    }
  }
  return result
})

const options = computed(() =>
  stations.value.filter((s) => districtSet.value.has(s.region_code)),
)

/** 按区县分组（跨多区县时用 el-option-group，组按区县名排序） */
const grouped = computed(() => {
  const byRegion = new Map<string, Station[]>()
  for (const s of options.value) {
    const arr = byRegion.get(s.region_code)
    if (arr) arr.push(s)
    else byRegion.set(s.region_code, [s])
  }
  const nameOf = (code: string) => flatRegions.value.find((r) => r.code === code)?.name || code
  return Array.from(byRegion.entries())
    .map(([code, list]) => ({ code, label: nameOf(code), list }))
    .sort((a, b) => (a.label < b.label ? -1 : 1))
})

const isGrouped = computed(() => grouped.value.length > 1)

/** 把当前值解析为完整项（emit 的 items 一律从全量列表反查，防面板切换后信息丢失） */
function resolveItems(value: string | string[] | null | undefined): StationPickItem[] {
  if (props.multiple) {
    const codes = Array.isArray(value) ? value : []
    const map = new Map(stations.value.map((s) => [s.code, s]))
    const out: StationPickItem[] = []
    for (const c of codes) {
      const s = map.get(c)
      if (s) out.push({ code: s.code, name: s.name, region_code: s.region_code })
    }
    return out
  }
  const name = typeof value === "string" ? value : ""
  if (!name) return []
  // 单选：先在当前面板找（区县明确），退回全量第一个同名
  const hit = options.value.find((s) => s.name === name) || stations.value.find((s) => s.name === name)
  return hit ? [{ code: hit.code, name: hit.name, region_code: hit.region_code }] : []
}

const selectedItems = computed(() => resolveItems(props.value))

/** 已选但不在当前区域面板的单位（多选跨区县累积），置底成组保证 tag 显示名 */
const crossSelected = computed(() => {
  if (!props.multiple) return []
  const inPanel = new Set(options.value.map((s) => s.code))
  return selectedItems.value.filter((i) => !inPanel.has(i.code))
})

function optVal(s: { code: string; name: string }): string {
  return props.multiple ? s.code : s.name
}

function onSelect(v: string | string[] | null | undefined) {
  const normalized: string | string[] = props.multiple
    ? Array.isArray(v) ? v : []
    : typeof v === "string" ? v : ""
  emit("update:value", normalized)
  emit("change", resolveItems(normalized))
}

const clearableComputed = computed(() => props.clearable || !props.multiple)

const selectDisabled = computed(() => props.disabled || !effectiveRegion.value)

const selectPlaceholder = computed(() => {
  if (effectiveRegion.value) return props.placeholder
  return props.standalone ? "请先选择地市/区县" : "请先选择区域"
})

onMounted(load)

// 单选：生效区域变化后，越界的已选单位自动清空（多选保留 = 跨区县累积）
watch([districtSet, loaded], () => {
  if (props.multiple || !loaded.value) return
  const name = typeof props.value === "string" ? props.value : ""
  if (!name) return
  if (!options.value.some((s) => s.name === name)) {
    emit("update:value", "")
    emit("change", [])
  }
})

defineExpose({ reload })
</script>

<template>
  <div>
    <RegionPicker
      v-if="standalone"
      v-model:value="innerRegion"
      mode="required-district"
      city-placeholder="选择地市"
      district-placeholder="选择区县"
      style="margin-bottom: 8px"
    />
    <el-select
      :model-value="value"
      :multiple="multiple"
      :clearable="clearableComputed"
      :filterable="filterable"
      :placeholder="selectPlaceholder"
      :disabled="selectDisabled"
      style="width: 100%"
      @update:model-value="onSelect"
    >
      <template v-if="isGrouped">
        <el-option-group v-for="g in grouped" :key="g.code" :label="g.label">
          <el-option v-for="s in g.list" :key="s.code" :label="s.name" :value="optVal(s)" />
        </el-option-group>
      </template>
      <template v-else>
        <el-option v-for="s in options" :key="s.code" :label="s.name" :value="optVal(s)" />
      </template>
      <el-option-group v-if="crossSelected.length" label="已选（跨区县）">
        <el-option v-for="s in crossSelected" :key="s.code" :label="s.name" :value="optVal(s)" />
      </el-option-group>
      <el-option v-if="loaded && effectiveRegion && !options.length" disabled label="该区域暂无单位" value="" />
    </el-select>
  </div>
</template>
