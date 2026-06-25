<template>
  <div class="home-page">
    <div class="home-layout">
      <SessionSidebar
        :sessions="chatStore.sessions"
        :current-session-id="chatStore.currentSessionId"
        @create="handleCreateSession"
        @select="handleSelectSession"
      />

      <ChatPanel
        :messages="chatStore.currentMessages"
        :current-session-title="chatStore.currentSession?.title || '新的饮食计划'"
        :workflow-state="chatStore.currentWorkflowState"
        :initializing="chatStore.initializing"
        :sending="chatStore.sending"
        :error-message="chatStore.errorMessage"
        @send="handleSendMessage"
      />

      <aside class="feature-panel">
        <div class="feature-panel__header">
          <span>功能导航</span>
          <h2>项目能力</h2>
          <p>选择一个常用场景，系统会自动进入对应服务。</p>
        </div>

        <div class="feature-list">
          <RouterLink
            v-for="feature in linkedFeatures"
            :key="feature.title"
            class="feature-card feature-card--link"
            :to="feature.path"
          >
            <div>
              <span class="feature-card__tag">{{ feature.agent }}</span>
              <h3>{{ feature.title }}</h3>
              <p>{{ feature.description }}</p>
            </div>
          </RouterLink>

          <article
            v-for="feature in features"
            :key="feature.title"
            class="feature-card"
          >
            <div>
              <span class="feature-card__tag">{{ feature.agent }}</span>
              <h3>{{ feature.title }}</h3>
              <p>{{ feature.description }}</p>
            </div>
          </article>
        </div>
      </aside>
    </div>
  </div>
</template>

<script setup>
import { onMounted } from 'vue'

import ChatPanel from '../components/chat/ChatPanel.vue'
import SessionSidebar from '../components/chat/SessionSidebar.vue'
import { useChatStore } from '../stores/chat'

const chatStore = useChatStore()
const linkedFeatures = [
  {
    title: '我的营养画像',
    agent: 'C 端升级',
    description: '维护目标、忌口、偏好和待确认记忆，让后续推荐更贴合。',
    path: '/profile'
  },
  {
    title: '餐食历史与复盘',
    agent: 'C 端升级',
    description: '查看最近 7 天餐食、营养趋势和下一餐调整建议。',
    path: '/meals'
  }
]

const features = [
  {
    title: '个性化菜谱生成',
    agent: '食谱规划服务',
    description: '按目标、忌口、地区和健康状态生成每日或每周食谱。'
  },
  {
    title: '餐食图片记录',
    agent: '餐食记录服务',
    description: '上传餐前餐后图片，记录摄入情况并分析饮食结构。'
  },
  {
    title: '饮食历史分析',
    agent: '历史分析服务',
    description: '也可以直接在聊天里询问最近饮食表现，系统会基于已保存记录回答。'
  }
]

// 页面进入时初始化聊天会话。
onMounted(async () => {
  await chatStore.initialize()
})

async function handleCreateSession() {
  await chatStore.createSession()
}

async function handleSelectSession(sessionId) {
  if (sessionId === chatStore.currentSessionId) {
    return
  }

  await chatStore.selectSession(sessionId)
}

async function handleSendMessage(content) {
  try {
    await chatStore.sendMessage(content)
  } catch (error) {
    console.error(error)
  }
}

</script>

<style lang="scss" scoped>
.home-page {
  height: 100dvh;
  padding: 16px;
  overflow: hidden;
  background:
    radial-gradient(circle at top left, rgba(134, 239, 172, 0.3), transparent 30%),
    linear-gradient(135deg, #f0fdf4 0%, #ecfdf5 40%, #f8fafc 100%);
}

.home-layout {
  display: grid;
  grid-template-columns: 300px minmax(0, 7fr) minmax(280px, 3fr);
  max-width: 1520px;
  height: calc(100dvh - 32px);
  margin: 0 auto;
  border: 1px solid rgba(34, 197, 94, 0.12);
  border-radius: 24px;
  overflow: hidden;
  background: rgba(255, 255, 255, 0.88);
  box-shadow: 0 24px 64px rgba(21, 128, 61, 0.12);
}

.feature-panel {
  display: flex;
  flex-direction: column;
  gap: 14px;
  min-width: 0;
  padding: 18px;
  overflow-y: auto;
  border-left: 1px solid rgba(34, 197, 94, 0.12);
  background: linear-gradient(180deg, rgba(240, 253, 244, 0.92), rgba(255, 255, 255, 0.96));
}

.feature-panel__header {
  span {
    color: #15803d;
    font-size: 12px;
    font-weight: 700;
  }

  h2 {
    margin: 6px 0 8px;
    color: #14532d;
    font-size: 20px;
  }

  p {
    margin: 0;
    color: #64748b;
    font-size: 12px;
    line-height: 1.55;
  }
}

.feature-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.feature-card {
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  gap: 8px;
  padding: 12px;
  border: 1px solid rgba(34, 197, 94, 0.14);
  border-radius: 8px;
  background: #ffffff;

  h3 {
    margin: 6px 0;
    color: #14532d;
    font-size: 13px;
  }

  p {
    margin: 0;
    color: #64748b;
    font-size: 11px;
    line-height: 1.45;
  }

}

.feature-card--link {
  color: inherit;
  text-decoration: none;
  cursor: pointer;
  transition: border-color 0.18s ease, box-shadow 0.18s ease, transform 0.18s ease;
}

.feature-card--link:hover {
  border-color: rgba(21, 128, 61, 0.32);
  box-shadow: 0 12px 28px rgba(21, 128, 61, 0.12);
  transform: translateY(-1px);
}

.feature-card__tag {
  display: inline-flex;
  color: #15803d;
  font-size: 10px;
  font-weight: 700;
}

.home-page {
  font-size: 12px;
}

.feature-panel {
  gap: 12px;
  padding: 16px;
}

.feature-panel__header {
  span {
    font-size: 11px;
  }

  h2 {
    font-size: 18px;
  }

  p {
    font-size: 11px;
  }
}

.feature-card {
  padding: 10px;

  h3 {
    font-size: 13px;
  }

  p {
    font-size: 11px;
  }
}

.home-page {
  padding: 10px;
  font-size: 11px;
}

.home-layout {
  grid-template-columns: 240px minmax(0, 1fr) 230px;
  height: calc(100dvh - 20px);
  max-width: 1680px;
  border-radius: 18px;
}

.feature-panel {
  gap: 8px;
  padding: 10px;
}

.feature-panel__header {
  h2 {
    margin: 4px 0 6px;
    font-size: 15px;
  }

  span,
  p {
    font-size: 10px;
    line-height: 1.4;
  }
}

.feature-list {
  gap: 7px;
}

.feature-card {
  gap: 5px;
  padding: 8px;

  h3 {
    margin: 4px 0;
    font-size: 11px;
  }

  p {
    font-size: 10px;
    line-height: 1.35;
  }
}

.feature-card__tag {
  font-size: 9px;
}

@media (max-width: 960px) {
  .home-page {
    padding: 12px;
    overflow-y: auto;
  }

  .home-layout {
    display: flex;
    flex-direction: column;
    min-height: calc(100dvh - 24px);
    height: auto;
    overflow-y: auto;
  }

  :deep(.chat-panel) {
    order: 1;
    min-height: 72dvh;
  }

  :deep(.session-sidebar) {
    order: 2;
  }

  .feature-panel {
    order: 3;
    border-left: none;
    border-top: 1px solid rgba(34, 197, 94, 0.12);
  }
}

@media (max-width: 640px) {
  .home-page {
    height: 100dvh;
    min-height: 100dvh;
    padding: 0;
    overflow: hidden;
    background: #f7fef9;
  }

  .home-layout {
    height: 100dvh;
    min-height: 100dvh;
    overflow: hidden;
    border: none;
    border-radius: 0;
    box-shadow: none;
  }

  :deep(.chat-panel) {
    height: 100dvh;
    min-height: 100dvh;
  }

  :deep(.session-sidebar) {
    display: none;
  }

  .feature-panel {
    display: none;
  }
}
</style>


