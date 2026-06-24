import { defineStore } from 'pinia'

import { getCurrentUser, loginUser, registerUser } from '../api/auth'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    token: localStorage.getItem('token') || '',
    userInfo: JSON.parse(localStorage.getItem('userInfo') || 'null')
  }),
  getters: {
    isLoggedIn: (state) => Boolean(state.token)
  },
  actions: {
    // 统一写入登录态数据。
    setAuthData(token, userInfo) {
      this.token = token
      this.userInfo = userInfo
      localStorage.setItem('token', token)
      localStorage.setItem('userInfo', JSON.stringify(userInfo))
    },
    // 清理本地登录态。
    clearAuthData() {
      this.token = ''
      this.userInfo = null
      localStorage.removeItem('token')
      localStorage.removeItem('userInfo')
    },
    async register(payload) {
      const response = await registerUser(payload)
      return response.data
    },
    async login(payload) {
      const response = await loginUser(payload)
      this.setAuthData(response.data.access_token, response.data.user)
      return response.data
    },
    async fetchProfile() {
      if (!this.token) {
        return null
      }

      const response = await getCurrentUser()
      this.userInfo = response.data
      localStorage.setItem('userInfo', JSON.stringify(response.data))
      return response.data
    },
    logout() {
      this.clearAuthData()
    }
  }
})

