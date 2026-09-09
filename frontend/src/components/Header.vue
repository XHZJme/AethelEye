<template>
  <div class="header-content">
    <!-- 左侧：折叠按钮 + 搜索触发 -->
    <div class="header-left">
      <!-- 折叠按钮 -->
      <button class="collapse-btn" @click="$emit('toggleSidebar')" :title="sidebarCollapsed ? '展开侧边栏' : '折叠侧边栏'">
        <el-icon :size="18">
          <Fold v-if="!sidebarCollapsed" />
          <Expand v-if="sidebarCollapsed" />
        </el-icon>
      </button>

      <!-- 搜索触发器 -->
      <button class="search-trigger" @click="openSearch">
        <el-icon :size="15"><Search /></el-icon>
        <span class="search-placeholder">搜索任务、商品、店铺...</span>
        <kbd class="search-shortcut">
          <span>{{ isMac ? '⌘' : 'Ctrl' }}</span>
          <span>K</span>
        </kbd>
      </button>
    </div>

    <!-- 右侧：用户信息 -->
    <div class="header-right">
      <!-- 运行状态指示（可点击展开异常任务列表） -->
      <el-popover
        placement="bottom-end"
        :width="380"
        trigger="click"
        popper-class="status-popover"
      >
        <template #reference>
          <div class="status-dot clickable" :class="'dot-' + systemStatus">
            <span class="dot" :class="{ 'dot-pulse': systemStatus !== 'normal' }"></span>
            <span class="status-text">{{ statusLabel }}</span>
            <el-badge v-if="errorTasks.length > 0" :value="errorTasks.length" :max="99" class="status-badge" />
          </div>
        </template>
        <div class="status-popover-content">
          <div class="popover-header">
            <span class="popover-title">系统状态</span>
            <span class="popover-rate" :class="'rate-' + systemStatus">采集成功率 {{ successRate }}%</span>
          </div>
          <div v-if="errorTasks.length === 0" class="popover-empty">
            <el-icon :size="32" style="color: var(--success)"><CircleCheckFilled /></el-icon>
            <span>所有任务运行正常</span>
          </div>
          <div v-else class="popover-list">
            <div class="popover-list-header">异常任务 ({{ errorTasks.length }})</div>
            <div
              v-for="t in errorTasks"
              :key="t.id"
              class="popover-task-item"
              @click="goTaskDetail(t.id)"
            >
              <div class="task-item-main">
                <el-tag :type="taskStatusInfo(t.status).type" size="small" effect="plain" style="flex-shrink:0">
                  {{ taskStatusInfo(t.status).label }}
                </el-tag>
                <span class="task-item-title">{{ t.product_title || t.shop_name || '未命名任务' }}</span>
              </div>
              <div class="task-item-error" v-if="t.last_error">
                {{ t.last_error.length > 60 ? t.last_error.substring(0, 60) + '...' : t.last_error }}
              </div>
            </div>
          </div>
          <div class="popover-footer" v-if="errorTasks.length > 0">
            <el-button text type="primary" size="small" @click="goTaskListFiltered">查看全部异常任务</el-button>
          </div>
        </div>
      </el-popover>

      <!-- 用户下拉 -->
      <el-dropdown trigger="click" @command="handleCommand">
        <div class="user-avatar-btn">
          <div class="user-avatar">
            {{ avatarLetter }}
          </div>
          <div class="user-meta">
            <span class="user-name-text">{{ username }}</span>
            <span class="user-role-text">{{ roleText }}</span>
          </div>
          <el-icon :size="12" class="dropdown-arrow"><ArrowDown /></el-icon>
        </div>

        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item disabled>
              <el-icon><User /></el-icon>
              {{ username }} · {{ roleText }}
            </el-dropdown-item>
            <el-dropdown-item divided command="logout">
              <el-icon><SwitchButton /></el-icon>
              退出登录
            </el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, inject, ref, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { CircleCheckFilled } from '@element-plus/icons-vue'
import { useUserStore } from '@/stores/user'
import { dashboardApi, taskStatusInfo } from '@/api'
import type { ErrorTaskSummary } from '@/api'

// Props & Emits
defineProps<{
  sidebarCollapsed: boolean
}>()

defineEmits<{
  (e: 'toggleSidebar'): void
}>()

const router = useRouter()
const userStore = useUserStore()

// 注入搜索面板开关
const openSearch = inject<() => void>('openSearch', () => {})

// 平台检测
const isMac = navigator.platform.toLowerCase().includes('mac')

// 用户名
const username = computed(() => userStore.username || '用户')

// 角色文本
const roleText = computed(() => {
  const roleMap: Record<string, string> = {
    admin: '超级管理员',
    operator: '运营',
    viewer: '访客',
  }
  return roleMap[userStore.role] || userStore.role
})

// 头像首字母
const avatarLetter = computed(() => {
  const name = userStore.username || 'U'
  return name.charAt(0).toUpperCase()
})

// 系统状态（UX-01: 动态获取 + 异常任务列表 + 30s 轮询自动刷新）
const successRate = ref(100)
const errorTasks = ref<ErrorTaskSummary[]>([])
let statusPollTimer: ReturnType<typeof setInterval> | null = null

async function fetchSystemStatus() {
  try {
    const data = await dashboardApi.getSummary()
    successRate.value = data.stats.collect_success_rate
    errorTasks.value = data.error_tasks || []
  } catch { /* ignore */ }
}

onMounted(() => {
  fetchSystemStatus()
  statusPollTimer = setInterval(fetchSystemStatus, 30_000)
})

onUnmounted(() => {
  if (statusPollTimer) {
    clearInterval(statusPollTimer)
    statusPollTimer = null
  }
})
const systemStatus = computed(() => {
  if (errorTasks.value.length > 0 || successRate.value < 50) return 'error'
  if (successRate.value < 80) return 'warning'
  return 'normal'
})
const statusLabel = computed(() => {
  if (errorTasks.value.length > 0) return `${errorTasks.value.length}个异常`
  const map: Record<string, string> = { normal: '运行正常', warning: '采集异常', error: '采集异常' }
  return map[systemStatus.value] || '未知'
})

function goTaskDetail(taskId: number) {
  router.push(`/tasks/${taskId}`)
}

function goTaskListFiltered() {
  router.push({ path: '/tasks', query: { status: 'has_error' } })
}

// 下拉菜单命令
async function handleCommand(command: string) {
  if (command === 'logout') {
    await userStore.logout()
    ElMessage.success('已退出登录')
    router.push('/login')
  }
}
</script>

<style scoped>
.header-content {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  gap: 16px;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
  flex: 1;
  min-width: 0;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-shrink: 0;
}

/* 折叠按钮 */
.collapse-btn {
  width: 34px;
  height: 34px;
  border-radius: 8px;
  border: 1px solid var(--border-color);
  background: var(--bg-card);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-secondary);
  transition: all var(--transition-fast);
  flex-shrink: 0;
}

.collapse-btn:hover {
  border-color: var(--primary-light);
  color: var(--primary);
  background: var(--primary-glow);
  box-shadow: 0 2px 8px rgba(99, 102, 241, 0.1);
}

/* 搜索触发器 */
.search-trigger {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 14px;
  border: 1px solid var(--border-color);
  border-radius: var(--border-radius-sm);
  background: var(--bg-card);
  cursor: pointer;
  min-width: 280px;
  max-width: 420px;
  flex: 1;
  transition: all var(--transition-fast);
  color: var(--text-muted);
  font-family: inherit;
}

.search-trigger:hover {
  border-color: var(--primary-light);
  box-shadow: 0 2px 12px rgba(99, 102, 241, 0.08);
}

.search-placeholder {
  flex: 1;
  text-align: left;
  font-size: 13px;
  color: var(--text-muted);
}

.search-shortcut {
  display: flex;
  align-items: center;
  gap: 3px;
  flex-shrink: 0;
}

.search-shortcut span {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 20px;
  height: 20px;
  padding: 0 4px;
  border: 1px solid var(--border-color);
  border-radius: 4px;
  background: #f8fafc;
  font-size: 11px;
  font-family: inherit;
  color: var(--text-secondary);
}

/* 状态指示 */
.status-dot {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 20px;
  background: var(--success-bg);
  position: relative;
}

.status-dot.clickable {
  cursor: pointer;
  transition: all var(--transition-fast);
}

.status-dot.clickable:hover {
  filter: brightness(0.95);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
}

.status-dot.dot-warning {
  background: var(--warning-bg);
}

.status-dot.dot-error {
  background: var(--danger-bg);
}

.dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--success);
  flex-shrink: 0;
}

.dot-pulse {
  animation: dot-pulse 2s ease-in-out infinite;
}

@keyframes dot-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}

.dot-warning .dot { background: var(--warning); }
.dot-error .dot { background: var(--danger); }

.status-text {
  font-size: 12px;
  color: var(--text-secondary);
  font-weight: 500;
}

.status-badge {
  position: absolute;
  top: -6px;
  right: -6px;
}

/* Popover 内容 */
.status-popover-content {
  margin: -4px;
}

.popover-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--border-color, #ebeef5);
  margin-bottom: 8px;
}

.popover-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary, #303133);
}

.popover-rate {
  font-size: 12px;
  font-weight: 500;
}

.popover-rate.rate-normal { color: var(--success, #67c23a); }
.popover-rate.rate-warning { color: var(--warning, #e6a23c); }
.popover-rate.rate-error { color: var(--danger, #f56c6c); }

.popover-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 20px 0;
  color: var(--text-muted, #909399);
  font-size: 13px;
}

.popover-list-header {
  font-size: 12px;
  color: var(--text-muted, #909399);
  margin-bottom: 6px;
}

.popover-task-item {
  padding: 8px;
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.15s;
  margin-bottom: 2px;
}

.popover-task-item:hover {
  background: var(--bg-page, #f5f7fa);
}

.task-item-main {
  display: flex;
  align-items: center;
  gap: 8px;
}

.task-item-title {
  font-size: 13px;
  color: var(--text-primary, #303133);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.task-item-error {
  font-size: 11px;
  color: var(--danger, #f56c6c);
  margin-top: 4px;
  padding-left: 4px;
  line-height: 1.4;
}

.popover-list {
  max-height: 300px;
  overflow-y: auto;
}

.popover-footer {
  border-top: 1px solid var(--border-color, #ebeef5);
  margin-top: 8px;
  padding-top: 8px;
  text-align: center;
}

/* 用户头像块 */
.user-avatar-btn {
  display: flex;
  align-items: center;
  gap: 10px;
  cursor: pointer;
  padding: 4px 8px 4px 4px;
  border-radius: var(--border-radius-sm);
  transition: background var(--transition-fast);
}

.user-avatar-btn:hover {
  background: var(--bg-page);
}

.user-avatar {
  width: 34px;
  height: 34px;
  border-radius: 10px;
  background: var(--primary-gradient);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  font-weight: 600;
  flex-shrink: 0;
}

.user-meta {
  display: flex;
  flex-direction: column;
  line-height: 1.3;
}

.user-name-text {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}

.user-role-text {
  font-size: 11px;
  color: var(--text-muted);
}

.dropdown-arrow {
  color: var(--text-muted);
  transition: transform var(--transition-fast);
}

.user-avatar-btn:hover .dropdown-arrow {
  transform: rotate(180deg);
}

@media (max-width: 768px) {
  .search-trigger {
    min-width: 0;
    flex: 0;
    padding: 7px;
  }

  .search-placeholder,
  .search-shortcut {
    display: none;
  }

  .user-meta,
  .status-text {
    display: none;
  }
}
</style>
