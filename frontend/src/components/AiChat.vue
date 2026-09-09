<template>
  <!-- 浮动触发按钮 -->
  <div
    v-if="!visible"
    class="ai-chat-fab"
    :style="fabStyle"
    @mousedown="startDragFab"
    title="AI 助手"
  >
    <el-icon :size="22"><ChatDotRound /></el-icon>
  </div>

  <!-- 聊天面板 -->
  <transition name="chat-slide">
    <div v-if="visible" class="ai-chat-panel" :style="panelStyle">
      <!-- 头部（可拖动） -->
      <div class="chat-header" @mousedown="startDragPanel">
        <div class="chat-header-left">
          <el-icon :size="18" style="margin-right:6px"><ChatDotRound /></el-icon>
          <span class="chat-title">AI 助手</span>
        </div>
        <div class="chat-header-right">
          <el-select v-model="currentModel" size="small" style="width: 155px" placeholder="选择模型">
            <el-option v-for="m in availableModels" :key="m" :label="m" :value="m" />
          </el-select>
          <el-button size="small" text @click="handleClear" title="清空对话">
            <el-icon><Delete /></el-icon>
          </el-button>
          <el-button size="small" text @click="visible = false" title="收起">
            <el-icon><ArrowDown /></el-icon>
          </el-button>
        </div>
      </div>

      <!-- 消息列表 -->
      <div ref="messagesRef" class="chat-messages">
        <div v-if="messages.length === 0" class="chat-empty">
          <el-icon :size="40" color="#c0c4cc"><ChatDotRound /></el-icon>
          <p>你好，我是 AI 助手</p>
          <p class="chat-empty-sub">可以帮你分析价格趋势、解读异动、提供运营建议</p>
        </div>
        <div
          v-for="(msg, idx) in messages"
          :key="idx"
          class="chat-msg"
          :class="msg.role"
        >
          <div class="chat-msg-avatar">
            <el-icon v-if="msg.role === 'user'" :size="16"><User /></el-icon>
            <el-icon v-else :size="16"><MagicStick /></el-icon>
          </div>
          <div class="chat-msg-content">
            <div v-if="msg.role === 'assistant'" class="chat-msg-text" v-html="renderMarkdown(msg.content)"></div>
            <div v-else class="chat-msg-text">{{ msg.content }}</div>
            <div v-if="msg.role === 'assistant' && msg.loading" class="chat-typing">
              <span></span><span></span><span></span>
            </div>
          </div>
        </div>
      </div>

      <!-- 输入区 -->
      <div class="chat-input-area">
        <el-input
          v-model="inputText"
          type="textarea"
          :autosize="{ minRows: 1, maxRows: 4 }"
          placeholder="输入消息，Enter 发送，Shift+Enter 换行"
          @keydown="handleInputKeydown"
          :disabled="streaming"
          resize="none"
        />
        <el-button
          type="primary"
          :icon="streaming ? undefined : Promotion"
          :loading="streaming"
          circle
          size="small"
          @click="handleSend"
          :disabled="!inputText.trim() && !streaming"
          class="chat-send-btn"
        />
      </div>
    </div>
  </transition>
</template>

<script setup lang="ts">
import { ref, reactive, nextTick, watch, computed } from 'vue'
import { ChatDotRound, Delete, ArrowDown, User, MagicStick, Promotion } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { getToken, llmApi } from '@/api'

interface ChatMsg {
  role: 'user' | 'assistant' | 'system'
  content: string
  loading?: boolean
}

const visible = ref(false)

// ===== 拖动逻辑 =====
const fabPos = reactive({ x: -1, y: -1 })   // -1 = 使用CSS默认值
const panelPos = reactive({ x: -1, y: -1 })
const dragging = ref(false)
const dragMoved = ref(false)

const fabStyle = computed(() => {
  if (fabPos.x < 0) return {}
  return { right: 'auto', bottom: 'auto', left: fabPos.x + 'px', top: fabPos.y + 'px' }
})
const panelStyle = computed(() => {
  if (panelPos.x < 0) return {}
  return { right: 'auto', bottom: 'auto', left: panelPos.x + 'px', top: panelPos.y + 'px' }
})

function startDragFab(e: MouseEvent) {
  dragMoved.value = false
  const el = e.currentTarget as HTMLElement
  const rect = el.getBoundingClientRect()
  const offsetX = e.clientX - rect.left
  const offsetY = e.clientY - rect.top
  dragging.value = true

  const onMove = (ev: MouseEvent) => {
    dragMoved.value = true
    fabPos.x = Math.max(0, Math.min(ev.clientX - offsetX, window.innerWidth - 48))
    fabPos.y = Math.max(0, Math.min(ev.clientY - offsetY, window.innerHeight - 48))
  }
  const onUp = () => {
    dragging.value = false
    document.removeEventListener('mousemove', onMove)
    document.removeEventListener('mouseup', onUp)
    if (!dragMoved.value) visible.value = true
  }
  document.addEventListener('mousemove', onMove)
  document.addEventListener('mouseup', onUp)
}

function startDragPanel(e: MouseEvent) {
  // 不拦截按钮点击
  if ((e.target as HTMLElement).closest('.el-button, .el-select, .el-input')) return
  const el = (e.currentTarget as HTMLElement).closest('.ai-chat-panel') as HTMLElement
  if (!el) return
  const rect = el.getBoundingClientRect()
  const offsetX = e.clientX - rect.left
  const offsetY = e.clientY - rect.top
  dragging.value = true

  const onMove = (ev: MouseEvent) => {
    panelPos.x = Math.max(0, Math.min(ev.clientX - offsetX, window.innerWidth - 400))
    panelPos.y = Math.max(0, Math.min(ev.clientY - offsetY, window.innerHeight - 200))
  }
  const onUp = () => {
    dragging.value = false
    document.removeEventListener('mousemove', onMove)
    document.removeEventListener('mouseup', onUp)
  }
  document.addEventListener('mousemove', onMove)
  document.addEventListener('mouseup', onUp)
}
const inputText = ref('')
const streaming = ref(false)
const messages = ref<ChatMsg[]>([])
const messagesRef = ref<HTMLElement | null>(null)
const currentModel = ref('')
const availableModels = ref<string[]>([])

// 加载可用模型
async function loadModels() {
  try {
    const data = await llmApi.getModels()
    const models: string[] = []
    let firstDefault = ''
    for (const p of (data.models || []) as any[]) {
      if (p.default_model) {
        models.push(p.default_model)
        if (!firstDefault) firstDefault = p.default_model
      } else {
        // 无 default_model 时用前缀生成占位模型名
        for (const prefix of p.prefixes || []) {
          models.push(prefix.replace(/-$/, ''))
        }
      }
    }
    availableModels.value = models.length > 0 ? models : ['deepseek-chat']
    if (!currentModel.value) {
      currentModel.value = firstDefault || availableModels.value[0]
    }
  } catch {
    availableModels.value = ['deepseek-chat']
    if (!currentModel.value) currentModel.value = 'deepseek-chat'
  }
}

// 简易 Markdown 渲染 (无外部依赖)
function renderMarkdown(text: string): string {
  if (!text) return ''
  let html = text
    // code blocks
    .replace(/```(\w*)\n([\s\S]*?)```/g, '<pre><code class="lang-$1">$2</code></pre>')
    // inline code
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    // bold
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    // italic
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    // line breaks
    .replace(/\n/g, '<br>')
  return html
}

function scrollToBottom() {
  nextTick(() => {
    if (messagesRef.value) {
      messagesRef.value.scrollTop = messagesRef.value.scrollHeight
    }
  })
}

function handleInputKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    handleSend()
  }
}

async function handleSend() {
  const text = inputText.value.trim()
  if (!text || streaming.value) return
  if (!currentModel.value) {
    ElMessage.warning('请先选择模型')
    return
  }

  // 添加用户消息
  messages.value.push({ role: 'user', content: text })
  inputText.value = ''
  scrollToBottom()

  // 添加助手占位
  const assistantIdx = messages.value.length
  messages.value.push({ role: 'assistant', content: '', loading: true })
  scrollToBottom()

  streaming.value = true

  try {
    // 构建请求体
    const body = {
      model: currentModel.value,
      messages: messages.value
        .filter(m => m.role !== 'system' || m.content)
        .slice(0, -1) // 排除占位消息
        .map(m => ({ role: m.role, content: m.content })),
      temperature: 0.7,
      stream: true,
    }

    const token = getToken()
    const response = await fetch('/api/llm/chat/stream', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
      },
      body: JSON.stringify(body),
    })

    if (!response.ok) {
      const errText = await response.text()
      throw new Error(`HTTP ${response.status}: ${errText.slice(0, 200)}`)
    }

    const reader = response.body?.getReader()
    if (!reader) throw new Error('无法读取响应流')

    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue
        const dataStr = line.slice(6).trim()
        if (dataStr === '[DONE]') continue
        // 检查是否是错误
        try {
          const data = JSON.parse(dataStr)
          if (data.error) {
            messages.value[assistantIdx].content += `\n\n⚠️ ${data.error.message}`
            messages.value[assistantIdx].loading = false
            scrollToBottom()
            continue
          }
          const delta = data.choices?.[0]?.delta
          if (delta?.content) {
            messages.value[assistantIdx].content += delta.content
            messages.value[assistantIdx].loading = false
            scrollToBottom()
          }
          if (data.choices?.[0]?.finish_reason) {
            messages.value[assistantIdx].loading = false
          }
        } catch {
          // JSON解析失败，忽略
        }
      }
    }

    messages.value[assistantIdx].loading = false
  } catch (e: any) {
    messages.value[assistantIdx].content = `⚠️ 请求失败: ${e.message || e}`
    messages.value[assistantIdx].loading = false
  } finally {
    streaming.value = false
    scrollToBottom()
  }
}

function handleClear() {
  messages.value = []
}

watch(visible, (v) => {
  if (v && availableModels.value.length === 0) {
    loadModels()
  }
})
</script>

<style scoped>
/* ===== 浮动按钮 ===== */
.ai-chat-fab {
  position: fixed;
  bottom: 60px;
  right: 24px;
  width: 48px;
  height: 48px;
  border-radius: 50%;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: grab;
  box-shadow: 0 4px 14px rgba(102, 126, 234, 0.4);
  z-index: 2000;
  transition: transform 0.2s, box-shadow 0.2s;
}
.ai-chat-fab:hover {
  transform: scale(1.08);
  box-shadow: 0 6px 20px rgba(102, 126, 234, 0.55);
}

/* ===== 聊天面板 ===== */
.ai-chat-panel {
  position: fixed;
  bottom: 20px;
  right: 20px;
  width: 400px;
  height: 560px;
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.15);
  z-index: 2001;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* 头部 */
.chat-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: #fff;
  flex-shrink: 0;
  cursor: move;
}
.chat-header-left {
  display: flex;
  align-items: center;
}
.chat-title {
  font-size: 14px;
  font-weight: 600;
}
.chat-header-right {
  display: flex;
  align-items: center;
  gap: 4px;
}
.chat-header-right .el-button {
  color: #fff !important;
}
.chat-header-right :deep(.el-select .el-input__wrapper) {
  background: rgba(255,255,255,0.2);
  box-shadow: none;
}
.chat-header-right :deep(.el-select .el-input__inner) {
  color: #fff;
  font-size: 12px;
}
.chat-header-right :deep(.el-select .el-input__suffix) {
  color: rgba(255,255,255,0.7);
}

/* 消息列表 */
.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 12px;
  background: #f8f9fb;
}

.chat-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: #909399;
}
.chat-empty p {
  margin: 8px 0 0;
  font-size: 14px;
}
.chat-empty-sub {
  font-size: 12px !important;
  color: #c0c4cc;
}

/* 单条消息 */
.chat-msg {
  display: flex;
  gap: 8px;
  margin-bottom: 14px;
}
.chat-msg.user {
  flex-direction: row-reverse;
}
.chat-msg-avatar {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.chat-msg.user .chat-msg-avatar {
  background: #e8eaed;
  color: #606266;
}
.chat-msg.assistant .chat-msg-avatar {
  background: linear-gradient(135deg, #667eea, #764ba2);
  color: #fff;
}
.chat-msg-content {
  max-width: 82%;
}
.chat-msg-text {
  padding: 8px 12px;
  border-radius: 10px;
  font-size: 13px;
  line-height: 1.6;
  word-break: break-word;
}
.chat-msg.user .chat-msg-text {
  background: #667eea;
  color: #fff;
  border-top-right-radius: 2px;
}
.chat-msg.assistant .chat-msg-text {
  background: #fff;
  color: #303133;
  border-top-left-radius: 2px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.06);
}
.chat-msg.assistant .chat-msg-text :deep(code) {
  background: #f0f2f5;
  padding: 1px 4px;
  border-radius: 3px;
  font-size: 12px;
}
.chat-msg.assistant .chat-msg-text :deep(pre) {
  background: #1e1e2e;
  color: #cdd6f4;
  padding: 10px;
  border-radius: 6px;
  overflow-x: auto;
  margin: 6px 0;
}
.chat-msg.assistant .chat-msg-text :deep(pre code) {
  background: none;
  padding: 0;
  color: inherit;
}
.chat-msg.assistant .chat-msg-text :deep(strong) {
  font-weight: 600;
}

/* 打字指示器 */
.chat-typing {
  display: flex;
  gap: 4px;
  padding: 4px 0;
}
.chat-typing span {
  width: 6px;
  height: 6px;
  background: #909399;
  border-radius: 50%;
  animation: typing-dot 1.2s infinite;
}
.chat-typing span:nth-child(2) { animation-delay: 0.2s; }
.chat-typing span:nth-child(3) { animation-delay: 0.4s; }
@keyframes typing-dot {
  0%, 60%, 100% { opacity: 0.3; transform: scale(0.8); }
  30% { opacity: 1; transform: scale(1); }
}

/* 输入区 */
.chat-input-area {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  padding: 10px 12px;
  border-top: 1px solid #ebeef5;
  background: #fff;
  flex-shrink: 0;
}
.chat-input-area :deep(.el-textarea__inner) {
  font-size: 13px;
  border-radius: 8px;
  padding: 8px 10px;
}
.chat-send-btn {
  flex-shrink: 0;
  margin-bottom: 2px;
}

/* 进出动画 */
.chat-slide-enter-active {
  animation: chat-in 0.3s ease;
}
.chat-slide-leave-active {
  animation: chat-in 0.2s ease reverse;
}
@keyframes chat-in {
  from {
    opacity: 0;
    transform: translateY(20px) scale(0.95);
  }
  to {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}

/* 滚动条 */
.chat-messages::-webkit-scrollbar {
  width: 5px;
}
.chat-messages::-webkit-scrollbar-thumb {
  background: #d0d3d9;
  border-radius: 3px;
}
.chat-messages::-webkit-scrollbar-track {
  background: transparent;
}
</style>
