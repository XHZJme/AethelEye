<template>
  <div class="logs-page">
    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <span class="card-title">系统日志</span>
          <div class="header-actions">
            <el-switch v-model="autoRefresh" active-text="自动刷新" style="margin-right: 12px" @change="toggleAutoRefresh" />
            <el-button size="small" @click="loadLogs">
              <el-icon><Refresh /></el-icon>
              刷新
            </el-button>
          </div>
        </div>
      </template>

      <!-- 筛选 -->
      <el-row :gutter="12" style="margin-bottom: 16px">
        <el-col :span="4">
          <el-select v-model="filters.category" placeholder="分类" clearable @change="loadLogs">
            <el-option label="系统" value="system" />
            <el-option label="采集" value="collector" />
            <el-option label="网络" value="network" />
            <el-option label="浏览器" value="browser" />
            <el-option label="操作" value="audit" />
            <el-option label="告警" value="alert" />
          </el-select>
        </el-col>
        <el-col :span="4">
          <el-select v-model="filters.level" placeholder="级别" clearable @change="loadLogs">
            <el-option label="ERROR" value="ERROR">
              <el-tag type="danger" size="small" effect="dark">ERROR</el-tag>
            </el-option>
            <el-option label="WARNING" value="WARNING">
              <el-tag type="warning" size="small" effect="dark">WARNING</el-tag>
            </el-option>
            <el-option label="INFO" value="INFO">
              <el-tag type="success" size="small" effect="dark">INFO</el-tag>
            </el-option>
            <el-option label="DEBUG" value="DEBUG">
              <el-tag type="info" size="small" effect="dark">DEBUG</el-tag>
            </el-option>
          </el-select>
        </el-col>
        <el-col :span="4">
          <el-date-picker
            v-model="filters.date"
            type="date"
            placeholder="日期"
            value-format="YYYY-MM-DD"
            @change="loadLogs"
            style="width: 100%"
          />
        </el-col>
        <el-col :span="3">
          <el-input
            v-model.number="filters.task_id"
            placeholder="任务ID"
            clearable
            @change="loadLogs"
          />
        </el-col>
        <el-col :span="5">
          <el-input
            v-model="filters.search"
            placeholder="搜索关键词..."
            clearable
            :prefix-icon="Search"
            @input="debounceSearch"
          />
        </el-col>
      </el-row>

      <!-- 日志列表 -->
      <el-table
        v-loading="loading"
        :data="logs"
        style="width: 100%"
        empty-text="暂无日志"
        size="small"
        :row-class-name="logRowClass"
        @row-click="showLogDetail"
      >
        <el-table-column prop="timestamp" label="时间" width="170">
          <template #default="{ row }">
            <span class="log-time">{{ row.timestamp }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="level" label="级别" width="85" align="center">
          <template #default="{ row }">
            <el-tag :type="levelType(row.level)" size="small" effect="dark">{{ row.level }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="category" label="分类" width="80" align="center">
          <template #default="{ row }">
            <span class="text-muted">{{ row.category }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="message" label="内容" min-width="260" show-overflow-tooltip />
        <el-table-column label="操作人" width="90" align="center">
          <template #default="{ row }">
            <span v-if="row.data?.operator" class="log-operator">{{ row.data.operator }}</span>
            <span v-else-if="row.user_id" class="log-operator">ID:{{ row.user_id }}</span>
            <span v-else class="text-muted">-</span>
          </template>
        </el-table-column>
        <el-table-column prop="task_id" label="任务" width="70" align="center">
          <template #default="{ row }">
            <el-link v-if="row.task_id" type="primary" @click.stop="$router.push(`/tasks/${row.task_id}`)">
              #{{ row.task_id }}
            </el-link>
            <span v-else class="text-muted">-</span>
          </template>
        </el-table-column>
        <el-table-column prop="trace_id" label="Trace" width="100">
          <template #default="{ row }">
            <el-link v-if="row.trace_id" type="primary" @click.stop="traceSearch(row.trace_id)">
              {{ row.trace_id.slice(0, 8) }}...
            </el-link>
            <span v-else class="text-muted">-</span>
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
          @current-change="loadLogs"
        />
      </div>
    </el-card>

    <!-- 日志详情抽屉 -->
    <el-drawer v-model="detailVisible" title="日志详情" size="500px">
      <div v-if="selectedLog">
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="时间">{{ selectedLog.timestamp }}</el-descriptions-item>
          <el-descriptions-item label="级别">
            <el-tag :type="levelType(selectedLog.level)" size="small" effect="dark">{{ selectedLog.level }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="分类">{{ selectedLog.category }}</el-descriptions-item>
          <el-descriptions-item label="模块">{{ selectedLog.module }}</el-descriptions-item>
          <el-descriptions-item label="消息">{{ selectedLog.message }}</el-descriptions-item>
          <el-descriptions-item label="任务ID" v-if="selectedLog.task_id">
            {{ selectedLog.task_id }}
          </el-descriptions-item>
          <el-descriptions-item label="操作人" v-if="selectedLog.user_id || selectedLog.data?.operator">
            <span v-if="selectedLog.data?.operator">{{ selectedLog.data.operator }}</span>
            <span v-else>User#{{ selectedLog.user_id }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="Trace ID" v-if="selectedLog.trace_id">
            {{ selectedLog.trace_id }}
          </el-descriptions-item>
        </el-descriptions>

        <div v-if="selectedLog.data" class="json-section">
          <div class="json-title">附加数据</div>
          <pre class="json-content">{{ JSON.stringify(selectedLog.data, null, 2) }}</pre>
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted, onBeforeUnmount } from 'vue'
import { Search } from '@element-plus/icons-vue'
import { logsApi } from '@/api'
import type { LogEntry } from '@/api'

const loading = ref(false)
const logs = ref<LogEntry[]>([])
const total = ref(0)
const currentPage = ref(1)
const pageSize = 50
const autoRefresh = ref(false)
let refreshTimer: ReturnType<typeof setInterval> | null = null
const AUTO_REFRESH_KEY = 'aetheleye_logs_auto_refresh'

const filters = reactive({
  category: '',
  level: '',
  date: '',
  task_id: null as number | null,
  search: '',
})

// 详情
const detailVisible = ref(false)
const selectedLog = ref<LogEntry | null>(null)

// 加载
async function loadLogs(options?: { silent?: boolean }) {
  const silent = !!options?.silent
  if (!silent) loading.value = true
  try {
    const params: Record<string, unknown> = {
      page: currentPage.value,
      page_size: pageSize,
    }
    if (filters.category) params.category = filters.category
    if (filters.level) params.level = filters.level
    if (filters.date) params.date = filters.date
    if (filters.task_id) params.task_id = filters.task_id
    if (filters.search) params.search = filters.search

    const res = await logsApi.query(params as Record<string, string>)
    logs.value = res.logs
    total.value = res.total
  } catch (e) {
    console.error('Load logs error:', e)
  } finally {
    if (!silent) loading.value = false
  }
}

// 防抖搜索
let searchTimer: ReturnType<typeof setTimeout> | null = null
function debounceSearch() {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => loadLogs(), 400)
}

// 自动刷新
function startAutoRefresh() {
  if (refreshTimer) clearInterval(refreshTimer)
  refreshTimer = setInterval(() => loadLogs({ silent: true }), 5000)
}

function stopAutoRefresh() {
  if (refreshTimer) clearInterval(refreshTimer)
  refreshTimer = null
}

function toggleAutoRefresh(val: boolean) {
  localStorage.setItem(AUTO_REFRESH_KEY, val ? '1' : '0')
  if (val) {
    startAutoRefresh()
  } else {
    stopAutoRefresh()
  }
}

// 级别颜色
function levelType(level: string): 'success' | 'warning' | 'danger' | 'info' {
  const map: Record<string, 'success' | 'warning' | 'danger' | 'info'> = {
    ERROR: 'danger',
    WARNING: 'warning',
    INFO: 'success',
    DEBUG: 'info',
  }
  return map[level] || 'info'
}

// 行样式
function logRowClass({ row }: { row: LogEntry }): string {
  if (row.level === 'ERROR') return 'log-row-error'
  if (row.level === 'WARNING') return 'log-row-warning'
  return ''
}

// 显示详情
function showLogDetail(row: LogEntry) {
  selectedLog.value = row
  detailVisible.value = true
}

// Trace追踪
async function traceSearch(traceId: string) {
  loading.value = true
  try {
    const res = await logsApi.getByTraceId(traceId)
    logs.value = res.logs
    total.value = res.total
  } catch (e) {
    console.error(e)
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  const saved = localStorage.getItem(AUTO_REFRESH_KEY)
  autoRefresh.value = saved === '1'
  loadLogs()
  if (autoRefresh.value) {
    startAutoRefresh()
  }
})

onBeforeUnmount(() => {
  stopAutoRefresh()
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

.header-actions {
  display: flex;
  align-items: center;
}

.text-muted {
  font-size: 12px;
  color: #909399;
}

.log-time {
  font-size: 12px;
  color: #606266;
  font-family: 'Consolas', 'Monaco', monospace;
}

.log-operator {
  font-size: 12px;
  color: #409eff;
  font-weight: 500;
}

.pagination-wrapper {
  margin-top: 16px;
  display: flex;
  justify-content: flex-end;
}

/* 行高亮 */
:deep(.log-row-error) {
  background-color: #fef0f0 !important;
}

:deep(.log-row-warning) {
  background-color: #fdf6ec !important;
}

/* JSON详情 */
.json-section {
  margin-top: 16px;
}

.json-title {
  font-size: 13px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 8px;
}

.json-content {
  background: #fafafa;
  border: 1px solid #ebeef5;
  border-radius: 6px;
  padding: 12px;
  font-size: 12px;
  font-family: 'Consolas', 'Monaco', monospace;
  color: #606266;
  overflow-x: auto;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 400px;
  overflow-y: auto;
}
</style>
