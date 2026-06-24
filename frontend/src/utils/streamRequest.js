import { buildRequestHeaders, requestBaseURL } from './request'

// 使用 XMLHttpRequest 实现浏览器端流式请求，避免使用 fetch。
export function streamRequest({
  url,
  method = 'POST',
  data,
  timeout = 120000,
  onEvent
}) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    let processedLength = 0
    let buffer = ''
    let settled = false

    function settle(callback, payload) {
      if (settled) {
        return
      }
      settled = true
      callback(payload)
    }

    function processIncomingText(text) {
      buffer += text
      const eventBlocks = buffer.split('\n\n')
      buffer = eventBlocks.pop() || ''

      eventBlocks.forEach((block) => {
        const dataLines = block
          .split('\n')
          .filter((line) => line.startsWith('data:'))
          .map((line) => line.slice(5).trim())

        if (!dataLines.length) {
          return
        }

        try {
          const payload = JSON.parse(dataLines.join('\n'))
          onEvent?.(payload)

          if (payload.type === 'done') {
            settle(resolve, payload.data?.session_detail || null)
          }

          if (payload.type === 'error') {
            settle(reject, new Error(payload.message || '流式请求失败'))
          }
        } catch (error) {
          settle(reject, new Error('流式响应解析失败'))
        }
      })
    }

    xhr.open(method, `${requestBaseURL}${url}`, true)
    xhr.timeout = timeout

    const isFormData = data instanceof FormData
    const headers = buildRequestHeaders(isFormData
      ? { Accept: 'text/event-stream' }
      : {
          Accept: 'text/event-stream',
          'Content-Type': 'application/json'
        })

    Object.entries(headers).forEach(([key, value]) => {
      if (value) {
        xhr.setRequestHeader(key, value)
      }
    })

    xhr.onprogress = () => {
      const nextChunk = xhr.responseText.slice(processedLength)
      processedLength = xhr.responseText.length
      if (nextChunk) {
        processIncomingText(nextChunk)
      }
    }

    xhr.onerror = () => {
      settle(reject, new Error('网络异常，流式请求失败'))
    }

    xhr.ontimeout = () => {
      settle(reject, new Error('请求超时，流式响应未完成'))
    }

    xhr.onload = () => {
      if (xhr.status < 200 || xhr.status >= 300) {
        try {
          const errorPayload = JSON.parse(xhr.responseText)
          settle(reject, new Error(errorPayload.detail || '流式请求失败'))
        } catch (error) {
          settle(reject, new Error(`流式请求失败，状态码：${xhr.status}`))
        }
        return
      }

      const finalChunk = xhr.responseText.slice(processedLength)
      if (finalChunk) {
        processIncomingText(finalChunk)
      }

      if (!settled) {
        settle(resolve, null)
      }
    }

    xhr.send(isFormData ? data : JSON.stringify(data || {}))
  })
}

