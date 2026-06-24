import request from '../utils/request'
import { streamRequest } from '../utils/streamRequest'

// 获取会话历史列表。
export function getChatSessions() {
  return request({
    url: '/api/chat/sessions',
    method: 'get'
  })
}

// 创建新会话。
export function createChatSession(data = {}) {
  return request({
    url: '/api/chat/sessions',
    method: 'post',
    data
  })
}

// 获取指定会话的完整消息。
export function getChatSessionDetail(sessionId) {
  return request({
    url: `/api/chat/sessions/${sessionId}`,
    method: 'get'
  })
}

// 向指定会话发送消息。
export function sendChatMessage(sessionId, data) {
  return request({
    url: `/api/chat/sessions/${sessionId}/messages`,
    method: 'post',
    data,
    timeout: 120000
  })
}

// 以流式方式发送纯文本聊天消息。
export function streamChatMessage(sessionId, data, options = {}) {
  return streamRequest({
    url: `/api/chat/sessions/${sessionId}/messages/stream`,
    method: 'post',
    data,
    timeout: 900000,
    onEvent: options.onEvent
  })
}


