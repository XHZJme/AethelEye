<template>
  <div class="login-container">
    <div class="login-box">
      <img class="brand-logo" :src="brandLogo" alt="筱和灵眸 Logo" />
      <h1 class="login-title">筱和灵眸</h1>
      <p class="login-subtitle">电商价格智能监控平台</p>

      <el-form
        ref="loginFormRef"
        :model="loginForm"
        :rules="loginRules"
        label-width="0"
        @submit.prevent="handleLogin"
      >
        <el-form-item prop="username">
          <el-input
            v-model="loginForm.username"
            placeholder="用户名"
            size="large"
            prefix-icon="User"
          />
        </el-form-item>

        <el-form-item prop="password">
          <el-input
            v-model="loginForm.password"
            type="password"
            placeholder="密码"
            size="large"
            prefix-icon="Lock"
            show-password
          />
        </el-form-item>

        <el-form-item>
          <el-checkbox v-model="loginForm.rememberMe">记住我</el-checkbox>
        </el-form-item>

        <el-form-item>
          <el-button
            type="primary"
            size="large"
            :loading="loading"
            @click="handleLogin"
            style="width: 100%"
          >
            登录
          </el-button>
        </el-form-item>
      </el-form>
    </div>

    <footer class="page-copyright">2026 © XHZJ · 筱和灵眸</footer>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { useUserStore } from '@/stores/user'
import brandLogo from '@/assets/brand-logo.png'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()

// 表单引用
const loginFormRef = ref<FormInstance>()
const loading = ref(false)

// 登录表单
const loginForm = reactive({
  username: '',
  password: '',
  rememberMe: false,
})

// 表单验证规则
const loginRules: FormRules = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    { min: 3, message: '用户名至少3个字符', trigger: 'blur' },
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, message: '密码至少6个字符', trigger: 'blur' },
  ],
}

// 检查系统是否需要初始化
onMounted(async () => {
  const status = await userStore.checkInitStatus()
  if (status.need_init) {
    router.push('/init')
  }
})

// 登录处理
async function handleLogin() {
  if (!loginFormRef.value) return

  await loginFormRef.value.validate(async (valid) => {
    if (!valid) return

    loading.value = true
    try {
      const success = await userStore.login(
        loginForm.username,
        loginForm.password,
        loginForm.rememberMe
      )

      if (success) {
        ElMessage.success('登录成功')
        router.push((route.query.redirect as string) || '/')
      } else {
        ElMessage.error('登录失败')
      }
    } finally {
      loading.value = false
    }
  })
}
</script>

<style scoped>
.brand-logo {
  width: 56px;
  height: 56px;
  display: block;
  margin: 0 auto 12px;
  object-fit: contain;
  border-radius: 12px;
}

.login-subtitle {
  text-align: center;
  color: #909399;
  margin-bottom: 30px;
  font-size: 14px;
}

.page-copyright {
  position: absolute;
  bottom: 18px;
  left: 0;
  width: 100%;
  text-align: center;
  color: rgba(255, 255, 255, 0.7);
  font-size: 12px;
  letter-spacing: 0.02em;
  z-index: 2;
}
</style>
