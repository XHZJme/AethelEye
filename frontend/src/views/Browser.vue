<template>
  <div class="browser-page">
    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <span class="card-title">浏览器配置管理</span>
          <el-button type="primary" @click="showAddDialog">
            <el-icon><Plus /></el-icon>
            新建配置
          </el-button>
        </div>
      </template>

      <el-table v-loading="loading" :data="profiles" style="width: 100%" empty-text="暂无浏览器配置，请先创建">
        <el-table-column prop="name" label="配置名称" min-width="120">
          <template #default="{ row }">
            <div>
              <strong>{{ row.name }}</strong>
              <el-tag v-if="!row.is_active" type="info" size="small" style="margin-left: 6px">已停用</el-tag>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="platform" label="平台" width="80" align="center">
          <template #default="{ row }">
            <el-tag :type="row.platform === 'tmall' ? 'danger' : 'warning'" size="small" effect="plain">
              {{ row.platform === 'tmall' ? '天猫' : '淘宝' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="user_agent" label="User-Agent" min-width="180" show-overflow-tooltip>
          <template #default="{ row }">
            <span class="text-muted">{{ row.user_agent || '默认' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="分辨率" width="110" align="center">
          <template #default="{ row }">
            <span class="text-muted">{{ row.viewport_width }}×{{ row.viewport_height }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="proxy_type" label="代理" width="80" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.proxy_type !== 'none'" type="warning" size="small">{{ row.proxy_type }}</el-tag>
            <span v-else class="text-muted">无</span>
          </template>
        </el-table-column>
        <el-table-column prop="cookie_status" label="Cookie" width="100" align="center">
          <template #default="{ row }">
            <el-tag
              :type="row.cookie_status === 'valid' ? 'success' : row.cookie_status === 'expired' ? 'danger' : 'info'"
              size="small"
            >
              {{ cookieLabel(row.cookie_status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="last_login_at" label="最后登录" width="150">
          <template #default="{ row }">
            <span class="text-muted">{{ formatDateTime(row.last_login_at) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="360" fixed="right">
          <template #default="{ row }">
            <!-- 登录：下拉菜单 3 种登录方式 -->
            <el-dropdown split-button size="small" type="primary" @click="openMall(row)" trigger="click">
              登录
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item @click="openMall(row)"><el-icon style="margin-right:6px"><ChromeFilled /></el-icon>打开淘宝首页（手动登录）</el-dropdown-item>
                  <el-dropdown-item @click="openAutoLogin(row)"><el-icon style="margin-right:6px"><EditPen /></el-icon>账号密码自动填充</el-dropdown-item>
                  <el-dropdown-item @click="openImportCookie(row)"><el-icon style="margin-right:6px"><Upload /></el-icon>粘贴 Cookie JSON 导入</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
            <el-button size="small" text type="success" @click="saveCookies(row)">保存Cookie</el-button>
            <el-button size="small" text @click="closeBrowser(row)">关闭</el-button>
            <el-button size="small" text type="primary" @click="showEditDialog(row)">编辑</el-button>
            <el-button size="small" text type="danger" @click="handleDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 导入 Cookie 对话框 -->
    <el-dialog v-model="importDialogVisible" title="粘贴 Cookie JSON 导入" width="620px" destroy-on-close append-to-body>
      <el-alert type="info" show-icon :closable="false" style="margin-bottom: 12px">
        <template #title>
          支持两种格式：Playwright storage_state 的 cookies 数组，或 <code>{ "cookies": [...] }</code> 对象。
          每个 Cookie 至少需包含 <code>name / value / domain</code> 字段。
        </template>
      </el-alert>
      <el-input
        v-model="importText"
        type="textarea"
        :rows="12"
        placeholder='[\n  { "name": "t", "value": "...", "domain": ".tmall.com", "path": "/" },\n  ...\n]'
      />
      <template #footer>
        <el-button @click="importDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="importSubmitting" @click="submitImportCookie">导入</el-button>
      </template>
    </el-dialog>

    <!-- 新建/编辑对话框 -->
    <el-dialog v-model="dialogVisible" :title="isEdit ? '编辑配置' : '新建浏览器配置'" width="560px" destroy-on-close append-to-body>
      <el-form :model="form" label-width="100px" :rules="rules" ref="formRef">
        <el-form-item label="配置名称" prop="name">
          <el-input v-model="form.name" placeholder="如：天猫主账号" />
        </el-form-item>
        <el-form-item label="平台" prop="platform" v-if="!isEdit">
          <el-select v-model="form.platform" style="width: 100%">
            <el-option label="天猫" value="tmall" />
            <el-option label="淘宝" value="taobao" />
          </el-select>
        </el-form-item>

        <el-divider content-position="left">浏览器参数</el-divider>

        <el-form-item label="User-Agent">
          <el-input v-model="form.user_agent" placeholder="留空使用默认" />
        </el-form-item>
        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="宽度">
              <el-input-number v-model="form.viewport_width" :min="800" :max="3840" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="高度">
              <el-input-number v-model="form.viewport_height" :min="600" :max="2160" style="width: 100%" />
            </el-form-item>
          </el-col>
        </el-row>

        <el-divider content-position="left">平台登录凭证（可选，用于账号密码自动填充）</el-divider>
        <el-form-item label="平台账号">
          <el-input v-model="form.login_username" placeholder="淘宝/天猫账号，留空不自动填充" autocomplete="off" />
        </el-form-item>
        <el-form-item label="平台密码">
          <el-input v-model="form.login_password" type="password" show-password autocomplete="new-password" :placeholder="isEdit ? '留空不修改已保存的密码' : '密码将加密存储'" />
        </el-form-item>

        <el-divider content-position="left">代理设置</el-divider>

        <el-form-item label="代理类型">
          <el-select v-model="form.proxy_type" style="width: 100%">
            <el-option label="无代理" value="none" />
            <el-option label="HTTP" value="http" />
            <el-option label="SOCKS5" value="socks5" />
          </el-select>
        </el-form-item>
        <template v-if="form.proxy_type !== 'none'">
          <el-row :gutter="12">
            <el-col :span="16">
              <el-form-item label="主机">
                <el-input v-model="form.proxy_host" placeholder="代理地址" />
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="端口">
                <el-input-number v-model="form.proxy_port" :min="1" :max="65535" style="width: 100%" />
              </el-form-item>
            </el-col>
          </el-row>
          <el-row :gutter="12">
            <el-col :span="12">
              <el-form-item label="用户名">
                <el-input v-model="form.proxy_username" />
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="密码">
                <el-input v-model="form.proxy_password" type="password" show-password />
              </el-form-item>
            </el-col>
          </el-row>
        </template>

        <el-form-item label="启用" v-if="isEdit">
          <el-switch v-model="form.is_active" />
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitForm" :loading="submitting">
          {{ isEdit ? '保存' : '创建' }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted, h } from 'vue'
import { ElMessage, ElMessageBox, ElCheckbox } from 'element-plus'
import type { CheckboxValueType, FormInstance, FormRules } from 'element-plus'
import { browserApi, formatDateTime } from '@/api'
import type { BrowserProfile } from '@/api'

const loading = ref(false)
const profiles = ref<BrowserProfile[]>([])

// 对话框
const dialogVisible = ref(false)
const isEdit = ref(false)
const submitting = ref(false)
const formRef = ref<FormInstance>()
let editId = 0

const form = reactive({
  name: '',
  platform: 'tmall',
  user_agent: '',
  viewport_width: 1280,
  viewport_height: 720,
  proxy_type: 'none',
  proxy_host: '',
  proxy_port: 0,
  proxy_username: '',
  proxy_password: '',
  login_username: '',
  login_password: '',
  is_active: true,
})

const rules: FormRules = {
  name: [{ required: true, message: '请输入配置名称', trigger: 'blur' }],
}

// 加载
async function loadProfiles() {
  loading.value = true
  try {
    const res = await browserApi.list()
    profiles.value = res.profiles
  } catch (e) {
    console.error(e)
  } finally {
    loading.value = false
  }
}

// 新建
function showAddDialog() {
  isEdit.value = false
  Object.assign(form, {
    name: '', platform: 'tmall', user_agent: '',
    viewport_width: 1280, viewport_height: 720,
    proxy_type: 'none', proxy_host: '', proxy_port: 0,
    proxy_username: '', proxy_password: '',
    login_username: '', login_password: '',
    is_active: true,
  })
  dialogVisible.value = true
}

// 编辑
function showEditDialog(row: BrowserProfile) {
  isEdit.value = true
  editId = row.id
  Object.assign(form, {
    name: row.name,
    platform: row.platform,
    user_agent: row.user_agent || '',
    viewport_width: row.viewport_width,
    viewport_height: row.viewport_height,
    proxy_type: row.proxy_type,
    proxy_host: row.proxy_host || '',
    proxy_port: row.proxy_port || 0,
    proxy_username: '',
    proxy_password: '',
    login_username: '',
    login_password: '',
    is_active: row.is_active,
  })
  dialogVisible.value = true
}

// 提交
async function submitForm() {
  try {
    await formRef.value?.validate()
  } catch { return }

  submitting.value = true
  try {
    const data: Record<string, unknown> = { name: form.name }
    if (form.user_agent) data.user_agent = form.user_agent
    data.viewport_width = form.viewport_width
    data.viewport_height = form.viewport_height
    data.proxy_type = form.proxy_type
    if (form.proxy_type !== 'none') {
      if (form.proxy_host) data.proxy_host = form.proxy_host
      if (form.proxy_port) data.proxy_port = form.proxy_port
      if (form.proxy_username) data.proxy_username = form.proxy_username
      if (form.proxy_password) data.proxy_password = form.proxy_password
    }
    if (form.login_username) data.login_username = form.login_username
    if (form.login_password) data.login_password = form.login_password

    if (isEdit.value) {
      data.is_active = form.is_active
      await browserApi.update(editId, data)
      ElMessage.success('配置已更新')
    } else {
      data.platform = form.platform
      await browserApi.create(data as never)
      ElMessage.success('配置已创建')
    }
    dialogVisible.value = false
    loadProfiles()
  } catch (e) {
    console.error(e)
  } finally {
    submitting.value = false
  }
}

// 删除
async function handleDelete(row: BrowserProfile) {
  try {
    await ElMessageBox.confirm(`确定删除配置「${row.name}」？`, '删除确认', { type: 'warning' })
    await browserApi.delete(row.id)
    ElMessage.success('配置已删除')
    loadProfiles()
  } catch (e) {
    // 取消
  }
}

// 方式 1：打开淘宝首页（手动登录）
async function openMall(row: BrowserProfile) {
  try {
    const res = await browserApi.openVisual(row.id, {
      url: 'https://www.taobao.com',
      timeout_seconds: 300,
    })
    ElMessage.success(res.message || '浏览器已打开，请在窗口中点击「登录」并完成身份验证，完成后点「保存Cookie」')
  } catch (e) {
    console.error(e)
  }
}

// 方式 2：账号密码自动填充
const autoSubmitRef = ref(false)
async function openAutoLogin(row: BrowserProfile) {
  if (!row.has_login_credentials) {
    ElMessageBox.confirm(
      '该配置尚未保存平台账号密码。请先点击「编辑」填入账号密码后再使用此功能。',
      '账号密码未配置',
      { confirmButtonText: '去编辑', cancelButtonText: '取消', type: 'warning' }
    ).then(() => showEditDialog(row)).catch(() => {})
    return
  }
  autoSubmitRef.value = false
  try {
    await ElMessageBox({
      title: '自动登录',
      message: h('div', null, [
        h('p', { style: 'margin: 0 0 10px' }, '将打开可视化浏览器并自动填充账号密码。'),
        h('p', { style: 'margin: 0 0 12px; color: #909399; font-size: 13px;' },
          '如出现滑块 / 短信验证，请在浏览器窗口内手动完成，登录后点「保存Cookie」。'),
        h(ElCheckbox, {
          modelValue: autoSubmitRef.value,
          'onUpdate:modelValue': (v: CheckboxValueType) => {
            autoSubmitRef.value = Boolean(v)
          },
        }, { default: () => '自动点击「登录」按钮（可能触发滑块，需手动过）' }),
      ]),
      confirmButtonText: '开始',
      cancelButtonText: '取消',
      showCancelButton: true,
      type: 'info',
    })
  } catch { return }
  try {
    const res = await browserApi.autoLogin(row.id, { auto_submit: autoSubmitRef.value })
    ElMessage.success(res.message || '已自动填充账号密码，请在浏览器窗口完成验证')
  } catch (e) {
    console.error(e)
  }
}

// 方式 3：粘贴 Cookie JSON 导入
const importDialogVisible = ref(false)
const importTarget = ref<BrowserProfile | null>(null)
const importText = ref('')
const importSubmitting = ref(false)

function openImportCookie(row: BrowserProfile) {
  importTarget.value = row
  importText.value = ''
  importDialogVisible.value = true
}

async function submitImportCookie() {
  if (!importTarget.value) return
  const raw = importText.value.trim()
  if (!raw) {
    ElMessage.warning('请粘贴 Cookie JSON 后再导入')
    return
  }
  let parsed: unknown
  try {
    parsed = JSON.parse(raw)
  } catch (e) {
    ElMessage.error('JSON 解析失败，请检查格式')
    return
  }
  // 支持两种输入：数组 or { cookies: [...] }
  let cookies: unknown[] = []
  if (Array.isArray(parsed)) {
    cookies = parsed
  } else if (parsed && typeof parsed === 'object' && Array.isArray((parsed as { cookies?: unknown[] }).cookies)) {
    cookies = (parsed as { cookies: unknown[] }).cookies
  } else {
    ElMessage.error('格式必须为 Cookie 数组或 { cookies: [...] }')
    return
  }
  if (cookies.length === 0) {
    ElMessage.warning('未解析到任何 Cookie')
    return
  }
  importSubmitting.value = true
  try {
    const res = await browserApi.importCookies(importTarget.value.id, cookies)
    ElMessage.success(res.message || `已导入 ${res.cookie_count} 条 Cookie`)
    importDialogVisible.value = false
    loadProfiles()
  } catch (e) {
    console.error(e)
  } finally {
    importSubmitting.value = false
  }
}

async function saveCookies(row: BrowserProfile) {
  try {
    const res = await browserApi.saveCookies(row.id)
    ElMessage.success(res.message || 'Cookie已保存')
    loadProfiles()
  } catch (e) {
    console.error(e)
  }
}

async function closeBrowser(row: BrowserProfile) {
  try {
    const res = await browserApi.close(row.id)
    ElMessage.success(res.message || '浏览器已关闭')
  } catch (e) {
    console.error(e)
  }
}

function cookieLabel(status: string): string {
  const map: Record<string, string> = { valid: '有效', expired: '已过期', none: '未登录' }
  return map[status] || status
}

onMounted(() => loadProfiles())
</script>

<style scoped>
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

.text-muted {
  font-size: 12px;
  color: #909399;
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
