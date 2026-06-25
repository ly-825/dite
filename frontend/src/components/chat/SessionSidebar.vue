<template>
  <aside class="session-sidebar">
    <div class="brand-card">
      <div class="brand-icon">AI</div>
      <div>
        <p class="brand-subtitle">健康饮食助手</p>
        <h2>Diet Delushan</h2>
      </div>
    </div>

    <button
      class="new-session-button"
      type="button"
      @click="$emit('create')"
    >
      + 新建对话
    </button>

    <div class="session-header">
      <span>对话历史</span>
      <span>{{ sessions.length }} 条</span>
    </div>

    <div class="session-list">
      <button
        v-for="session in sessions"
        :key="session.id"
        class="session-item"
        :class="{ 'session-item--active': session.id === currentSessionId }"
        type="button"
        @click="$emit('select', session.id)"
      >
        <strong>{{ session.title }}</strong>
        <span class="session-preview">{{ session.last_message_preview || '点击继续完善你的饮食计划' }}</span>
        <span>{{ formatDate(session.updated_at) }}</span>
      </button>

      <div
        v-if="!sessions.length"
        class="session-empty"
      >
        暂无历史对话，点击上方按钮开始第一轮营养咨询。
      </div>
    </div>

    <div class="account-panel">
      <div>
        <span>当前账号</span>
        <strong>{{ userInfo?.username || '已登录用户' }}</strong>
      </div>
      <button type="button" @click="$emit('logout')">退出登录</button>
    </div>
  </aside>
</template>

<script setup>
defineProps({
  sessions: {
    type: Array,
    default: () => []
  },
  currentSessionId: {
    type: String,
    default: ''
  },
  userInfo: {
    type: Object,
    default: null
  }
})

defineEmits(['create', 'select', 'logout'])

// 将时间格式化为更易阅读的中文样式。
function formatDate(value) {
  if (!value) {
    return '--'
  }

  const date = new Date(value)

  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  }).format(date)
}
</script>

<style lang="scss" scoped>
.session-sidebar {
  display: flex;
  flex-direction: column;
  gap: 18px;
  height: 100%;
  min-height: 0;
  padding: 24px 20px;
  border-right: 1px solid rgba(34, 197, 94, 0.12);
  overflow: hidden;
  background: linear-gradient(180deg, #f0fdf4 0%, #ecfdf5 100%);
}

.brand-card {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 18px;
  border-radius: 20px;
  background: rgba(255, 255, 255, 0.82);
  box-shadow: 0 10px 30px rgba(22, 101, 52, 0.08);

  h2 {
    margin: 4px 0 0;
    font-size: 20px;
    color: #14532d;
  }
}

.brand-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 52px;
  height: 52px;
  border-radius: 16px;
  background: linear-gradient(135deg, #22c55e 0%, #16a34a 100%);
  color: #ffffff;
  font-weight: 700;
  font-size: 18px;
}

.brand-subtitle {
  margin: 0;
  font-size: 13px;
  color: #4b5563;
}

.new-session-button {
  height: 46px;
  border: none;
  border-radius: 14px;
  background: #16a34a;
  color: #ffffff;
  font-size: 15px;
  font-weight: 600;
  cursor: pointer;
  transition: transform 0.2s ease, box-shadow 0.2s ease;

  &:hover {
    transform: translateY(-1px);
    box-shadow: 0 12px 24px rgba(22, 163, 74, 0.22);
  }
}

.session-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  color: #4b5563;
  font-size: 14px;
  font-weight: 600;
}

.session-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}

.session-item {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 16px;
  border: 1px solid transparent;
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.78);
  text-align: left;
  cursor: pointer;
  transition: all 0.2s ease;

  strong {
    color: #14532d;
    font-size: 15px;
  }

  span {
    color: #9ca3af;
    font-size: 12px;
  }

  &:hover {
    border-color: rgba(34, 197, 94, 0.25);
    transform: translateY(-1px);
  }

  &--active {
    border-color: rgba(22, 163, 74, 0.35);
    background: #ffffff;
    box-shadow: 0 10px 30px rgba(22, 101, 52, 0.08);
  }
}

.session-preview {
  color: #6b7280 !important;
  line-height: 1.5;
  font-size: 13px !important;
}

.meta-tag {
  display: inline-flex;
  align-items: center;
  padding: 4px 8px;
  border-radius: 999px;
  background: #f3f4f6;
  color: #4b5563 !important;
  font-size: 12px !important;

  &--success {
    background: #dcfce7;
    color: #166534 !important;
  }

  &--warning {
    background: #fef3c7;
    color: #92400e !important;
  }
}

.session-empty {
  padding: 20px 16px;
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.7);
  color: #6b7280;
  line-height: 1.7;
  font-size: 14px;
}

.account-panel {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 12px;
  border: 1px solid rgba(34, 197, 94, 0.14);
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.76);

  div {
    min-width: 0;
  }

  span,
  strong {
    display: block;
  }

  span {
    color: #6b7280;
    font-size: 11px;
  }

  strong {
    margin-top: 3px;
    overflow: hidden;
    color: #14532d;
    font-size: 13px;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  button {
    flex: 0 0 auto;
    height: 30px;
    padding: 0 10px;
    border: 1px solid rgba(220, 38, 38, 0.18);
    border-radius: 8px;
    color: #b91c1c;
    background: #fff7f7;
    font-size: 12px;
    font-weight: 700;
    cursor: pointer;
  }
}

.session-sidebar {
  gap: 12px;
  padding: 18px 16px;
  font-size: 13px;
}

.brand-card {
  gap: 10px;
  padding: 12px;
  border-radius: 14px;

  h2 {
    font-size: 16px;
  }
}

.brand-icon {
  width: 40px;
  height: 40px;
  border-radius: 12px;
  font-size: 14px;
}

.brand-subtitle {
  font-size: 11px;
}

.new-session-button {
  height: 38px;
  border-radius: 10px;
  font-size: 13px;
}

.session-header {
  font-size: 12px;
}

.session-list {
  gap: 8px;
}

.session-item {
  gap: 6px;
  padding: 11px;
  border-radius: 12px;

  strong {
    font-size: 13px;
  }

  span {
    font-size: 11px;
  }
}

.session-preview {
  font-size: 12px !important;
  line-height: 1.4;
}

.meta-tag {
  padding: 3px 6px;
  font-size: 11px !important;
}

.session-empty {
  padding: 14px 12px;
  border-radius: 12px;
  font-size: 12px;
  line-height: 1.55;
}

.session-sidebar {
  gap: 10px;
  padding: 16px 14px;
  font-size: 12px;
}

.brand-card {
  padding: 10px;

  h2 {
    font-size: 14px;
  }
}

.brand-icon {
  width: 34px;
  height: 34px;
  border-radius: 10px;
  font-size: 12px;
}

.brand-subtitle {
  font-size: 10px;
}

.new-session-button {
  height: 34px;
  font-size: 12px;
}

.session-header {
  font-size: 11px;
}

.session-item {
  padding: 9px;

  strong {
    font-size: 12px;
  }

  span {
    font-size: 10px;
  }
}

.session-preview,
.session-empty {
  font-size: 11px !important;
}

.meta-tag {
  font-size: 10px !important;
}

.session-sidebar {
  gap: 8px;
  padding: 10px;
  font-size: 11px;
}

.brand-card {
  gap: 8px;
  padding: 8px;
  border-radius: 10px;

  h2 {
    margin-top: 2px;
    font-size: 12px;
  }
}

.brand-icon {
  width: 28px;
  height: 28px;
  border-radius: 8px;
  font-size: 10px;
}

.brand-subtitle {
  font-size: 9px;
}

.new-session-button {
  height: 30px;
  border-radius: 8px;
  font-size: 11px;
}

.session-header {
  font-size: 10px;
}

.session-list {
  gap: 6px;
}

.session-item {
  gap: 4px;
  padding: 7px;
  border-radius: 9px;

  strong {
    font-size: 11px;
  }

  span {
    font-size: 9px;
  }
}

.session-preview,
.session-empty {
  font-size: 10px !important;
  line-height: 1.35;
}

.meta-tag {
  padding: 2px 5px;
  font-size: 9px !important;
}

.session-empty {
  padding: 10px;
}

@media (max-width: 960px) {
  .session-sidebar {
    border-right: none;
    border-bottom: 1px solid rgba(34, 197, 94, 0.12);
  }
}

@media (max-width: 640px) {
  .session-sidebar {
    height: auto;
    max-height: none;
    gap: 10px;
    padding: 12px;
    overflow: visible;
  }

  .brand-card {
    padding: 10px;
  }

  .brand-icon {
    width: 34px;
    height: 34px;
    border-radius: 10px;
    font-size: 12px;
  }

  .brand-subtitle {
    font-size: 10px;
  }

  .brand-card h2 {
    font-size: 14px;
  }

  .new-session-button {
    height: 38px;
    font-size: 13px;
  }

  .session-list {
    flex-direction: row;
    gap: 8px;
    min-height: 0;
    max-height: none;
    overflow-x: auto;
    overflow-y: hidden;
    padding-bottom: 4px;
  }

  .session-item {
    flex: 0 0 220px;
    gap: 5px;
    padding: 10px;
  }

  .session-preview {
    display: -webkit-box;
    overflow: hidden;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
  }
}
</style>


