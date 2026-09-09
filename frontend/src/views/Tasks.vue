<template>
  <div class="tasks-page">
    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <span class="card-title">监控任务列表</span>
          <el-button v-if="userStore.isOperator" type="primary" @click="showAddDialog">
            <el-icon><Plus /></el-icon>
            添加任务
          </el-button>
        </div>
      </template>

      <!-- 筛选和搜索 -->
      <el-row :gutter="16" style="margin-bottom: 16px">
        <el-col :xs="24" :sm="12" :md="6" :lg="5">
          <el-select v-model="filters.platform" placeholder="平台" clearable @change="loadTasks">
            <el-option label="天猫" value="tmall" />
            <el-option label="淘宝" value="taobao" />
          </el-select>
        </el-col>
        <el-col :xs="24" :sm="12" :md="6" :lg="5">
          <el-select v-model="filters.status" placeholder="状态" clearable @change="loadTasks">
            <el-option label="运行中" value="active" />
            <el-option label="已暂停" value="paused" />
            <el-option label="异常" value="error" />
            <el-option label="有异常(含错误)" value="has_error" />
          </el-select>
        </el-col>
        <el-col :xs="24" :sm="16" :md="8" :lg="8">
          <el-input
            v-model="filters.search"
            placeholder="搜索商品名称/店铺名称..."
            clearable
            :prefix-icon="Search"
            @input="debounceSearch"
          />
        </el-col>
        <el-col :xs="24" :sm="8" :md="4" :lg="3">
          <el-button @click="loadTasks">
            <el-icon><Refresh /></el-icon>
            刷新
          </el-button>
        </el-col>
      </el-row>

      <!-- 任务表格 -->
      <div class="tasks-table-wrap">
        <el-table
          v-loading="loading"
          :data="tasks"
          style="width: 100%"
          empty-text="暂无监控任务，点击右上角「添加任务」开始"
          @row-click="goDetail"
          :row-class-name="() => 'clickable-row'"
        >
        <el-table-column prop="product_title" label="商品" min-width="200" show-overflow-tooltip>
          <template #default="{ row }">
            <div class="product-cell">
              <span class="product-title">{{ taskDisplayTitle(row) }}</span>
              <span class="product-shop">{{ row.shop_name || '' }}</span>
              <span v-if="row.note" class="product-note">{{ row.note }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="platform" label="平台" width="80" align="center">
          <template #default="{ row }">
            <el-tag :type="row.platform === 'tmall' ? 'danger' : 'warning'" size="small" effect="plain">
              {{ platformLabel(row.platform) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="110" align="center">
          <template #default="{ row }">
            <el-tooltip
              v-if="row.last_error"
              :content="row.last_error"
              placement="top"
              :show-after="200"
              effect="dark"
              :popper-options="{ modifiers: [{ name: 'computeStyles', options: { adaptive: false } }] }"
            >
              <div class="status-cell-error">
                <el-tag :type="taskStatusInfo(row.status).type" size="small">
                  {{ taskStatusInfo(row.status).label }}
                </el-tag>
                <el-icon class="status-warn-icon" color="#f56c6c" :size="14"><WarningFilled /></el-icon>
              </div>
            </el-tooltip>
            <el-tag v-else :type="taskStatusInfo(row.status).type" size="small">
              {{ taskStatusInfo(row.status).label }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="frequency_minutes" label="采集频率" width="100" align="center">
          <template #default="{ row }">
            <span class="text-muted">{{ formatFrequency(row.frequency_minutes) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="last_check_at" label="最后采集" width="150">
          <template #default="{ row }">
            <span class="text-muted">{{ formatDateTime(row.last_check_at) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="next_check_at" label="下次采集" width="150">
          <template #default="{ row }">
            <span class="text-muted">{{ formatDateTime(row.next_check_at) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="280" fixed="right">
          <template #default="{ row }">
            <el-button size="small" text type="primary" @click.stop="goDetail(row)">详情</el-button>
            <template v-if="userStore.isOperator">
              <el-tooltip content="重新获取商品标题和SKU信息" placement="top">
                <el-button
                  v-if="isPendingParseTask(row)"
                  size="small"
                  text
                  type="primary"
                  :loading="reparsingTaskId === row.id"
                  @click.stop="reparseTask(row)"
                >
                  重新解析
                </el-button>
              </el-tooltip>
              <el-button
                size="small"
                text
                :type="row.status === 'active' ? 'warning' : 'success'"
                @click.stop="toggleStatus(row)"
              >
                {{ row.status === 'active' ? '暂停' : '恢复' }}
              </el-button>
              <el-button size="small" text type="primary" @click.stop="runNow(row)" :disabled="row.status !== 'active'">
                立即采集
              </el-button>
            </template>
            <el-button v-if="userStore.isAdmin" size="small" text type="danger" @click.stop="handleDelete(row)">删除</el-button>
          </template>
        </el-table-column>
        </el-table>
      </div>

      <!-- 分页 -->
      <div class="table-footer">
        <span class="text-muted" v-if="total > 0">共 {{ total }} 个任务</span>
        <el-pagination
          v-if="total > pageSize"
          v-model:current-page="currentPage"
          :page-size="pageSize"
          :total="total"
          layout="total, prev, pager, next"
          @current-change="loadTasks"
        />
      </div>
    </el-card>

    <!-- 添加任务对话框 -->
    <el-dialog v-model="addDialogVisible" title="添加监控任务" width="560px" destroy-on-close append-to-body>
      <el-form :model="addForm" label-width="100px" :rules="addRules">
        <el-form-item label="商品链接" prop="url">
          <el-input
            v-model="addForm.url"
            placeholder="粘贴天猫/淘宝商品链接"
            type="textarea"
            :rows="2"
          />
          <div class="text-muted" style="margin-top: 6px">仅支持 `http(s)` 的天猫/淘宝商品链接</div>
        </el-form-item>

        <el-alert
          v-if="parsing"
          type="info"
          :closable="false"
          show-icon
          style="margin-bottom: 12px"
        >
          <template #title>
            正在解析商品与SKU（{{ parsingStage }}，已用时 {{ parsingElapsed }} 秒）
          </template>
        </el-alert>

        <!-- 解析结果 -->
        <div v-if="parseResult" class="parse-result">
          <el-alert type="success" :closable="false" show-icon>
            <template #title>
              <div>
                <strong>{{ parseResult.product_title }}</strong>
                <el-tag size="small" style="margin-left: 8px">{{ platformLabel(parseResult.platform) }}</el-tag>
              </div>
            </template>
          </el-alert>
          <div class="sku-list" v-if="parsedSkuConfigs.length > 0">
            <div class="sku-list-header">
              <span>SKU配置（{{ parsedSkuConfigs.length }}个）</span>
              <span class="text-muted">已选 {{ selectedSkuCount }} 个</span>
            </div>
            <div class="sku-actions">
              <el-button size="small" @click="selectAllSkus">全选</el-button>
              <el-button size="small" @click="invertSkuSelection">反选</el-button>
              <el-input-number
                v-model="batchBasePrice"
                :min="0"
                :precision="2"
                :step="1"
                size="small"
                controls-position="right"
                placeholder="批量基准价"
              />
              <el-button size="small" type="primary" plain @click="applyBatchBasePrice">应用到选中</el-button>
              <el-input
                v-model="batchNote"
                size="small"
                placeholder="批量备注"
                clearable
                style="width: 220px"
              />
              <el-button size="small" type="primary" plain @click="applyBatchNote">备注应用到选中</el-button>
              <el-button size="small" @click="clearBatchNote">清空选中备注</el-button>
            </div>
            <div class="sku-item-config sku-header">
              <span></span>
              <span>SKU名称</span>
              <span>到手价</span>
              <span>基准价</span>
              <span></span>
            </div>
            <div v-for="(sku, i) in parsedSkuConfigs" :key="i" class="sku-item sku-item-config">
              <el-checkbox v-model="sku.is_monitored" />
              <span class="sku-name">{{ sku.name }}</span>
              <span class="sku-price">{{ sku.price > 0 ? `¥${sku.price.toFixed(2)}` : '待采集' }}</span>
              <el-input-number
                v-model="sku.base_price"
                :min="0"
                :precision="2"
                :step="1"
                size="small"
                controls-position="right"
                placeholder="基准价"
              />
              <el-tag
                v-if="sku.note_conflict"
                size="small"
                type="warning"
                effect="plain"
              >
                记忆冲突
              </el-tag>
              <div class="sku-note-row">
                <el-input
                  v-model="sku.note"
                  size="small"
                  placeholder="输入备注（自由文本，长期记忆到该SKU）"
                  clearable
                />
              </div>
            </div>
          </div>
        </div>

        <el-form-item label="采集频率">
          <el-select v-model="addForm.frequency_minutes" style="width: 100%">
            <el-option
              v-for="opt in addFrequencyOptions"
              :key="opt.value"
              :label="opt.label"
              :value="opt.value"
            />
          </el-select>
        </el-form-item>

        <el-form-item v-if="userStore.isAdmin" label="调试模式">
          <el-switch v-model="debugModeEnabled" />
          <span class="text-muted debug-tip">开启后可设置30分钟以下采集频率</span>
        </el-form-item>

        <el-form-item label="开启录屏">
          <el-switch v-model="addForm.recording_enabled" />
        </el-form-item>

        <el-form-item label="备注">
          <el-input v-model="addForm.note" placeholder="可选备注" />
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="addDialogVisible = false">取消</el-button>
        <el-button v-if="!parseResult" type="primary" @click="parseUrl" :loading="parsing">
          解析链接
        </el-button>
        <el-button v-else type="primary" @click="submitAdd" :loading="submitting" :disabled="selectedSkuCount <= 0">
          创建任务
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted, onBeforeUnmount, computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { Search, WarningFilled } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { FormRules } from 'element-plus'
import {
  tasksApi,
  formatDateTime,
  platformLabel,
  taskStatusInfo,
} from '@/api'
import type { TaskResponse, ParseURLResponse } from '@/api'
import { useUserStore } from '@/stores/user'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()

// 状态
const loading = ref(false)
const tasks = ref<TaskResponse[]>([])
const total = ref(0)
const currentPage = ref(1)
const pageSize = 20
const filters = reactive({
  platform: (route.query.platform as string) || '',
  status: (route.query.status as string) || '',
  search: (route.query.search as string) || '',
})
const reparsingTaskId = ref<number | null>(null)

// 添加任务
const addDialogVisible = ref(false)
const parsing = ref(false)
const parsingElapsed = ref(0)
const parsingStage = ref('准备中')
let parsingTimer: ReturnType<typeof setInterval> | null = null
const submitting = ref(false)
const parseResult = ref<ParseURLResponse | null>(null)
interface ParsedSkuConfig {
  name: string
  price: number
  sku_id: string | null
  is_monitored: boolean
  base_price: number | null
  note: string
  note_conflict?: boolean
  note_candidates?: string[]
}
const parsedSkuConfigs = ref<ParsedSkuConfig[]>([])
const batchBasePrice = ref<number | null>(null)
const batchNote = ref('')
const selectedSkuCount = computed(() => parsedSkuConfigs.value.filter(s => s.is_monitored).length)
const debugModeEnabled = ref(false)

interface FrequencyOption {
  label: string
  value: number
}
const normalFrequencyOptions: FrequencyOption[] = [
  { label: '每30分钟', value: 30 },
  { label: '每1小时', value: 60 },
  { label: '每2小时', value: 120 },
  { label: '每4小时', value: 240 },
  { label: '每8小时', value: 480 },
  { label: '每天', value: 1440 },
]
const debugFrequencyOptions: FrequencyOption[] = [
  { label: '每1分钟', value: 1 },
  { label: '每5分钟', value: 5 },
  { label: '每10分钟', value: 10 },
  { label: '每15分钟', value: 15 },
]
const canUseDebugFrequency = computed(() => userStore.isAdmin && debugModeEnabled.value)
const addFrequencyOptions = computed(() =>
  canUseDebugFrequency.value
    ? [...debugFrequencyOptions, ...normalFrequencyOptions]
    : normalFrequencyOptions
)
const addForm = reactive({
  url: '',
  frequency_minutes: 120,
  recording_enabled: false,
  note: '',
})
const addRules: FormRules = {
  url: [{ required: true, message: '请输入商品链接', trigger: 'blur' }],
}

// 加载任务列表
async function loadTasks() {
  loading.value = true
  try {
    const params: Record<string, string | number> = {
      page: currentPage.value,
      page_size: pageSize,
    }
    if (filters.platform) params.platform = filters.platform
    if (filters.status) params.status = filters.status
    if (filters.search) params.search = filters.search
    const res = await tasksApi.list(params as Record<string, string>)
    tasks.value = res.tasks
    total.value = res.total
  } catch (e) {
    console.error('Load tasks error:', e)
  } finally {
    loading.value = false
  }
}

// 防抖搜索
let searchTimer: ReturnType<typeof setTimeout> | null = null
function debounceSearch() {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    currentPage.value = 1
    loadTasks()
  }, 400)
}

// 显示添加对话框
function showAddDialog() {
  addForm.url = ''
  addForm.frequency_minutes = 120
  addForm.recording_enabled = false
  addForm.note = ''
  parseResult.value = null
  parsingElapsed.value = 0
  parsedSkuConfigs.value = []
  batchBasePrice.value = null
  batchNote.value = ''
  debugModeEnabled.value = false
  addDialogVisible.value = true
}

function normalizeAndValidateProductUrl(rawUrl: string): string | null {
  const url = rawUrl.trim()
  if (!url) {
    ElMessage.warning('请输入商品链接')
    return null
  }

  let parsed: URL
  try {
    parsed = new URL(url)
  } catch {
    ElMessage.warning('链接格式不正确，请粘贴完整商品链接')
    return null
  }

  if (!['http:', 'https:'].includes(parsed.protocol)) {
    ElMessage.warning('仅支持 http 或 https 链接')
    return null
  }

  const host = parsed.hostname.toLowerCase()
  const allowed = ['taobao.com', 'tmall.com', 'tb.cn']
  const ok = allowed.some((d) => host === d || host.endsWith(`.${d}`))
  if (!ok) {
    ElMessage.warning('仅支持天猫/淘宝商品链接')
    return null
  }

  return parsed.toString()
}

function startParsingProgress() {
  parsingElapsed.value = 0
  parsingStage.value = '加载页面'
  if (parsingTimer) clearInterval(parsingTimer)
  parsingTimer = setInterval(() => {
    parsingElapsed.value += 1
    if (parsingElapsed.value >= 20) {
      parsingStage.value = '提取SKU结构'
    }
    if (parsingElapsed.value >= 40) {
      parsingStage.value = '计算SKU价格'
    }
  }, 1000)
}

function stopParsingProgress() {
  if (parsingTimer) {
    clearInterval(parsingTimer)
    parsingTimer = null
  }
}

// 解析链接
async function parseUrl() {
  const safeUrl = normalizeAndValidateProductUrl(addForm.url)
  if (!safeUrl) {
    return
  }
  addForm.url = safeUrl
  ElMessage.info('开始解析，复杂SKU商品可能需要30-120秒，请勿关闭弹窗')
  parsing.value = true
  startParsingProgress()
  try {
    const res = await tasksApi.parseUrl(safeUrl)
    parseResult.value = res
    parsedSkuConfigs.value = (res.skus || []).map((sku) => ({
      name: sku.name,
      price: Number(sku.price || 0),
      sku_id: sku.sku_id,
      is_monitored: true,
      // 参考自动填充：默认等于当前到手价
      base_price: Number(sku.price || 0) > 0 ? Number(sku.price) : null,
      note: (sku.note || '').trim(),
      note_conflict: !!sku.note_conflict,
      note_candidates: sku.note_candidates || [],
    }))
    if (
      res.product_title === '未获取到标题' &&
      res.skus.length === 1 &&
      res.skus[0]?.name === '默认SKU' &&
      Number(res.skus[0]?.price || 0) <= 0
    ) {
      ElMessage.warning('链接可访问，但未解析到有效SKU价格，请先检查浏览器登录态后重试')
    }
  } catch (e) {
    console.error('Parse URL error:', e)
    const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || ''
    if (msg.includes('解析超时')) {
      ElMessage.warning('解析超时：请先到「浏览器管理」重新登录并保存Cookie后重试')
    }
  } finally {
    parsing.value = false
    stopParsingProgress()
  }
}

function selectAllSkus() {
  parsedSkuConfigs.value.forEach((sku) => {
    sku.is_monitored = true
  })
}

function invertSkuSelection() {
  parsedSkuConfigs.value.forEach((sku) => {
    sku.is_monitored = !sku.is_monitored
  })
}

function applyBatchBasePrice() {
  if (batchBasePrice.value === null || Number(batchBasePrice.value) <= 0) {
    ElMessage.warning('请输入有效的批量基准价')
    return
  }
  parsedSkuConfigs.value.forEach((sku) => {
    if (sku.is_monitored) sku.base_price = Number(batchBasePrice.value)
  })
}

function applyBatchNote() {
  const note = batchNote.value.trim()
  if (!note) {
    ElMessage.warning('请输入批量备注内容')
    return
  }
  parsedSkuConfigs.value.forEach((sku) => {
    if (sku.is_monitored) sku.note = note
  })
}

function clearBatchNote() {
  parsedSkuConfigs.value.forEach((sku) => {
    if (sku.is_monitored) sku.note = ''
  })
}

// 提交创建
async function submitAdd() {
  const safeUrl = normalizeAndValidateProductUrl(addForm.url)
  if (!safeUrl) {
    return
  }
  addForm.url = safeUrl

  const selected = parsedSkuConfigs.value.filter((sku) => sku.is_monitored)
  if (selected.length === 0) {
    ElMessage.warning('请至少选择1个SKU进行监控')
    return
  }
  const invalidSku = selected.find((sku) => !sku.base_price || Number(sku.base_price) <= 0)
  if (invalidSku) {
    ElMessage.warning('已选SKU存在未设置基准价，请先补全')
    return
  }

  submitting.value = true
  try {
    if (addForm.frequency_minutes < 30 && !canUseDebugFrequency.value) {
      ElMessage.warning('仅超级管理员开启调试模式后可设置30分钟以下采集频率')
      return
    }

    const title =
      parseResult.value?.product_title && parseResult.value.product_title !== '未获取到标题'
        ? parseResult.value.product_title
        : undefined
    const shop =
      parseResult.value?.shop_name && parseResult.value.shop_name !== '未获取到店铺'
        ? parseResult.value.shop_name
        : undefined

    const task = await tasksApi.create({
      url: safeUrl,
      frequency_minutes: addForm.frequency_minutes,
      recording_enabled: addForm.recording_enabled,
      note: addForm.note || undefined,
      product_title: title,
      shop_name: shop,
    })

    // 创建任务后立即配置SKU监控与基准价
    await tasksApi.configureSkus(
      task.id,
      selected.map((sku) => ({
        sku_name: sku.name,
        sku_id_external: sku.sku_id || undefined,
        base_price: Number(sku.base_price),
        is_monitored: true,
        note: sku.note || undefined,
      }))
    )

    ElMessage.success('任务创建成功')
    addDialogVisible.value = false
    loadTasks()
  } catch (e) {
    console.error('Create task error:', e)
  } finally {
    submitting.value = false
  }
}

// 跳转详情
function goDetail(row: TaskResponse) {
  router.push(`/tasks/${row.id}`)
}

function isPendingParseTask(row: TaskResponse): boolean {
  return !(row.product_title || '').trim()
}

function taskDisplayTitle(row: TaskResponse): string {
  if (row.product_title) return row.product_title
  try {
    const u = new URL(row.url)
    const itemId = u.searchParams.get('id')
    if (itemId) {
      return row.shop_name ? `${row.shop_name} #${itemId}` : `商品 #${itemId}`
    }
  } catch { /* ignore */ }
  return '待解析...'
}

// 切换状态
async function toggleStatus(row: TaskResponse) {
  const newStatus = row.status === 'active' ? 'paused' : 'active'
  const label = newStatus === 'active' ? '恢复' : '暂停'
  try {
    await tasksApi.update(row.id, { status: newStatus })
    ElMessage.success(`任务已${label}`)
    loadTasks()
  } catch (e) {
    console.error('Toggle status error:', e)
  }
}

// 立即采集
async function runNow(row: TaskResponse) {
  try {
    await tasksApi.runNow(row.id)
    ElMessage.success('采集任务已启动')
  } catch (e) {
    console.error('Run now error:', e)
  }
}

async function reparseTask(row: TaskResponse) {
  reparsingTaskId.value = row.id
  try {
    const parsed = await tasksApi.reparse(row.id)
    ElMessage.success(`重解析完成：${parsed.skus.length} 个SKU`)
    await loadTasks()
  } catch (e) {
    console.error('Reparse task error:', e)
  } finally {
    reparsingTaskId.value = null
  }
}

// 删除任务
async function handleDelete(row: TaskResponse) {
  try {
    await ElMessageBox.confirm(
      `确定删除任务「${row.product_title || row.url}」？此操作不可恢复。`,
      '删除确认',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
    await tasksApi.delete(row.id)
    ElMessage.success('任务已删除')
    loadTasks()
  } catch (e) {
    // 用户取消
  }
}

// 格式化频率
function formatFrequency(minutes: number): string {
  if (minutes < 60) return `每${minutes}分钟`
  if (minutes < 1440) return `每${minutes / 60}小时`
  return `每${minutes / 1440}天`
}

let listRefreshTimer: ReturnType<typeof setInterval> | null = null

onMounted(() => {
  loadTasks()
  listRefreshTimer = setInterval(() => loadTasks(), 30000)
})

onBeforeUnmount(() => {
  if (listRefreshTimer) {
    clearInterval(listRefreshTimer)
    listRefreshTimer = null
  }
})
</script>

<style scoped>
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.card-title {
  font-size: 15px;
  font-weight: 600;
  color: #303133;
}

.product-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.product-title {
  font-size: 13px;
  color: #303133;
}

.product-shop {
  font-size: 12px;
  color: #909399;
}

.product-note {
  font-size: 12px;
  color: #e6a23c;
  font-style: italic;
}

.status-cell-error {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  cursor: help;
}

.status-warn-icon {
  animation: warn-pulse 2s ease-in-out infinite;
}

@keyframes warn-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}

.text-muted {
  color: #909399;
  font-size: 12px;
}

.debug-tip {
  margin-left: 10px;
}

.table-footer {
  margin-top: 12px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

:deep(.clickable-row) {
  cursor: pointer;
}

:deep(.clickable-row:hover) {
  background-color: #f5f7fa !important;
}

/* 添加任务对话框 */
.parse-result {
  margin: 12px 0 16px;
  padding: 0 0 0 100px;
}

.sku-list {
  margin-top: 12px;
  border: 1px solid #ebeef5;
  border-radius: 6px;
  overflow: hidden;
}

.sku-list-header {
  padding: 8px 12px;
  background: #f5f7fa;
  font-size: 13px;
  font-weight: 500;
  color: #606266;
}

.sku-item {
  display: flex;
  justify-content: space-between;
  padding: 8px 12px;
  font-size: 13px;
  border-top: 1px solid #ebeef5;
}

.sku-price {
  color: #f56c6c;
  font-weight: 500;
}

.tasks-table-wrap {
  width: 100%;
  overflow-x: auto;
}

.sku-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  border-top: 1px solid #ebeef5;
  border-bottom: 1px solid #ebeef5;
  flex-wrap: wrap;
}

.sku-item-config {
  display: grid;
  grid-template-columns: 22px 1fr 70px 100px auto;
  align-items: center;
  gap: 4px 6px;
  padding-bottom: 6px;
  border-bottom: 1px solid #f2f3f5;
}

.sku-item-config .sku-note-row {
  grid-column: 2 / -1;
}

.sku-header {
  font-size: 12px;
  color: #909399;
  font-weight: 500;
  padding: 4px 0;
  border-bottom: 1px solid #ebeef5;
}

.sku-header .sku-note-row {
  display: none;
}

.sku-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* BUG-2修复：对话框内容可滚动，防止底部按钮被截断 */
:deep(.el-dialog) {
  max-height: 85vh;
  display: flex;
  flex-direction: column;
}

:deep(.el-dialog__body) {
  max-height: 60vh;
  overflow-y: auto;
}

@media (max-width: 768px) {
  .sku-item-config {
    grid-template-columns: 22px 1fr;
    grid-auto-rows: auto;
  }

  .sku-item-config .sku-price {
    justify-self: start;
  }

  .sku-item-config :deep(.el-input) {
    grid-column: 1 / -1;
  }
}
</style>
