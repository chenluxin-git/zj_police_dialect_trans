<script setup lang="ts">
/**
 * 归属区域选择器（P0 公用件）
 *
 * 抽掉原本近乎逐字复制在 6~7 个页面里的那一整套逻辑：
 * needDistrictPick / findNode / cityOptions / districtOptions / onCityChange / ownRegionName
 * + Promise.all([/regions, /regions/tree])。
 *
 * 权限口径（与后端一致）：
 * - 区县管理员：无下拉，只读显示本辖区名称（mode=required-district 时）
 * - 市级管理员：地市锁本市，只需选到区县
 * - 省管/超管：全省地市 + 区县
 *
 * 两种模式：
 * - required-district：必须选到区县（导入类，市/省级归属会产生县级用户领不到的死数据）
 * - filter：可只选地市（市码 = 整域），也可选到区县（精确）；区县可不选
 */
import { computed, onMounted, ref, watch } from "vue"
import { useUserStore } from "@/stores/user"
import { api } from "@/api/http"
import { listRegions, type RegionItem } from "@/api/admin/texts"

interface RegionNode {
  code: string
  name: string
  level: string
  children: RegionNode[]
}

const props = withDefaults(
  defineProps<{
    /** 已解析的归属码：区县码优先，否则地市码 */
    value?: string
    mode?: "required-district" | "filter"
    /** 只在超管场景渲染（false 时空 div，用于 v-if 替代） */
    superOnly?: boolean
    /** 是否允许只选地市（filter 模式下默认允许；required-district 模式忽略） */
    cityOnly?: boolean
    cityPlaceholder?: string
    districtPlaceholder?: string
    cityAriaLabel?: string
    districtAriaLabel?: string
    disabled?: boolean
  }>(),
  {
    value: "",
    mode: "required-district",
    superOnly: false,
    cityOnly: false,
    cityPlaceholder: "选择地市",
    districtPlaceholder: "选择区县",
    cityAriaLabel: "地市",
    districtAriaLabel: "区县",
    disabled: false,
  },
)

const emit = defineEmits<{
  /** 归属码变化（区县优先，否则地市）；第二参为当前地市码，便于级联刷新下级列表 */
  (e: "update:value", code: string, cityCode: string): void
  (e: "change", code: string, cityCode: string): void
}>()

const userStore = useUserStore()

const regionTree = ref<RegionNode[]>([])
const flatRegions = ref<RegionItem[]>([])
const cityCode = ref("")
const districtCode = ref("")

/** 当前账号所属区域（用于判断是否需要选到区县） */
const ownRegion = computed(() =>
  flatRegions.value.find((r) => r.code === userStore.user?.region_code),
)
const ownRegionName = computed(() => ownRegion.value?.name || userStore.user?.region_code || "本辖区")

/** 区县管理员无需选择；其他级别需要 */
const readonlyOwn = computed(
  () => props.mode === "required-district" && flatRegions.value.length > 0 && ownRegion.value?.level === "district",
)

/** 关掉只读后是否还要渲染省/市/县下拉（filter 模式下始终渲染） */
const readonlyCompact = computed(
  () => props.mode === "filter" && flatRegions.value.length > 0 && ownRegion.value?.level === "district",
)

const cityOptions = computed<RegionNode[]>(() => {
  if (props.mode === "required-district") {
    // 市管锁本市，省管/超管全省
    if (ownRegion.value?.level === "city") {
      const own = findNode(regionTree.value, ownRegion.value.code)
      return own ? [own] : []
    }
    return regionTree.value.flatMap((r) => (r.level === "province" ? r.children : [r]))
  }
  // filter：市管不含市级筛选（自身就是整域），这里仍给全省供超管/省管用
  return regionTree.value.flatMap((r) => (r.level === "province" ? r.children : [r]))
})

const districtOptions = computed<RegionNode[]>(() =>
  cityCode.value
    ? cityOptions.value.find((c) => c.code === cityCode.value)?.children ?? []
    : [],
)

/** 是否允许只选到地市 */
const allowCityOnly = computed(() => props.mode === "filter" && props.cityOnly)

/** 区县下拉是否展示 */
const showDistrict = computed(() => cityCode.value !== "" || !allowCityOnly.value)

function findNode(nodes: RegionNode[], code: string): RegionNode | null {
  for (const n of nodes) {
    if (n.code === code) return n
    const hit = findNode(n.children, code)
    if (hit) return hit
  }
  return null
}

function resolved(): string {
  return districtCode.value || cityCode.value
}

function emitValue() {
  emit("update:value", resolved(), cityCode.value)
  emit("change", resolved(), cityCode.value)
}

function onCityChange() {
  districtCode.value = ""
  emitValue()
}

function onDistrictChange() {
  emitValue()
}

/** 外部回填：区县码 → 市+县；地市码 → 仅市 */
function fill(code: string) {
  cityCode.value = ""
  districtCode.value = ""
  if (!code) return
  const city = cityOptions.value.find(
    (c) => c.code === code || c.children.some((d) => d.code === code),
  )
  if (city) {
    cityCode.value = city.code
    if (code !== city.code) districtCode.value = code
  } else {
    // 树未含该码（权限外），退化为只读展示
    cityCode.value = code
  }
}

async function load() {
  try {
    flatRegions.value = await listRegions()
  } catch {
    /* 错误已由 http 拦截器提示 */
  }
  try {
    regionTree.value = await api.get<RegionNode[]>("/regions/tree")
  } catch {
    /* 错误已由 http 拦截器提示 */
    return
  }
  // 市管自动锁定本市（required-district 模式下城市下拉只有本市一项，提前选中更省一次点击）
  if (props.mode === "required-district" && cityOptions.value.length === 1 && !cityCode.value) {
    cityCode.value = cityOptions.value[0].code
    emitValue()
  }
  if (props.value) fill(props.value)
}

onMounted(load)

// 外部值变化时同步回填（编辑回填、重置等）
watch(
  () => props.value,
  (v) => {
    if (v !== resolved()) fill(v)
  },
)

defineExpose({ reload: load, ownRegionName })
</script>

<template>
  <!-- 区县管理员：只读显示本辖区 -->
  <input v-if="readonlyOwn || readonlyCompact" class="zp-input" :value="ownRegionName" disabled />

  <!-- 省/市管理员：地市 + 区县两级 -->
  <div v-else class="zp-flex" style="gap: 8px">
    <select
      class="zp-select"
      :value="cityCode"
      :aria-label="cityAriaLabel"
      :disabled="disabled"
      style="flex: 1"
      @change="cityCode = ($event.target as HTMLSelectElement).value; onCityChange()"
    >
      <option value="">{{ cityPlaceholder }}</option>
      <option v-for="c in cityOptions" :key="c.code" :value="c.code">{{ c.name }}</option>
    </select>
    <select
      v-if="showDistrict"
      class="zp-select"
      :value="districtCode"
      :aria-label="districtAriaLabel"
      :disabled="disabled || !cityCode"
      style="flex: 1"
      @change="districtCode = ($event.target as HTMLSelectElement).value; onDistrictChange()"
    >
      <option value="">{{ districtPlaceholder }}</option>
      <option v-for="d in districtOptions" :key="d.code" :value="d.code">{{ d.name }}</option>
    </select>
  </div>
</template>

<style scoped>
/* 筛选栏全局 .zp-filter .zp-select 有 min-width:150px，会把本组件两个级联下拉
  （flex:1 分宽）撑出定宽容器横向溢出，压到相邻筛选项；级联对豁免该最小宽 */
select.zp-select {
  min-width: 0;
}
</style>
