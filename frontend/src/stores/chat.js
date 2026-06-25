import { defineStore } from 'pinia'

import {
  createChatSession,
  getChatSessionDetail,
  getChatSessions,
  streamChatMessage,
} from '../api/chat'

function resolveRequestErrorMessage(error, fallbackMessage) {
  if (error?.response?.data?.detail) {
    return error.response.data.detail
  }

  if (error?.message) {
    return `${fallbackMessage}，请确认后端已启动且已放行 http://127.0.0.1:5174 的跨域访问`
  }

  return fallbackMessage
}

function createTempId(prefix) {
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`
}

function buildOptimisticUserContent(content, files) {
  const trimmedContent = content.trim()
  const normalizedFiles = Array.isArray(files) ? files.filter(Boolean) : files ? [files] : []

  if (normalizedFiles.length === 0) {
    return trimmedContent
  }

  const fileNote = normalizedFiles.map((file) => {
    const isPdf = file.name?.toLowerCase().endsWith('.pdf')
    return isPdf
      ? `已上传 PDF 文件：${file.name}`
      : `已上传图片文件：${file.name}`
  }).join('\n')

  return [trimmedContent, fileNote].filter(Boolean).join('\n')
}

function buildSessionSummary(detail) {
  const lastMessage = detail.messages[detail.messages.length - 1]

  return {
    id: detail.id,
    title: detail.title,
    created_at: detail.created_at,
    updated_at: detail.updated_at,
    message_count: detail.message_count,
    last_message_preview: lastMessage?.content?.slice(0, 36) || '',
    has_medical_report: detail.has_medical_report,
    health_risk_level: detail.health_risk_level
  }
}

export const useChatStore = defineStore('chat', {
  state: () => ({
    sessions: [],
    currentSessionId: '',
    currentMessages: [],
    currentWorkflowState: null,
    initializing: false,
    sending: false,
    activeStreamSessionId: '',
    errorMessage: ''
  }),
  getters: {
    currentSession(state) {
      return state.sessions.find((item) => item.id === state.currentSessionId) || null
    }
  },
  actions: {
    // 初始化聊天页面数据。
    async initialize() {
      this.initializing = true
      this.errorMessage = ''

      try {
        if (this.sending && this.currentSessionId) {
          await this.fetchSessions()
          return
        }

        await this.fetchSessions()

        if (this.sessions.length > 0) {
          await this.selectSession(this.sessions[0].id)
          return
        }

        const session = await this.createSession()
        await this.selectSession(session.id)
      } catch (error) {
        this.errorMessage = resolveRequestErrorMessage(error, '初始化聊天失败，请稍后重试')
      } finally {
        this.initializing = false
      }
    },
    // 获取会话列表。
    async fetchSessions() {
      const response = await getChatSessions()
      this.sessions = response.data
      return this.sessions
    },
    // 创建新会话。
    async createSession(title = '') {
      const response = await createChatSession({ title: title || null })
      const session = response.data
      this.applySessionDetail(session)
      return session
    },
    // 切换当前会话。
    async selectSession(sessionId) {
      if (this.sending && this.activeStreamSessionId && sessionId !== this.activeStreamSessionId) {
        this.errorMessage = '当前回复还在生成中，请稍后再切换会话。'
        return null
      }

      const response = await getChatSessionDetail(sessionId)
      const session = response.data
      this.applySessionDetail(session)
      return session
    },
    // 发送用户消息，可附带图片或 PDF。
    async sendMessage(payload) {
      const content = typeof payload === 'string' ? payload : payload?.content || ''
      const files = typeof payload === 'string'
        ? []
        : Array.isArray(payload?.files)
          ? payload.files.filter(Boolean)
          : payload?.file
            ? [payload.file]
            : []
      const trimmedContent = content.trim()

      if (!trimmedContent && files.length === 0) {
        return null
      }

      this.sending = true
      this.errorMessage = ''

      try {
        if (!this.currentSessionId) {
          const session = await this.createSession()
          this.currentSessionId = session.id
        }
        this.activeStreamSessionId = this.currentSessionId

        const optimisticUserMessage = {
          id: createTempId('user'),
          role: 'user',
          content: buildOptimisticUserContent(content, files),
          created_at: new Date().toISOString(),
          pending: true,
          failed: false
        }
        const optimisticAssistantMessage = {
          id: createTempId('assistant'),
          role: 'assistant',
          content: '',
          thinking_content: '',
          created_at: new Date().toISOString(),
          pending: true,
          failed: false
        }

        this.currentMessages = [
          ...this.currentMessages,
          optimisticUserMessage,
          optimisticAssistantMessage
        ]

        let streamPayload = { content: trimmedContent }
        if (files.length > 0) {
          const formData = new FormData()
          if (files.length === 1) {
            formData.append('file', files[0])
          } else {
            files.forEach((file) => formData.append('files', file))
          }
          if (trimmedContent) {
            formData.append('content', trimmedContent)
          }
          streamPayload = formData
        }

        const session = await streamChatMessage(
          this.currentSessionId,
          streamPayload,
          {
            onEvent: (event) => {
              if (event.type !== 'delta' && event.type !== 'thinking_delta') {
                return
              }

              this.currentMessages = this.currentMessages.map((message) => {
                if (message.id === optimisticUserMessage.id) {
                  return {
                    ...message,
                    pending: false
                  }
                }

                if (message.id === optimisticAssistantMessage.id) {
                  const eventContent = event.data?.content || ''
                  return {
                    ...message,
                    content: event.type === 'delta'
                      ? `${message.content || ''}${eventContent}`
                      : message.content,
                    thinking_content: event.type === 'thinking_delta'
                      ? `${message.thinking_content || ''}${eventContent}`
                      : message.thinking_content || '',
                    pending: true,
                    failed: false
                  }
                }

                return message
              })
            }
          }
        )

        this.currentMessages = this.currentMessages.map((message) => {
          if (message.id === optimisticUserMessage.id) {
            return {
              ...message,
              pending: false
            }
          }

          return message
        })

        if (!session) {
          this.currentMessages = this.currentMessages.map((message) => {
            if (message.id === optimisticAssistantMessage.id) {
              return {
                ...message,
                pending: false,
                content: message.content || '本次流式响应未返回完整会话，请刷新后查看。'
              }
            }

            return message
          })
          return null
        }

        this.applySessionDetail(session, { force: true })
        return session
      } catch (error) {
        this.currentMessages = this.currentMessages.map((message) => {
          if (message.pending && message.role === 'user') {
            return {
              ...message,
              pending: false,
              failed: true
            }
          }

          if (message.pending && message.role === 'assistant') {
            return {
              ...message,
              pending: false,
              failed: true,
              content: '发送失败，请检查网络或稍后重试。'
            }
          }

          return message
        })
        this.errorMessage = resolveRequestErrorMessage(error, '发送消息失败，请稍后重试')
        throw error
      } finally {
        this.sending = false
        this.activeStreamSessionId = ''
      }
    },
    // 将会话详情同步到左侧历史列表。
    upsertSession(sessionDetail) {
      const summary = buildSessionSummary(sessionDetail)
      const existedIndex = this.sessions.findIndex((item) => item.id === summary.id)

      if (existedIndex >= 0) {
        this.sessions.splice(existedIndex, 1, summary)
      } else {
        this.sessions.unshift(summary)
      }

      this.sessions.sort(
        (prev, next) => new Date(next.updated_at).getTime() - new Date(prev.updated_at).getTime()
      )
    },
    // 统一把会话详情同步到当前页面状态。
    applySessionDetail(sessionDetail, options = {}) {
      if (!options.force && this.sending && sessionDetail.id === this.activeStreamSessionId) {
        this.currentWorkflowState = sessionDetail.workflow_state || this.currentWorkflowState
        this.upsertSession(sessionDetail)
        return
      }

      this.currentSessionId = sessionDetail.id
      this.currentMessages = sessionDetail.messages
      this.currentWorkflowState = sessionDetail.workflow_state || null
      this.upsertSession(sessionDetail)
    },
    resetState() {
      this.sessions = []
      this.currentSessionId = ''
      this.currentMessages = []
      this.currentWorkflowState = null
      this.initializing = false
      this.sending = false
      this.activeStreamSessionId = ''
      this.errorMessage = ''
    }
  }
})

