<template>
  <div class="page-container">
    <div class="page-header">
      <h2>筱和智眸</h2>
      <div class="header-actions">
        <el-tag :type="statusData.is_running ? 'success' : 'info'" size="large">
          {{ statusData.is_running ? '运行中' : '已停止' }}
        </el-tag>
        <el-button
          v-if="!statusData.is_running"
          type="success"
          @click="handleStart"
        >启动</el-button>
        <el-button
          v-else
          type="warning"
          @click="handleStop"
        >停止</el-button>
      </div>
    </div>

    <el-row :gutter="20" style="margin-bottom: 20px">
      <el-col :span="8">
        <el-card shadow="hover">
          <template #header>运行状态</template>
          <el-descriptions :column="1" size="small">
            <el-descriptions-item label="状态">
              <el-tag :type="statusData.is_running ? 'success' : 'info'" size="small">
                {{ statusData.is_running ? '运行中' : '已停止' }}
              </el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="自治级别">
              <el-tag :type="autonomyTagType" size="small">{{ autonomyLabel }}</el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="报告数量">
              {{ statusData.recent_reports_count }}
            </el-descriptions-item>
          </el-descriptions>
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card shadow="hover">
          <template #header>AI 记忆概览</template>
          <el-descriptions :column="1" size="small">
            <el-descriptions-item label="已识别模式">{{ memoryData.total_patterns || 0 }}</el-descriptions-item>
            <el-descriptions-item label="历史决策">{{ memoryData.total_decisions || 0 }}</el-descriptions-item>
            <el-descriptions-item label="历史报告">{{ memoryData.total_reports || 0 }}</el-descriptions-item>
          </el-descriptions>
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card shadow="hover">
          <template #header>自治级别说明</template>
          <div class="level-list">
            <p><el-tag size="small" type="info">0 全手动</el-tag> 关闭后台健康检查</p>
            <p><el-tag size="small">1 观察</el-tag> 仅记录本地报告</p>
            <p><el-tag size="small" type="warning">2 保守</el-tag> 生成配置调整建议，需人工确认</p>
            <p><el-tag size="small" type="danger">3 激进</el-tag> 生成高优先级处置建议，需人工确认</p>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-tabs v-model="activeTab">
      <el-tab-pane label="最近报告" name="reports">
        <!-- 搜索栏 -->
        <el-row :gutter="12" style="margin-bottom: 12px">
          <el-col :span="8">
            <el-input v-model="reportSearch" placeholder="搜索标题/摘要..." clearable prefix-icon="Search" />
          </el-col>
          <el-col :span="5">
            <el-select v-model="reportSeverityFilter" placeholder="全部级别" clearable style="width: 100%">
              <el-option label="正常" value="normal" />
              <el-option label="警告" value="warning" />
              <el-option label="严重" value="critical" />
            </el-select>
          </el-col>
          <el-col :span="5">
            <el-select v-model="reportTypeFilter" placeholder="全部类型" clearable style="width: 100%">
              <el-option label="Bug" value="bug" />
              <el-option label="性能" value="performance" />
              <el-option label="安全" value="security" />
              <el-option label="建议" value="suggestion" />
            </el-select>
          </el-col>
          <el-col :span="6" style="text-align:right">
            <el-text type="info" size="small">共 {{ filteredReports.length }} 条</el-text>
          </el-col>
        </el-row>

        <el-table :data="filteredReports" v-loading="reportsLoading" stripe @row-click="openReportDrawer" style="cursor: pointer">
          <el-table-column prop="timestamp" label="时间" width="150">
            <template #default="{ row }">{{ formatTime(row.timestamp) }}</template>
          </el-table-column>
          <el-table-column prop="severity" label="严重程度" width="100">
            <template #default="{ row }">
              <el-tag :type="severityColor(row.severity)" size="small">{{ severityLabel(row.severity) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="report_type" label="类型" width="80">
            <template #default="{ row }">
              <el-tag size="small">{{ reportTypeLabel(row.report_type) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="title" label="标题" min-width="220" show-overflow-tooltip />
          <el-table-column prop="summary" label="摘要" min-width="300" show-overflow-tooltip />
        </el-table>
        <el-empty v-if="!reportsLoading && filteredReports.length === 0" description="暂无匹配的报告" />
      </el-tab-pane>

      <el-tab-pane label="AI 记忆" name="memory">
        <!-- 记忆搜索栏 -->
        <el-row :gutter="12" style="margin-bottom: 16px">
          <el-col :span="10">
            <el-input v-model="memorySearchQuery" placeholder="语义搜索记忆内容..." clearable prefix-icon="Search" @keyup.enter="searchMemory" />
          </el-col>
          <el-col :span="4">
            <el-button type="primary" @click="searchMemory" :loading="memorySearching">搜索</el-button>
          </el-col>
          <el-col :span="10" style="text-align: right">
            <el-tag type="info" size="small" style="margin-right: 8px">短期: {{ memoryStats.short_term || 0 }}</el-tag>
            <el-tag type="success" size="small" style="margin-right: 8px">长期: {{ memoryStats.long_term || 0 }}</el-tag>
            <el-tag type="warning" size="small">实体: {{ memoryStats.entities || 0 }}</el-tag>
          </el-col>
        </el-row>

        <!-- 搜索结果 -->
        <div v-if="memorySearchResults.length > 0" style="margin-bottom: 16px">
          <el-divider content-position="left">搜索结果（{{ memorySearchResults.length }} 条）</el-divider>
          <el-table :data="memorySearchResults" size="small" stripe max-height="240">
            <el-table-column prop="layer" label="层级" width="80">
              <template #default="{ row }">
                <el-tag :type="layerTagType(row.layer)" size="small">{{ layerLabel(row.layer) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="content" label="内容" min-width="300" show-overflow-tooltip />
            <el-table-column prop="relevance" label="相关度" width="80" align="center">
              <template #default="{ row }">
                <el-progress :percentage="Math.round((row.relevance || 0) * 100)" :stroke-width="6" :show-text="false" />
              </template>
            </el-table-column>
            <el-table-column prop="updated_at" label="时间" width="140">
              <template #default="{ row }">{{ formatTime(row.updated_at) }}</template>
            </el-table-column>
          </el-table>
        </div>

        <!-- 三层记忆面板 -->
        <el-tabs v-model="memorySubTab" type="border-card">
          <!-- 短期记忆：最近上下文 -->
          <el-tab-pane name="short_term">
            <template #label><el-icon style="margin-right:4px"><Clock /></el-icon>短期记忆</template>
            <p class="memory-desc">最近的对话上下文、采集事件和临时状态，自动过期或合并到长期记忆。</p>
            <el-table :data="memoryData.short_term || []" size="small" stripe max-height="320">
              <el-table-column prop="content" label="内容" min-width="300" show-overflow-tooltip />
              <el-table-column prop="source" label="来源" width="100" />
              <el-table-column prop="ttl" label="有效期" width="80" align="center">
                <template #default="{ row }">{{ row.ttl || '∞' }}</template>
              </el-table-column>
              <el-table-column prop="created_at" label="时间" width="140">
                <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
              </el-table-column>
              <el-table-column label="操作" width="120" align="center">
                <template #default="{ row }">
                  <el-button size="small" link type="primary" @click="promoteMemory(row)">提升</el-button>
                  <el-button size="small" link type="danger" @click="deleteMemory(row)">删除</el-button>
                </template>
              </el-table-column>
            </el-table>
            <el-empty v-if="(memoryData.short_term || []).length === 0" description="暂无短期记忆" :image-size="48" />
          </el-tab-pane>

          <!-- 长期记忆：模式+决策 -->
          <el-tab-pane name="long_term">
            <template #label><el-icon style="margin-right:4px"><Collection /></el-icon>长期记忆</template>
            <p class="memory-desc">经过合并和巩固的持久知识：已识别的模式规律、历史决策记录和运营经验。</p>
            <el-row :gutter="20">
              <el-col :span="12">
                <h4 style="margin-top:0">识别的模式</h4>
                <el-table :data="memoryData.recent_patterns || []" size="small" stripe max-height="280">
                  <el-table-column prop="pattern" label="模式" min-width="150" show-overflow-tooltip />
                  <el-table-column prop="count" label="次数" width="60" />
                  <el-table-column prop="confidence" label="置信" width="60" align="center">
                    <template #default="{ row }">{{ row.confidence ? (row.confidence * 100).toFixed(0) + '%' : '-' }}</template>
                  </el-table-column>
                  <el-table-column prop="last_seen" label="最近" width="120">
                    <template #default="{ row }">{{ formatTime(row.last_seen) }}</template>
                  </el-table-column>
                </el-table>
                <el-empty v-if="(memoryData.recent_patterns || []).length === 0" description="暂无模式" :image-size="40" />
              </el-col>
              <el-col :span="12">
                <h4 style="margin-top:0">自治决策</h4>
                <el-table :data="memoryData.recent_decisions || []" size="small" stripe max-height="280">
                  <el-table-column prop="action" label="决策" min-width="200" show-overflow-tooltip />
                  <el-table-column prop="autonomy_level" label="级别" width="60" />
                  <el-table-column prop="outcome" label="结果" width="60">
                    <template #default="{ row }">
                      <el-tag v-if="row.outcome" :type="row.outcome === 'success' ? 'success' : 'danger'" size="small">{{ row.outcome === 'success' ? '成功' : '失败' }}</el-tag>
                      <span v-else>-</span>
                    </template>
                  </el-table-column>
                  <el-table-column prop="timestamp" label="时间" width="120">
                    <template #default="{ row }">{{ formatTime(row.timestamp) }}</template>
                  </el-table-column>
                </el-table>
                <el-empty v-if="(memoryData.recent_decisions || []).length === 0" description="暂无决策" :image-size="40" />
              </el-col>
            </el-row>
          </el-tab-pane>

          <!-- 实体知识图谱 -->
          <el-tab-pane name="entities">
            <template #label><el-icon style="margin-right:4px"><Connection /></el-icon>实体图谱</template>
            <p class="memory-desc">自动提取的关键实体（SKU、店铺、规则、引擎等）及其关联关系，构成知识网络。</p>
            <el-table :data="memoryData.entities || []" size="small" stripe max-height="320">
              <el-table-column prop="name" label="实体" width="180" />
              <el-table-column prop="entity_type" label="类型" width="100">
                <template #default="{ row }">
                  <el-tag size="small">{{ row.entity_type }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="properties" label="属性" min-width="250" show-overflow-tooltip>
                <template #default="{ row }">
                  {{ typeof row.properties === 'object' ? JSON.stringify(row.properties) : row.properties }}
                </template>
              </el-table-column>
              <el-table-column prop="relations_count" label="关联数" width="80" align="center" />
              <el-table-column prop="updated_at" label="更新" width="140">
                <template #default="{ row }">{{ formatTime(row.updated_at) }}</template>
              </el-table-column>
            </el-table>
            <el-empty v-if="(memoryData.entities || []).length === 0" description="暂无实体记录" :image-size="48" />
          </el-tab-pane>
        </el-tabs>
      </el-tab-pane>
    </el-tabs>

    <!-- 报告详情抽屉 -->
    <el-drawer v-model="reportDrawerVisible" title="报告详情" size="520px" direction="rtl">
      <template v-if="selectedReport">
        <el-descriptions :column="1" border size="small" style="margin-bottom: 16px">
          <el-descriptions-item label="时间">{{ formatTimeFull(selectedReport.timestamp) }}</el-descriptions-item>
          <el-descriptions-item label="严重程度">
            <el-tag :type="severityColor(selectedReport.severity)" size="small">{{ severityLabel(selectedReport.severity) }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="类型">
            <el-tag size="small">{{ reportTypeLabel(selectedReport.report_type) }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="标题">{{ selectedReport.title }}</el-descriptions-item>
        </el-descriptions>

        <h4>摘要</h4>
        <p class="report-summary">{{ selectedReport.summary || '无' }}</p>

        <h4>详细内容</h4>
        <pre class="report-detail">{{ selectedReport.details || selectedReport.detail || '无详细内容' }}</pre>

        <h4>建议措施</h4>
        <div v-if="(selectedReport.recommendations || []).length > 0">
          <div v-for="(rec, i) in selectedReport.recommendations" :key="i" class="rec-item-drawer">
            <el-icon color="#409eff" style="margin-right: 6px"><CircleCheck /></el-icon>
            {{ rec }}
          </div>
        </div>
        <el-empty v-else description="无建议" :image-size="40" />

        <h4 v-if="selectedReport.metrics">关联指标</h4>
        <el-descriptions v-if="selectedReport.metrics" :column="2" border size="small">
          <el-descriptions-item v-for="(val, key) in selectedReport.metrics" :key="key" :label="String(key)">
            {{ val }}
          </el-descriptions-item>
        </el-descriptions>
      </template>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { CircleCheck, Clock, Collection, Connection } from '@element-plus/icons-vue'
import apiClient from '@/api'
import { watchdogApi } from '@/api'

const activeTab = ref('reports')
const statusData = ref<any>({ is_running: false, autonomy_level: 1, recent_reports_count: 0 })
const reports = ref<any[]>([])
const reportsLoading = ref(false)
const memoryData = ref<any>({})

// AI记忆相关
const memorySubTab = ref('short_term')
const memorySearchQuery = ref('')
const memorySearching = ref(false)
const memorySearchResults = ref<any[]>([])
const memoryStats = computed(() => ({
  short_term: (memoryData.value.short_term || []).length,
  long_term: (memoryData.value.recent_patterns || []).length + (memoryData.value.recent_decisions || []).length,
  entities: (memoryData.value.entities || []).length,
}))

// 报告搜索/筛选
const reportSearch = ref('')
const reportSeverityFilter = ref('')
const reportTypeFilter = ref('')

// 报告抽屉
const reportDrawerVisible = ref(false)
const selectedReport = ref<any>(null)

const filteredReports = computed(() => {
  let list = reports.value
  if (reportSeverityFilter.value) {
    list = list.filter(r => r.severity === reportSeverityFilter.value)
  }
  if (reportTypeFilter.value) {
    list = list.filter(r => r.report_type === reportTypeFilter.value)
  }
  if (reportSearch.value.trim()) {
    const q = reportSearch.value.trim().toLowerCase()
    list = list.filter(r =>
      (r.title || '').toLowerCase().includes(q) ||
      (r.summary || '').toLowerCase().includes(q)
    )
  }
  return list
})

function openReportDrawer(row: any) {
  selectedReport.value = row
  reportDrawerVisible.value = true
}

const autonomyLabel = computed(() => {
  const map: Record<number, string> = { 0: '全手动', 1: '观察模式', 2: '保守模式', 3: '激进模式' }
  return map[statusData.value.autonomy_level] || '未知'
})

const autonomyTagType = computed(() => {
  const map: Record<number, string> = { 0: 'info', 1: '', 2: 'warning', 3: 'danger' }
  return map[statusData.value.autonomy_level] || 'info'
})

async function loadStatus() {
  try {
    statusData.value = await watchdogApi.status()
  } catch (e) {
    console.error('Failed to load watchdog status:', e)
  }
}

async function loadReports() {
  reportsLoading.value = true
  try {
    const data = await watchdogApi.reports()
    reports.value = (data.reports || []).reverse()
  } catch (e) {
    console.error('Failed to load reports:', e)
  } finally {
    reportsLoading.value = false
  }
}

async function loadMemory() {
  try {
    const data = await watchdogApi.memory()
    memoryData.value = data.memory || {}
  } catch (e) {
    console.error('Failed to load memory:', e)
  }
}

async function handleStart() {
  try {
    await watchdogApi.start()
    ElMessage.success('筱和智眸已启动')
    await loadStatus()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '启动失败')
  }
}

async function handleStop() {
  try {
    await watchdogApi.stop()
    ElMessage.success('筱和智眸已停止')
    await loadStatus()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '停止失败')
  }
}

function formatTime(ts: string) {
  if (!ts) return '-'
  return new Date(ts).toLocaleString('zh-CN', {
    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
  })
}

function formatTimeFull(ts: string) {
  if (!ts) return '-'
  return new Date(ts).toLocaleString('zh-CN')
}

function severityColor(s: string) {
  const map: Record<string, string> = { normal: 'success', warning: 'warning', critical: 'danger' }
  return map[s] || 'info'
}

function severityLabel(s: string) {
  const map: Record<string, string> = { normal: '正常', warning: '警告', critical: '严重' }
  return map[s] || s
}

function reportTypeLabel(t: string) {
  const map: Record<string, string> = { bug: 'Bug', performance: '性能', security: '安全', suggestion: '建议' }
  return map[t] || t
}

// 记忆层级标签
function layerTagType(layer: string) {
  const map: Record<string, string> = { short_term: 'info', long_term: 'success', entity: 'warning' }
  return map[layer] || 'info'
}
function layerLabel(layer: string) {
  const map: Record<string, string> = { short_term: '短期', long_term: '长期', entity: '实体' }
  return map[layer] || layer
}

async function searchMemory() {
  if (!memorySearchQuery.value.trim()) {
    memorySearchResults.value = []
    return
  }
  memorySearching.value = true
  try {
    const resp = await apiClient.get('/watchdog/memory/search', { params: { q: memorySearchQuery.value.trim() } })
    memorySearchResults.value = resp.data.results || []
  } catch (e) {
    memorySearchResults.value = []
    console.error('Memory search failed:', e)
  } finally {
    memorySearching.value = false
  }
}

async function promoteMemory(row: any) {
  try {
    await apiClient.post('/watchdog/memory/promote', { memory_id: row.id })
    ElMessage.success('已提升到长期记忆')
    await loadMemory()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '操作失败')
  }
}

async function deleteMemory(row: any) {
  try {
    await apiClient.delete(`/watchdog/memory/${row.id}`)
    ElMessage.success('已删除')
    await loadMemory()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '删除失败')
  }
}

onMounted(() => {
  loadStatus()
  loadReports()
  loadMemory()
})
</script>

<style scoped>
.page-container {
  padding: 20px;
}
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}
.page-header h2 {
  margin: 0;
}
.header-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}
.level-list p {
  margin: 6px 0;
  font-size: 13px;
}
.report-summary {
  color: #606266;
  font-size: 14px;
  line-height: 1.7;
  margin: 8px 0 16px;
}
.report-detail {
  background: #f5f7fa;
  border: 1px solid #ebeef5;
  border-radius: 4px;
  padding: 12px;
  font-size: 13px;
  line-height: 1.6;
  color: #303133;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 200px;
  overflow-y: auto;
  margin: 8px 0 16px;
}
.rec-item-drawer {
  display: flex;
  align-items: flex-start;
  font-size: 13px;
  color: #303133;
  line-height: 1.7;
  margin-bottom: 8px;
}
.memory-desc {
  color: #909399;
  font-size: 13px;
  margin: 0 0 12px;
}
</style>
