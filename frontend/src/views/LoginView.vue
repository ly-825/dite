<template>
  <div class="auth-page">
    <div class="auth-shell">
      <section class="brand-panel" aria-label="Diet Delushan 项目介绍">
        <div class="brand-mark">
          <span>DD</span>
        </div>
        <div>
          <span class="brand-kicker">AI HEALTH NUTRITION</span>
          <h1>Diet Delushan</h1>
          <p>把体检报告、饮食偏好和真实餐食记录串起来，生成更贴近个人状态的健康饮食建议。</p>
        </div>
        <div class="brand-grid">
          <div>
            <strong>画像</strong>
            <span>忌口偏好长期记忆</span>
          </div>
          <div>
            <strong>餐食</strong>
            <span>拍照记录真实摄入</span>
          </div>
          <div>
            <strong>复盘</strong>
            <span>7 天营养趋势调整</span>
          </div>
        </div>
      </section>

      <section class="auth-card" aria-label="登录 Diet Delushan">
        <div class="auth-heading">
          <span>欢迎回来</span>
          <h2>登录账号</h2>
          <p>继续查看你的营养画像、餐食复盘和个性化推荐。</p>
        </div>

        <form
          class="auth-form"
          @submit.prevent="handleLogin"
        >
          <label>
            <span>账号</span>
            <input
              v-model.trim="form.account"
              type="text"
              placeholder="请输入用户名"
              autocomplete="username"
            >
          </label>

          <label>
            <span>密码</span>
            <input
              v-model.trim="form.password"
              type="password"
              placeholder="请输入密码"
              autocomplete="current-password"
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
            创建账号
          </RouterLink>
        </p>
      </section>
    </div>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { useAuthStore } from '../stores/auth'

const route = useRoute()
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
    await router.push(route.query.redirect || '/')
  } catch (error) {
    errorMessage.value = error.response?.data?.detail || '登录失败，请稍后重试'
  } finally {
    submitting.value = false
  }
}
</script>

<style lang="scss" scoped>
.auth-page {
  --auth-green: #16a34a;
  --auth-green-dark: #14532d;
  --auth-mint: #dcfce7;
  --auth-line: rgba(22, 163, 74, 0.16);
  min-height: 100dvh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  overflow-y: auto;
  background:
    linear-gradient(120deg, rgba(22, 163, 74, 0.12) 0 1px, transparent 1px 100%),
    linear-gradient(145deg, #ecfdf5 0%, #f8fafc 48%, #f0fdf4 100%);
  background-size: 28px 28px, auto;
}

.auth-shell {
  display: grid;
  grid-template-columns: minmax(0, 1.08fr) minmax(360px, 0.72fr);
  width: min(1120px, 100%);
  min-height: min(700px, calc(100dvh - 48px));
  border: 1px solid var(--auth-line);
  border-radius: 8px;
  overflow: hidden;
  background: rgba(255, 255, 255, 0.86);
  box-shadow: 0 28px 80px rgba(21, 128, 61, 0.14);
}

.brand-panel {
  position: relative;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  gap: 44px;
  min-width: 0;
  padding: clamp(28px, 5vw, 56px);
  overflow: hidden;
  color: #ffffff;
  background:
    linear-gradient(150deg, rgba(20, 83, 45, 0.96), rgba(21, 128, 61, 0.92)),
    linear-gradient(90deg, rgba(255, 255, 255, 0.08) 1px, transparent 1px),
    linear-gradient(0deg, rgba(255, 255, 255, 0.08) 1px, transparent 1px);
  background-size: auto, 42px 42px, 42px 42px;

  &::after {
    content: '';
    position: absolute;
    right: -120px;
    bottom: -160px;
    width: 420px;
    height: 420px;
    border: 1px solid rgba(255, 255, 255, 0.18);
    border-radius: 50%;
    box-shadow: inset 0 0 0 40px rgba(255, 255, 255, 0.035);
  }

  h1 {
    position: relative;
    z-index: 1;
    max-width: 640px;
    margin: 12px 0 16px;
    font-size: clamp(42px, 7vw, 82px);
    line-height: 0.94;
    letter-spacing: 0;
  }

  p {
    position: relative;
    z-index: 1;
    max-width: 620px;
    margin: 0;
    color: rgba(255, 255, 255, 0.82);
    font-size: 16px;
    line-height: 1.8;
  }
}

.brand-mark {
  position: relative;
  z-index: 1;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 56px;
  height: 56px;
  border: 1px solid rgba(255, 255, 255, 0.24);
  border-radius: 8px;
  color: #14532d;
  font-weight: 900;
  background: #bbf7d0;
}

.brand-kicker {
  position: relative;
  z-index: 1;
  color: #bbf7d0;
  font-size: 12px;
  font-weight: 900;
}

.brand-grid {
  position: relative;
  z-index: 1;
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;

  div {
    min-width: 0;
    padding: 14px;
    border: 1px solid rgba(255, 255, 255, 0.18);
    border-radius: 8px;
    background: rgba(255, 255, 255, 0.08);
  }

  strong,
  span {
    display: block;
  }

  strong {
    margin-bottom: 8px;
    color: #ffffff;
    font-size: 18px;
  }

  span {
    color: rgba(255, 255, 255, 0.78);
    font-size: 12px;
    line-height: 1.5;
  }
}

.auth-card {
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 24px;
  width: 100%;
  min-width: 0;
  padding: clamp(28px, 4vw, 48px);
  background: rgba(255, 255, 255, 0.96);
}

.auth-heading {
  span {
    color: var(--auth-green);
    font-size: 13px;
    font-weight: 900;
  }

  h2 {
    margin: 8px 0 10px;
    color: var(--auth-green-dark);
    font-size: 34px;
    line-height: 1.15;
  }

  p {
    margin: 0;
    color: #64748b;
    font-size: 14px;
    line-height: 1.7;
  }
}

.auth-form {
  display: flex;
  flex-direction: column;
  gap: 16px;

  label {
    display: flex;
    flex-direction: column;
    gap: 8px;
    color: #14532d;
    font-size: 13px;
    font-weight: 800;
  }

  input {
    height: 48px;
    padding: 0 15px;
    border: 1px solid rgba(21, 128, 61, 0.16);
    border-radius: 8px;
    color: #0f172a;
    font-size: 14px;
    background: #f8fafc;
    transition: border-color 0.2s ease, box-shadow 0.2s ease, background 0.2s ease;

    &::placeholder {
      color: #94a3b8;
    }

    &:focus {
      outline: none;
      border-color: var(--auth-green);
      background: #ffffff;
      box-shadow: 0 0 0 4px rgba(22, 163, 74, 0.12);
    }
  }
}

.form-error {
  margin: 0;
  color: #dc2626;
  font-size: 14px;
}

.submit-button {
  height: 48px;
  border: none;
  border-radius: 8px;
  background: linear-gradient(135deg, #16a34a, #15803d);
  color: #ffffff;
  font-size: 15px;
  font-weight: 900;
  cursor: pointer;
  box-shadow: 0 14px 30px rgba(22, 163, 74, 0.24);
  transition: transform 0.2s ease, box-shadow 0.2s ease, opacity 0.2s ease;

  &:not(:disabled):hover {
    transform: translateY(-1px);
    box-shadow: 0 18px 34px rgba(22, 163, 74, 0.3);
  }

  &:disabled {
    opacity: 0.7;
    cursor: not-allowed;
  }
}

.switch-link {
  margin: 0;
  color: #64748b;
  font-size: 14px;
  text-align: center;

  a {
    color: var(--auth-green-dark);
    font-weight: 900;
  }
}

@media (max-width: 860px) {
  .auth-page {
    align-items: flex-start;
    padding: 14px;
  }

  .auth-shell {
    grid-template-columns: 1fr;
    min-height: auto;
  }

  .brand-panel {
    gap: 24px;
    padding: 26px;

    h1 {
      font-size: clamp(36px, 12vw, 54px);
    }
  }

  .brand-grid {
    grid-template-columns: 1fr;
  }
}
</style>


