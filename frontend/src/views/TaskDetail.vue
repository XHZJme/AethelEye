<template>
  <div class="task-detail" v-loading="loading">
    <el-page-header @back="goBack" title="返回任务列表">
      <template #content>
        <div class="page-header-content" v-if="task">
          <span class="page-title">{{ displayTitle }}</span>
          <el-tag :type="taskStatusInfo(task.status).type" size="small" style="margin-left: 8px">
            {{ taskStatusInfo(task.status).label }}
          </el-tag>
          <el-tag :type="task.platform === 'tmall' ? 'danger' : 'warning'" size="small" effect="plain" style="margin-left: 4px">
            {{ platformLabel(task.platform) }}
          </el-tag>
        </div>
      </template>
      <template #extra v-if="task && userStore.isOperator">
        <el-button size="small" :loading="reparsing" @click="reparseTask">
          <el-icon><Refresh /></el-icon>
          重新解析
        </el-button>
        <el-button type="primary" size="small" @click="runNow" :disabled="task.status !== 'active'">
          <el-icon><VideoPlay /></el-icon>
          立即采集
        </el-button>
        <el-button size="small" @click="editTask">
          <el-icon><Edit /></el-icon>
          编辑
        </el-button>
      </template>
    </el-page-header>

    <template v-if="task">
      <!-- 任务信息卡片 -->
      <el-row :gutter="16" style="margin-top: 16px">
        <el-col :span="24">
          <el-card shadow="hover">
            <el-descriptions :column="descColumn" size="small" border>
              <el-descriptions-item label="商品链接">
                <el-tooltip :content="task.url" placement="top" :show-after="300" :disabled="!task.url || task.url.length <= 60">
                  <a v-if="task.url && (task.url.startsWith('http://') || task.url.startsWith('https://'))" :href="task.url" target="_blank" rel="noopener noreferrer" class="link-text link-truncate">{{ task.url }}</a>
                  <span v-else class="link-text link-truncate">{{ task.url }}</span>
                </el-tooltip>
              </el-descriptions-item>
              <el-descriptions-item label="店铺">{{ task.shop_name || '-' }}</el-descriptions-item>
              <el-descriptions-item label="采集频率">{{ formatFrequency(task.frequency_minutes) }}</el-descriptions-item>
              <el-descriptions-item label="录屏">
                <el-tag :type="task.recording_enabled ? 'success' : 'info'" size="small">
                  {{ task.recording_enabled ? '已开启' : '未开启' }}
                </el-tag>
              </el-descriptions-item>
              <el-descriptions-item label="最后采集">{{ formatDateTime(task.last_check_at) }}</el-descriptions-item>
              <el-descriptions-item label="下次采集">{{ formatDateTime(task.next_check_at) }}</el-descriptions-item>
              <el-descriptions-item label="创建时间">{{ formatDateTime(task.created_at) }}</el-descriptions-item>
              <el-descriptions-item label="备注" v-if="task.note">
                <span style="color: #e6a23c">{{ task.note }}</span>
              </el-descriptions-item>
            </el-descriptions>
          </el-card>
        </el-col>
      </el-row>

      <!-- 采集错误提示（UX-04） -->
      <el-alert
        v-if="task.last_error"
        :title="friendlyError"
        type="warning"
        show-icon
        :closable="false"
        style="margin-top: 12px"
      >
        <template #default>
          <div class="text-muted" style="font-size: 12px; margin-top: 4px">{{ task.last_error }}</div>
        </template>
      </el-alert>

      <!-- SKU价格表 + 趋势图 -->
      <el-row :gutter="16" class="content-row" style="margin-top: 16px">
        <el-col :xs="24" :sm="24" :md="24" :lg="14" :xl="16">
          <el-card shadow="hover">
            <template #header>
              <div class="card-header">
                <span class="card-title">SKU价格监控</span>
                <span class="text-muted">共 {{ skus.length }} 个SKU</span>
              </div>
            </template>
            <el-table ref="skuTableRef" :data="skus" size="small" highlight-current-row @current-change="selectSku" empty-text="暂无SKU数据" max-height="400">
              <el-table-column prop="sku_name" label="SKU名称" min-width="180" show-overflow-tooltip />
              <el-table-column prop="note" label="备注" width="80" show-overflow-tooltip>
                <template #default="{ row }">
                  <el-input
                    v-if="skuEditMode"
                    v-model="row._editNote"
                    type="textarea"
                    :autosize="{ minRows: 1, maxRows: 4 }"
                    size="small"
                    placeholder="自由输入备注信息"
                    resize="none"
                  />
                  <span v-else class="note-cell">{{ row.note || '-' }}</span>
                </template>
              </el-table-column>
              <el-table-column prop="base_price" label="基准价" min-width="90" align="right">
                <template #default="{ row }">
                  <el-input-number
                    v-if="skuEditMode"
                    v-model="row._editBasePrice"
                    :min="0"
                    :precision="2"
                    :step="1"
                    size="small"
                    :controls="false"
                    style="width: 90px"
                    placeholder="基准价"
                  />
                  <span v-else>{{ formatPrice(row.base_price) }}</span>
                </template>
              </el-table-column>
              <el-table-column prop="current_price" label="到手价" min-width="90" align="right">
                <template #default="{ row }">
                  <span v-if="row.current_price != null" :class="priceClass(row)">{{ formatPrice(row.current_price) }}</span>
                  <span v-else class="text-muted">暂无数据</span>
                </template>
              </el-table-column>
              <el-table-column label="价差" min-width="70" align="right">
                <template #default="{ row }">
                  <span v-if="row.base_price && row.current_price" :class="priceClass(row)">
                    {{ priceDiff(row) }}
                  </span>
                  <span v-else class="text-muted">暂无数据</span>
                </template>
              </el-table-column>
              <el-table-column prop="status" label="状态" min-width="65" align="center">
                <template #default="{ row }">
                  <el-tag :type="row.status === 'alert' ? 'danger' : 'success'" size="small">
                    {{ row.status === 'alert' ? '异动' : '正常' }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="is_monitored" label="监控" min-width="55" align="center">
                <template #default="{ row }">
                  <el-switch
                    v-if="skuEditMode"
                    v-model="row._editMonitored"
                    size="small"
                  />
                  <el-icon v-else :color="row.is_monitored ? '#67c23a' : '#c0c4cc'">
                    <component :is="row.is_monitored ? 'CircleCheck' : 'CircleClose'" />
                  </el-icon>
                </template>
              </el-table-column>
            </el-table>
            <div style="margin-top: 12px; text-align: right">
              <el-button v-if="!skuEditMode && userStore.isOperator" size="small" @click="enterSkuEditMode">
                <el-icon><Edit /></el-icon>
                编辑SKU
              </el-button>
              <template v-else>
                <el-button size="small" @click="cancelSkuEditMode">取消</el-button>
                <el-button type="primary" size="small" :loading="skuSaving" @click="saveSkuEdits">保存修改</el-button>
              </template>
            </div>
          </el-card>
        </el-col>

        <!-- 趋势图 -->
        <el-col :xs="24" :sm="24" :md="24" :lg="10" :xl="8">
          <el-card shadow="hover">
            <template #header>
              <div class="card-header">
                <span class="card-title">
                  {{ selectedSku ? `${selectedSku.sku_name} 价格趋势` : '价格趋势' }}
                </span>
                <el-select v-model="trendDays" size="small" style="width: 110px" @change="loadTrend">
                  <el-option label="近7天" :value="7" />
                  <el-option label="近14天" :value="14" />
                  <el-option label="近30天" :value="30" />
                </el-select>
              </div>
            </template>
            <div ref="trendChartRef" class="chart-container">
              <el-empty v-if="!selectedSku" description="点击左侧SKU查看趋势" :image-size="80" />
            </div>
          </el-card>
        </el-col>
      </el-row>

      <!-- 录屏列表 -->
      <el-row :gutter="16" style="margin-top: 16px" v-if="task.recording_enabled">
        <el-col :span="24">
          <el-card shadow="hover">
            <template #header>
              <div class="card-header">
                <span class="card-title">采集录屏</span>
                <el-button text type="primary" size="small" @click="loadRecordings">
                  <el-icon><Refresh /></el-icon>
                  刷新
                </el-button>
              </div>
            </template>
            <el-table :data="recordings" size="small" empty-text="暂无录屏（录屏仅在采集成功时保存）">
              <el-table-column prop="filename" label="文件名" min-width="200" />
              <el-table-column prop="created_at" label="录制时间" width="170" />
              <el-table-column prop="size_mb" label="大小" width="90" align="right">
                <template #default="{ row }">{{ row.size_mb }} MB</template>
              </el-table-column>
              <el-table-column label="操作" width="130">
                <template #default="{ row }">
                  <el-button size="small" text type="primary" @click="playRecording(row.filename)">播放</el-button>
                  <el-button size="small" text type="danger" @click="deleteRecording(row.filename)">删除</el-button>
                </template>
              </el-table-column>
            </el-table>
          </el-card>
        </el-col>
      </el-row>

      <!-- 异动记录（降序、附截图、滚动） -->
      <el-row :gutter="16" style="margin-top: 16px">
        <el-col :span="24">
          <el-card shadow="hover">
            <template #header>
              <div class="card-header">
                <span class="card-title">异动记录</span>
                <span class="text-muted">{{ taskAlerts.length }} 条异动</span>
              </div>
            </template>
            <div v-if="taskAlerts.length" class="alert-scroll-container">
              <div
                v-for="alert in taskAlerts"
                :key="alert.id"
                class="alert-record-item"
              >
                <div class="alert-record-main">
                  <div class="alert-record-info">
                    <el-tag type="danger" size="small" effect="plain">
                      {{ alert.alert_type === 'price_drop' ? '降价' : alert.alert_type === 'price_rise' ? '涨价' : alert.alert_type }}
                    </el-tag>
                    <span class="alert-sku-name">{{ alert.sku_name || `SKU#${alert.sku_id}` }}</span>
                    <span class="alert-time text-muted">{{ formatDateTime(alert.detected_at) }}</span>
                  </div>
                  <div class="alert-price-diff">
                    <span class="diff-old">¥{{ alert.base_price.toFixed(2) }}</span>
                    <span class="diff-arrow"> → </span>
                    <span class="diff-new">¥{{ alert.alert_price.toFixed(2) }}</span>
                    <span :class="['diff-pct', alert.price_diff < 0 ? 'diff-down' : 'diff-up']">
                      {{ alert.price_diff < 0 ? '' : '+' }}{{ alert.price_diff.toFixed(2) }}
                      ({{ (alert.price_diff_pct * 100).toFixed(1) }}%)
                    </span>
                  </div>
                </div>
                <div v-if="alert.screenshot_path" class="alert-screenshot">
                  <el-image
                    :src="alertsApi.getScreenshotUrl(alert.screenshot_path)"
                    :preview-src-list="[alertsApi.getScreenshotUrl(alert.screenshot_path)]"
                    fit="cover"
                    class="screenshot-thumb"
                    :z-index="3000"
                  >
                    <template #error>
                      <div class="screenshot-error">截图不可用</div>
                    </template>
                  </el-image>
                </div>
              </div>
            </div>
            <el-empty v-else description="暂无异动记录" :image-size="80" />
          </el-card>
        </el-col>
      </el-row>

      <el-row :gutter="16" style="margin-top: 16px">
        <el-col :span="24">
          <el-card shadow="hover">
            <template #header>
              <div class="card-header">
                <span class="card-title">SKU变更节点</span>
                <span class="text-muted">{{ filteredChangeEvents.length }} 条变更{{ collapsedCreatedCount > 0 ? `（已折叠 ${collapsedCreatedCount} 条初始创建）` : '' }}</span>
                <el-button v-if="collapsedCreatedCount > 0" text size="small" @click="showCreatedEvents = !showCreatedEvents">
                  {{ showCreatedEvents ? '折叠初始创建' : '展开全部' }}
                </el-button>
              </div>
            </template>
            <el-timeline v-if="filteredChangeEvents.length">
              <el-timeline-item
                v-for="event in filteredChangeEvents"
                :key="event.id"
                :timestamp="formatDateTime(event.changed_at)"
                placement="top"
                :type="event.change_type === 'created' ? 'primary' : event.change_type === 'price_update' ? 'warning' : 'info'"
              >
                <div class="event-title">{{ event.sku_name }}</div>
                <div class="text-muted">
                  {{ changeTypeLabel(event.change_type) }}
                  <span style="margin-left: 8px">来源：{{ event.source === 'collector' ? '采集' : '手动' }}</span>
                </div>
                <div v-if="event.change_type !== 'created'" class="change-diff">
                  <template v-for="field in event.changed_fields" :key="field">
                    <span class="diff-item">
                      <span class="diff-label">{{ fieldLabel(field) }}：</span>
                      <span class="diff-old">{{ formatChangeValue(field, event.old_values[field]) }}</span>
                      <span class="diff-arrow"> → </span>
                      <span class="diff-new">{{ formatChangeValue(field, event.new_values[field]) }}</span>
                    </span>
                  </template>
                </div>
                <div v-else class="change-diff">
                  <span class="diff-item" v-if="event.new_values.current_price">
                    <span class="diff-label">到手价：</span>
                    <span class="diff-new">¥{{ Number(event.new_values.current_price).toFixed(2) }}</span>
                  </span>
                </div>
              </el-timeline-item>
            </el-timeline>
            <el-empty v-else description="暂无SKU变更记录" :image-size="80" />
          </el-card>
        </el-col>
      </el-row>
    </template>

    <!-- 编辑对话框 -->
    <el-dialog v-model="editDialogVisible" title="编辑任务" width="480px" append-to-body>
      <el-form :model="editForm" label-width="100px">
        <el-form-item label="采集频率">
          <el-select v-model="editForm.frequency_minutes" style="width: 100%">
            <el-option
              v-for="opt in editFrequencyOptions"
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
          <el-switch v-model="editForm.recording_enabled" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="editForm.note" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitEdit" :loading="editSubmitting">保存</el-button>
      </template>
    </el-dialog>

    <!-- 录屏播放 -->
    <el-dialog v-model="playerVisible" title="录屏回放" width="800px" destroy-on-close append-to-body>
      <video v-if="playerUrl" :src="playerUrl" controls autoplay style="width: 100%; max-height: 500px; border-radius: 4px;"></video>
    </el-dialog>

  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted, onBeforeUnmount, computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  tasksApi,
  trendsApi,
  recordingsApi,
  alertsApi,
  formatDateTime,
  formatPrice,
  platformLabel,
  taskStatusInfo,
} from '@/api'
import type { TaskResponse, SKUResponse, RecordingFile, TrendResponse, SKUChangeEvent, TaskAlertItem } from '@/api'
import * as echarts from 'echarts'
import { useUserStore } from '@/stores/user'

const router = useRouter()
const route = useRoute()
const taskId = Number(route.params.id)
const userStore = useUserStore()

// 状态
const loading = ref(true)
const reparsing = ref(false)
const task = ref<TaskResponse | null>(null)
const skus = ref<SKUResponse[]>([])
const skuChangeEvents = ref<SKUChangeEvent[]>([])
const taskAlerts = ref<TaskAlertItem[]>([])
const selectedSku = ref<SKUResponse | null>(null)
const trendDays = ref(7)
const recordings = ref<RecordingFile[]>([])
const descColumn = ref(4)

// 图表
const trendChartRef = ref<HTMLElement>()
const skuTableRef = ref()
let trendChart: echarts.ECharts | null = null

// 编辑
const editDialogVisible = ref(false)
const editSubmitting = ref(false)
const editForm = reactive({
  frequency_minutes: 120,
  recording_enabled: false,
  note: '',
})
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
const editFrequencyOptions = computed(() => {
  const base = canUseDebugFrequency.value
    ? [...debugFrequencyOptions, ...normalFrequencyOptions]
    : [...normalFrequencyOptions]
  if (editForm.frequency_minutes < 30 && !base.some((item) => item.value === editForm.frequency_minutes)) {
    base.unshift({ label: `每${editForm.frequency_minutes}分钟（当前）`, value: editForm.frequency_minutes })
  }
  return base
})

// 显示标题（UX-02: fallback 到 item ID）
const displayTitle = computed(() => {
  if (task.value?.product_title) return task.value.product_title
  const url = task.value?.url || ''
  try {
    const u = new URL(url)
    const itemId = u.searchParams.get('id')
    if (itemId) {
      const shop = task.value?.shop_name
      return shop ? `${shop} #${itemId}` : `商品 #${itemId}`
    }
  } catch { /* ignore */ }
  return '待解析...'
})

// 错误信息通俗化（UX-04）
const friendlyError = computed(() => {
  const err = task.value?.last_error || ''
  if (err.includes('SKU价格') || err.includes('未提取到')) return '采集失败：无法提取价格信息，可能是页面结构变化或反爬限制'
  if (err.includes('登录') || err.includes('Cookie')) return '采集失败：登录状态可能已失效，请前往浏览器管理页重新登录'
  if (err.includes('超时') || err.includes('timeout')) return '采集失败：页面加载超时，请检查网络连接'
  if (err.includes('页面结构')) return '采集失败：商品页面结构发生变化，需要技术人员更新采集规则'
  if (err.includes('BrowserContext') || err.includes('browser has been closed')) return '采集失败：浏览器意外关闭，请前往浏览器管理页重新打开并登录'
  if (err.includes('net::ERR') || err.includes('Navigation')) return '采集失败：网络连接异常，请检查网络状态'
  return '采集失败：' + err.substring(0, 80)
})

// 播放器
const playerVisible = ref(false)
const playerUrl = ref('')
let autoRefreshTimer: ReturnType<typeof setInterval> | null = null

// 加载数据
async function loadData(options?: { silent?: boolean }) {
  const silent = !!options?.silent
  // 编辑模式下跳过自动刷新，避免覆盖用户正在编辑的数据
  if (silent && (editDialogVisible.value || skuEditMode.value)) return
  if (!silent) loading.value = true
  const previousSelectedSkuId = selectedSku.value?.id
  try {
    const res = await tasksApi.getDetail(taskId)
    task.value = res.task
    skus.value = res.skus
    skuChangeEvents.value = res.sku_change_events || []
    taskAlerts.value = res.alerts || []
    if (previousSelectedSkuId) {
      const found = skus.value.find((item) => item.id === previousSelectedSkuId) || null
      selectedSku.value = found
      if (found && skuTableRef.value?.setCurrentRow) {
        skuTableRef.value.setCurrentRow(found)
      }
    }
    if (res.task.recording_enabled) loadRecordings()
  } catch (e) {
    if (!silent) ElMessage.error('加载任务详情失败')
    console.error(e)
  } finally {
    if (!silent) loading.value = false
  }
}

async function reparseTask() {
  reparsing.value = true
  try {
    const parsed = await tasksApi.reparse(taskId)
    await loadData()
    ElMessage.success(`重解析完成：${parsed.skus.length} 个SKU，已同步任务信息`)
  } catch (e) {
    console.error(e)
  } finally {
    reparsing.value = false
  }
}

// 选中SKU
function selectSku(row: SKUResponse | null) {
  selectedSku.value = row
  if (row) loadTrend()
}

// 加载趋势
async function loadTrend() {
  if (!selectedSku.value) return
  try {
    const res: TrendResponse = await trendsApi.getSkuTrend(selectedSku.value.id, trendDays.value)
    renderTrendChart(res)
  } catch (e) {
    console.error('Load trend error:', e)
  }
}

// 渲染趋势图
function renderTrendChart(data: TrendResponse) {
  if (!trendChartRef.value) return
  if (!trendChart) {
    trendChart = echarts.init(trendChartRef.value)
  }
  const basePrice = data.base_price

  trendChart.setOption({
    tooltip: {
      trigger: 'axis',
      formatter(params: unknown) {
        const p = (params as Array<{ axisValue: string; value: number }>)[0]
        return `${p.axisValue}<br/>到手价: <b>¥${p.value.toFixed(2)}</b>${basePrice ? `<br/>基准价: ¥${basePrice.toFixed(2)}` : ''}`
      },
    },
    grid: { top: 30, right: 20, bottom: 30, left: 50 },
    xAxis: {
      type: 'category',
      data: data.points.map(p => p.collected_at || p.date),
      axisLabel: { fontSize: 10, color: '#909399', rotate: 30 },
    },
    yAxis: {
      type: 'value',
      axisLabel: { fontSize: 11, color: '#909399', formatter: '¥{value}' },
      splitLine: { lineStyle: { color: '#f0f2f5', type: 'dashed' } },
    },
    series: [
      {
        data: data.points.map(p => p.price),
        type: 'line',
        smooth: true,
        lineStyle: { color: '#409eff', width: 2 },
        itemStyle: { color: '#409eff' },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: 'rgba(64,158,255,0.2)' },
            { offset: 1, color: 'rgba(64,158,255,0.02)' },
          ]),
        },
        markLine: basePrice ? {
          silent: true,
          data: [{ yAxis: basePrice, name: '基准价' }],
          lineStyle: { color: '#e6a23c', type: 'dashed' },
          label: { formatter: '基准 ¥' + basePrice.toFixed(2), fontSize: 10 },
        } : undefined,
      },
    ],
  }, true)
}

// 加载录屏
async function loadRecordings() {
  try {
    const res = await recordingsApi.list({ task_id: taskId })
    recordings.value = res.recordings
  } catch (e) {
    console.error('Load recordings error:', e)
  }
}

// 播放录屏
function playRecording(filename: string) {
  playerUrl.value = recordingsApi.getPlayUrl(filename)
  playerVisible.value = true
}

// 删除录屏
async function deleteRecording(filename: string) {
  try {
    await ElMessageBox.confirm('确定删除该录屏文件？删除后不可恢复。', '删除确认', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
    await recordingsApi.delete(filename)
    ElMessage.success('已删除')
    loadRecordings()
  } catch (e) {
    // 用户取消或请求失败
  }
}

// 立即采集
async function runNow() {
  try {
    await tasksApi.runNow(taskId)
    ElMessage.success('采集任务已启动')
  } catch (e) {
    console.error(e)
  }
}

// 编辑
function editTask() {
  if (!task.value) return
  editForm.frequency_minutes = task.value.frequency_minutes
  editForm.recording_enabled = task.value.recording_enabled
  editForm.note = task.value.note || ''
  debugModeEnabled.value = false
  editDialogVisible.value = true
}

async function submitEdit() {
  editSubmitting.value = true
  try {
    const currentFrequency = task.value?.frequency_minutes ?? null
    const changedToLowFrequency =
      editForm.frequency_minutes < 30 && editForm.frequency_minutes !== currentFrequency
    if (changedToLowFrequency && !canUseDebugFrequency.value) {
      ElMessage.warning('仅超级管理员开启调试模式后可设置30分钟以下采集频率')
      return
    }

    await tasksApi.update(taskId, {
      frequency_minutes: editForm.frequency_minutes,
      recording_enabled: editForm.recording_enabled,
      note: editForm.note ?? '',
    })
    ElMessage.success('任务已更新')
    editDialogVisible.value = false
    loadData()
  } catch (e) {
    console.error(e)
  } finally {
    editSubmitting.value = false
  }
}

// SKU变更记录：折叠与格式化
const showCreatedEvents = ref(false)

const collapsedCreatedCount = computed(() => {
  if (!skuChangeEvents.value.length) return 0
  const createdEvents = skuChangeEvents.value.filter(e => e.change_type === 'created')
  return createdEvents.length > 3 ? createdEvents.length : 0
})

const filteredChangeEvents = computed(() => {
  if (showCreatedEvents.value || collapsedCreatedCount.value === 0) {
    return skuChangeEvents.value
  }
  return skuChangeEvents.value.filter(e => e.change_type !== 'created')
})

function changeTypeLabel(type: string): string {
  const map: Record<string, string> = {
    created: '新增SKU',
    price_update: '价格变动',
    manual_update: '手动修改',
    deleted: '删除',
  }
  return map[type] || type
}

function fieldLabel(field: string): string {
  const map: Record<string, string> = {
    current_price: '到手价',
    base_price: '基准价',
    is_monitored: '监控状态',
    note: '备注',
  }
  return map[field] || field
}

function formatChangeValue(field: string, value: unknown): string {
  if (value === null || value === undefined) return '-'
  if (field === 'current_price' || field === 'base_price') {
    return `¥${Number(value).toFixed(2)}`
  }
  if (field === 'is_monitored') {
    return value ? '开启' : '关闭'
  }
  return String(value)
}

// SKU编辑模式
const skuEditMode = ref(false)
const skuSaving = ref(false)

function enterSkuEditMode() {
  skus.value.forEach((sku: any) => {
    sku._editBasePrice = sku.base_price ?? undefined
    sku._editMonitored = sku.is_monitored
    sku._editNote = sku.note || ''
  })
  skuEditMode.value = true
}

function cancelSkuEditMode() {
  skuEditMode.value = false
}

async function saveSkuEdits() {
  skuSaving.value = true
  try {
    const configs = skus.value.map((sku: any) => ({
      sku_name: sku.sku_name,
      sku_id_external: sku.sku_id_external,
      base_price: sku._editBasePrice ?? null,
      is_monitored: sku._editMonitored,
      note: sku._editNote ?? '',
    }))
    await tasksApi.configureSkus(taskId, configs)
    ElMessage.success('SKU配置已保存')
    skuEditMode.value = false
    await loadData({ silent: true })
  } catch (e) {
    ElMessage.error('保存失败')
    console.error(e)
  } finally {
    skuSaving.value = false
  }
}

// 价格相关
function priceClass(row: SKUResponse): string {
  if (!row.base_price || !row.current_price) return ''
  return row.current_price < row.base_price ? 'price-negative' : ''
}

function priceDiff(row: SKUResponse): string {
  if (!row.base_price || !row.current_price) return '-'
  const diff = row.current_price - row.base_price
  const pct = (diff / row.base_price * 100).toFixed(1)
  return `${diff > 0 ? '+' : ''}${pct}%`
}

function formatFrequency(minutes: number): string {
  if (minutes < 60) return `每${minutes}分钟`
  if (minutes < 1440) return `每${minutes / 60}小时`
  return `每${minutes / 1440}天`
}

function goBack() {
  router.push('/tasks')
}

// 窗口resize
function handleResize() { trendChart?.resize() }

function updateResponsiveState() {
  const width = window.innerWidth
  if (width <= 768) {
    descColumn.value = 1
  } else if (width <= 1200) {
    descColumn.value = 2
  } else {
    descColumn.value = 4
  }
}

onMounted(() => {
  updateResponsiveState()
  loadData()
  autoRefreshTimer = setInterval(() => loadData({ silent: true }), 8000)
  window.addEventListener('resize', handleResize)
  window.addEventListener('resize', updateResponsiveState)
})

onBeforeUnmount(() => {
  if (autoRefreshTimer) {
    clearInterval(autoRefreshTimer)
    autoRefreshTimer = null
  }
  window.removeEventListener('resize', handleResize)
  window.removeEventListener('resize', updateResponsiveState)
  trendChart?.dispose()
})
</script>

<style scoped>
.page-header-content {
  display: flex;
  align-items: center;
}

.page-title {
  font-size: 16px;
  font-weight: 600;
  color: #303133;
}

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

.text-muted {
  font-size: 12px;
  color: #909399;
}

.event-title {
  font-size: 13px;
  font-weight: 600;
  color: #303133;
}

.debug-tip {
  margin-left: 10px;
}

.link-text {
  color: #409eff;
  text-decoration: none;
}
.link-text:hover {
  text-decoration: underline;
}

.link-truncate {
  display: inline-block;
  max-width: 360px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: middle;
}

.chart-container {
  height: 320px;
  width: 100%;
}

.change-diff {
  margin-top: 4px;
}

.diff-item {
  display: inline-block;
  margin-right: 16px;
  font-size: 12px;
  line-height: 1.8;
}

.diff-label {
  color: #606266;
}

.diff-old {
  color: #909399;
  text-decoration: line-through;
}

.diff-arrow {
  color: #c0c4cc;
}

.diff-new {
  color: #e6a23c;
  font-weight: 600;
}

.price-negative {
  color: #67c23a;
  font-weight: 600;
}

.note-cell {
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.4;
  font-size: 12px;
  color: #606266;
}

/* 异动记录 */
.alert-scroll-container {
  max-height: 480px;
  overflow-y: auto;
  padding-right: 4px;
}

.alert-record-item {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 12px;
  border-bottom: 1px solid var(--border-color, #ebeef5);
  transition: background 0.15s;
}

.alert-record-item:last-child {
  border-bottom: none;
}

.alert-record-item:hover {
  background: var(--bg-page, #f5f7fa);
  border-radius: 6px;
}

.alert-record-main {
  flex: 1;
  min-width: 0;
}

.alert-record-info {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
  flex-wrap: wrap;
}

.alert-sku-name {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary, #303133);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 300px;
}

.alert-time {
  font-size: 12px;
  flex-shrink: 0;
}

.alert-price-diff {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 13px;
  flex-wrap: wrap;
}

.alert-price-diff .diff-old {
  color: #909399;
  text-decoration: line-through;
}

.alert-price-diff .diff-arrow {
  color: #c0c4cc;
}

.alert-price-diff .diff-new {
  color: #e6a23c;
  font-weight: 600;
}

.diff-pct {
  font-size: 12px;
  margin-left: 4px;
}

.diff-down {
  color: #67c23a;
}

.diff-up {
  color: #f56c6c;
}

.alert-screenshot {
  flex-shrink: 0;
}

.screenshot-thumb {
  width: 100px;
  height: 64px;
  border-radius: 4px;
  border: 1px solid var(--border-color, #ebeef5);
  cursor: pointer;
}

.screenshot-error {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100px;
  height: 64px;
  background: #f5f7fa;
  color: #c0c4cc;
  font-size: 11px;
  border-radius: 4px;
}

</style>

<!-- 非scoped样式：穿透el-card/el-row内部 -->
<style>
.content-row {
  display: flex !important;
  flex-wrap: wrap;
  align-items: stretch !important;
}
.content-row > .el-col {
  display: flex;
}
.content-row > .el-col > .el-card {
  flex: 1;
  display: flex;
  flex-direction: column;
}
.content-row > .el-col > .el-card > .el-card__body {
  flex: 1;
}
</style>
