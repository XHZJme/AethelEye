<template>
  <div class="main-container" :class="{ 'is-mobile': isMobile, 'mobile-sidebar-open': mobileSidebarOpen }">
    <div v-if="isMobile && mobileSidebarOpen" class="mobile-sidebar-mask" @click="mobileSidebarOpen = false"></div>

    <!-- 侧边栏 -->
    <div class="sidebar-container" :class="{ collapsed: !isMobile && sidebarCollapsed, 'mobile-open': isMobile && mobileSidebarOpen }">
      <Sidebar :collapsed="isMobile ? false : sidebarCollapsed" @navigate="handleSidebarNavigate" />
    </div>

    <!-- 主内容区 -->
    <div class="main-content">
      <!-- 顶部栏 -->
      <div class="header-container">
        <Header
          :sidebar-collapsed="isMobile ? !mobileSidebarOpen : sidebarCollapsed"
          @toggle-sidebar="toggleSidebar"
        />
      </div>

      <!-- 内容区 -->
      <div class="content-container">
        <router-view v-slot="{ Component }">
          <transition name="page-fade" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </div>

      <footer class="global-copyright">
        2026 © XHZJ · 筱和灵眸
      </footer>
    </div>

    <!-- 全局搜索面板 -->
    <SearchPanel v-model:visible="searchVisible" />

    <!-- AI 对话浮窗 -->
    <AiChat />
  </div>
</template>

<script setup lang="ts">
import { ref, provide, onMounted, onBeforeUnmount } from 'vue'
import Sidebar from './Sidebar.vue'
import Header from './Header.vue'
import SearchPanel from './SearchPanel.vue'
import AiChat from './AiChat.vue'

// 侧边栏折叠状态
const sidebarCollapsed = ref(false)
const isMobile = ref(false)
const mobileSidebarOpen = ref(false)

// 全局搜索可见状态
const searchVisible = ref(false)

// 向子组件提供搜索开关方法
provide('openSearch', () => { searchVisible.value = true })

// 全局键盘监听 Ctrl+K / Cmd+K
function handleKeydown(e: KeyboardEvent) {
  if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
    e.preventDefault()
    searchVisible.value = true
  }
}

function syncViewport() {
  const mobile = window.innerWidth <= 992
  isMobile.value = mobile
  if (!mobile) mobileSidebarOpen.value = false
}

function toggleSidebar() {
  if (isMobile.value) {
    mobileSidebarOpen.value = !mobileSidebarOpen.value
  } else {
    sidebarCollapsed.value = !sidebarCollapsed.value
  }
}

function handleSidebarNavigate() {
  if (isMobile.value) {
    mobileSidebarOpen.value = false
  }
}

onMounted(() => {
  syncViewport()
  document.addEventListener('keydown', handleKeydown)
  window.addEventListener('resize', syncViewport)
})

onBeforeUnmount(() => {
  document.removeEventListener('keydown', handleKeydown)
  window.removeEventListener('resize', syncViewport)
})
</script>

<style scoped>
/* 页面进出动画 */
.page-fade-enter-active,
.page-fade-leave-active {
  transition: opacity 0.2s ease, transform 0.2s ease;
}

.page-fade-enter-from {
  opacity: 0;
  transform: translateY(6px);
}

.page-fade-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}

.global-copyright {
  height: 38px;
  border-top: 1px solid var(--border-color);
  background: #f8fafc;
  color: var(--text-muted);
  font-size: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
</style>
