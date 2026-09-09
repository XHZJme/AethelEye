<template>
  <div class="login-container">
    <div class="login-box">
      <img class="brand-logo" :src="brandLogo" alt="筱和灵眸 Logo" />
      <h1 class="login-title">筱和灵眸</h1>
      <p class="login-subtitle">首次使用，请创建管理员账号</p>

      <el-alert
        title="这是系统首次启动"
        description="请创建管理员账号，用于管理整个系统"
        type="info"
        show-icon
        :closable="false"
        style="margin-bottom: 20px"
      />

      <el-form
        ref="initFormRef"
        :model="initForm"
        :rules="initRules"
        label-width="80px"
        @submit.prevent="handleInit"
      >
        <el-form-item label="用户名" prop="username">
          <el-input
            v-model="initForm.username"
            placeholder="管理员用户名"
            prefix-icon="User"
          />
        </el-form-item>

        <el-form-item label="密码" prop="password">
          <el-input
            v-model="initForm.password"
            type="password"
            placeholder="管理员密码"
            prefix-icon="Lock"
            show-password
          />
        </el-form-item>

        <el-form-item label="确认密码" prop="confirmPassword">
          <el-input
            v-model="initForm.confirmPassword"
            type="password"
            placeholder="再次输入密码"
            prefix-icon="Lock"
            show-password
          />
        </el-form-item>

        <el-form-item>
          <el-button
            type="primary"
            :loading="loading"
            @click="handleInit"
            style="width: 100%"
          >
            创建管理员账号
          </el-button>
        </el-form-item>
      </el-form>
    </div>

    <footer class="page-copyright">2026 © XHZJ · 筱和灵眸</footer>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { useUserStore } from '@/stores/user'
import brandLogo from '@/assets/brand-logo.png'

const router = useRouter()
const userStore = useUserStore()

// 表单引用
const initFormRef = ref<FormInstance>()
const loading = ref(false)

// 初始化表单
const initForm = reactive({
  username: '',
  password: '',
  confirmPassword: '',
})

// 密码确认验证
const validateConfirmPassword = (_rule: any, value: string, callback: any) => {
  if (value !== initForm.password) {
    callback(new Error('两次输入的密码不一致'))
  } else {
    callback()
  }
}

// 表单验证规则
const initRules: FormRules = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    { min: 3, max: 50, message: '用户名长度需在3-50字符之间', trigger: 'blur' },
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, message: '密码至少6个字符', trigger: 'blur' },
  ],
  confirmPassword: [
    { required: true, message: '请再次输入密码', trigger: 'blur' },
    { validator: validateConfirmPassword, trigger: 'blur' },
  ],
}

onMounted(async () => {
  const status = await userStore.checkInitStatus()
  // 系统已初始化时，不允许停留在/init，避免误导用户
  if (!status.need_init) {
    router.replace('/login')
  }
})

// 初始化处理
async function handleInit() {
  if (!initFormRef.value) return

  await initFormRef.value.validate(async (valid) => {
    if (!valid) return

    loading.value = true
    try {
      const success = await userStore.initAdmin(
        initForm.username,
        initForm.password
      )

      if (success) {
        ElMessage.success('管理员账号创建成功，正在登录...')
        router.push('/')
      } else {
        ElMessage.error('创建失败')
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
  margin-bottom: 20px;
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
