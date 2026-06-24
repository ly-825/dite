<template>
  <main class="profile-page">
    <section class="profile-shell">
      <header class="profile-header">
        <div>
          <span class="profile-header__eyebrow">我的营养画像</span>
          <h1>偏好、记忆与推荐反馈</h1>
        </div>
        <RouterLink class="profile-header__back" to="/">返回聊天</RouterLink>
      </header>

      <div v-if="profileStore.errorMessage" class="notice notice--error">
        {{ profileStore.errorMessage }}
      </div>

      <div class="profile-grid">
        <form class="profile-editor" @submit.prevent="handleSaveProfile">
          <div class="section-title">
            <span>基础资料</span>
            <strong>{{ profileStore.loading ? '读取中' : profileStatusText }}</strong>
          </div>

          <div class="field-grid">
            <label>
              <span>年龄</span>
              <input v-model.number="form.age" type="number" min="1" max="120" placeholder="例如 32" />
            </label>
            <label>
              <span>性别</span>
              <select v-model="form.gender">
                <option value="">未填写</option>
                <option value="男">男</option>
                <option value="女">女</option>
                <option value="其他">其他</option>
              </select>
            </label>
            <label>
              <span>身高 cm</span>
              <input v-model.number="form.height_cm" type="number" min="50" max="260" step="0.1" placeholder="例如 172" />
            </label>
            <label>
              <span>体重 kg</span>
              <input v-model.number="form.weight_kg" type="number" min="10" max="400" step="0.1" placeholder="例如 68" />
            </label>
          </div>

          <label class="field-block">
            <span>当前目标</span>
            <select v-model="form.goal">
              <option value="">暂不设定</option>
              <option value="减脂">减脂</option>
              <option value="增肌">增肌</option>
              <option value="控糖">控糖</option>
              <option value="均衡饮食">均衡饮食</option>
            </select>
          </label>

          <div class="tag-sections">
            <div
              v-for="item in tagSections"
              :key="item.key"
              class="tag-editor"
            >
              <div class="tag-editor__head">
                <span>{{ item.label }}</span>
                <small>{{ form[item.key].length }}</small>
              </div>
              <div class="tag-editor__chips">
                <button
                  v-for="tag in form[item.key]"
                  :key="tag"
                  type="button"
                  class="chip chip--editable"
                  @click="removeTag(item.key, tag)"
                >
                  {{ tag }} ×
                </button>
                <span v-if="form[item.key].length === 0" class="empty-inline">暂无</span>
              </div>
              <div class="tag-editor__input">
                <input
                  v-model="tagDrafts[item.key]"
                  type="text"
                  :placeholder="item.placeholder"
                  @keydown.enter.prevent="addTag(item.key)"
                />
                <button type="button" @click="addTag(item.key)">添加</button>
              </div>
            </div>
          </div>

          <button class="primary-action" type="submit" :disabled="profileStore.saving">
            {{ profileStore.saving ? '保存中' : '保存画像' }}
          </button>
        </form>

        <aside class="memory-panel">
          <section class="memory-section">
            <div class="section-title">
              <span>待确认记忆</span>
              <strong>{{ profileStore.pendingMemories.length }}</strong>
            </div>
            <div class="memory-list">
              <article
                v-for="memory in profileStore.pendingMemories"
                :key="memory.id"
                class="memory-item"
              >
                <div>
                  <span class="pill">{{ memoryTypeLabel(memory.memory_type) }}</span>
                  <p>{{ memory.content }}</p>
                </div>
                <div class="memory-item__actions">
                  <button type="button" @click="handleConfirmMemory(memory.id)">确认</button>
                  <button type="button" class="ghost-button" @click="handleRejectMemory(memory.id)">忽略</button>
                </div>
              </article>
              <p v-if="profileStore.pendingMemories.length === 0" class="empty-state">聊天中识别到的新偏好会出现在这里。</p>
            </div>
          </section>

          <section class="memory-section">
            <div class="section-title">
              <span>已确认记忆</span>
              <strong>{{ profileStore.confirmedMemories.length }}</strong>
            </div>
            <div class="confirmed-list">
              <span
                v-for="memory in profileStore.confirmedMemories"
                :key="memory.id"
                class="chip"
              >
                {{ memoryTypeLabel(memory.memory_type) }} · {{ memory.content }}
              </span>
              <p v-if="profileStore.confirmedMemories.length === 0" class="empty-state">确认后的记忆会自动参与后续推荐。</p>
            </div>
          </section>
        </aside>
      </div>

      <section class="history-band">
        <div class="section-title">
          <span>近期推荐</span>
          <strong>{{ profileStore.recipePlans.length }}</strong>
        </div>
        <div class="plan-list">
          <article
            v-for="plan in profileStore.recipePlans"
            :key="plan.id"
            class="plan-card"
          >
            <header>
              <div>
                <span class="pill">{{ plan.plan_type === 'week' ? '周计划' : '今日计划' }}</span>
                <h2>{{ formatDate(plan.created_at) }}</h2>
              </div>
              <span>{{ planItems(plan).length }} 道</span>
            </header>

            <div class="dish-list">
              <div
                v-for="dish in planItems(plan)"
                :key="`${plan.id}-${dish.day_label || ''}-${dish.meal_type}-${dish.dish_name}`"
                class="dish-row"
              >
                <div>
                  <strong>{{ dish.dish_name }}</strong>
                  <span>{{ [dish.day_label, dish.meal_type].filter(Boolean).join(' · ') }}</span>
                </div>
                <div class="dish-row__actions">
                  <button type="button" title="喜欢" @click="handleDishFeedback(plan.id, dish.dish_name, 'like')">赞</button>
                  <button type="button" title="不喜欢" @click="handleDishFeedback(plan.id, dish.dish_name, 'dislike')">踩</button>
                  <button type="button" title="买不到" @click="handleDishFeedback(plan.id, dish.dish_name, 'unavailable')">缺</button>
                  <button type="button" title="太复杂" @click="handleDishFeedback(plan.id, dish.dish_name, 'too_complex')">繁</button>
                </div>
              </div>
              <p v-if="planItems(plan).length === 0" class="empty-state">这条推荐暂未解析出菜品明细。</p>
            </div>
          </article>
          <p v-if="profileStore.recipePlans.length === 0" class="empty-state">生成过食谱后，方案会沉淀到这里。</p>
        </div>
      </section>

      <section class="feedback-band">
        <div class="section-title">
          <span>反馈记录</span>
          <strong>{{ profileStore.recipeFeedbacks.length }}</strong>
        </div>
        <div class="feedback-list">
          <span
            v-for="feedback in profileStore.recipeFeedbacks"
            :key="feedback.id"
            class="chip"
          >
            {{ feedback.dish_name }} · {{ feedbackTypeLabel(feedback.feedback_type) }}
          </span>
          <p v-if="profileStore.recipeFeedbacks.length === 0" class="empty-state">你对菜品的反馈会影响下一次推荐。</p>
        </div>
      </section>
    </section>
  </main>
</template>

<script setup>
import { computed, onMounted, reactive, watch } from 'vue'

import { useProfileStore } from '../stores/profile'

const profileStore = useProfileStore()

const tagSections = [
  { key: 'allergies', label: '过敏', placeholder: '花生、虾、乳糖等' },
  { key: 'taboos', label: '忌口', placeholder: '香菜、肥肉、内脏等' },
  { key: 'preferences', label: '偏好', placeholder: '清淡、鸡胸肉、南瓜等' },
  { key: 'health_concerns', label: '健康关注', placeholder: '血糖偏高、尿酸偏高等' }
]

const form = reactive({
  age: null,
  gender: '',
  height_cm: null,
  weight_kg: null,
  goal: '',
  allergies: [],
  taboos: [],
  preferences: [],
  health_concerns: []
})

const tagDrafts = reactive({
  allergies: '',
  taboos: '',
  preferences: '',
  health_concerns: ''
})

const profileStatusText = computed(() => {
  return profileStore.profile.has_medical_report ? '已接入体检报告' : '未上传体检报告'
})

watch(
  () => profileStore.profile,
  (profile) => {
    form.age = profile.age
    form.gender = profile.gender || ''
    form.height_cm = profile.height_cm
    form.weight_kg = profile.weight_kg
    form.goal = profile.goal || ''
    form.allergies = [...(profile.allergies || [])]
    form.taboos = [...(profile.taboos || [])]
    form.preferences = [...(profile.preferences || [])]
    form.health_concerns = [...(profile.health_concerns || [])]
  },
  { immediate: true, deep: true }
)

onMounted(async () => {
  await profileStore.fetchBundle()
})

function normalizeList(values) {
  return [...new Set(values.map((item) => String(item).trim()).filter(Boolean))]
}

function nullableNumber(value) {
  return value === '' || value === undefined || value === null ? null : Number(value)
}

async function handleSaveProfile() {
  await profileStore.saveProfile({
    age: nullableNumber(form.age),
    gender: form.gender || null,
    height_cm: nullableNumber(form.height_cm),
    weight_kg: nullableNumber(form.weight_kg),
    goal: form.goal || '',
    allergies: normalizeList(form.allergies),
    taboos: normalizeList(form.taboos),
    preferences: normalizeList(form.preferences),
    health_concerns: normalizeList(form.health_concerns)
  })
}

function addTag(key) {
  const nextTags = normalizeList([
    ...form[key],
    ...String(tagDrafts[key] || '').split(/[，,]/)
  ])
  form[key] = nextTags
  tagDrafts[key] = ''
}

function removeTag(key, tag) {
  form[key] = form[key].filter((item) => item !== tag)
}

async function handleConfirmMemory(memoryId) {
  await profileStore.confirmMemory(memoryId)
}

async function handleRejectMemory(memoryId) {
  await profileStore.rejectMemory(memoryId)
}

async function handleDishFeedback(recipePlanId, dishName, feedbackType) {
  await profileStore.sendRecipeFeedback({
    recipe_plan_id: recipePlanId,
    dish_name: dishName,
    feedback_type: feedbackType
  })
}

function planItems(plan) {
  const items = plan?.plan_content?.items
  return Array.isArray(items) ? items : []
}

function formatDate(value) {
  if (!value) {
    return '暂无时间'
  }
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  }).format(new Date(value))
}

function memoryTypeLabel(type) {
  const labels = {
    goal: '目标',
    allergy: '过敏',
    taboo: '忌口',
    preference: '偏好',
    health_concern: '健康'
  }
  return labels[type] || type
}

function feedbackTypeLabel(type) {
  const labels = {
    like: '喜欢',
    dislike: '不喜欢',
    unavailable: '买不到',
    too_complex: '太复杂'
  }
  return labels[type] || type
}
</script>

<style lang="scss" scoped>
.profile-page {
  height: 100dvh;
  padding: 18px;
  overflow-y: auto;
  background:
    radial-gradient(circle at top left, rgba(187, 247, 208, 0.35), transparent 28%),
    linear-gradient(135deg, #f7fee7 0%, #f0fdfa 48%, #f8fafc 100%);
}

.profile-shell {
  display: flex;
  flex-direction: column;
  gap: 14px;
  width: min(1440px, 100%);
  min-height: calc(100dvh - 36px);
  margin: 0 auto;
}

.profile-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 18px 20px;
  border: 1px solid rgba(34, 197, 94, 0.12);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.9);
  box-shadow: 0 20px 54px rgba(21, 128, 61, 0.1);

  h1 {
    margin: 4px 0 0;
    color: #14532d;
    font-size: 24px;
  }
}

.profile-header__eyebrow {
  color: #15803d;
  font-size: 12px;
  font-weight: 800;
}

.profile-header__back,
.primary-action,
.memory-item__actions button,
.tag-editor__input button,
.dish-row__actions button {
  border: 0;
  border-radius: 8px;
  color: #ffffff;
  font-weight: 800;
  cursor: pointer;
  background: #15803d;
}

.profile-header__back {
  padding: 10px 14px;
  font-size: 13px;
}

.profile-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.35fr) minmax(340px, 0.8fr);
  gap: 14px;
}

.profile-editor,
.memory-panel,
.history-band,
.feedback-band {
  border: 1px solid rgba(34, 197, 94, 0.12);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.94);
}

.profile-editor {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 18px;
}

.section-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;

  span {
    color: #14532d;
    font-size: 16px;
    font-weight: 900;
  }

  strong {
    color: #15803d;
    font-size: 12px;
  }
}

.field-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}

label {
  display: flex;
  flex-direction: column;
  gap: 6px;
  color: #475569;
  font-size: 12px;
  font-weight: 800;
}

input,
select {
  width: 100%;
  min-height: 38px;
  padding: 8px 10px;
  border: 1px solid rgba(34, 197, 94, 0.16);
  border-radius: 8px;
  color: #14532d;
  background: #ffffff;
  outline: none;
}

input:focus,
select:focus {
  border-color: #22c55e;
  box-shadow: 0 0 0 3px rgba(34, 197, 94, 0.12);
}

.field-block {
  width: min(360px, 100%);
}

.tag-sections {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.tag-editor {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 12px;
  border: 1px solid rgba(34, 197, 94, 0.12);
  border-radius: 8px;
  background: #f8fafc;
}

.tag-editor__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  color: #14532d;
  font-size: 13px;
  font-weight: 900;

  small {
    color: #15803d;
  }
}

.tag-editor__chips,
.confirmed-list,
.feedback-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.tag-editor__input {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 60px;
  gap: 8px;

  button {
    font-size: 12px;
  }
}

.chip,
.pill {
  display: inline-flex;
  align-items: center;
  min-height: 26px;
  padding: 5px 9px;
  border-radius: 999px;
  color: #166534;
  font-size: 12px;
  font-weight: 800;
  background: #dcfce7;
}

.chip--editable {
  border: 0;
  cursor: pointer;
}

.primary-action {
  align-self: flex-start;
  min-width: 120px;
  min-height: 40px;
  padding: 0 16px;
}

.primary-action:disabled {
  cursor: wait;
  opacity: 0.68;
}

.memory-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 16px;
}

.memory-section {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.memory-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.memory-item {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 10px;
  padding: 12px;
  border: 1px solid rgba(34, 197, 94, 0.12);
  border-radius: 8px;
  background: #ffffff;

  p {
    margin: 8px 0 0;
    color: #1f2937;
    font-size: 14px;
    font-weight: 800;
  }
}

.memory-item__actions {
  display: flex;
  gap: 8px;
  align-items: center;

  button {
    min-width: 52px;
    min-height: 32px;
    font-size: 12px;
  }

  .ghost-button {
    color: #15803d;
    background: #dcfce7;
  }
}

.history-band,
.feedback-band {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 16px;
}

.plan-list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.plan-card {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 14px;
  border: 1px solid rgba(34, 197, 94, 0.12);
  border-radius: 8px;
  background: #ffffff;

  header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 12px;
    color: #64748b;
    font-size: 12px;
    font-weight: 800;
  }

  h2 {
    margin: 8px 0 0;
    color: #14532d;
    font-size: 18px;
  }
}

.dish-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.dish-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 10px;
  align-items: center;
  padding: 10px;
  border-radius: 8px;
  background: #f8fafc;

  strong {
    display: block;
    color: #1f2937;
    font-size: 13px;
  }

  span {
    display: block;
    margin-top: 3px;
    color: #64748b;
    font-size: 11px;
  }
}

.dish-row__actions {
  display: grid;
  grid-template-columns: repeat(4, 32px);
  gap: 6px;

  button {
    width: 32px;
    height: 32px;
    padding: 0;
    font-size: 12px;
  }
}

.notice,
.empty-state,
.empty-inline {
  margin: 0;
  color: #64748b;
  font-size: 12px;
  line-height: 1.5;
}

.notice {
  padding: 10px 12px;
  border-radius: 8px;
  background: #fff7ed;
}

.notice--error {
  color: #9a3412;
}

@media (max-width: 1100px) {
  .profile-grid,
  .plan-list {
    grid-template-columns: 1fr;
  }

  .field-grid,
  .tag-sections {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 640px) {
  .profile-page {
    padding: 0;
  }

  .profile-shell {
    min-height: 100dvh;
  }

  .profile-header {
    flex-direction: column;
    align-items: stretch;
    border-radius: 0;

    h1 {
      font-size: 20px;
    }
  }

  .field-grid,
  .tag-sections {
    grid-template-columns: 1fr;
  }

  .profile-editor,
  .memory-panel,
  .history-band,
  .feedback-band {
    border-radius: 0;
  }

  .dish-row {
    grid-template-columns: 1fr;
  }
}
</style>
