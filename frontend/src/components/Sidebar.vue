<template>
  <div class="sidebar" :class="{ collapsed }">
    <!-- Logo区域 -->
    <div class="sidebar-logo">
      <div class="logo-icon">
        <img :src="brandLogo" alt="筱和灵眸 Logo" />
      </div>
      <transition name="fade-text">
        <span v-if="!collapsed" class="logo-text">筱和灵眸</span>
      </transition>
    </div>

    <!-- 菜单列表 -->
    <nav class="sidebar-nav">
      <div
        v-for="item in menuItems"
        :key="item.path"
        class="nav-item"
        :class="{ active: isActive(item.path) }"
        @click="navigateTo(item.path)"
      >
        <el-tooltip :content="item.label" placement="right" :disabled="!collapsed">
          <div class="nav-item-inner">
            <el-icon :size="20"><component :is="item.icon" /></el-icon>
            <transition name="fade-text">
              <span v-if="!collapsed" class="nav-label">{{ item.label }}</span>
            </transition>
            <transition name="fade-text">
              <span v-if="!collapsed && item.badge" class="nav-badge badge-pulse">{{ item.badge }}</span>
            </transition>
          </div>
        </el-tooltip>
      </div>

      <!-- 管理员菜单 -->
      <template v-if="isAdmin && adminItems.length > 0">
        <div class="nav-divider">
          <div class="divider-line"></div>
        </div>
        <div
          v-for="item in adminItems"
          :key="item.path"
          class="nav-item"
          :class="{ active: isActive(item.path) }"
          @click="navigateTo(item.path)"
        >
          <el-tooltip :content="item.label" placement="right" :disabled="!collapsed">
            <div class="nav-item-inner">
              <template v-if="item.iconSvg">
                <span class="custom-icon" v-html="item.iconSvg"></span>
              </template>
              <el-icon v-else :size="20"><component :is="item.icon" /></el-icon>
              <transition name="fade-text">
                <span v-if="!collapsed" class="nav-label">{{ item.label }}</span>
              </transition>
            </div>
          </el-tooltip>
        </div>
      </template>
    </nav>

    <!-- 底部版本信息 -->
    <div class="sidebar-footer">
      <transition name="fade-text">
        <span v-if="!collapsed" class="version-text">AethelEye v2.0</span>
      </transition>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useUserStore } from '@/stores/user'
import brandLogo from '@/assets/brand-logo.png'

interface MenuItem {
  path: string
  label: string
  icon?: string
  iconSvg?: string
  badge?: number
}

// Props
defineProps<{
  collapsed: boolean
}>()

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const emit = defineEmits<{
  (e: 'navigate'): void
}>()

// 是否为管理员
const isAdmin = computed(() => userStore.isAdmin)

// 主菜单
const menuItems: MenuItem[] = [
  { path: '/', label: '数据总览', icon: 'Odometer' },
  { path: '/tasks', label: '监控任务', icon: 'Document' },
  { path: '/alerts', label: '异动记录', icon: 'Bell' },
  { path: '/browser', label: '浏览器配置', icon: 'Monitor' },
]

// 管理员菜单
const adminItems: MenuItem[] = [
  { path: '/ai-panel', label: '筱和智眸', iconSvg: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="7" width="14" height="10" rx="2"/><circle cx="9" cy="12" r="1.2" fill="currentColor" stroke="none"/><circle cx="15" cy="12" r="1.2" fill="currentColor" stroke="none"/><path d="M9 17v2M15 17v2"/><path d="M12 7V4"/><circle cx="12" cy="3" r="1" fill="currentColor" stroke="none"/><path d="M3 11h2M19 11h2"/></svg>' },
  { path: '/plugins', label: '应用市场', icon: 'Grid' },
  { path: '/users', label: '用户管理', icon: 'User' },
  { path: '/logs', label: '系统日志', icon: 'Tickets' },
  { path: '/settings', label: '系统设置', icon: 'Setting' },
]

// 当前路由是否匹配
function isActive(path: string): boolean {
  if (path === '/') return route.path === '/'
  return route.path.startsWith(path)
}

// 导航
function navigateTo(path: string) {
  router.push(path)
  emit('navigate')
}
</script>

<style scoped>
.sidebar {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: linear-gradient(180deg, #0f172a 0%, #1a1f3a 100%);
  overflow: hidden;
  user-select: none;
}

/* Logo */
.sidebar-logo {
  height: 60px;
  display: flex;
  align-items: center;
  padding: 0 16px;
  gap: 12px;
  flex-shrink: 0;
  border-bottom: 1px solid rgba(148, 163, 184, 0.06);
}

.collapsed .sidebar-logo {
  justify-content: center;
  padding: 0;
}

.logo-icon {
  width: 34px;
  height: 34px;
  flex-shrink: 0;
}

.logo-icon img {
  width: 100%;
  height: 100%;
  object-fit: contain;
  border-radius: 8px;
  filter: drop-shadow(0 2px 8px rgba(99, 102, 241, 0.28));
}

.logo-text {
  font-size: 17px;
  font-weight: 700;
  color: #e2e8f0;
  letter-spacing: 0.04em;
  white-space: nowrap;
}

/* Navigation */
.sidebar-nav {
  flex: 1;
  padding: 12px 8px;
  overflow-y: auto;
  overflow-x: hidden;
}

.nav-item {
  margin-bottom: 2px;
}

.nav-item-inner {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  border-radius: 10px;
  cursor: pointer;
  color: #7c8db5;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
  position: relative;
  white-space: nowrap;
}

.collapsed .nav-item-inner {
  justify-content: center;
  padding: 10px;
}

.nav-item-inner:hover {
  background: rgba(99, 102, 241, 0.08);
  color: #c7d2e8;
}

.nav-item.active .nav-item-inner {
  background: rgba(99, 102, 241, 0.18);
  color: #ffffff;
  box-shadow: 0 0 16px rgba(99, 102, 241, 0.12);
}

.nav-item.active .nav-item-inner::before {
  content: '';
  position: absolute;
  left: -8px;
  top: 50%;
  transform: translateY(-50%);
  width: 3px;
  height: 20px;
  border-radius: 0 3px 3px 0;
  background: linear-gradient(180deg, #818cf8, #6366f1);
}

.collapsed .nav-item.active .nav-item-inner::before {
  display: none;
}

.nav-label {
  font-size: 14px;
  font-weight: 500;
}

.nav-badge {
  margin-left: auto;
  min-width: 20px;
  height: 20px;
  padding: 0 6px;
  border-radius: 10px;
  background: #ef4444;
  color: #fff;
  font-size: 11px;
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: center;
}

/* Divider */
.nav-divider {
  padding: 10px 12px;
  display: flex;
  align-items: center;
}

.divider-line {
  width: 100%;
  height: 1px;
  background: rgba(148, 163, 184, 0.1);
}

.collapsed .nav-divider {
  padding: 10px 8px;
}

/* Custom SVG Icon */
.custom-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  flex-shrink: 0;
}
.custom-icon svg {
  width: 20px;
  height: 20px;
}

/* Footer */
.sidebar-footer {
  padding: 12px 16px;
  border-top: 1px solid rgba(148, 163, 184, 0.06);
  flex-shrink: 0;
  display: flex;
  justify-content: center;
}

.version-text {
  font-size: 11px;
  color: #475569;
  white-space: nowrap;
}

/* Text Fade Transition */
.fade-text-enter-active,
.fade-text-leave-active {
  transition: opacity 0.15s ease, transform 0.15s ease;
}

.fade-text-enter-from,
.fade-text-leave-to {
  opacity: 0;
  transform: translateX(-4px);
}
</style>
