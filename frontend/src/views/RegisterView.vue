<template>
  <div class="auth-page">
    <div class="auth-card">
      <h1>注册</h1>
      <p class="auth-subtitle">
        创建你的新账号，完成后即可登录
      </p>

      <form
        class="auth-form"
        @submit.prevent="handleRegister"
      >
        <label>
          <span>用户名</span>
          <input
            v-model.trim="form.username"
            type="text"
            placeholder="请输入用户名，3-20 位"
          >
        </label>

        <label>
          <span>邮箱</span>
          <input
            v-model.trim="form.email"
            type="email"
            placeholder="请输入邮箱"
          >
        </label>

        <label>
          <span>密码</span>
          <input
            v-model.trim="form.password"
            type="password"
            placeholder="请输入密码，6-20 位"
          >
        </label>

        <label>
          <span>确认密码</span>
          <input
            v-model.trim="form.confirmPassword"
            type="password"
            placeholder="请再次输入密码"
          >
        </label>

        <p
          v-if="successMessage"
          class="form-success"
        >
          {{ successMessage }}
        </p>
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
          {{ submitting ? '注册中...' : '立即注册' }}
        </button>
      </form>

      <p class="switch-link">
        已有账号？
        <RouterLink to="/login">
          去登录
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

// 注册表单数据。
const form = reactive({
  username: '',
  email: '',
  password: '',
  confirmPassword: ''
})
const submitting = ref(false)
const errorMessage = ref('')
const successMessage = ref('')

async function handleRegister() {
  errorMessage.value = ''
  successMessage.value = ''

  if (!form.username || !form.email || !form.password || !form.confirmPassword) {
    errorMessage.value = '请完整填写注册信息'
    return
  }

  if (form.password !== form.confirmPassword) {
    errorMessage.value = '两次输入的密码不一致'
    return
  }

  submitting.value = true

  try {
    await authStore.register({
      username: form.username,
      email: form.email,
      password: form.password
    })
    successMessage.value = '注册成功，正在跳转到登录页'
    setTimeout(() => {
      router.push('/login')
    }, 800)
  } catch (error) {
    errorMessage.value = error.response?.data?.detail || '注册失败，请稍后重试'
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
  background: linear-gradient(135deg, #fff7ed 0%, #fdf2f8 100%);
}

.auth-card {
  width: 100%;
  max-width: 460px;
  padding: 36px 32px;
  border-radius: 20px;
  background: #ffffff;
  box-shadow: 0 16px 48px rgba(124, 58, 237, 0.12);

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
      border-color: #f97316;
    }
  }
}

.form-error,
.form-success {
  margin: 0;
  font-size: 14px;
}

.form-error {
  color: #dc2626;
}

.form-success {
  color: #16a34a;
}

.submit-button {
  height: 46px;
  border: none;
  border-radius: 12px;
  background: #f97316;
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
    color: #f97316;
    font-weight: 600;
  }
}
</style>


