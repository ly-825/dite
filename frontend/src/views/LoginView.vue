<template>
  <div class="auth-page">
    <div class="auth-card">
      <h1>登录</h1>
      <p class="auth-subtitle">
        请输入账号和密码登录系统
      </p>

      <form
        class="auth-form"
        @submit.prevent="handleLogin"
      >
        <label>
          <span>账号</span>
          <input
            v-model.trim="form.account"
            type="text"
            placeholder="请输入用户名或邮箱"
          >
        </label>

        <label>
          <span>密码</span>
          <input
            v-model.trim="form.password"
            type="password"
            placeholder="请输入密码"
          >
        </label>

        <p
          v-if="errorMessage"
          class="form-error"
        >
          {{ errorMessage }}
        </p>

        <button
          class="submit-button"
          :disabled="submitting"
          type="submit"
        >
          {{ submitting ? '登录中...' : '立即登录' }}
        </button>
      </form>

      <p class="switch-link">
        还没有账号？
        <RouterLink to="/register">
          去注册
        </RouterLink>
      </p>
    </div>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'

import { useAuthStore } from '../stores/auth'

const router = useRouter()
const authStore = useAuthStore()

// 登录表单数据。
const form = reactive({
  account: '',
  password: ''
})
const submitting = ref(false)
const errorMessage = ref('')

async function handleLogin() {
  errorMessage.value = ''

  if (!form.account || !form.password) {
    errorMessage.value = '请输入完整的登录信息'
    return
  }

  submitting.value = true

  try {
    await authStore.login(form)
    await router.push('/')
  } catch (error) {
    errorMessage.value = error.response?.data?.detail || '登录失败，请稍后重试'
  } finally {
    submitting.value = false
  }
}
</script>

<style lang="scss" scoped>
.auth-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: linear-gradient(135deg, #f4f7ff 0%, #eef3f8 100%);
}

.auth-card {
  width: 100%;
  max-width: 420px;
  padding: 36px 32px;
  border-radius: 20px;
  background: #ffffff;
  box-shadow: 0 16px 48px rgba(39, 67, 117, 0.12);

  h1 {
    margin: 0;
    font-size: 30px;
    color: #1f2937;
  }
}

.auth-subtitle {
  margin: 12px 0 24px;
  color: #6b7280;
}

.auth-form {
  display: flex;
  flex-direction: column;
  gap: 16px;

  label {
    display: flex;
    flex-direction: column;
    gap: 8px;
    color: #374151;
    font-weight: 600;
  }

  input {
    height: 44px;
    padding: 0 14px;
    border: 1px solid #d1d5db;
    border-radius: 12px;
    font-size: 14px;
    transition: border-color 0.2s ease;

    &:focus {
      outline: none;
      border-color: #4f46e5;
    }
  }
}

.form-error {
  margin: 0;
  color: #dc2626;
  font-size: 14px;
}

.submit-button {
  height: 46px;
  border: none;
  border-radius: 12px;
  background: #4f46e5;
  color: #ffffff;
  font-size: 15px;
  font-weight: 600;
  cursor: pointer;

  &:disabled {
    opacity: 0.7;
    cursor: not-allowed;
  }
}

.switch-link {
  margin: 20px 0 0;
  color: #6b7280;
  text-align: center;

  a {
    color: #4f46e5;
    font-weight: 600;
  }
}
</style>


