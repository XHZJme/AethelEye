<template>
  <div class="alerts-page">
    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <span class="card-title">异动记录</span>
          <div class="header-actions">
            <el-button type="success" size="small" @click="handleExport" :loading="exporting">
              <el-icon><Download /></el-icon>
              导出Excel
            </el-button>
          </div>
        </div>
      </template>

      <!-- 统计栏 -->
      <el-row :gutter="12" style="margin-bottom: 16px" v-if="statistics">
        <el-col :lg="6" :md="8" :sm="8" :xs="12">
          <div class="mini-stat">
            <span class="mini-stat-number danger">{{ statistics.unprocessed }}</span>
            <span class="mini-stat-label">待处理</span>
          </div>
        </el-col>
        <el-col :lg="6" :md="8" :sm="8" :xs="12">
          <div class="mini-stat">
            <span class="mini-stat-number warning">{{ statistics.today_new }}</span>
            <span class="mini-stat-label">今日新增</span>
          </div>
        </el-col>
        <el-col :lg="6" :md="8" :sm="8" :xs="12">
          <div class="mini-stat">
            <span class="mini-stat-number">{{ statistics.last_7_days }}</span>
            <span class="mini-stat-label">近7天</span>
          </div>
        </el-col>
      </el-row>

      <!-- 筛选 -->
      <el-row :gutter="12" style="margin-bottom: 16px">
        <el-col :lg="4" :md="6" :sm="12" :xs="24">
          <el-select v-model="filters.status" placeholder="处理状态" clearable @change="() => { currentPage = 1; loadAlerts(); }">
            <el-option label="未处理" value="new" />
            <el-option label="已确认" value="confirmed" />
            <el-option label="已处理" value="resolved" />
            <el-option label="误报" value="false_alarm" />
          </el-select>
        </el-col>
        <el-col :lg="4" :md="6" :sm="12" :xs="24">
          <el-select v-model="filters.platform" placeholder="平台" clearable @change="() => { currentPage = 1; loadAlerts(); }">
            <el-option label="天猫" value="tmall" />
            <el-option label="淘宝" value="taobao" />
          </el-select>
        </el-col>
        <el-col :lg="4" :md="6" :sm="12" :xs="24">
          <el-select v-model="filters.alert_type" placeholder="异动类型" clearable @change="() => { currentPage = 1; loadAlerts(); }">
            <el-option label="价格下探" value="price_drop" />
            <el-option label="采集失败" value="collect_fail" />
            <el-option label="账号异常" value="account_issue" />
          </el-select>
        </el-col>
        <el-col :lg="4" :md="6" :sm="12" :xs="24">
          <el-select v-model="filters.recent_hours" placeholder="时效" clearable @change="() => { currentPage = 1; loadAlerts(); }">
            <el-option label="近6小时" :value="6" />
            <el-option label="近24小时" :value="24" />
            <el-option label="近72小时" :value="72" />
            <el-option label="近7天" :value="168" />
          </el-select>
        </el-col>
        <el-col :lg="6" :md="8" :sm="12" :xs="24">
          <el-date-picker
            v-model="dateRange"
            type="daterange"
            start-placeholder="开始日期"
            end-placeholder="结束日期"
            value-format="YYYY-MM-DDTHH:mm:ss"
            @change="() => { currentPage = 1; loadAlerts(); }"
            style="width: 100%"
          />
        </el-col>
        <el-col :lg="6" :md="8" :sm="12" :xs="24">
          <el-input
            v-model="filters.search"
            placeholder="搜索商品/店铺/SKU..."
            clearable
            :prefix-icon="Search"
            @input="debounceSearch"
          />
        </el-col>
        <el-col :lg="2" :md="4" :sm="12" :xs="24">
          <el-button @click="loadAlerts">
            <el-icon><Refresh /></el-icon>
          </el-button>
        </el-col>
      </el-row>

      <!-- 异动表格 -->
      <div style="margin-bottom: 8px">
        <el-button v-if="userStore.isOperator" size="small" type="danger" plain :disabled="selectedAlertIds.length === 0" @click="batchDeleteAlerts">
          批量删除（{{ selectedAlertIds.length }}）
        </el-button>
      </div>
      <el-table v-loading="loading" :data="alerts" style="width: 100%" empty-text="暂无异动记录" @selection-change="onSelectionChange">
        <el-table-column type="selection" width="42" />
        <el-table-column prop="detected_at" label="发现时间" width="150">
          <template #default="{ row }">
            <span class="text-muted">{{ formatDateTime(row.detected_at) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="shop_name" label="店铺" min-width="120" show-overflow-tooltip />
        <el-table-column prop="product_title" label="商品" min-width="160" show-overflow-tooltip />
        <el-table-column prop="sku_name" label="SKU" min-width="100" show-overflow-tooltip />
        <el-table-column prop="alert_type" label="类型" width="90" align="center">
          <template #default="{ row }">
            <el-tag size="small" effect="plain">{{ alertTypeLabel(row.alert_type) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="platform" label="平台" width="70" align="center">
          <template #default="{ row }">
            <el-tag :type="row.platform === 'tmall' ? 'danger' : 'warning'" size="small" effect="plain">
              {{ platformLabel(row.platform) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="base_price" label="基准价" width="90" align="right">
          <template #default="{ row }">
            <span v-if="row.alert_type !== 'collect_fail'">{{ formatPrice(row.base_price) }}</span>
            <span v-else class="text-muted">-</span>
          </template>
        </el-table-column>
        <el-table-column prop="alert_price" label="异动价" width="90" align="right">
          <template #default="{ row }">
            <span v-if="row.alert_type !== 'collect_fail'" class="price-negative">{{ formatPrice(row.alert_price) }}</span>
            <span v-else class="text-muted">-</span>
          </template>
        </el-table-column>
        <el-table-column prop="price_diff_pct" label="价差率" width="80" align="right">
          <template #default="{ row }">
            <span v-if="row.alert_type !== 'collect_fail'" class="price-negative">{{ row.price_diff_pct.toFixed(1) }}%</span>
            <span v-else class="text-muted">-</span>
          </template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="85" align="center">
          <template #default="{ row }">
            <el-tag :type="alertStatusInfo(row.status).type" size="small">
              {{ alertStatusInfo(row.status).label }}
            </el-tag>
            <div class="text-muted" v-if="row.age_minutes !== null && row.age_minutes !== undefined">{{ formatAge(row.age_minutes) }}</div>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="280" fixed="right">
          <template #default="{ row }">
            <template v-if="row.status === 'new'">
              <el-tooltip content="标记为已知悉，稍后处理" placement="top">
                <el-button size="small" text type="warning" @click="updateStatus(row.id, 'confirmed')">已知悉</el-button>
              </el-tooltip>
              <el-tooltip content="异动已处理完毕" placement="top">
                <el-button size="small" text type="success" @click="updateStatus(row.id, 'resolved', true)">已处理</el-button>
              </el-tooltip>
              <el-tooltip content="该异动为误报，无需处理" placement="top">
                <el-button size="small" text @click="updateStatus(row.id, 'false_alarm')">误报</el-button>
              </el-tooltip>
            </template>
            <template v-else-if="row.status === 'confirmed'">
              <el-tooltip content="异动已处理完毕" placement="top">
                <el-button size="small" text type="success" @click="updateStatus(row.id, 'resolved', true)">已处理</el-button>
              </el-tooltip>
              <el-tooltip content="该异动为误报，无需处理" placement="top">
                <el-button size="small" text @click="updateStatus(row.id, 'false_alarm')">误报</el-button>
              </el-tooltip>
            </template>
            <template v-else>
              <span class="text-muted">{{ alertStatusInfo(row.status).label }}</span>
            </template>
            <el-button v-if="row.screenshot_path" size="small" text type="primary" @click="viewScreenshot(row.screenshot_path)">截图</el-button>
            <el-button v-if="userStore.isOperator" size="small" text type="danger" @click="deleteAlert(row.id)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <!-- 分页 -->
      <div class="pagination-wrapper" v-if="total > pageSize">
        <el-pagination
          v-model:current-page="currentPage"
          :page-size="pageSize"
          :total="total"
          layout="total, prev, pager, next"
          @current-change="loadAlerts"
        />
      </div>
    </el-card>

    <!-- 截图查看 -->
    <el-dialog v-model="screenshotVisible" title="采集截图" width="800px" destroy-on-close>
      <el-image :src="screenshotUrl" style="width: 100%" fit="contain">
        <template #error>
          <el-empty description="截图不存在或已被清理" :image-size="100" />
        </template>
      </el-image>
    </el-dialog>

    <!-- 处理备注对话框 -->
    <el-dialog v-model="noteDialogVisible" title="处理异动" width="400px">
      <el-input v-model="resolveNote" type="textarea" :rows="3" placeholder="请输入处理说明（可选）" />
      <template #footer>
        <el-button @click="noteDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitResolve">确认处理</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { Search } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  alertsApi,
  exportApi,
  formatDateTime,
  formatPrice,
  platformLabel,
  alertStatusInfo,
  downloadBlob,
} from '@/api'
import type { AlertResponse, AlertStatistics } from '@/api'
import { useUserStore } from '@/stores/user'

const userStore = useUserStore()

// 状态
const loading = ref(false)
const exporting = ref(false)
const alerts = ref<AlertResponse[]>([])
const total = ref(0)
const currentPage = ref(1)
const pageSize = 20
const statistics = ref<AlertStatistics | null>(null)
const dateRange = ref<[string, string] | null>(null)

const filters = reactive({
  status: '',
  platform: '',
  alert_type: '',
  recent_hours: undefined as number | undefined,
  search: '',
})
const selectedAlertIds = ref<number[]>([])

// 截图
const screenshotVisible = ref(false)
const screenshotUrl = ref('')

// 处理备注
const noteDialogVisible = ref(false)
const resolveNote = ref('')
let pendingResolveId: number | null = null

// 加载
async function loadAlerts() {
  loading.value = true
  try {
    const params: Record<string, unknown> = {
      page: currentPage.value,
      page_size: pageSize,
    }
    if (filters.status) params.status = filters.status
    if (filters.platform) params.platform = filters.platform
    if (filters.alert_type) params.alert_type = filters.alert_type
    if (filters.recent_hours) params.recent_hours = filters.recent_hours
    if (filters.search) params.search = filters.search
    if (dateRange.value && dateRange.value[0]) {
      params.start_date = dateRange.value[0]
      params.end_date = dateRange.value[1]
    }
    const res = await alertsApi.list(params as Record<string, string>)
    alerts.value = res.alerts
    total.value = res.total
  } catch (e) {
    console.error('Load alerts error:', e)
  } finally {
    loading.value = false
  }
}

async function loadStatistics() {
  try {
    statistics.value = await alertsApi.getStatistics()
  } catch (e) {
    console.error('Load statistics error:', e)
  }
}

// 防抖搜索
let searchTimer: ReturnType<typeof setTimeout> | null = null
function debounceSearch() {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    currentPage.value = 1
    loadAlerts()
  }, 400)
}

// 更新状态
async function updateStatus(alertId: number, status: string, needNote = false) {
  if (needNote) {
    pendingResolveId = alertId
    resolveNote.value = ''
    noteDialogVisible.value = true
    return
  }
  try {
    await alertsApi.updateStatus(alertId, { status })
    ElMessage.success('状态已更新')
    loadAlerts()
    loadStatistics()
  } catch (e) {
    console.error(e)
  }
}

async function submitResolve() {
  if (pendingResolveId === null) return
  try {
    await alertsApi.updateStatus(pendingResolveId, {
      status: 'resolved',
      resolved_note: resolveNote.value || undefined,
    })
    ElMessage.success('已处理')
    noteDialogVisible.value = false
    loadAlerts()
    loadStatistics()
  } catch (e) {
    console.error(e)
  }
}

// 截图
function viewScreenshot(path: string) {
  screenshotUrl.value = alertsApi.getScreenshotUrl(path)
  screenshotVisible.value = true
}

function alertTypeLabel(alertType: string): string {
  const map: Record<string, string> = {
    price_drop: '价格下探',
    collect_fail: '采集失败',
    account_issue: '账号异常',
  }
  return map[alertType] || alertType
}

function formatAge(minutes: number): string {
  if (minutes < 60) return `${minutes}分钟前`
  if (minutes < 1440) return `${Math.floor(minutes / 60)}小时前`
  return `${Math.floor(minutes / 1440)}天前`
}

function onSelectionChange(rows: AlertResponse[]) {
  selectedAlertIds.value = rows.map((item) => item.id)
}

async function deleteAlert(alertId: number) {
  try {
    await ElMessageBox.confirm('确定删除该异动记录？删除后不可恢复。', '删除确认', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
    await alertsApi.delete(alertId)
    ElMessage.success('已删除')
    loadAlerts()
    loadStatistics()
  } catch (e) {
    // 用户取消或请求失败
  }
}

async function batchDeleteAlerts() {
  if (selectedAlertIds.value.length === 0) return
  try {
    await ElMessageBox.confirm(
      `确定删除选中的 ${selectedAlertIds.value.length} 条异动记录？删除后不可恢复。`,
      '批量删除确认',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
    await alertsApi.batchDelete(selectedAlertIds.value)
    ElMessage.success('批量删除完成')
    selectedAlertIds.value = []
    loadAlerts()
    loadStatistics()
  } catch (e) {
    // 用户取消或请求失败
  }
}

// 导出
async function handleExport() {
  exporting.value = true
  try {
    const params: Record<string, string> = {}
    if (filters.status) params.status = filters.status
    if (filters.platform) params.platform = filters.platform
    if (dateRange.value && dateRange.value[0]) {
      params.start_date = dateRange.value[0]
      params.end_date = dateRange.value[1]
    }
    const blob = await exportApi.exportAlerts(params)
    const filename = `异动记录_${new Date().toISOString().slice(0, 10)}.xlsx`
    downloadBlob(blob, filename)
    ElMessage.success('导出成功')
  } catch (e) {
    console.error('Export error:', e)
  } finally {
    exporting.value = false
  }
}

onMounted(() => {
  loadAlerts()
  loadStatistics()
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

.mini-stat {
  display: flex;
  align-items: baseline;
  gap: 6px;
  padding: 8px 12px;
  background: #f5f7fa;
  border-radius: 6px;
}

.mini-stat-number {
  font-size: 20px;
  font-weight: 700;
  color: #303133;
}

.mini-stat-number.danger { color: #f56c6c; }
.mini-stat-number.warning { color: #e6a23c; }

.mini-stat-label {
  font-size: 12px;
  color: #909399;
}

.text-muted {
  font-size: 12px;
  color: #909399;
}

.pagination-wrapper {
  margin-top: 16px;
  display: flex;
  justify-content: flex-end;
}
</style>