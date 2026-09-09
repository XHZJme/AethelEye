<template>
  <div class="not-found">
    <div class="not-found-content">
      <el-result
        icon="error"
        title="页面不存在"
        sub-title="您访问的页面不存在或已被移除"
      >
        <template #extra>
          <el-button type="primary" @click="goHome">返回首页</el-button>
        </template>
      </el-result>
    </div>
    <footer class="page-copyright">2026 © XHZJ · 筱和灵眸</footer>
  </div>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router'

const router = useRouter()

function goHome() {
  router.push('/')
}
</script>

<style scoped>
.not-found {
  min-height: 100%;
  display: flex;
  flex-direction: column;
}

.not-found-content {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}

.page-copyright {
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-muted);
  font-size: 12px;
  border-top: 1px solid var(--border-color);
  background: #f8fafc;
}
</style>
