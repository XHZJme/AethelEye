<template>
  <div class="page-container">
    <div class="page-header">
      <h2>应用市场</h2>
      <div class="header-actions">
        <el-upload
          :show-file-list="false"
          :before-upload="handleUpload"
          accept=".zip"
        >
          <el-button type="primary" :icon="Upload">上传插件</el-button>
        </el-upload>
      </div>
    </div>

    <el-tabs v-model="activeTab">
      <el-tab-pane label="已安装" name="installed">
        <el-table :data="installedPlugins" v-loading="loading" stripe>
          <el-table-column prop="display_name" label="名称" min-width="150" />
          <el-table-column prop="plugin_type" label="类型" width="100">
            <template #default="{ row }">
              <el-tag size="small" :type="typeTagColor(row.plugin_type)">{{ typeLabel(row.plugin_type) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="version" label="版本" width="80" />
          <el-table-column prop="author" label="作者" width="100" />
          <el-table-column prop="status" label="状态" width="100">
            <template #default="{ row }">
              <el-tag size="small" :type="statusTagColor(row.status)">{{ statusLabel(row.status) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="is_enabled" label="启用" width="70">
            <template #default="{ row }">
              <el-switch
                v-model="row.is_enabled"
                :disabled="row.status !== 'approved'"
                @change="handleToggle(row)"
                size="small"
              />
            </template>
          </el-table-column>
          <el-table-column prop="description" label="描述" min-width="180" show-overflow-tooltip />
          <el-table-column label="操作" width="280" fixed="right">
            <template #default="{ row }">
              <el-button
                v-if="row.status === 'pending'"
                type="success"
                size="small"
                @click="handleReview(row, 'approve')"
              >审核通过</el-button>
              <el-button
                v-if="row.status === 'pending'"
                type="warning"
                size="small"
                @click="handleReview(row, 'reject')"
              >拒绝</el-button>
              <el-button
                v-if="row.is_enabled"
                type="primary"
                size="small"
                :loading="row._executing"
                @click="handleExecute(row)"
              >执行</el-button>
              <el-button
                type="danger"
                size="small"
                @click="handleDelete(row)"
              >卸载</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="执行记录" name="execlog" v-if="execResults.length">
        <div v-for="(r, i) in execResults" :key="i" class="exec-result-item">
          <div class="exec-result-header">
            <el-tag :type="r.success ? 'success' : 'danger'" size="small">{{ r.success ? '成功' : '失败' }}</el-tag>
            <span class="exec-result-name">{{ r.pluginName }} / {{ r.functionName }}</span>
            <span class="exec-result-time">{{ r.time }}</span>
          </div>
          <pre class="exec-result-output">{{ r.output }}</pre>
        </div>
      </el-tab-pane>

      <el-tab-pane label="插件说明" name="info">
        <div class="info-section">
          <h3>插件类型</h3>
          <el-descriptions :column="1" border>
            <el-descriptions-item label="引擎插件 (engine)">新的采集引擎（如京东解析器）</el-descriptions-item>
            <el-descriptions-item label="分析插件 (analysis)">数据分析/可视化</el-descriptions-item>
            <el-descriptions-item label="告警插件 (alert)">新的告警通道（钉钉/飞书/邮件）</el-descriptions-item>
            <el-descriptions-item label="工具插件 (tool)">辅助功能（批量导入/报表生成）</el-descriptions-item>
            <el-descriptions-item label="MCP扩展 (mcp)">MCP Server/Client 定义</el-descriptions-item>
            <el-descriptions-item label="技能包 (skill)">可复用的AI能力包</el-descriptions-item>
          </el-descriptions>

          <h3 style="margin-top: 20px">插件包格式</h3>
          <el-alert type="info" :closable="false" show-icon>
            <template #title>
              将以下文件打包为 ZIP 上传：manifest.json（必需）、main.py（入口）、requirements.txt（可选）、README.md（可选）
            </template>
          </el-alert>

          <h3 style="margin-top: 20px">安全说明</h3>
          <el-alert type="warning" :closable="false" show-icon>
            <template #title>
              所有插件必须经管理员审核后才能启用运行。插件在受限沙箱中执行，禁止直接访问网络、数据库和系统命令。
            </template>
          </el-alert>
        </div>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Upload } from '@element-plus/icons-vue'
import { pluginsApi } from '@/api'

const activeTab = ref('installed')
const loading = ref(false)
const plugins = ref<any[]>([])
const execResults = reactive<Array<{ pluginName: string; functionName: string; success: boolean; output: string; time: string }>>([])

const installedPlugins = computed(() => plugins.value)

async function loadPlugins() {
  loading.value = true
  try {
    const data = await pluginsApi.list()
    plugins.value = data.plugins || []
  } catch (e) {
    console.error('Failed to load plugins:', e)
  } finally {
    loading.value = false
  }
}

async function handleUpload(file: File) {
  try {
    const result = await pluginsApi.upload(file)
    ElMessage.success(result.message)
    await loadPlugins()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '上传失败')
  }
  return false
}

async function handleReview(row: any, action: string) {
  if (action === 'reject') {
    try {
      const { value } = await ElMessageBox.prompt('请输入拒绝原因', '拒绝插件', {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
      })
      await pluginsApi.review(row.id, 'reject', value)
      ElMessage.warning('插件已拒绝')
    } catch (e: any) {
      if (e !== 'cancel') ElMessage.error('操作失败')
    }
  } else {
    try {
      await pluginsApi.review(row.id, 'approve')
      ElMessage.success('插件已审核通过')
    } catch (e: any) {
      ElMessage.error(e?.response?.data?.detail || '操作失败')
    }
  }
  await loadPlugins()
}

async function handleToggle(row: any) {
  try {
    await pluginsApi.toggle(row.id, row.is_enabled)
    ElMessage.success(`插件已${row.is_enabled ? '启用' : '禁用'}`)
  } catch (e: any) {
    row.is_enabled = !row.is_enabled
    ElMessage.error(e?.response?.data?.detail || '操作失败')
  }
}

async function handleExecute(row: any) {
  let funcName = 'run'
  try {
    const { value } = await ElMessageBox.prompt(
      `输入要执行的函数名（默认 run）`,
      `执行插件: ${row.display_name}`,
      {
        confirmButtonText: '执行',
        cancelButtonText: '取消',
        inputValue: 'run',
      }
    )
    funcName = value || 'run'
  } catch {
    return
  }

  row._executing = true
  try {
    const result = await pluginsApi.execute(row.id, funcName)
    const output = typeof result.result === 'object' ? JSON.stringify(result.result, null, 2) : String(result.result ?? '')
    execResults.unshift({
      pluginName: row.display_name,
      functionName: funcName,
      success: result.success !== false,
      output: output || '（无输出）',
      time: new Date().toLocaleTimeString(),
    })
    ElMessage.success('插件执行成功')
    activeTab.value = 'execlog'
  } catch (e: any) {
    const errMsg = e?.response?.data?.detail || e?.message || '执行失败'
    execResults.unshift({
      pluginName: row.display_name,
      functionName: funcName,
      success: false,
      output: errMsg,
      time: new Date().toLocaleTimeString(),
    })
    ElMessage.error(errMsg)
    activeTab.value = 'execlog'
  } finally {
    row._executing = false
  }
}

async function handleDelete(row: any) {
  try {
    await ElMessageBox.confirm(`确定卸载插件「${row.display_name}」？此操作不可恢复。`, '确认卸载', { type: 'warning' })
    await pluginsApi.remove(row.id)
    ElMessage.success('插件已卸载')
    await loadPlugins()
  } catch (e: any) {
    if (e !== 'cancel') ElMessage.error('卸载失败')
  }
}

function typeLabel(t: string) {
  const map: Record<string, string> = {
    engine: '引擎', analysis: '分析', alert: '告警',
    tool: '工具', mcp: 'MCP', skill: '技能',
  }
  return map[t] || t
}

function typeTagColor(t: string) {
  const map: Record<string, string> = {
    engine: '', analysis: 'success', alert: 'warning',
    tool: 'info', mcp: 'danger', skill: '',
  }
  return map[t] || 'info'
}

function statusLabel(s: string) {
  const map: Record<string, string> = {
    pending: '待审核', approved: '已通过', rejected: '已拒绝', disabled: '已禁用',
  }
  return map[s] || s
}

function statusTagColor(s: string) {
  const map: Record<string, string> = {
    pending: 'warning', approved: 'success', rejected: 'danger', disabled: 'info',
  }
  return map[s] || 'info'
}

onMounted(() => {
  loadPlugins()
})
</script>

<style scoped>
.page-container {
  padding: 20px;
}
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}
.page-header h2 {
  margin: 0;
}
.info-section h3 {
  font-size: 16px;
  color: #303133;
}
.exec-result-item {
  border: 1px solid #ebeef5;
  border-radius: 8px;
  padding: 12px 16px;
  margin-bottom: 12px;
  background: #fafafa;
}
.exec-result-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}
.exec-result-name {
  font-weight: 600;
  color: #303133;
}
.exec-result-time {
  margin-left: auto;
  font-size: 12px;
  color: #909399;
}
.exec-result-output {
  background: #1e1e1e;
  color: #d4d4d4;
  padding: 12px;
  border-radius: 6px;
  font-size: 13px;
  line-height: 1.5;
  max-height: 300px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-all;
  margin: 0;
}
</style>
