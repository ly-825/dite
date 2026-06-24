import axios from 'axios'

export const requestBaseURL = import.meta.env.VITE_API_BASE_URL || ''

export function buildRequestHeaders(extraHeaders = {}) {
  const token = localStorage.getItem('token')
  const headers = {
    ...extraHeaders
  }

  if (token) {
    headers.Authorization = `Bearer ${token}`
  }

  return headers
}

const request = axios.create({
  baseURL: requestBaseURL,
  timeout: 20000
})

// 所有请求统一从本封装发送，避免直接使用 fetch。
request.interceptors.request.use(
  (config) => {
    const headers = buildRequestHeaders(config.headers || {})
    config.headers = headers

    return config
  },
  (error) => Promise.reject(error)
)

request.interceptors.response.use(
  (response) => response,
  (error) => Promise.reject(error)
)

export default request

