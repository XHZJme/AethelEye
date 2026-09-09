<template>
  <div class="settings-page">
    <el-card v-loading="loading">
      <template #header>
        <span>系统设置</span>
      </template>

      <el-tabs v-model="activeTab">
        <!-- 通用设置 -->
        <el-tab-pane label="通用设置" name="general">
          <el-form label-width="120px">
            <el-form-item label="服务端口">
              <el-input v-model="settings.port" disabled />
              <div class="form-tip">端口配置在安装时设定，如需修改请重新安装</div>
            </el-form-item>
            <el-form-item label="数据存储路径">
              <el-input v-model="settings.dataPath" disabled />
            </el-form-item>
            <el-form-item label="截图存储路径">
              <el-input v-model="settings.screenshotPath" disabled />
            </el-form-item>
          </el-form>
        </el-tab-pane>

        <!-- 采集设置 -->
        <el-tab-pane label="采集设置" name="collector">
          <el-form label-width="120px">
            <el-form-item label="运行模式">
              <el-radio-group v-model="settings.runningMode">
                <el-radio label="silent">静默模式</el-radio>
                <el-radio label="visual">可视化模式</el-radio>
              </el-radio-group>
              <div class="form-tip">静默模式：浏览器后台运行；可视化模式：显示浏览器窗口</div>
            </el-form-item>
            <el-form-item label="采集超时">
              <el-input-number v-model="settings.collectTimeout" :min="10" :max="60" />
              <span style="margin-left: 10px">秒</span>
            </el-form-item>
            <el-form-item label="失败重试次数">
              <el-input-number v-model="settings.collectRetry" :min="1" :max="5" />
            </el-form-item>
            <el-form-item label="任务间延迟">
              <el-input-number v-model="settings.collectDelayMin" :min="1" :max="30" />
              <span> ~ </span>
              <el-input-number v-model="settings.collectDelayMax" :min="1" :max="60" />
              <span style="margin-left: 10px">秒</span>
            </el-form-item>
          </el-form>
        </el-tab-pane>

        <!-- 录屏设置 -->
        <el-tab-pane label="录屏设置" name="recording">
          <el-form label-width="120px">
            <el-form-item label="全局录屏开关">
              <el-switch v-model="settings.recordingEnabled" />
            </el-form-item>
            <el-form-item label="录屏分辨率">
              <el-select v-model="settings.recordingResolution">
                <el-option label="1280×720" value="1280x720" />
                <el-option label="1920×1080" value="1920x1080" />
              </el-select>
            </el-form-item>
            <el-form-item label="保留天数">
              <el-input-number v-model="settings.recordingRetention" :min="1" :max="30" />
              <span style="margin-left: 10px">天</span>
            </el-form-item>
            <el-form-item label="仅异常保留">
              <el-switch v-model="settings.recordingOnlyException" />
              <div class="form-tip">开启后，正常采集的录屏自动删除，仅保留失败/异动的录屏</div>
            </el-form-item>
          </el-form>
        </el-tab-pane>

        <!-- 日志设置 -->
        <el-tab-pane label="日志设置" name="logs">
          <el-form label-width="120px">
            <el-form-item label="日志级别">
              <el-select v-model="settings.logLevel">
                <el-option label="DEBUG" value="DEBUG" />
                <el-option label="INFO" value="INFO" />
                <el-option label="WARNING" value="WARNING" />
                <el-option label="ERROR" value="ERROR" />
              </el-select>
            </el-form-item>
            <el-form-item label="保留天数">
              <el-input-number v-model="settings.logRetention" :min="7" :max="365" />
              <span style="margin-left: 10px">天</span>
            </el-form-item>
          </el-form>
        </el-tab-pane>

        <!-- 访问限制处理 -->
        <el-tab-pane label="访问限制" name="risk">
          <el-form label-width="140px">
            <el-form-item label="冷却重试时间">
              <el-input-number v-model="settings.riskControlCooldown" :min="0" :max="1440" />
              <span style="margin-left: 10px">分钟</span>
              <div class="form-tip">检测到验证码、限流或拒绝访问后暂停任务。默认设为 0，由获得授权的管理员人工确认后再恢复。</div>
            </el-form-item>
          </el-form>
        </el-tab-pane>

        <!-- Webhook设置 -->
        <el-tab-pane label="Webhook推送" name="webhook">
          <template v-if="activeTab === 'webhook'">
            <div style="margin-bottom: 16px">
              <el-button type="primary" size="small" @click="showWebhookDialog()">
                <el-icon><Plus /></el-icon> 新增Webhook
              </el-button>
            </div>
            <el-table :data="webhooks" v-loading="webhookLoading" border size="small" empty-text="暂未配置Webhook" style="width: 100%">
              <el-table-column prop="name" label="名称" width="160" />
              <el-table-column prop="webhook_type" label="类型" width="100" align="center">
                <template #default="{ row }">
                  <el-tag size="small" :type="row.webhook_type === 'wecom' ? '' : row.webhook_type === 'dingtalk' ? 'warning' : 'info'">
                    {{ row.webhook_type === 'wecom' ? '企业微信' : row.webhook_type === 'dingtalk' ? '钉钉' : '自定义' }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="webhook_url" label="Webhook地址" min-width="200" show-overflow-tooltip />
              <el-table-column prop="is_default" label="默认" width="70" align="center">
                <template #default="{ row }">
                  <el-tag v-if="row.is_default" type="success" size="small">是</el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="is_active" label="状态" width="80" align="center">
                <template #default="{ row }">
                  <el-switch v-model="row.is_active" size="small" @change="handleWebhookToggle(row)" />
                </template>
              </el-table-column>
              <el-table-column label="操作" width="200" align="center">
                <template #default="{ row }">
                  <el-button size="small" link type="primary" @click="handleWebhookTest(row.id)">测试</el-button>
                  <el-button size="small" link type="primary" @click="showWebhookDialog(row)">编辑</el-button>
                  <el-button size="small" link type="danger" @click="handleWebhookDelete(row)">删除</el-button>
                </template>
              </el-table-column>
            </el-table>
          </template>
        </el-tab-pane>

        <!-- AI模型配置 -->
        <el-tab-pane label="AI模型" name="llm">
          <template v-if="activeTab === 'llm'">
            <div style="margin-bottom: 16px; display: flex; justify-content: space-between; align-items: center">
              <el-button type="primary" size="small" @click="showProviderDialog()">
                <el-icon><Plus /></el-icon> 添加服务商
              </el-button>
              <el-tag type="info" size="small">配置 LLM 服务商的 API Key 后即可使用 AI 功能</el-tag>
            </div>
            <el-table :data="llmProviders" v-loading="llmLoading" border size="small" empty-text="暂未配置 AI 模型" style="width: 100%">
              <el-table-column prop="display_name" label="名称" width="160" />
              <el-table-column prop="provider_type" label="类型" width="130" align="center">
                <template #default="{ row }">
                  <el-tag size="small" :type="providerTagType(row.provider_type)">{{ providerTypeLabel(row.provider_type) }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="base_url" label="API 地址" min-width="180" show-overflow-tooltip>
                <template #default="{ row }">
                  <span>{{ row.base_url || '默认' }}</span>
                </template>
              </el-table-column>
              <el-table-column prop="api_key_masked" label="API Key" width="160" />
              <el-table-column prop="priority" label="优先级" width="80" align="center" />
              <el-table-column prop="is_active" label="状态" width="80" align="center">
                <template #default="{ row }">
                  <el-switch v-model="row.is_active" size="small" @change="handleProviderToggle(row)" />
                </template>
              </el-table-column>
              <el-table-column label="操作" width="200" align="center">
                <template #default="{ row }">
                  <el-button size="small" link type="success" @click="handleProviderTest(row)" :loading="row._testing">测试</el-button>
                  <el-button size="small" link type="primary" @click="showProviderDialog(row)">编辑</el-button>
                  <el-button size="small" link type="danger" @click="handleProviderDelete(row)">删除</el-button>
                </template>
              </el-table-column>
            </el-table>

            <!-- 用量统计 -->
            <div v-if="llmUsage" style="margin-top: 20px">
              <el-divider content-position="left">近7天用量</el-divider>
              <el-descriptions :column="3" border size="small">
                <el-descriptions-item label="总请求">{{ llmUsage.summary.requests }}</el-descriptions-item>
                <el-descriptions-item label="总Token">{{ llmUsage.summary.total_tokens.toLocaleString() }}</el-descriptions-item>
                <el-descriptions-item label="平均耗时">{{ llmUsage.summary.avg_duration_ms }}ms</el-descriptions-item>
                <el-descriptions-item label="错误次数">
                  <el-tag :type="llmUsage.summary.errors > 0 ? 'danger' : 'success'" size="small">{{ llmUsage.summary.errors }}</el-tag>
                </el-descriptions-item>
              </el-descriptions>
            </div>
          </template>
        </el-tab-pane>

        <!-- AI引擎设置 -->
        <el-tab-pane label="AI引擎" name="ai_engine">
          <template v-if="activeTab === 'ai_engine'">
            <!-- 引擎策略 -->
            <el-divider content-position="left">引擎策略</el-divider>
            <el-form label-width="140px" style="max-width: 600px">
              <el-form-item label="引擎选择策略">
                <el-select v-model="engineConfig.engine_strategy" @change="handleEngineConfigSave">
                  <el-option label="默认（硬编码优先，AI降级）" value="default" />
                  <el-option label="仅硬编码引擎" value="hardcoded_only" />
                  <el-option label="仅AI引擎" value="ai_only" />
                  <el-option label="手动选择" value="manual" />
                </el-select>
                <div class="form-tip">默认策略：硬编码引擎先行，AI监控看守；硬编码失败时AI降级接管</div>
              </el-form-item>
              <el-form-item label="AI自治级别">
                <el-select v-model="engineConfig.ai_autonomy_level" @change="handleEngineConfigSave">
                  <el-option :label="'全手动'" :value="0" />
                  <el-option :label="'观察模式'" :value="1" />
                  <el-option :label="'保守模式'" :value="2" />
                  <el-option :label="'激进模式'" :value="3" />
                </el-select>
                <div class="form-tip">0=全手动 1=观察模式 2=保守模式 3=激进模式；高风险变更需人工确认</div>
              </el-form-item>
              <el-form-item label="AI RPA探索轮数">
                <el-input-number v-model="engineConfig.ai_rpa_max_explore_rounds" :min="1" :max="50" @change="handleEngineConfigSave" />
              </el-form-item>
              <el-form-item label="AI RPA超时">
                <el-input-number v-model="engineConfig.ai_rpa_timeout_seconds" :min="10" :max="300" @change="handleEngineConfigSave" />
                <span style="margin-left: 10px">秒</span>
              </el-form-item>
            </el-form>

            <!-- AI 服务绑定 -->
            <el-divider content-position="left">AI 服务→模型绑定</el-divider>
            <div class="form-tip" style="margin-bottom: 12px">每个 AI 服务独立绑定使用的服务商和模型。未绑定的服务将使用默认路由。</div>
            <el-table :data="serviceBindings" border size="small" v-loading="bindingsLoading" style="width: 100%">
              <el-table-column prop="service_display_name" label="AI服务" width="200" />
              <el-table-column prop="service_name" label="标识" width="120" />
              <el-table-column label="绑定服务商" min-width="180">
                <template #default="{ row }">
                  <el-select
                    v-model="row.provider_config_id"
                    placeholder="选择服务商"
                    clearable
                    size="small"
                    @change="handleBindingChange(row)"
                  >
                    <el-option
                      v-for="p in llmProviders"
                      :key="p.id"
                      :label="p.display_name"
                      :value="p.id"
                    />
                  </el-select>
                </template>
              </el-table-column>
              <el-table-column label="模型" min-width="180">
                <template #default="{ row }">
                  <el-input
                    v-model="row.model"
                    placeholder="如 abab6.5s-chat"
                    size="small"
                    clearable
                    @blur="handleBindingChange(row)"
                  />
                </template>
              </el-table-column>
              <el-table-column label="启用" width="70" align="center">
                <template #default="{ row }">
                  <el-switch v-model="row.is_enabled" size="small" @change="handleBindingChange(row)" />
                </template>
              </el-table-column>
            </el-table>

            <!-- 引擎列表 -->
            <el-divider content-position="left">已注册引擎</el-divider>
            <el-table :data="enginesList" border size="small" v-loading="enginesLoading" style="width: 100%">
              <el-table-column prop="display_name" label="引擎名称" width="200" />
              <el-table-column prop="name" label="标识" width="140" />
              <el-table-column prop="version" label="版本" width="100" />
              <el-table-column prop="source" label="来源" width="120">
                <template #default="{ row }">
                  <el-tag :type="row.source === 'builtin' ? 'success' : 'warning'" size="small">
                    {{ row.source === 'builtin' ? '内置' : '外部' }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="活跃" width="70" align="center">
                <template #default="{ row }">
                  <el-tag v-if="row.is_active" type="success" size="small">当前</el-tag>
                </template>
              </el-table-column>
            </el-table>
          </template>
        </el-tab-pane>

        <!-- MCP / Skill -->
        <el-tab-pane label="MCP/Skill" name="mcp">
          <template #default>
            <el-divider content-position="left">外部 MCP Server 管理</el-divider>
            <el-row :gutter="16" style="margin-bottom: 12px">
              <el-col :span="16">
                <el-alert type="info" :closable="false" show-icon>
                  <template #title>
                    连接外部 MCP Server 以扩展系统能力（如记忆服务、搜索服务等）。
                  </template>
                </el-alert>
              </el-col>
              <el-col :span="8" style="text-align: right">
                <el-button type="primary" @click="showAddMcpDialog = true">添加 MCP Server</el-button>
              </el-col>
            </el-row>
            <el-table :data="externalMcpServers" border size="small" style="width:100%; margin-bottom: 16px" v-loading="mcpServersLoading">
              <el-table-column prop="name" label="名称" width="160" />
              <el-table-column prop="url" label="端点" min-width="260" show-overflow-tooltip />
              <el-table-column prop="transport" label="协议" width="130" />
              <el-table-column prop="description" label="说明" min-width="180" show-overflow-tooltip />
              <el-table-column label="状态" width="80" align="center">
                <template #default="{ row }">
                  <el-tag :type="row.enabled ? 'success' : 'info'" size="small">{{ row.enabled ? '启用' : '禁用' }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="200" align="center">
                <template #default="{ row }">
                  <el-button size="small" @click="testMcpServer(row)">测试</el-button>
                  <el-button size="small" :type="row.enabled ? 'warning' : 'success'" @click="toggleMcpServer(row)">
                    {{ row.enabled ? '禁用' : '启用' }}
                  </el-button>
                  <el-button size="small" type="danger" @click="removeMcpServer(row)">删除</el-button>
                </template>
              </el-table-column>
            </el-table>
            <el-empty v-if="!mcpServersLoading && externalMcpServers.length === 0" description="暂无外部 MCP Server" :image-size="48" />

            <!-- 添加 MCP Server 对话框 -->
            <el-dialog v-model="showAddMcpDialog" title="添加外部 MCP Server" width="520px">
              <el-form :model="newMcpForm" label-width="80px">
                <el-form-item label="名称" required>
                  <el-input v-model="newMcpForm.name" placeholder="如：memory-service" />
                </el-form-item>
                <el-form-item label="端点" required>
                  <el-input v-model="newMcpForm.url" placeholder="http://127.0.0.1:3100/mcp" />
                </el-form-item>
                <el-form-item label="协议">
                  <el-select v-model="newMcpForm.transport" style="width:100%">
                    <el-option label="Streamable HTTP" value="streamable-http" />
                    <el-option label="SSE" value="sse" />
                  </el-select>
                </el-form-item>
                <el-form-item label="说明">
                  <el-input v-model="newMcpForm.description" placeholder="可选描述" />
                </el-form-item>
              </el-form>
              <template #footer>
                <el-button @click="showAddMcpDialog = false">取消</el-button>
                <el-button type="primary" @click="addMcpServer" :loading="addingMcpServer">添加</el-button>
              </template>
            </el-dialog>

            <el-divider content-position="left">外部 Skill 安装</el-divider>
            <el-row :gutter="16" style="margin-bottom: 12px">
              <el-col :span="6">
                <el-input v-model="githubSkillUrl" placeholder="GitHub 仓库 URL" clearable />
              </el-col>
              <el-col :span="4">
                <el-button type="primary" @click="installGithubSkill" :loading="installingSkill" :disabled="!githubSkillUrl.trim()">
                  从 GitHub 安装
                </el-button>
              </el-col>
              <el-col :span="4">
                <el-upload :show-file-list="false" :before-upload="installZipSkill" accept=".zip">
                  <el-button :loading="installingSkill">上传 ZIP 安装</el-button>
                </el-upload>
              </el-col>
            </el-row>
            <el-table :data="installedSkills" border size="small" style="width:100%" v-loading="skillsLoading">
              <el-table-column prop="name" label="名称" width="180" />
              <el-table-column prop="description" label="描述" min-width="250" show-overflow-tooltip />
              <el-table-column prop="version" label="版本" width="80" />
              <el-table-column prop="source" label="来源" width="80">
                <template #default="{ row }">
                  <el-tag size="small" :type="row.source === 'github' ? '' : 'info'">{{ row.source === 'github' ? 'GitHub' : 'ZIP' }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="SKILL.md" width="90" align="center">
                <template #default="{ row }">
                  <el-tag :type="row.has_skill_md ? 'success' : 'warning'" size="small">{{ row.has_skill_md ? '有' : '无' }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="状态" width="80" align="center">
                <template #default="{ row }">
                  <el-tag :type="row.enabled ? 'success' : 'info'" size="small">{{ row.enabled ? '启用' : '禁用' }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="160" align="center">
                <template #default="{ row }">
                  <el-button size="small" :type="row.enabled ? 'warning' : 'success'" @click="toggleInstalledSkill(row)">
                    {{ row.enabled ? '禁用' : '启用' }}
                  </el-button>
                  <el-button size="small" type="danger" @click="uninstallSkill(row)">卸载</el-button>
                </template>
              </el-table-column>
            </el-table>
            <el-empty v-if="!skillsLoading && installedSkills.length === 0" description="暂无已安装的外部 Skill" :image-size="48" />

            <el-divider content-position="left">内置 MCP Server</el-divider>
            <el-descriptions :column="2" border>
              <el-descriptions-item label="端口">8687</el-descriptions-item>
              <el-descriptions-item label="端点">http://127.0.0.1:8687/mcp</el-descriptions-item>
              <el-descriptions-item label="协议">JSON-RPC 2.0</el-descriptions-item>
              <el-descriptions-item label="认证">
                <el-tag v-if="mcpTokenConfigured" type="success" size="small">已配置</el-tag>
                <el-tag v-else type="info" size="small">开放（仅本地）</el-tag>
              </el-descriptions-item>
            </el-descriptions>

            <el-divider content-position="left">已注册 MCP Tools</el-divider>
            <el-table :data="mcpTools" border size="small" style="width: 100%">
              <el-table-column prop="name" label="Tool名称" min-width="220" />
              <el-table-column prop="description" label="说明" min-width="300" show-overflow-tooltip />
            </el-table>

            <el-divider content-position="left">Skill 导出（OpenClaw / Claude Code 兼容）</el-divider>
            <el-row :gutter="16" style="margin-bottom: 16px">
              <el-col :span="16">
                <el-alert type="success" :closable="false" show-icon>
                  <template #title>
                    生成标准 SKILL.md（YAML frontmatter + Markdown），兼容 OpenClaw / Claude Code / Codex CLI / Hermes。
                  </template>
                </el-alert>
              </el-col>
              <el-col :span="8" style="text-align: right">
                <el-button type="primary" @click="exportSkill" :loading="skillExporting">
                  导出 SKILL.md 到磁盘
                </el-button>
                <el-button @click="previewSkill">预览 SKILL.md</el-button>
              </el-col>
            </el-row>

            <el-table :data="skillCompatTable" border size="small" style="width: 100%; margin-bottom: 16px">
              <el-table-column prop="platform" label="平台" width="160" />
              <el-table-column prop="format" label="格式" width="200" />
              <el-table-column prop="status" label="兼容" width="80" align="center">
                <template #default="{ row }">
                  <el-tag type="success" size="small">{{ row.status }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="note" label="说明" min-width="300" />
            </el-table>

            <el-dialog v-model="skillPreviewVisible" title="SKILL.md 预览" width="700px">
              <pre class="skill-json">{{ skillPreviewContent }}</pre>
            </el-dialog>
          </template>
        </el-tab-pane>

        <!-- 数据管理 -->
        <el-tab-pane label="数据管理" name="data">
          <el-descriptions :column="1" border v-loading="storageLoading">
            <el-descriptions-item label="数据库大小">{{ storageInfo.databaseSize }} MB</el-descriptions-item>
            <el-descriptions-item label="截图占用">{{ storageInfo.screenshotsSize }} MB</el-descriptions-item>
            <el-descriptions-item label="日志占用">{{ storageInfo.logsSize }} MB</el-descriptions-item>
            <el-descriptions-item label="录屏占用">{{ storageInfo.recordingsSize }} MB</el-descriptions-item>
            <el-descriptions-item label="总占用空间"><strong>{{ storageInfo.totalSize }} MB</strong></el-descriptions-item>
          </el-descriptions>

          <el-divider />

          <el-button @click="handleExportBackup">
            <el-icon><Download /></el-icon>
            导出备份
          </el-button>
          <el-button @click="handleImportBackup">
            <el-icon><Upload /></el-icon>
            导入恢复
          </el-button>
        </el-tab-pane>

      </el-tabs>

      <el-divider />

      <el-button type="primary" @click="handleSave">保存设置</el-button>
    </el-card>

    <!-- Webhook 编辑对话框 -->
    <el-dialog v-model="webhookDialogVisible" :title="webhookForm.id ? '编辑Webhook' : '新增Webhook'" width="580px" destroy-on-close append-to-body>
      <el-form :model="webhookForm" label-width="110px">
        <el-form-item label="名称" required>
          <el-input v-model="webhookForm.name" placeholder="如：运营群通知" />
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="webhookForm.webhook_type">
            <el-option label="企业微信" value="wecom" />
            <el-option label="钉钉" value="dingtalk" />
            <el-option label="自定义" value="custom" />
          </el-select>
        </el-form-item>
        <el-form-item label="Webhook地址" required>
          <el-input v-model="webhookForm.webhook_url" :placeholder="webhookForm.id ? '留空则保持现有地址不变' : 'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=...'" />
          <div v-if="webhookForm.id" class="form-tip">出于安全考虑，已保存地址不会回显。</div>
        </el-form-item>
        <el-form-item label="消息类型">
          <el-radio-group v-model="webhookForm.msg_type">
            <el-radio label="markdown">Markdown（推荐）</el-radio>
            <el-radio label="text">文本</el-radio>
          </el-radio-group>
          <div class="form-tip">text类型支持@指定人手机号提醒，markdown支持富文本格式</div>
        </el-form-item>

        <el-divider content-position="left">高级配置</el-divider>

        <el-form-item label="关键词">
          <el-input v-model="webhookForm.keyword" placeholder="部分机器人要求消息含关键词" clearable />
          <div class="form-tip">如果企微机器人设置了安全关键词，此处填写以确保消息能发送</div>
        </el-form-item>
        <el-form-item label="@用户ID">
          <el-input v-model="webhookForm.mentioned_list" placeholder='["userid1","userid2"] 或 ["@all"]' clearable />
          <div class="form-tip">JSON数组格式，企业微信用户ID。填 @all 可@所有人</div>
        </el-form-item>
        <el-form-item label="@手机号">
          <el-input v-model="webhookForm.mentioned_mobile_list" placeholder='["138****1111","139****2222"]' clearable />
          <div class="form-tip">JSON数组格式，仅text类型消息有效。填 @all 可@所有人</div>
        </el-form-item>
        <el-form-item label="签名密钥">
          <el-input v-model="webhookForm.secret" :placeholder="webhookForm.id ? '留空则保持现有密钥不变' : '可选，部分机器人需要'" clearable show-password />
        </el-form-item>
        <el-form-item label="设为默认">
          <el-switch v-model="webhookForm.is_default" />
          <div class="form-tip">默认Webhook将用于所有未单独配置Webhook的任务</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="webhookDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleWebhookSave" :loading="webhookSaving">保存</el-button>
      </template>
    </el-dialog>

    <!-- LLM 服务商编辑对话框 -->
    <el-dialog v-model="providerDialogVisible" :title="providerForm.id ? '编辑服务商' : '添加服务商'" width="560px" destroy-on-close append-to-body>
      <el-form :model="providerForm" label-width="110px">
        <el-form-item label="服务商类型" required>
          <el-select v-model="providerForm.provider_type" :disabled="!!providerForm.id" placeholder="选择类型">
            <el-option v-for="t in providerTypes" :key="t.type" :label="t.display_name" :value="t.type" />
          </el-select>
        </el-form-item>
        <el-form-item label="显示名称" required>
          <el-input v-model="providerForm.display_name" placeholder="如：主用 DeepSeek" />
        </el-form-item>
        <el-form-item label="API Key" required>
          <el-input v-model="providerForm.api_key" placeholder="sk-..." show-password />
        </el-form-item>
        <el-form-item label="API 地址">
          <el-input v-model="providerForm.base_url" placeholder="留空使用默认地址" clearable />
          <div class="form-tip">OpenAI: https://api.openai.com | DeepSeek: https://api.deepseek.com | 自定义中转地址</div>
        </el-form-item>
        <el-form-item label="默认模型">
          <el-input v-model="providerForm.default_model" placeholder="如 deepseek-chat, gpt-4o-mini" clearable />
        </el-form-item>
        <el-form-item label="优先级">
          <el-input-number v-model="providerForm.priority" :min="1" :max="999" />
          <div class="form-tip">数字越小优先级越高，同模型多服务商时按优先级路由</div>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="providerForm.note" placeholder="可选备注" clearable />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="providerDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleProviderSave" :loading="providerSaving">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Download, Upload } from '@element-plus/icons-vue'
import apiClient, { settingsApi, webhookApi, llmApi, enginesApi } from '@/api'
import type { WebhookConfig } from '@/api'

const activeTab = ref('general')

// 设置数据
const settings = reactive({
  port: '',
  dataPath: '',
  screenshotPath: '',
  runningMode: 'silent',
  collectTimeout: 30,
  collectRetry: 3,
  collectDelayMin: 3,
  collectDelayMax: 8,
  recordingEnabled: false,
  recordingResolution: '1280x720',
  recordingRetention: 7,
  recordingOnlyException: true,
  logLevel: 'INFO',
  logRetention: 90,
  riskControlCooldown: 0,
})

const loading = ref(false)
const storageLoading = ref(false)

const storageInfo = reactive({
  databaseSize: 0,
  screenshotsSize: 0,
  logsSize: 0,
  recordingsSize: 0,
  totalSize: 0,
})

async function loadStorageInfo() {
  storageLoading.value = true
  try {
    const data = await settingsApi.getStorageInfo()
    storageInfo.databaseSize = data.database_size_mb || 0
    storageInfo.screenshotsSize = data.screenshots_size_mb || 0
    storageInfo.logsSize = data.logs_size_mb || 0
    storageInfo.recordingsSize = data.recordings_size_mb || 0
    storageInfo.totalSize = data.total_size_mb || 0
  } catch (e) {
    console.error('Failed to load storage info:', e)
  } finally {
    storageLoading.value = false
  }
}

async function loadSettings() {
  loading.value = true
  try {
    const data = await settingsApi.getAll()
    settings.port = String(data.port || '')
    settings.dataPath = String(data.data_dir || '')
    settings.screenshotPath = String(data.screenshots_dir || '')
    settings.runningMode = String(data.running_mode || 'silent')
    settings.collectTimeout = Number(data.collect_timeout || 30)
    settings.collectRetry = Number(data.collect_retry || 3)
    settings.collectDelayMin = Number(data.collect_delay_min || 3)
    settings.collectDelayMax = Number(data.collect_delay_max || 8)
    settings.recordingEnabled = Boolean(data.recording_enabled)
    settings.recordingResolution = String(data.recording_resolution || '1280x720')
    settings.recordingRetention = Number(data.recording_retention || 7)
    settings.recordingOnlyException = Boolean(data.recording_only_exception)
    settings.logLevel = String(data.log_level || 'INFO')
    settings.logRetention = Number(data.log_retention || 90)
    settings.riskControlCooldown = Number(data.risk_control_cooldown_minutes ?? 0)
  } catch (e) {
    console.error('Failed to load settings:', e)
  } finally {
    loading.value = false
  }
}

async function handleSave() {
  loading.value = true
  try {
    await settingsApi.update({
      running_mode: settings.runningMode,
      collect_timeout: settings.collectTimeout,
      collect_retry: settings.collectRetry,
      collect_delay_min: settings.collectDelayMin,
      collect_delay_max: settings.collectDelayMax,
      recording_enabled: settings.recordingEnabled,
      recording_resolution: settings.recordingResolution,
      recording_retention: settings.recordingRetention,
      recording_only_exception: settings.recordingOnlyException,
      log_level: settings.logLevel,
      log_retention: settings.logRetention,
      risk_control_cooldown_minutes: settings.riskControlCooldown,
    })
    ElMessage.success('设置已保存')
  } catch (e) {
    console.error('Failed to save settings:', e)
  } finally {
    loading.value = false
  }
}

function handleExportBackup() {
  ElMessage.info('导出功能将在后续版本完善')
}

function handleImportBackup() {
  ElMessage.info('导入功能将在后续版本完善')
}

// ===== Webhook管理 =====
const webhooks = ref<WebhookConfig[]>([])
const webhookLoading = ref(false)
const webhookDialogVisible = ref(false)
const webhookSaving = ref(false)
const webhookForm = reactive({
  id: 0,
  name: '',
  webhook_url: '',
  webhook_type: 'wecom',
  is_default: false,
  msg_type: 'markdown',
  keyword: '',
  mentioned_list: '',
  mentioned_mobile_list: '',
  secret: '',
})

async function loadWebhooks() {
  webhookLoading.value = true
  try {
    const data = await webhookApi.list()
    webhooks.value = data.webhooks || []
  } catch (e) {
    console.error('Failed to load webhooks:', e)
  } finally {
    webhookLoading.value = false
  }
}

function showWebhookDialog(row?: WebhookConfig) {
  if (row) {
    webhookForm.id = row.id
    webhookForm.name = row.name
    webhookForm.webhook_url = ''
    webhookForm.webhook_type = row.webhook_type
    webhookForm.is_default = row.is_default
    webhookForm.msg_type = row.msg_type || 'markdown'
    webhookForm.keyword = row.keyword || ''
    webhookForm.mentioned_list = row.mentioned_list || ''
    webhookForm.mentioned_mobile_list = row.mentioned_mobile_list || ''
    webhookForm.secret = ''
  } else {
    webhookForm.id = 0
    webhookForm.name = ''
    webhookForm.webhook_url = ''
    webhookForm.webhook_type = 'wecom'
    webhookForm.is_default = false
    webhookForm.msg_type = 'markdown'
    webhookForm.keyword = ''
    webhookForm.mentioned_list = ''
    webhookForm.mentioned_mobile_list = ''
    webhookForm.secret = ''
  }
  webhookDialogVisible.value = true
}

async function handleWebhookSave() {
  if (!webhookForm.name.trim() || (!webhookForm.id && !webhookForm.webhook_url.trim())) {
    ElMessage.warning(webhookForm.id ? '请填写名称' : '请填写名称和Webhook地址')
    return
  }
  webhookSaving.value = true
  try {
    const formData = {
      name: webhookForm.name,
      webhook_type: webhookForm.webhook_type,
      is_default: webhookForm.is_default,
      msg_type: webhookForm.msg_type,
      keyword: webhookForm.keyword || undefined,
      mentioned_list: webhookForm.mentioned_list || undefined,
      mentioned_mobile_list: webhookForm.mentioned_mobile_list || undefined,
      ...(webhookForm.webhook_url.trim() ? { webhook_url: webhookForm.webhook_url.trim() } : {}),
      ...(webhookForm.secret.trim() ? { secret: webhookForm.secret.trim() } : {}),
    }
    if (webhookForm.id) {
      await webhookApi.update(webhookForm.id, formData)
      ElMessage.success('Webhook已更新')
    } else {
      await webhookApi.create({ ...formData, webhook_url: webhookForm.webhook_url.trim() })
      ElMessage.success('Webhook已创建')
    }
    webhookDialogVisible.value = false
    await loadWebhooks()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '操作失败')
  } finally {
    webhookSaving.value = false
  }
}

async function handleWebhookToggle(row: WebhookConfig) {
  try {
    await webhookApi.update(row.id, { is_active: row.is_active })
    ElMessage.success(row.is_active ? '已启用' : '已禁用')
  } catch (e) {
    row.is_active = !row.is_active
    ElMessage.error('操作失败')
  }
}

async function handleWebhookTest(id: number) {
  try {
    const result = await webhookApi.test(id)
    if (result.success) {
      ElMessage.success('测试消息发送成功')
    } else {
      ElMessage.warning(`测试失败: ${result.message}`)
    }
  } catch (e) {
    ElMessage.error('测试请求失败')
  }
}

async function handleWebhookDelete(row: WebhookConfig) {
  try {
    await ElMessageBox.confirm(`确定删除 Webhook「${row.name}」？`, '确认删除', { type: 'warning' })
    await webhookApi.delete(row.id)
    ElMessage.success('已删除')
    await loadWebhooks()
  } catch (e: any) {
    if (e !== 'cancel') ElMessage.error('删除失败')
  }
}

// ===== LLM Provider 管理 =====
const llmProviders = ref<any[]>([])
const llmLoading = ref(false)
const llmUsage = ref<any>(null)
const providerTypes = ref<{ type: string; display_name: string; default_prefixes: string[] }[]>([])
const providerDialogVisible = ref(false)
const providerSaving = ref(false)
const providerForm = reactive({
  id: 0,
  provider_type: 'openai_compatible',
  display_name: '',
  api_key: '',
  base_url: '',
  default_model: '',
  priority: 100,
  note: '',
})

async function loadProviders() {
  llmLoading.value = true
  try {
    const data = await llmApi.getProviders()
    llmProviders.value = data.providers || []
  } catch (e) {
    console.error('Failed to load LLM providers:', e)
  } finally {
    llmLoading.value = false
  }
}

async function loadProviderTypes() {
  try {
    const data = await llmApi.getProviderTypes()
    providerTypes.value = data.types || []
  } catch (e) {
    console.error('Failed to load provider types:', e)
  }
}

async function loadLlmUsage() {
  try {
    const data = await llmApi.getUsage(7)
    llmUsage.value = data
  } catch (e) {
    console.error('Failed to load LLM usage:', e)
  }
}

function showProviderDialog(row?: any) {
  if (row) {
    providerForm.id = row.id
    providerForm.provider_type = row.provider_type
    providerForm.display_name = row.display_name
    providerForm.api_key = ''
    providerForm.base_url = row.base_url || ''
    providerForm.default_model = row.default_model || ''
    providerForm.priority = row.priority || 100
    providerForm.note = row.note || ''
  } else {
    providerForm.id = 0
    providerForm.provider_type = 'openai_compatible'
    providerForm.display_name = ''
    providerForm.api_key = ''
    providerForm.base_url = ''
    providerForm.default_model = ''
    providerForm.priority = 100
    providerForm.note = ''
  }
  providerDialogVisible.value = true
}

async function handleProviderSave() {
  if (!providerForm.display_name.trim() || !providerForm.api_key.trim()) {
    if (!providerForm.id && !providerForm.api_key.trim()) {
      ElMessage.warning('请填写名称和 API Key')
      return
    }
    if (!providerForm.display_name.trim()) {
      ElMessage.warning('请填写名称')
      return
    }
  }
  providerSaving.value = true
  try {
    if (providerForm.id) {
      const updateData: Record<string, any> = {
        display_name: providerForm.display_name,
        base_url: providerForm.base_url || undefined,
        default_model: providerForm.default_model || undefined,
        priority: providerForm.priority,
        note: providerForm.note || undefined,
      }
      if (providerForm.api_key) updateData.api_key = providerForm.api_key
      await llmApi.updateProvider(providerForm.id, updateData)
      ElMessage.success('Provider 已更新')
    } else {
      await llmApi.createProvider({
        provider_type: providerForm.provider_type,
        display_name: providerForm.display_name,
        api_key: providerForm.api_key,
        base_url: providerForm.base_url || undefined,
        default_model: providerForm.default_model || undefined,
        priority: providerForm.priority,
        note: providerForm.note || undefined,
      })
      ElMessage.success('Provider 已添加')
    }
    providerDialogVisible.value = false
    await loadProviders()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '操作失败')
  } finally {
    providerSaving.value = false
  }
}

async function handleProviderToggle(row: any) {
  try {
    await llmApi.updateProvider(row.id, { is_active: row.is_active })
    ElMessage.success(row.is_active ? '已启用' : '已禁用')
  } catch (e) {
    row.is_active = !row.is_active
    ElMessage.error('操作失败')
  }
}

async function handleProviderDelete(row: any) {
  try {
    await ElMessageBox.confirm(`确定删除 Provider「${row.display_name}」？`, '确认删除', { type: 'warning' })
    await llmApi.deleteProvider(row.id)
    ElMessage.success('已删除')
    await loadProviders()
  } catch (e: any) {
    if (e !== 'cancel') ElMessage.error('删除失败')
  }
}

async function handleProviderTest(row: any) {
  row._testing = true
  try {
    const result = await llmApi.testProvider(row.id)
    if (result.success) {
      ElMessage.success(`连通成功！延迟 ${result.latency_ms}ms，模型: ${result.model}`)
    } else {
      ElMessage.error(`连通失败: ${result.error}`)
    }
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '测试请求失败')
  } finally {
    row._testing = false
  }
}

// ===== AI引擎管理 =====
const enginesList = ref<any[]>([])
const enginesLoading = ref(false)
const engineConfig = reactive({
  engine_strategy: 'default',
  ai_rpa_max_explore_rounds: 10,
  ai_rpa_timeout_seconds: 60,
  ai_autonomy_level: 1,
})
const serviceBindings = ref<any[]>([])
const bindingsLoading = ref(false)

async function loadEngines() {
  enginesLoading.value = true
  try {
    const data = await enginesApi.list()
    enginesList.value = data.engines || []
  } catch (e) {
    console.error('Failed to load engines:', e)
  } finally {
    enginesLoading.value = false
  }
}

async function loadEngineConfig() {
  try {
    const data = await enginesApi.getConfig()
    engineConfig.engine_strategy = data.engine_strategy
    engineConfig.ai_rpa_max_explore_rounds = data.ai_rpa_max_explore_rounds
    engineConfig.ai_rpa_timeout_seconds = data.ai_rpa_timeout_seconds
    engineConfig.ai_autonomy_level = data.ai_autonomy_level
  } catch (e) {
    console.error('Failed to load engine config:', e)
  }
}

async function handleEngineConfigSave() {
  try {
    await enginesApi.updateConfig({
      engine_strategy: engineConfig.engine_strategy,
      ai_rpa_max_explore_rounds: engineConfig.ai_rpa_max_explore_rounds,
      ai_rpa_timeout_seconds: engineConfig.ai_rpa_timeout_seconds,
      ai_autonomy_level: engineConfig.ai_autonomy_level,
    })
    ElMessage.success('引擎配置已保存')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
  }
}

async function loadServiceBindings() {
  bindingsLoading.value = true
  try {
    const data = await enginesApi.getServiceBindings()
    serviceBindings.value = data.bindings || []
  } catch (e) {
    console.error('Failed to load service bindings:', e)
  } finally {
    bindingsLoading.value = false
  }
}

async function handleBindingChange(row: any) {
  try {
    await enginesApi.updateServiceBinding(row.service_name, {
      provider_config_id: row.provider_config_id || null,
      model: row.model || null,
      is_enabled: row.is_enabled,
    })
    ElMessage.success(`${row.service_display_name} 绑定已更新`)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '更新失败')
  }
}

function providerTypeLabel(type: string) {
  const map: Record<string, string> = {
    openai_compatible: 'OpenAI 兼容',
    minimax: 'MiniMax',
    anthropic: 'Claude',
  }
  return map[type] || type
}

function providerTagType(type: string) {
  const map: Record<string, string> = {
    openai_compatible: '',
    minimax: 'success',
    anthropic: 'warning',
  }
  return map[type] || 'info'
}

// ===== MCP / Skill =====
const mcpTokenConfigured = ref(false)
const mcpTools = ref([
  { name: 'aetheleye.list_tasks', description: '查询监控任务列表' },
  { name: 'aetheleye.get_task_detail', description: '获取任务详情+SKU价格' },
  { name: 'aetheleye.get_alerts', description: '获取价格异动记录' },
  { name: 'aetheleye.collect_now', description: '立即触发一次采集' },
  { name: 'aetheleye.create_task', description: '创建新的监控任务' },
  { name: 'aetheleye.get_price_trend', description: '获取SKU价格趋势数据' },
  { name: 'aetheleye.export_data', description: '导出数据为CSV/Excel' },
])

const skillExporting = ref(false)
const skillPreviewVisible = ref(false)
const skillPreviewContent = ref('')
const skillCompatTable = ref([
  { platform: 'OpenClaw', format: 'SKILL.md (YAML frontmatter)', status: '✅', note: '导出后复制到 ~/.openclaw/skills/' },
  { platform: 'Claude Code', format: 'SKILL.md (symlink)', status: '✅', note: 'symlink 到 ~/.claude/skills/' },
  { platform: 'Codex CLI', format: 'SKILL.md', status: '✅', note: 'SKILL.md 兼容格式' },
  { platform: 'Hermes Agent', format: 'JSON (/skill)', status: '✅', note: 'GET http://127.0.0.1:8687/skill' },
])

async function previewSkill() {
  try {
    const resp = await fetch('http://127.0.0.1:8687/skill/preview')
    skillPreviewContent.value = await resp.text()
    skillPreviewVisible.value = true
  } catch (e) {
    ElMessage.error('MCP Server 未启动或不可达')
  }
}

async function exportSkill() {
  skillExporting.value = true
  try {
    const resp = await fetch('http://127.0.0.1:8687/skill/export', { method: 'POST' })
    const data = await resp.json()
    ElMessage.success(`${data.message}：${data.path}`)
  } catch (e) {
    ElMessage.error('导出失败，MCP Server 未启动或不可达')
  } finally {
    skillExporting.value = false
  }
}

// ===== 外部 MCP Server 管理 =====
const externalMcpServers = ref<any[]>([])
const mcpServersLoading = ref(false)
const showAddMcpDialog = ref(false)
const addingMcpServer = ref(false)
const newMcpForm = reactive({
  name: '',
  url: '',
  transport: 'streamable-http',
  description: '',
})

async function loadMcpServers() {
  mcpServersLoading.value = true
  try {
    const data: any = await apiClient.get('/mcp/servers')
    externalMcpServers.value = data.servers || []
  } catch (e) {
    console.error('Failed to load MCP servers:', e)
  } finally {
    mcpServersLoading.value = false
  }
}

async function addMcpServer() {
  if (!newMcpForm.name.trim() || !newMcpForm.url.trim()) {
    ElMessage.warning('请填写名称和端点')
    return
  }
  addingMcpServer.value = true
  try {
    await apiClient.post('/mcp/servers', newMcpForm)
    ElMessage.success('MCP Server 已添加')
    showAddMcpDialog.value = false
    newMcpForm.name = ''
    newMcpForm.url = ''
    newMcpForm.description = ''
    await loadMcpServers()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '添加失败')
  } finally {
    addingMcpServer.value = false
  }
}

async function removeMcpServer(row: any) {
  try {
    await apiClient.delete(`/mcp/servers/${row.id}`)
    ElMessage.success('已移除')
    await loadMcpServers()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '移除失败')
  }
}

async function toggleMcpServer(row: any) {
  try {
    await apiClient.put(`/mcp/servers/${row.id}/toggle`)
    await loadMcpServers()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '操作失败')
  }
}

async function testMcpServer(row: any) {
  try {
    const data: any = await apiClient.post('/mcp/servers/test', {
      url: row.url,
      transport: row.transport,
      headers: row.headers,
    })
    if (data.success) {
      ElMessage.success(`连接成功：${row.name}`)
    } else {
      ElMessage.warning(`连接失败：${data.message}`)
    }
  } catch (e: any) {
    ElMessage.error('测试失败')
  }
}

// ===== 外部 Skill 安装 =====
const installedSkills = ref<any[]>([])
const skillsLoading = ref(false)
const installingSkill = ref(false)
const githubSkillUrl = ref('')

async function loadInstalledSkills() {
  skillsLoading.value = true
  try {
    const data: any = await apiClient.get('/mcp/skills')
    installedSkills.value = data.skills || []
  } catch (e) {
    console.error('Failed to load installed skills:', e)
  } finally {
    skillsLoading.value = false
  }
}

async function installGithubSkill() {
  if (!githubSkillUrl.value.trim()) return
  installingSkill.value = true
  try {
    const data: any = await apiClient.post('/mcp/skills/install/github', { repo_url: githubSkillUrl.value.trim() })
    ElMessage.success(`Skill "${data.name}" 已安装`)
    githubSkillUrl.value = ''
    await loadInstalledSkills()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '安装失败')
  } finally {
    installingSkill.value = false
  }
}

function installZipSkill(file: File) {
  installingSkill.value = true
  const formData = new FormData()
  formData.append('file', file)
  apiClient.post('/mcp/skills/install/zip', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  }).then((data: any) => {
    ElMessage.success(`Skill "${data.name}" 已安装`)
    loadInstalledSkills()
  }).catch((e: any) => {
    ElMessage.error(e?.response?.data?.detail || '安装失败')
  }).finally(() => {
    installingSkill.value = false
  })
  return false // 阻止 el-upload 默认行为
}

async function toggleInstalledSkill(row: any) {
  try {
    await apiClient.put(`/mcp/skills/${row.id}/toggle`)
    await loadInstalledSkills()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '操作失败')
  }
}

async function uninstallSkill(row: any) {
  try {
    await apiClient.delete(`/mcp/skills/${row.id}`)
    ElMessage.success('已卸载')
    await loadInstalledSkills()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '卸载失败')
  }
}

onMounted(() => {
  loadSettings()
  loadStorageInfo()
  loadWebhooks()
  loadProviders()
  loadProviderTypes()
  loadLlmUsage()
  loadEngines()
  loadEngineConfig()
  loadServiceBindings()
  loadMcpServers()
  loadInstalledSkills()
})
</script>

<style scoped>
.form-tip {
  color: #909399;
  font-size: 12px;
  margin-top: 5px;
}

/* 弹窗内容可滚动，防止底部按钮被截断（与 Tasks.vue 保持一致） */
:deep(.el-dialog) {
  max-height: 85vh;
  display: flex;
  flex-direction: column;
}

:deep(.el-dialog__body) {
  max-height: 60vh;
  overflow-y: auto;
}
.skill-json {
  background: #f5f7fa;
  border: 1px solid #ebeef5;
  border-radius: 4px;
  padding: 12px 16px;
  font-size: 13px;
  line-height: 1.6;
  color: #303133;
  overflow-x: auto;
  white-space: pre;
}
</style>
