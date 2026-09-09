/**
 * 筱和灵眸(AethelEye) - 全量API封装
 * 对照后端14个Router，完整封装所有API调用
 * AethelEye 前端 API 封装
 */

import axios from 'axios'
import type { AxiosInstance, InternalAxiosRequestConfig, AxiosResponse } from 'axios'
import { ElMessage } from 'element-plus'

// ===== HTTP 客户端 =====

const apiClient: AxiosInstance = axios.create({
  baseURL: '/api',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// Token管理
const TOKEN_KEY = 'aetheleye_token'

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token)
}

export function removeToken(): void {
  localStorage.removeItem(TOKEN_KEY)
}

export function isLoggedIn(): boolean {
  return !!getToken()
}

// 请求拦截器 - 添加Token
apiClient.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    const token = getToken()
    if (token) {
      config.headers['Authorization'] = `Bearer ${token}`
    }
    return config
  },
  (error) => {
    return Promise.reject(error)
  }
)

// 响应拦截器 - 处理错误
apiClient.interceptors.response.use(
  (response: AxiosResponse) => {
    return response.data
  },
  (error) => {
    const { response } = error

    if (response) {
      const { status, data } = response

      // 401 - 未登录或Token过期
      if (status === 401) {
        removeToken()
        ElMessage.error('登录已过期，请重新登录')
        // 使用延迟跳转避免在请求拦截器中直接操作路由的循环问题
        setTimeout(() => { window.location.href = '/login' }, 100)
        return Promise.reject(error)
      }

      // 403 - 权限不足
      if (status === 403) {
        ElMessage.error('权限不足')
        return Promise.reject(error)
      }

      // 其他错误 - 更健壮的error message提取
      let message = '请求失败'
      if (typeof data === 'string') {
        message = data
      } else if (data) {
        message = data.detail || data.error || data.message || data.msg || `请求失败 (${status})`
      }
      // 截断过长的错误信息,避免显示raw JSON
      ElMessage.error(String(message).slice(0, 100))
      return Promise.reject(error)
    }

    // 网络错误
    ElMessage.error('网络连接失败')
    return Promise.reject(error)
  }
)

export default apiClient

// ===== 类型定义 =====

// -- 认证 --
export interface LoginRequest {
  username: string
  password: string
  remember_me: boolean
}

export interface LoginResponse {
  token: string
  user_id: number
  username: string
  role: string
}

export interface InitStatusResponse {
  need_init: boolean
  message: string
}

export interface InitAdminRequest {
  username: string
  password: string
}

export interface UserInfo {
  id: number
  username: string
  role: string
  is_active: boolean
  last_login_at: string | null
}

// -- 用户 --
export interface User {
  id: number
  username: string
  role: string
  is_active: boolean
  created_at: string
  last_login_at: string | null
}

export interface UserCreateRequest {
  username: string
  password: string
  role: string
}

export interface UserUpdateRequest {
  username?: string
  role?: string
  is_active?: boolean
}

// -- 任务 --
export interface TaskResponse {
  id: number
  url: string
  platform: string
  product_title: string | null
  shop_name: string | null
  product_image: string | null
  frequency_minutes: number
  status: string
  last_check_at: string | null
  next_check_at: string | null
  recording_enabled: boolean
  last_error: string | null
  note: string | null
  created_at: string
}

export interface TaskCreateRequest {
  url: string
  frequency_minutes?: number
  browser_profile_id?: number
  webhook_config_id?: number
  recording_enabled?: boolean
  note?: string
  product_title?: string
  shop_name?: string
}

export interface TaskUpdateRequest {
  frequency_minutes?: number
  browser_profile_id?: number
  webhook_config_id?: number
  recording_enabled?: boolean
  note?: string
  status?: string
}

export interface SKUResponse {
  id: number
  sku_name: string
  sku_id_external: string | null
  base_price: number | null
  current_price: number | null
  is_monitored: boolean
  status: string
  note: string | null
  sort_order: number
  last_updated_at: string | null
}

export interface SKUConfig {
  sku_name: string
  sku_id_external?: string
  base_price?: number
  is_monitored?: boolean
  note?: string
}

export interface SKUChangeEvent {
  id: number
  task_id: number
  sku_id: number | null
  sku_name: string
  source: string
  change_type: string
  changed_fields: string[]
  old_values: Record<string, unknown>
  new_values: Record<string, unknown>
  changed_by: number | null
  changed_at: string
}

export interface TaskAlertItem {
  id: number
  sku_id: number
  alert_type: string
  base_price: number
  alert_price: number
  price_diff: number
  price_diff_pct: number
  screenshot_path: string | null
  status: string
  detected_at: string | null
  sku_name: string | null
}

export interface TaskDetailResponse {
  task: TaskResponse
  skus: SKUResponse[]
  sku_change_events: SKUChangeEvent[]
  alerts: TaskAlertItem[]
}

export interface ParseURLResponse {
  platform: string
  product_title: string | null
  shop_name: string | null
  product_image: string | null
  skus: Array<{
    name: string
    price: number
    sku_id: string | null
    note?: string | null
    note_conflict?: boolean
    note_candidates?: string[]
  }>
}

// -- Dashboard --
export interface DashboardStats {
  total_tasks: number
  alert_sku_count: number
  today_new_alerts: number
  collect_success_rate: number
  account_status: string
}

export interface AlertSummary {
  id: number
  detected_at: string
  shop_name: string | null
  product_title: string | null
  sku_name: string | null
  price_diff_pct: number
  platform: string | null
}

export interface TrendData {
  date: string
  count: number
}

export interface ShopRank {
  shop_name: string
  alert_count: number
  platform: string
}

export interface ErrorTaskSummary {
  id: number
  product_title: string | null
  shop_name: string | null
  platform: string
  status: string
  last_error: string | null
  last_check_at: string | null
}

export interface DashboardResponse {
  stats: DashboardStats
  latest_alerts: AlertSummary[]
  trend_7days: TrendData[]
  shop_rank: ShopRank[]
  error_tasks: ErrorTaskSummary[]
}

// -- 异动 --
export interface AlertResponse {
  id: number
  task_id: number
  sku_id: number
  alert_type: string
  base_price: number
  alert_price: number
  price_diff: number
  price_diff_pct: number
  screenshot_path: string | null
  status: string
  resolved_note: string | null
  webhook_sent: boolean
  detected_at: string
  resolved_at: string | null
  product_title: string | null
  shop_name: string | null
  sku_name: string | null
  platform: string | null
  age_minutes?: number | null
}

export interface AlertListResponse {
  total: number
  alerts: AlertResponse[]
}

export interface AlertStatusUpdate {
  status: string
  resolved_note?: string
}

export interface AlertStatistics {
  today_new: number
  last_7_days: number
  unprocessed: number
  status_distribution: Record<string, number>
}

// -- 浏览器配置 --
export interface BrowserProfile {
  id: number
  name: string
  platform: string
  user_agent: string | null
  viewport_width: number
  viewport_height: number
  locale: string
  timezone: string
  proxy_type: string
  proxy_host: string | null
  proxy_port: number | null
  cookie_status: string
  is_active: boolean
  last_login_at: string | null
  has_login_credentials: boolean
  created_at: string
}

export interface BrowserProfileCreate {
  name: string
  platform?: string
  user_agent?: string
  viewport_width?: number
  viewport_height?: number
  locale?: string
  timezone?: string
  proxy_type?: string
  proxy_host?: string
  proxy_port?: number
  proxy_username?: string
  proxy_password?: string
  login_username?: string
  login_password?: string
}

export interface BrowserProfileUpdate {
  name?: string
  user_agent?: string
  viewport_width?: number
  viewport_height?: number
  proxy_type?: string
  proxy_host?: string
  proxy_port?: number
  proxy_username?: string
  proxy_password?: string
  login_username?: string
  login_password?: string
  is_active?: boolean
}

// -- Webhook --
export interface WebhookConfig {
  id: number
  name: string
  webhook_url: string
  webhook_type: string
  is_default: boolean
  is_active: boolean
  created_at: string
  secret: string | null
  mentioned_list: string | null
  mentioned_mobile_list: string | null
  msg_type: string
  keyword: string | null
  webhook_url_configured: boolean
  secret_configured: boolean
}

export interface WebhookCreate {
  name: string
  webhook_url: string
  webhook_type?: string
  is_default?: boolean
  secret?: string
  mentioned_list?: string
  mentioned_mobile_list?: string
  msg_type?: string
  keyword?: string
}

export interface WebhookUpdate {
  name?: string
  webhook_url?: string
  webhook_type?: string
  is_default?: boolean
  is_active?: boolean
  secret?: string
  mentioned_list?: string
  mentioned_mobile_list?: string
  msg_type?: string
  keyword?: string
}

// -- 日志 --
export interface LogEntry {
  timestamp: string
  level: string
  category: string
  module: string
  message: string
  task_id: number | null
  sku_id: number | null
  user_id: number | null
  trace_id: string | null
  data: Record<string, unknown> | null
}

export interface LogListResponse {
  total: number
  logs: LogEntry[]
}

// -- 录屏 --
export interface RecordingFile {
  filename: string
  path: string
  size_mb: number
  created_at: string
  task_id: number | null
}

export interface RecordingListResponse {
  total: number
  recordings: RecordingFile[]
  total_size_mb: number
}

// -- 趋势 --
export interface TrendPoint {
  date: string
  price: number
  collected_at?: string
}

export interface TrendResponse {
  sku_id: number
  sku_name: string
  base_price: number
  points: TrendPoint[]
}

// -- 系统设置 --
export interface SystemSettings {
  [key: string]: unknown
}

// ===== API 模块 =====

// 1. 认证API
export const authApi = {
  getInitStatus(): Promise<InitStatusResponse> {
    return apiClient.get('/auth/init-status')
  },
  initAdmin(data: InitAdminRequest): Promise<LoginResponse> {
    return apiClient.post('/auth/init-admin', data)
  },
  login(data: LoginRequest): Promise<LoginResponse> {
    return apiClient.post('/auth/login', data)
  },
  logout(): Promise<{ message: string }> {
    return apiClient.post('/auth/logout')
  },
  getCurrentUser(): Promise<UserInfo> {
    return apiClient.get('/auth/me')
  },
  changePassword(oldPassword: string, newPassword: string): Promise<{ message: string }> {
    return apiClient.post('/auth/change-password', {
      old_password: oldPassword,
      new_password: newPassword,
    })
  },
}

// 2. 用户管理API
export const usersApi = {
  list(): Promise<{ total: number; users: User[] }> {
    return apiClient.get('/users')
  },
  create(data: UserCreateRequest): Promise<User> {
    return apiClient.post('/users', data)
  },
  update(userId: number, data: UserUpdateRequest): Promise<User> {
    return apiClient.put(`/users/${userId}`, data)
  },
  delete(userId: number): Promise<{ message: string }> {
    return apiClient.delete(`/users/${userId}`)
  },
  resetPassword(userId: number, newPassword: string): Promise<{ message: string }> {
    return apiClient.post(`/users/${userId}/reset-password`, { new_password: newPassword })
  },
}

// 3. Dashboard API
export const dashboardApi = {
  getSummary(): Promise<DashboardResponse> {
    return apiClient.get('/dashboard')
  },
  getStats(): Promise<DashboardStats> {
    return apiClient.get('/dashboard/stats')
  },
}

// 4. 任务API
export const tasksApi = {
  list(params?: { platform?: string; status?: string; search?: string; page?: number; page_size?: number }): Promise<{ total: number; tasks: TaskResponse[] }> {
    return apiClient.get('/tasks', { params })
  },
  getDetail(taskId: number): Promise<TaskDetailResponse> {
    return apiClient.get(`/tasks/${taskId}`)
  },
  create(data: TaskCreateRequest): Promise<TaskResponse> {
    return apiClient.post('/tasks', data)
  },
  update(taskId: number, data: TaskUpdateRequest): Promise<TaskResponse> {
    return apiClient.put(`/tasks/${taskId}`, data)
  },
  delete(taskId: number): Promise<{ message: string }> {
    return apiClient.delete(`/tasks/${taskId}`)
  },
  parseUrl(url: string): Promise<ParseURLResponse> {
    // SKU解析会驱动浏览器自动化点击，多SKU场景可能超过30秒
    return apiClient.post('/tasks/parse-url', null, {
      params: { url },
      timeout: 120000,
    })
  },
  reparse(taskId: number): Promise<ParseURLResponse> {
    return apiClient.post(`/tasks/${taskId}/reparse`, null, {
      timeout: 120000,
    })
  },
  runNow(taskId: number): Promise<{ message: string; task_id: number }> {
    return apiClient.post(`/tasks/${taskId}/run`)
  },
  configureSkus(taskId: number, skus: SKUConfig[]): Promise<{ message: string }> {
    return apiClient.post(`/tasks/${taskId}/skus`, skus)
  },
  listScreenshots(taskId: number): Promise<{ screenshots: { filename: string; size_kb: number; created_at: string }[] }> {
    return apiClient.get(`/tasks/${taskId}/screenshots`)
  },
  getScreenshotUrl(filename: string): string {
    const token = getToken()
    const encoded = encodeURIComponent(filename)
    return `/api/alerts/screenshot/file?path=${encoded}${token ? `&token=${encodeURIComponent(token)}` : ''}`
  },
}

// 5. 异动记录API
export const alertsApi = {
  list(params?: {
    status?: string
    platform?: string
    alert_type?: string
    start_date?: string
    end_date?: string
    recent_hours?: number
    search?: string
    page?: number
    page_size?: number
  }): Promise<AlertListResponse> {
    return apiClient.get('/alerts', { params })
  },
  getDetail(alertId: number): Promise<AlertResponse> {
    return apiClient.get(`/alerts/${alertId}`)
  },
  updateStatus(alertId: number, data: AlertStatusUpdate): Promise<{ message: string }> {
    return apiClient.put(`/alerts/${alertId}/status`, data)
  },
  delete(alertId: number): Promise<{ message: string }> {
    return apiClient.delete(`/alerts/${alertId}`)
  },
  batchDelete(alertIds: number[]): Promise<{ message: string; deleted_count: number }> {
    return apiClient.post('/alerts/batch-delete', { alert_ids: alertIds })
  },
  getScreenshotUrl(path: string): string {
    const token = getToken()
    const encoded = encodeURIComponent(path)
    return `/api/alerts/screenshot/file?path=${encoded}${token ? `&token=${encodeURIComponent(token)}` : ''}`
  },
  getStatistics(): Promise<AlertStatistics> {
    return apiClient.get('/alerts/statistics')
  },
}

// 6. 浏览器管理API
export const browserApi = {
  list(): Promise<{ total: number; profiles: BrowserProfile[] }> {
    return apiClient.get('/browser')
  },
  getDetail(profileId: number): Promise<BrowserProfile> {
    return apiClient.get(`/browser/${profileId}`)
  },
  create(data: BrowserProfileCreate): Promise<BrowserProfile> {
    return apiClient.post('/browser', data)
  },
  update(profileId: number, data: BrowserProfileUpdate): Promise<BrowserProfile> {
    return apiClient.put(`/browser/${profileId}`, data)
  },
  delete(profileId: number): Promise<{ message: string }> {
    return apiClient.delete(`/browser/${profileId}`)
  },
  openVisual(profileId: number, data?: { url?: string; timeout_seconds?: number }): Promise<{ success: boolean; message: string; profile_id: number; opened_url: string }> {
    return apiClient.post(`/browser/${profileId}/open-visual`, data || {})
  },
  saveCookies(profileId: number): Promise<{ success: boolean; message: string; cookie_count: number; cookie_status: string }> {
    return apiClient.post(`/browser/${profileId}/save-cookies`)
  },
  close(profileId: number): Promise<{ success: boolean; message: string }> {
    return apiClient.post(`/browser/${profileId}/close`)
  },
  importCookies(profileId: number, cookies: unknown[]): Promise<{ success: boolean; message: string; cookie_count: number; cookie_status: string }> {
    return apiClient.post(`/browser/${profileId}/import-cookies`, { cookies })
  },
  autoLogin(profileId: number, data?: { auto_submit?: boolean }): Promise<{ success: boolean; message: string; profile_id: number; opened_url: string }> {
    return apiClient.post(`/browser/${profileId}/auto-login`, data || {})
  },
}

// 7. Webhook配置API
export const webhookApi = {
  list(): Promise<{ total: number; webhooks: WebhookConfig[] }> {
    return apiClient.get('/webhook')
  },
  getDetail(webhookId: number): Promise<WebhookConfig> {
    return apiClient.get(`/webhook/${webhookId}`)
  },
  create(data: WebhookCreate): Promise<WebhookConfig> {
    return apiClient.post('/webhook', data)
  },
  update(webhookId: number, data: WebhookUpdate): Promise<WebhookConfig> {
    return apiClient.put(`/webhook/${webhookId}`, data)
  },
  delete(webhookId: number): Promise<{ message: string }> {
    return apiClient.delete(`/webhook/${webhookId}`)
  },
  test(webhookId: number): Promise<{ success: boolean; message: string }> {
    return apiClient.post(`/webhook/${webhookId}/test`)
  },
}

// 8. 日志查看API
export const logsApi = {
  getCategories(): Promise<{ categories: string[] }> {
    return apiClient.get('/logs/categories')
  },
  query(params?: {
    category?: string
    level?: string
    task_id?: number
    trace_id?: string
    date?: string
    search?: string
    page?: number
    page_size?: number
  }): Promise<LogListResponse> {
    return apiClient.get('/logs', { params })
  },
  getByTraceId(traceId: string): Promise<LogListResponse> {
    return apiClient.get(`/logs/trace/${traceId}`)
  },
}

// 9. 录屏管理API
export const recordingsApi = {
  list(params?: { task_id?: number; days?: number }): Promise<RecordingListResponse> {
    return apiClient.get('/recordings', { params })
  },
  getPlayUrl(filename: string): string {
    const token = getToken()
    return `/api/recordings/${filename}?token=${token}`
  },
  delete(filename: string): Promise<{ message: string }> {
    return apiClient.delete(`/recordings/${filename}`)
  },
  cleanup(days?: number): Promise<{ message: string; deleted_count: number }> {
    return apiClient.post('/recordings/cleanup', null, { params: { days: days || 7 } })
  },
  getStorageInfo(): Promise<{ exists: boolean; path?: string; total_files: number; total_size_mb: number }> {
    return apiClient.get('/recordings/storage-info')
  },
}

// 10. 数据导出API
export const exportApi = {
  exportAlerts(params?: { status?: string; platform?: string; start_date?: string; end_date?: string }): Promise<Blob> {
    return apiClient.get('/export/alerts', {
      params,
      responseType: 'blob',
    }) as unknown as Promise<Blob>
  },
  exportPriceRecords(taskId: number, params?: { start_date?: string; end_date?: string }): Promise<Blob> {
    return apiClient.get(`/export/price-records/${taskId}`, {
      params,
      responseType: 'blob',
    }) as unknown as Promise<Blob>
  },
}

// 11. 价格趋势API
export const trendsApi = {
  getSkuTrend(skuId: number, days?: number): Promise<TrendResponse> {
    return apiClient.get(`/trends/sku/${skuId}`, { params: { days: days || 7 } })
  },
  getTaskTrends(taskId: number, days?: number): Promise<{ task_id: number; skus: Array<TrendResponse & { current_price: number | null }> }> {
    return apiClient.get(`/trends/task/${taskId}`, { params: { days: days || 7 } })
  },
  getTaskSkuList(taskId: number): Promise<{ task_id: number; skus: Array<{ sku_id: number; sku_name: string; base_price: number | null; current_price: number | null }> }> {
    return apiClient.get(`/trends/task/${taskId}/skus`)
  },
}

// 12. 系统设置API
export const settingsApi = {
  getAll(): Promise<SystemSettings> {
    return apiClient.get('/system-settings')
  },
  update(data: SystemSettings): Promise<{ message: string }> {
    return apiClient.put('/system-settings', data)
  },
  getStorageInfo(): Promise<{ database_size_mb: number; screenshots_size_mb: number; recordings_size_mb: number; logs_size_mb: number; total_size_mb: number }> {
    return apiClient.get('/system-settings/storage')
  }
}

// 13. 系统API
export const systemApi = {
  health(): Promise<{ status: string; version: string }> {
    return apiClient.get('/health')
  },
  info(): Promise<{ name: string; version: string; initialized: boolean }> {
    return apiClient.get('/system/info')
  },
}

// 14. LLM 网关 API
export const llmApi = {
  chat(data: {
    model: string
    messages: { role: string; content: string }[]
    temperature?: number
    max_tokens?: number
  }): Promise<{
    id: string
    model: string
    choices: { index: number; message: { role: string; content: string }; finish_reason: string }[]
    usage: { prompt_tokens: number; completion_tokens: number; total_tokens: number }
  }> {
    return apiClient.post('/llm/chat', data)
  },

  getModels(): Promise<{ models: { config_id: number; provider: string; display_name: string; prefixes: string[]; default_model?: string }[] }> {
    return apiClient.get('/llm/models')
  },

  getProviderTypes(): Promise<{ types: { type: string; display_name: string; default_prefixes: string[] }[] }> {
    return apiClient.get('/llm/provider-types')
  },

  getProviders(): Promise<{ providers: any[] }> {
    return apiClient.get('/llm/providers')
  },

  createProvider(data: {
    provider_type: string
    display_name: string
    api_key: string
    base_url?: string
    model_prefixes?: string[]
    default_model?: string
    priority?: number
    rate_limit_rpm?: number
    note?: string
  }): Promise<{ id: number; message: string }> {
    return apiClient.post('/llm/providers', data)
  },

  updateProvider(id: number, data: Record<string, any>): Promise<{ message: string }> {
    return apiClient.put(`/llm/providers/${id}`, data)
  },

  deleteProvider(id: number): Promise<{ message: string }> {
    return apiClient.delete(`/llm/providers/${id}`)
  },

  getUsage(days: number = 7): Promise<{
    period_days: number
    summary: { requests: number; total_tokens: number; prompt_tokens: number; completion_tokens: number; avg_duration_ms: number; errors: number }
    by_model: { model: string; requests: number; total_tokens: number }[]
  }> {
    return apiClient.get('/llm/usage', { params: { days } })
  },

  testProvider(id: number): Promise<{ success: boolean; latency_ms: number; model?: string; response?: string; error?: string }> {
    return apiClient.post(`/llm/providers/${id}/test`)
  },
}

// 16. 引擎管理 API
export const enginesApi = {
  list(): Promise<{ engines: any[] }> {
    return apiClient.get('/engines')
  },
  getActive(): Promise<{ active_engine: any }> {
    return apiClient.get('/engines/active')
  },
  setActive(engine_name: string): Promise<{ message: string }> {
    return apiClient.put('/engines/active', { engine_name })
  },
  reload(): Promise<{ message: string; newly_registered: string[]; all_engines: any[] }> {
    return apiClient.post('/engines/reload')
  },
  getConfig(): Promise<{ engine_strategy: string; ai_rpa_max_explore_rounds: number; ai_rpa_timeout_seconds: number; ai_autonomy_level: number }> {
    return apiClient.get('/engines/config')
  },
  updateConfig(data: Record<string, any>): Promise<{ message: string; config: any }> {
    return apiClient.put('/engines/config', data)
  },
  getServiceBindings(): Promise<{ bindings: any[] }> {
    return apiClient.get('/engines/service-bindings')
  },
  updateServiceBinding(service_name: string, data: Record<string, any>): Promise<{ message: string; binding: any }> {
    return apiClient.put(`/engines/service-bindings/${service_name}`, data)
  },
}

// ===== 插件市场 API =====

export const pluginsApi = {
  list(): Promise<{ plugins: any[] }> {
    return apiClient.get('/plugins')
  },
  upload(file: File): Promise<{ message: string; plugin_id: number }> {
    const formData = new FormData()
    formData.append('file', file)
    return apiClient.post('/plugins/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  },
  review(pluginId: number, action: string, reason?: string): Promise<{ message: string }> {
    return apiClient.put(`/plugins/${pluginId}/review`, { action, reason })
  },
  toggle(pluginId: number, isEnabled: boolean): Promise<{ message: string }> {
    return apiClient.put(`/plugins/${pluginId}/toggle`, { is_enabled: isEnabled })
  },
  remove(pluginId: number): Promise<{ message: string }> {
    return apiClient.delete(`/plugins/${pluginId}`)
  },
  execute(pluginId: number, functionName: string = 'run', kwargs?: Record<string, any>): Promise<any> {
    return apiClient.post(`/plugins/${pluginId}/execute`, { function_name: functionName, kwargs })
  },
  getConfig(pluginId: number): Promise<{ config_schema: any; config_values: any }> {
    return apiClient.get(`/plugins/${pluginId}/config`)
  },
  updateConfig(pluginId: number, configValues: Record<string, any>): Promise<{ message: string }> {
    return apiClient.put(`/plugins/${pluginId}/config`, { config_values: configValues })
  },
}

// ===== AI Watchdog API =====

export const watchdogApi = {
  status(): Promise<{ is_running: boolean; autonomy_level: number; recent_reports_count: number }> {
    return apiClient.get('/watchdog/status')
  },
  reports(): Promise<{ reports: any[] }> {
    return apiClient.get('/watchdog/reports')
  },
  memory(): Promise<{ memory: any }> {
    return apiClient.get('/watchdog/memory')
  },
  start(): Promise<{ message: string }> {
    return apiClient.post('/watchdog/start')
  },
  stop(): Promise<{ message: string }> {
    return apiClient.post('/watchdog/stop')
  },
}

// ===== 工具函数 =====

/**
 * 下载Blob为文件
 */
export function downloadBlob(blob: Blob, filename: string) {
  const url = window.URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  window.URL.revokeObjectURL(url)
}

/**
 * 格式化时间
 */
export function formatDateTime(dateStr: string | null): string {
  if (!dateStr) return '-'
  const date = new Date(dateStr)
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/**
 * 格式化价格
 */
export function formatPrice(price: number | null): string {
  if (price === null || price === undefined) return '-'
  return `¥${price.toFixed(2)}`
}

/**
 * 平台中文名
 */
export function platformLabel(platform: string): string {
  const map: Record<string, string> = {
    tmall: '天猫',
    taobao: '淘宝',
  }
  return map[platform] || platform
}

/**
 * 状态中文名 + 颜色
 */
export function taskStatusInfo(status: string): { label: string; type: 'success' | 'warning' | 'danger' | 'info' } {
  const map: Record<string, { label: string; type: 'success' | 'warning' | 'danger' | 'info' }> = {
    active: { label: '运行中', type: 'success' },
    paused: { label: '已暂停', type: 'info' },
    error: { label: '异常', type: 'danger' },
    alert: { label: '异动', type: 'warning' },
  }
  return map[status] || { label: status, type: 'info' }
}

/**
 * 异动状态中文名 + 颜色
 */
export function alertStatusInfo(status: string): { label: string; type: 'success' | 'warning' | 'danger' | 'info' } {
  const map: Record<string, { label: string; type: 'success' | 'warning' | 'danger' | 'info' }> = {
    new: { label: '未处理', type: 'danger' },
    confirmed: { label: '已确认', type: 'warning' },
    resolved: { label: '已处理', type: 'success' },
    false_alarm: { label: '误报', type: 'info' },
  }
  return map[status] || { label: status, type: 'info' }
}
