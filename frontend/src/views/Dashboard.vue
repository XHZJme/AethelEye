<template>
  <div class="dashboard">
    <!-- 统计卡片 -->
    <div class="stats-grid">
      <div>
        <el-card class="stat-card stat-card-clickable" shadow="hover" @click="$router.push('/tasks')">
          <div class="stat-icon" style="background: linear-gradient(135deg, #409eff, #66b1ff)">
            <el-icon :size="24"><Document /></el-icon>
          </div>
          <div class="stat-info">
            <div class="stat-number">{{ stats.total_tasks }}</div>
            <div class="stat-label">监控任务</div>
          </div>
        </el-card>
      </div>
      <div>
        <el-card class="stat-card stat-card-clickable" shadow="hover" @click="$router.push('/alerts')">
          <div class="stat-icon" style="background: linear-gradient(135deg, #f56c6c, #f89898)">
            <el-icon :size="24"><Warning /></el-icon>
          </div>
          <div class="stat-info">
            <div class="stat-number alert-color">{{ stats.alert_sku_count }}</div>
            <div class="stat-label">异动SKU</div>
          </div>
        </el-card>
      </div>
      <div>
        <el-card class="stat-card stat-card-clickable" shadow="hover" @click="$router.push('/alerts')">
          <div class="stat-icon" style="background: linear-gradient(135deg, #e6a23c, #f0c78a)">
            <el-icon :size="24"><Bell /></el-icon>
          </div>
          <div class="stat-info">
            <div class="stat-number">{{ stats.today_new_alerts }}</div>
            <div class="stat-label">今日新增</div>
          </div>
        </el-card>
      </div>
      <div>
        <el-card class="stat-card stat-card-clickable" shadow="hover" @click="$router.push('/logs')">
          <div class="stat-icon" :style="`background: linear-gradient(135deg, ${successRateColor}, ${successRateColorLight})`">
            <el-icon :size="24"><CircleCheck /></el-icon>
          </div>
          <div class="stat-info">
            <div class="stat-number" :style="{ color: successRateColor }">{{ stats.collect_success_rate }}%</div>
            <div class="stat-label">采集成功率</div>
          </div>
        </el-card>
      </div>
      <div>
        <el-card
          class="stat-card stat-card-clickable"
          shadow="hover"
          @click="$router.push('/browser')"
        >
          <div class="stat-icon" :style="`background: linear-gradient(135deg, ${accountColor}, ${accountColorLight})`">
            <el-icon :size="24"><UserFilled /></el-icon>
          </div>
          <div class="stat-info">
            <div class="stat-number" :style="{ color: accountColor }">{{ accountLabel }}</div>
            <div class="stat-label">账号状态</div>
          </div>
        </el-card>
      </div>
    </div>

    <el-row :gutter="16" class="content-row" style="margin-top: 16px">
      <!-- 最新异动 -->
      <el-col :span="12" :xs="24">
        <el-card shadow="hover">
          <template #header>
            <div class="card-header">
              <span class="card-title">最新异动</span>
              <el-button text type="primary" @click="$router.push('/alerts')">查看全部</el-button>
            </div>
          </template>
          <el-table
            v-if="latestAlerts.length > 0"
            :data="latestAlerts"
            size="small"
            :show-header="true"
            max-height="320"
          >
            <el-table-column prop="detected_at" label="时间" width="140">
              <template #default="{ row }">
                <span class="text-muted">{{ formatDateTime(row.detected_at) }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="shop_name" label="店铺" min-width="100" show-overflow-tooltip />
            <el-table-column prop="sku_name" label="SKU" min-width="100" show-overflow-tooltip />
            <el-table-column prop="price_diff_pct" label="价差率" width="90" align="right">
              <template #default="{ row }">
                <span class="price-negative">{{ row.price_diff_pct.toFixed(1) }}%</span>
              </template>
            </el-table-column>
          </el-table>
          <el-empty v-else description="暂无异动记录" :image-size="80" />
        </el-card>
      </el-col>

      <!-- 异动趋势 -->
      <el-col :span="12" :xs="24">
        <el-card shadow="hover">
          <template #header>
            <div class="card-header">
              <span class="card-title">异动趋势（近7天）</span>
            </div>
          </template>
          <div ref="trendChartRef" class="chart-container"></div>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="16" class="content-row" style="margin-top: 16px">
      <!-- 店铺违规排行 -->
      <el-col :span="12" :xs="24">
        <el-card shadow="hover">
          <template #header>
            <div class="card-header">
              <span class="card-title">店铺违规排行</span>
            </div>
          </template>
          <div ref="shopRankChartRef" class="chart-container"></div>
        </el-card>
      </el-col>

      <!-- 异动分布 -->
      <el-col :span="12" :xs="24">
        <el-card shadow="hover">
          <template #header>
            <div class="card-header">
              <span class="card-title">平台异动分布</span>
            </div>
          </template>
          <div ref="platformChartRef" class="chart-container"></div>
        </el-card>
      </el-col>
    </el-row>

    <!-- AI 健康状态 -->
    <el-row :gutter="16" class="content-row" style="margin-top: 16px">
      <el-col :span="8" :xs="24">
        <el-card shadow="hover" class="ai-health-card" @click="$router.push('/ai-panel')">
          <template #header>
            <div class="card-header">
              <span class="card-title">🤖 筱和智眸</span>
              <el-tag :type="aiStatus.is_running ? 'success' : 'info'" size="small">
                {{ aiStatus.is_running ? '运行中' : '已停止' }}
              </el-tag>
            </div>
          </template>
          <el-descriptions :column="1" size="small">
            <el-descriptions-item label="自治级别">
              <el-tag size="small" :type="aiAutonomyTag">{{ aiAutonomyLabel }}</el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="待处理报告">{{ aiStatus.recent_reports_count || 0 }}</el-descriptions-item>
          </el-descriptions>
        </el-card>
      </el-col>
      <el-col :span="16" :xs="24">
        <el-card shadow="hover">
          <template #header>
            <div class="card-header">
              <span class="card-title">最近 AI 报告</span>
              <el-button text type="primary" @click="$router.push('/ai-panel')">查看全部</el-button>
            </div>
          </template>
          <el-table
            v-if="aiReports.length > 0"
            :data="aiReports"
            size="small"
            max-height="200"
          >
            <el-table-column prop="timestamp" label="时间" width="140">
              <template #default="{ row }">
                <span class="text-muted">{{ formatDateTime(row.timestamp) }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="severity" label="级别" width="80">
              <template #default="{ row }">
                <el-tag size="small" :type="row.severity === 'critical' ? 'danger' : row.severity === 'warning' ? 'warning' : 'success'">{{ row.severity }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="title" label="标题" min-width="200" show-overflow-tooltip />
            <el-table-column prop="summary" label="摘要" min-width="250" show-overflow-tooltip />
          </el-table>
          <el-empty v-else description="暂无AI报告，系统运行正常" :image-size="60" />
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted, onBeforeUnmount, nextTick, computed } from 'vue'
import { dashboardApi, watchdogApi, formatDateTime } from '@/api'
import type { AlertSummary, TrendData, ShopRank, DashboardStats } from '@/api'
import * as echarts from 'echarts'

// 统计数据
const stats = reactive<DashboardStats>({
  total_tasks: 0,
  alert_sku_count: 0,
  today_new_alerts: 0,
  collect_success_rate: 100,
  account_status: 'normal',
})

// 最新异动
const latestAlerts = ref<AlertSummary[]>([])

// 图表ref
const trendChartRef = ref<HTMLElement>()
const shopRankChartRef = ref<HTMLElement>()
const platformChartRef = ref<HTMLElement>()

// 图表实例
let trendChart: echarts.ECharts | null = null
let shopRankChart: echarts.ECharts | null = null
let platformChart: echarts.ECharts | null = null

// 采集成功率颜色（UX-01）
const successRateColor = computed(() => {
  const rate = stats.collect_success_rate
  if (rate < 50) return '#f56c6c'
  if (rate < 80) return '#e6a23c'
  return '#67c23a'
})
const successRateColorLight = computed(() => {
  const rate = stats.collect_success_rate
  if (rate < 50) return '#f89898'
  if (rate < 80) return '#f0c78a'
  return '#95d475'
})

// 账号状态颜色
const accountColor = computed(() => {
  const map: Record<string, string> = { normal: '#67c23a', warning: '#e6a23c', error: '#f56c6c' }
  return map[stats.account_status] || '#909399'
})
const accountColorLight = computed(() => {
  const map: Record<string, string> = { normal: '#95d475', warning: '#f0c78a', error: '#f89898' }
  return map[stats.account_status] || '#c0c4cc'
})
const accountLabel = computed(() => {
  const map: Record<string, string> = { normal: '正常', warning: '异常', error: '失效' }
  return map[stats.account_status] || '未知'
})

// ===== 筱和智眸 =====
const aiStatus = reactive({ is_running: false, autonomy_level: 1, recent_reports_count: 0 })
const aiReports = ref<any[]>([])

const aiAutonomyLabel = computed(() => {
  const map: Record<number, string> = { 0: '全手动', 1: '观察', 2: '保守', 3: '激进' }
  return map[aiStatus.autonomy_level] || '未知'
})
const aiAutonomyTag = computed(() => {
  const map: Record<number, string> = { 0: 'info', 1: '', 2: 'warning', 3: 'danger' }
  return map[aiStatus.autonomy_level] || 'info'
})

async function loadAiData() {
  try {
    const s = await watchdogApi.status()
    Object.assign(aiStatus, s)
    const r = await watchdogApi.reports()
    aiReports.value = (r.reports || []).reverse().slice(0, 5)
  } catch (e) {
    // AI API可能未启用，静默忽略
  }
}

// 加载数据
async function loadData() {
  try {
    const data = await dashboardApi.getSummary()
    Object.assign(stats, data.stats)
    latestAlerts.value = data.latest_alerts
    await nextTick()
    renderTrendChart(data.trend_7days)
    renderShopRankChart(data.shop_rank)
    renderPlatformChart(data.shop_rank)
  } catch (e) {
    console.error('Dashboard load error:', e)
  }
}

// 异动趋势折线图
function renderTrendChart(data: TrendData[]) {
  if (!trendChartRef.value) return
  if (!trendChart) {
    trendChart = echarts.init(trendChartRef.value)
  }
  trendChart.setOption({
    tooltip: {
      trigger: 'axis',
      formatter: '{b}<br/>异动数量: <b>{c}</b>',
    },
    grid: { top: 20, right: 20, bottom: 30, left: 45 },
    xAxis: {
      type: 'category',
      data: data.map(d => d.date.slice(5)), // MM-DD
      axisLabel: { fontSize: 11, color: '#909399' },
      axisLine: { lineStyle: { color: '#e4e7ed' } },
    },
    yAxis: {
      type: 'value',
      minInterval: 1,
      axisLabel: { fontSize: 11, color: '#909399' },
      splitLine: { lineStyle: { color: '#f0f2f5', type: 'dashed' } },
    },
    series: [{
      data: data.map(d => d.count),
      type: 'line',
      smooth: true,
      lineStyle: { color: '#f56c6c', width: 2 },
      itemStyle: { color: '#f56c6c' },
      areaStyle: {
        color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
          { offset: 0, color: 'rgba(245, 108, 108, 0.25)' },
          { offset: 1, color: 'rgba(245, 108, 108, 0.02)' },
        ]),
      },
    }],
  })
}

// 店铺排行横向柱状图
function renderShopRankChart(data: ShopRank[]) {
  if (!shopRankChartRef.value) return
  if (!shopRankChart) {
    shopRankChart = echarts.init(shopRankChartRef.value)
  }
  const top5 = data.slice(0, 5).reverse()
  if (top5.length === 0) {
    shopRankChart.setOption({
      title: { text: '暂无数据', left: 'center', top: 'center', textStyle: { color: '#c0c4cc', fontSize: 14, fontWeight: 'normal' } },
    })
    return
  }
  shopRankChart.setOption({
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { top: 10, right: 30, bottom: 10, left: 10, containLabel: true },
    xAxis: {
      type: 'value',
      minInterval: 1,
      axisLabel: { fontSize: 11, color: '#909399' },
      splitLine: { lineStyle: { color: '#f0f2f5', type: 'dashed' } },
    },
    yAxis: {
      type: 'category',
      data: top5.map(d => d.shop_name.length > 8 ? d.shop_name.slice(0, 8) + '...' : d.shop_name),
      axisLabel: { fontSize: 11, color: '#606266' },
    },
    series: [{
      type: 'bar',
      data: top5.map(d => d.alert_count),
      barWidth: 16,
      itemStyle: {
        borderRadius: [0, 4, 4, 0],
        color: new echarts.graphic.LinearGradient(0, 0, 1, 0, [
          { offset: 0, color: '#f56c6c' },
          { offset: 1, color: '#f89898' },
        ]),
      },
    }],
  })
}

// 平台分布饼图
function renderPlatformChart(shopData: ShopRank[]) {
  if (!platformChartRef.value) return
  if (!platformChart) {
    platformChart = echarts.init(platformChartRef.value)
  }
  // 按平台汇总
  const platformMap: Record<string, number> = {}
  shopData.forEach(s => {
    const label = s.platform === 'tmall' ? '天猫' : s.platform === 'taobao' ? '淘宝' : s.platform
    platformMap[label] = (platformMap[label] || 0) + s.alert_count
  })
  const pieData = Object.entries(platformMap).map(([name, value]) => ({ name, value }))
  if (pieData.length === 0) {
    platformChart.setOption({
      title: { text: '暂无数据', left: 'center', top: 'center', textStyle: { color: '#c0c4cc', fontSize: 14, fontWeight: 'normal' } },
    })
    return
  }
  platformChart.setOption({
    tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
    legend: { bottom: 0, textStyle: { fontSize: 12 } },
    series: [{
      type: 'pie',
      radius: ['40%', '65%'],
      center: ['50%', '45%'],
      data: pieData,
      label: { show: true, formatter: '{b}\n{d}%', fontSize: 12 },
      emphasis: { itemStyle: { shadowBlur: 10, shadowOffsetX: 0, shadowColor: 'rgba(0,0,0,0.2)' } },
      itemStyle: {
        borderRadius: 4,
        borderColor: '#fff',
        borderWidth: 2,
      },
      color: ['#f56c6c', '#409eff', '#e6a23c', '#67c23a'],
    }],
  })
}

// 窗口resize处理
function handleResize() {
  trendChart?.resize()
  shopRankChart?.resize()
  platformChart?.resize()
}

onMounted(() => {
  loadData()
  loadAiData()
  window.addEventListener('resize', handleResize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  trendChart?.dispose()
  shopRankChart?.dispose()
  platformChart?.dispose()
})
</script>

<style scoped>
.dashboard {
  padding: 0;
}

/* 5 等分统计卡片网格 */
.stats-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 16px;
}
@media (max-width: 1280px) {
  .stats-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}
@media (max-width: 768px) {
  .stats-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

.stat-card-clickable {
  cursor: pointer;
  transition: transform var(--transition-fast), box-shadow var(--transition-fast);
}
.stat-card-clickable:hover {
  transform: translateY(-2px);
}

.stat-label-icon {
  margin-left: 4px;
  vertical-align: middle;
  font-size: 11px;
}

.stat-icon {
  width: 48px;
  height: 48px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  flex-shrink: 0;
}

.stat-info {
  flex: 1;
  min-width: 0;
}

.stat-number {
  font-size: 22px;
  font-weight: 700;
  color: #303133;
  line-height: 1.2;
}

.stat-number.alert-color {
  color: #f56c6c;
}

.stat-label {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
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

.chart-container {
  height: 280px;
  width: 100%;
}

.text-muted {
  color: #909399;
  font-size: 12px;
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

.stat-card .el-card__body {
  display: flex !important;
  align-items: center !important;
  gap: 14px !important;
  padding: 16px !important;
  width: 100% !important;
}
</style>
