<template>
  <teleport to="body">
    <transition name="search-overlay">
      <div v-if="visible" class="search-overlay" @click.self="close">
        <div class="search-panel" @keydown="handleKeydown">
          <!-- 搜索输入区 -->
          <div class="search-panel-input">
            <el-icon><Search /></el-icon>
            <input
              ref="inputRef"
              v-model="query"
              placeholder="搜索任务、店铺、SKU…"
              @input="handleSearch"
            />
            <kbd class="search-kbd" @click="close">ESC</kbd>
          </div>

          <!-- 搜索结果 -->
          <div class="search-panel-results">
            <!-- 无搜索时：显示快捷入口 -->
            <template v-if="!query">
              <div class="search-result-group">
                <div class="search-result-group-title">快捷跳转</div>
                <div
                  v-for="(shortcut, idx) in shortcuts"
                  :key="shortcut.path"
                  class="search-result-item"
                  :class="{ active: activeIndex === idx }"
                  @click="goTo(shortcut.path)"
                  @mouseenter="activeIndex = idx"
                >
                  <div class="result-icon page">
                    <el-icon><component :is="shortcut.icon" /></el-icon>
                  </div>
                  <div class="result-text">
                    <div class="result-title">{{ shortcut.label }}</div>
                  </div>
                  <span class="result-shortcut">↵</span>
                </div>
              </div>
            </template>

            <!-- 搜索中 -->
            <template v-else-if="searching">
              <div class="search-empty">
                <el-icon class="is-loading" :size="20"><Loading /></el-icon>
                <div style="margin-top: 8px">搜索中...</div>
              </div>
            </template>

            <!-- 有结果 -->
            <template v-else-if="hasResults">
              <!-- 任务结果 -->
              <div v-if="taskResults.length > 0" class="search-result-group">
                <div class="search-result-group-title">监控任务</div>
                <div
                  v-for="task in taskResults"
                  :key="'t' + task.id"
                  class="search-result-item"
                  :class="{ active: activeIndex === getGlobalIndex('task', task) }"
                  @click="goTo(`/tasks/${task.id}`)"
                  @mouseenter="activeIndex = getGlobalIndex('task', task)"
                >
                  <div class="result-icon task">
                    <el-icon><Document /></el-icon>
                  </div>
                  <div class="result-text">
                    <div class="result-title">{{ task.product_title || task.url }}</div>
                    <div class="result-desc">{{ task.shop_name || task.platform }} · {{ taskStatusLabel(task.status) }}</div>
                  </div>
                  <span class="result-shortcut">↵</span>
                </div>
              </div>

              <!-- 异动结果 -->
              <div v-if="alertResults.length > 0" class="search-result-group">
                <div class="search-result-group-title">异动记录</div>
                <div
                  v-for="alert in alertResults"
                  :key="'a' + alert.id"
                  class="search-result-item"
                  :class="{ active: activeIndex === getGlobalIndex('alert', alert) }"
                  @click="goTo(`/tasks/${alert.task_id}`)"
                  @mouseenter="activeIndex = getGlobalIndex('alert', alert)"
                >
                  <div class="result-icon alert">
                    <el-icon><Bell /></el-icon>
                  </div>
                  <div class="result-text">
                    <div class="result-title">{{ alert.sku_name || alert.product_title || '异动' }}</div>
                    <div class="result-desc">{{ alert.shop_name }} · 价差 {{ alert.price_diff_pct?.toFixed(1) }}%</div>
                  </div>
                  <span class="result-shortcut">↵</span>
                </div>
              </div>
            </template>

            <!-- 无结果 -->
            <template v-else>
              <div class="search-empty">
                <div>未找到与「{{ query }}」相关的结果</div>
              </div>
            </template>
          </div>

          <!-- 底部提示 -->
          <div class="search-panel-footer">
            <span><kbd>↑</kbd><kbd>↓</kbd> 选择</span>
            <span><kbd>↵</kbd> 打开</span>
            <span><kbd>ESC</kbd> 关闭</span>
          </div>
        </div>
      </div>
    </transition>
  </teleport>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { tasksApi, alertsApi } from '@/api'
import type { TaskResponse, AlertResponse } from '@/api'

// Props & Emits
const props = defineProps<{
  visible: boolean
}>()

const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void
}>()

const router = useRouter()

// 搜索状态
const query = ref('')
const searching = ref(false)
const inputRef = ref<HTMLInputElement>()
const activeIndex = ref(0)

// 搜索结果
const taskResults = ref<TaskResponse[]>([])
const alertResults = ref<AlertResponse[]>([])

// 防抖定时器
let searchTimer: ReturnType<typeof setTimeout> | null = null

// 快捷入口
const shortcuts = [
  { path: '/', label: '总览 Dashboard', icon: 'Odometer' },
  { path: '/tasks', label: '监控任务', icon: 'Document' },
  { path: '/alerts', label: '异动记录', icon: 'Bell' },
  { path: '/browser', label: '浏览器管理', icon: 'Monitor' },
  { path: '/logs', label: '系统日志', icon: 'Tickets' },
  { path: '/settings', label: '系统设置', icon: 'Setting' },
]

// 是否有搜索结果
const hasResults = computed(() => taskResults.value.length > 0 || alertResults.value.length > 0)

// 全部结果列表（用于键盘导航）
const allItems = computed(() => {
  if (!query.value) return shortcuts.map(s => ({ type: 'shortcut' as const, data: s }))
  const items: Array<{ type: 'task' | 'alert'; data: TaskResponse | AlertResponse }> = []
  taskResults.value.forEach(t => items.push({ type: 'task', data: t }))
  alertResults.value.forEach(a => items.push({ type: 'alert', data: a }))
  return items
})

// 全局索引
function getGlobalIndex(type: 'task' | 'alert', item: TaskResponse | AlertResponse): number {
  if (type === 'task') {
    return taskResults.value.indexOf(item as TaskResponse)
  }
  return taskResults.value.length + alertResults.value.indexOf(item as AlertResponse)
}

// 任务状态标签
function taskStatusLabel(status: string): string {
  const map: Record<string, string> = { active: '运行中', paused: '已暂停', error: '异常', alert: '异动' }
  return map[status] || status
}

// 搜索（防抖）
function handleSearch() {
  if (searchTimer) clearTimeout(searchTimer)
  activeIndex.value = 0

  if (!query.value.trim()) {
    taskResults.value = []
    alertResults.value = []
    searching.value = false
    return
  }

  searching.value = true
  searchTimer = setTimeout(async () => {
    try {
      const [tasksRes, alertsRes] = await Promise.allSettled([
        tasksApi.list({ search: query.value.trim() }),
        alertsApi.list({ search: query.value.trim(), page_size: 5 }),
      ])

      taskResults.value = tasksRes.status === 'fulfilled' ? tasksRes.value.tasks.slice(0, 5) : []
      alertResults.value = alertsRes.status === 'fulfilled' ? alertsRes.value.alerts.slice(0, 5) : []
    } catch (e) {
      console.error('Search error:', e)
    } finally {
      searching.value = false
    }
  }, 300)
}

// 导航
function goTo(path: string) {
  close()
  router.push(path)
}

// 关闭
function close() {
  emit('update:visible', false)
  query.value = ''
  taskResults.value = []
  alertResults.value = []
  activeIndex.value = 0
}

// 键盘导航
function handleKeydown(e: KeyboardEvent) {
  const total = allItems.value.length
  if (!total) return

  if (e.key === 'ArrowDown') {
    e.preventDefault()
    activeIndex.value = (activeIndex.value + 1) % total
  } else if (e.key === 'ArrowUp') {
    e.preventDefault()
    activeIndex.value = (activeIndex.value - 1 + total) % total
  } else if (e.key === 'Enter') {
    e.preventDefault()
    const item = allItems.value[activeIndex.value]
    if (!item) return
    if ('path' in item.data) {
      goTo((item.data as { path: string }).path)
    } else if (item.type === 'task') {
      goTo(`/tasks/${(item.data as TaskResponse).id}`)
    } else if (item.type === 'alert') {
      goTo(`/tasks/${(item.data as AlertResponse).task_id}`)
    }
  } else if (e.key === 'Escape') {
    close()
  }
}

// 打开时聚焦
watch(() => props.visible, async (val) => {
  if (val) {
    await nextTick()
    inputRef.value?.focus()
  }
})
</script>

<style scoped>
/* 动画已在main.css中定义，这里添加transition name */
.search-overlay-enter-active,
.search-overlay-leave-active {
  transition: opacity 0.15s ease;
}

.search-overlay-enter-from,
.search-overlay-leave-to {
  opacity: 0;
}

.search-overlay-enter-active .search-panel {
  animation: panelIn 0.2s cubic-bezier(0.34, 1.56, 0.64, 1) both;
}

.search-overlay-leave-active .search-panel {
  animation: panelIn 0.15s ease reverse both;
}

@keyframes panelIn {
  from {
    opacity: 0;
    transform: translateY(-8px) scale(0.98);
  }
  to {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}

.is-loading {
  animation: rotate 1s linear infinite;
  color: var(--primary);
}

@keyframes rotate {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
</style>
