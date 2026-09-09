<template>
  <div class="users-page">
    <el-card>
      <template #header>
        <div class="card-header">
          <span>用户管理</span>
          <el-button type="primary" @click="handleAdd">
            <el-icon><Plus /></el-icon>
            新建用户
          </el-button>
        </div>
      </template>

      <!-- 用户表格 -->
      <el-table :data="users" style="width: 100%" v-loading="loading">
        <el-table-column prop="id" label="ID" width="80" />
        <el-table-column prop="username" label="用户名" />
        <el-table-column prop="role" label="角色">
          <template #default="{ row }">
            <el-tag :type="getRoleType(row.role)">{{ getRoleText(row.role) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="is_active" label="状态">
          <template #default="{ row }">
            <el-tag :type="row.is_active ? 'success' : 'danger'">
              {{ row.is_active ? '正常' : '禁用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="180">
          <template #default="{ row }">
            {{ formatDate(row.created_at) }}
          </template>
        </el-table-column>
        <el-table-column prop="last_login_at" label="最后登录" width="180">
          <template #default="{ row }">
            {{ row.last_login_at ? formatDate(row.last_login_at) : '-' }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="200">
          <template #default="{ row }">
            <el-button size="small" @click="handleEdit(row)">编辑</el-button>
            <el-button size="small" @click="handleResetPassword(row)">重置密码</el-button>
            <el-button size="small" type="danger" @click="handleDelete(row)" v-if="row.id !== currentUserId">
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 新建/编辑用户对话框 -->
    <el-dialog v-model="dialogVisible" :title="dialogTitle" width="400px" append-to-body>
      <el-form :model="userForm" label-width="80px">
        <el-form-item label="用户名">
          <el-input v-model="userForm.username" />
        </el-form-item>
        <el-form-item label="角色">
          <el-select v-model="userForm.role">
            <el-option label="超级管理员" value="admin" />
            <el-option label="运营" value="operator" />
            <el-option label="访客" value="viewer" />
          </el-select>
        </el-form-item>
        <el-form-item label="状态">
          <el-switch v-model="userForm.is_active" active-text="启用" inactive-text="禁用" />
        </el-form-item>
        <el-form-item label="密码" v-if="isNewUser">
          <el-input v-model="userForm.password" type="password" show-password />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleSave">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { usersApi, type User } from '@/api'
import { useUserStore } from '@/stores/user'

const userStore = useUserStore()

// 数据
const users = ref<User[]>([])
const loading = ref(false)

// 当前用户ID（不允许删除自己）
const currentUserId = computed(() => userStore.userInfo?.id)

// 对话框
const dialogVisible = ref(false)
const dialogTitle = ref('')
const isNewUser = ref(false)
const editingUserId = ref<number | null>(null)

// 用户表单
const userForm = reactive({
  username: '',
  role: 'operator',
  is_active: true,
  password: '',
})

// 加载用户列表
async function loadUsers() {
  loading.value = true
  try {
    const result = await usersApi.list()
    users.value = result.users
  } finally {
    loading.value = false
  }
}

// 添加用户
function handleAdd() {
  isNewUser.value = true
  editingUserId.value = null
  userForm.username = ''
  userForm.role = 'operator'
  userForm.is_active = true
  userForm.password = ''
  dialogTitle.value = '新建用户'
  dialogVisible.value = true
}

// 编辑用户
function handleEdit(user: User) {
  isNewUser.value = false
  editingUserId.value = user.id
  userForm.username = user.username
  userForm.role = user.role
  userForm.is_active = user.is_active
  userForm.password = ''
  dialogTitle.value = '编辑用户'
  dialogVisible.value = true
}

// 保存用户
async function handleSave() {
  try {
    if (isNewUser.value) {
      // 创建新用户
      if (!userForm.password) {
        ElMessage.warning('请输入密码')
        return
      }
      await usersApi.create({
        username: userForm.username,
        password: userForm.password,
        role: userForm.role,
      })
      ElMessage.success('用户创建成功')
    } else {
      // 更新用户
      await usersApi.update(editingUserId.value!, {
        username: userForm.username,
        role: userForm.role,
        is_active: userForm.is_active,
      })
      ElMessage.success('用户更新成功')
    }
    dialogVisible.value = false
    loadUsers()
  } catch (error) {
    // 错误已在API层处理
  }
}

// 重置密码
async function handleResetPassword(user: User) {
  const { value } = await ElMessageBox.prompt('请输入新密码', '重置密码', {
    inputPattern: /^.{6,}$/,
    inputErrorMessage: '密码至少6个字符',
  })
  if (value) {
    await usersApi.resetPassword(user.id, value)
    ElMessage.success('密码已重置')
  }
}

// 删除用户
async function handleDelete(user: User) {
  await ElMessageBox.confirm(`确定删除用户 "${user.username}"？`, '删除用户', {
    type: 'warning',
  })
  await usersApi.delete(user.id)
  ElMessage.success('用户已删除')
  loadUsers()
}

// 辅助函数
function getRoleType(role: string) {
  const map: Record<string, string> = { admin: 'danger', operator: 'primary', viewer: 'info' }
  return map[role] || 'info'
}

function getRoleText(role: string) {
  const map: Record<string, string> = { admin: '超级管理员', operator: '运营', viewer: '访客' }
  return map[role] || role
}

function formatDate(date: string) {
  return new Date(date).toLocaleString('zh-CN')
}

// 初始化
onMounted(() => {
  loadUsers()
})
</script>

<style scoped>
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

:deep(.el-dialog) {
  max-height: 85vh;
  display: flex;
  flex-direction: column;
}

:deep(.el-dialog__body) {
  max-height: 60vh;
  overflow-y: auto;
}
</style>
