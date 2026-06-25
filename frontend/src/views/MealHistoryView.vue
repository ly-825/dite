<template>
  <main class="meal-page">
    <section class="meal-shell">
      <header class="meal-header">
        <div>
          <span class="meal-header__eyebrow">餐食历史与饮食复盘</span>
          <h1>最近 7 天摄入趋势</h1>
          <p>系统会把餐食记录写入推荐上下文，让下一次食谱避开重复并按近期摄入调整。</p>
        </div>
        <div class="meal-header__actions">
          <button class="ghost-action" type="button" :disabled="mealsStore.loading" @click="refresh">
            {{ mealsStore.loading ? '刷新中' : '刷新' }}
          </button>
          <RouterLink class="ghost-action" to="/">返回聊天</RouterLink>
        </div>
      </header>

      <div v-if="mealsStore.errorMessage" class="notice notice--error">
        {{ mealsStore.errorMessage }}
      </div>

      <section class="metric-grid">
        <article class="metric-card">
          <span>记录餐次</span>
          <strong>{{ mealsStore.review.record_count }}</strong>
          <small>{{ mealsStore.review.days_with_records }} 天有记录</small>
        </article>
        <article class="metric-card">
          <span>日均热量</span>
          <strong>{{ mealsStore.review.average_daily_calories_kcal }}</strong>
          <small>kcal</small>
        </article>
        <article class="metric-card">
          <span>日均蛋白质</span>
          <strong>{{ formatNumber(mealsStore.review.average_daily_protein_g) }}</strong>
          <small>g</small>
        </article>
        <article class="metric-card">
          <span>日均碳水 / 脂肪</span>
          <strong>{{ formatNumber(mealsStore.review.average_daily_carbohydrate_g) }} / {{ formatNumber(mealsStore.review.average_daily_fat_g) }}</strong>
          <small>g</small>
        </article>
      </section>

      <section class="review-grid">
        <article class="review-panel">
          <div class="section-title">
            <span>系统发现</span>
            <strong>{{ mealsStore.review.problems.length || '暂无明显问题' }}</strong>
          </div>
          <ul v-if="mealsStore.review.problems.length" class="text-list">
            <li v-for="problem in mealsStore.review.problems" :key="problem">{{ problem }}</li>
          </ul>
          <p v-else class="empty-state">最近记录整体没有明显异常，继续保持规律记录。</p>
        </article>

        <article class="review-panel">
          <div class="section-title">
            <span>下一步建议</span>
            <strong>{{ mealsStore.review.suggestions.length }}</strong>
          </div>
          <ul class="text-list">
            <li v-for="suggestion in mealsStore.review.suggestions" :key="suggestion">{{ suggestion }}</li>
          </ul>
        </article>

        <article class="review-panel">
          <div class="section-title">
            <span>最近出现食物</span>
            <strong>{{ mealsStore.review.recent_foods.length }}</strong>
          </div>
          <div v-if="mealsStore.review.recent_foods.length" class="tag-cloud">
            <span v-for="food in mealsStore.review.recent_foods" :key="food">{{ food }}</span>
          </div>
          <p v-else class="empty-state">上传餐前餐后图片后，这里会显示近期吃过的食物。</p>
        </article>
      </section>

      <section class="history-grid">
        <article class="summary-panel">
          <div class="section-title">
            <span>每日汇总</span>
            <strong>{{ mealsStore.history.daily_summaries.length }}</strong>
          </div>
          <div v-if="mealsStore.history.daily_summaries.length" class="summary-list">
            <div v-for="day in mealsStore.history.daily_summaries" :key="day.date" class="summary-row">
              <div>
                <strong>{{ day.date }}</strong>
                <span>{{ day.meal_count }} 餐</span>
              </div>
              <p>{{ day.calories_kcal }} kcal · 蛋白质 {{ formatNumber(day.protein_g) }}g · 碳水 {{ formatNumber(day.carbohydrate_g) }}g · 脂肪 {{ formatNumber(day.fat_g) }}g</p>
            </div>
          </div>
          <p v-else class="empty-state">暂无餐食记录。</p>
        </article>

        <article class="records-panel">
          <div class="section-title">
            <span>餐食明细</span>
            <strong>{{ mealsStore.history.records.length }}</strong>
          </div>

          <div v-if="mealsStore.history.records.length" class="record-list">
            <article v-for="record in mealsStore.history.records" :key="record.id" class="record-card">
              <div class="record-card__header">
                <div>
                  <strong>{{ record.meal_type }}</strong>
                  <span>{{ formatDateTime(record.recorded_at) }}</span>
                </div>
                <div class="record-card__meta">
                  <span>{{ record.estimated_calories_kcal || 0 }} kcal</span>
                  <button
                    class="delete-record-button"
                    type="button"
                    :disabled="isDeletingRecord(record.id)"
                    @click="handleDeleteRecord(record)"
                  >
                    {{ isDeletingRecord(record.id) ? '删除中' : '删除' }}
                  </button>
                </div>
              </div>

              <div class="record-card__foods">
                <span v-for="food in resolveFoodNames(record.foods)" :key="food">{{ food }}</span>
              </div>

              <div class="record-card__nutrition">
                <span>蛋白质 {{ formatNumber(record.estimated_protein_g) }}g</span>
                <span>碳水 {{ formatNumber(record.estimated_carbohydrate_g) }}g</span>
                <span>脂肪 {{ formatNumber(record.estimated_fat_g) }}g</span>
              </div>

              <details class="analysis-detail">
                <summary>查看分析</summary>
                <!-- eslint-disable-next-line vue/no-v-html -->
                <div class="markdown-body" v-html="renderMarkdown(record.analysis_markdown)"></div>
              </details>
            </article>
          </div>

          <div v-else class="empty-hero">
            <strong>还没有餐食历史</strong>
            <p>回到聊天页上传餐前和餐后图片，系统会自动生成餐食记录和复盘趋势。</p>
            <RouterLink class="primary-action" to="/">去记录一餐</RouterLink>
          </div>
        </article>
      </section>
    </section>
  </main>
</template>

<script setup>
import { onMounted } from 'vue'

import { useMealsStore } from '../stores/meals'
import { renderMarkdown } from '../utils/markdown'

const mealsStore = useMealsStore()

onMounted(async () => {
  await refresh()
})

async function refresh() {
  await mealsStore.fetchMealDashboard(7)
}

async function handleDeleteRecord(record) {
  const confirmed = window.confirm(`删除这条${record.meal_type || '餐食'}记录？删除后不会再进入复盘统计。`)
  if (!confirmed) {
    return
  }
  await mealsStore.deleteRecord(record.id, 7)
}

function isDeletingRecord(recordId) {
  return mealsStore.deletingRecordIds.includes(recordId)
}

function formatNumber(value) {
  const number = Number(value || 0)
  return Number.isInteger(number) ? String(number) : number.toFixed(1)
}

function formatDateTime(value) {
  if (!value) {
    return ''
  }
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  }).format(new Date(value))
}

function resolveFoodNames(foods) {
  return (foods || [])
    .map((item) => item.name || item.food_name || item.dish_name || item['食物'] || item['菜品'])
    .filter(Boolean)
}
</script>

<style lang="scss" scoped>
.meal-page {
  height: 100dvh;
  padding: 18px;
  overflow-x: hidden;
  overflow-y: auto;
  background: linear-gradient(135deg, #f0fdf4 0%, #f8fafc 52%, #ecfdf5 100%);
  -webkit-overflow-scrolling: touch;
}

.meal-shell {
  display: flex;
  flex-direction: column;
  gap: 16px;
  max-width: 1320px;
  margin: 0 auto;
}

.meal-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 18px;
  padding: 22px;
  border: 1px solid rgba(34, 197, 94, 0.14);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.92);
  box-shadow: 0 20px 52px rgba(21, 128, 61, 0.1);

  h1 {
    margin: 6px 0 8px;
    color: #14532d;
    font-size: 28px;
    line-height: 1.15;
  }

  p {
    max-width: 720px;
    margin: 0;
    color: #64748b;
    font-size: 14px;
    line-height: 1.7;
  }
}

.meal-header__eyebrow {
  color: #15803d;
  font-size: 13px;
  font-weight: 800;
}

.meal-header__actions {
  display: flex;
  gap: 10px;
}

.ghost-action,
.primary-action {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 38px;
  padding: 0 14px;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 700;
  text-decoration: none;
}

.ghost-action {
  border: 1px solid rgba(21, 128, 61, 0.18);
  color: #166534;
  background: #ffffff;
}

.ghost-action:disabled {
  cursor: not-allowed;
  opacity: 0.6;
}

.primary-action {
  color: #ffffff;
  background: #16a34a;
}

.notice {
  padding: 12px 14px;
  border-radius: 8px;
  font-size: 13px;
}

.notice--error {
  color: #991b1b;
  background: #fee2e2;
}

.metric-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.metric-card,
.review-panel,
.summary-panel,
.records-panel {
  border: 1px solid rgba(34, 197, 94, 0.14);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.94);
}

.metric-card {
  padding: 16px;

  span,
  small {
    display: block;
    color: #64748b;
    font-size: 12px;
  }

  strong {
    display: block;
    margin: 8px 0 4px;
    color: #14532d;
    font-size: 28px;
    line-height: 1;
  }
}

.review-grid {
  display: grid;
  grid-template-columns: 1fr 1fr 0.9fr;
  gap: 12px;
}

.review-panel,
.summary-panel,
.records-panel {
  padding: 16px;
}

.section-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;

  span {
    color: #15803d;
    font-size: 12px;
    font-weight: 800;
  }

  strong {
    color: #14532d;
    font-size: 15px;
  }
}

.text-list {
  display: grid;
  gap: 8px;
  margin: 0;
  padding-left: 18px;
  color: #334155;
  font-size: 13px;
  line-height: 1.6;
}

.tag-cloud {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;

  span {
    padding: 6px 9px;
    border-radius: 999px;
    color: #166534;
    font-size: 12px;
    font-weight: 700;
    background: #dcfce7;
  }
}

.history-grid {
  display: grid;
  grid-template-columns: minmax(300px, 0.9fr) minmax(0, 1.5fr);
  gap: 12px;
}

.summary-list,
.record-list {
  display: grid;
  gap: 10px;
}

.summary-row {
  padding: 12px;
  border: 1px solid rgba(34, 197, 94, 0.12);
  border-radius: 8px;
  background: #f8fafc;

  div {
    display: flex;
    justify-content: space-between;
    gap: 12px;
  }

  strong {
    color: #14532d;
    font-size: 13px;
  }

  span,
  p {
    color: #64748b;
    font-size: 12px;
  }

  p {
    margin: 8px 0 0;
    line-height: 1.55;
  }
}

.record-card {
  display: grid;
  gap: 10px;
  padding: 14px;
  border: 1px solid rgba(34, 197, 94, 0.12);
  border-radius: 8px;
  background: #ffffff;
}

.record-card__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;

  strong {
    display: block;
    color: #14532d;
    font-size: 15px;
  }

  span {
    color: #64748b;
    font-size: 12px;
  }
}

.record-card__meta {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
  min-width: 96px;
}

.delete-record-button {
  min-height: 28px;
  padding: 0 9px;
  border: 1px solid rgba(220, 38, 38, 0.18);
  border-radius: 8px;
  color: #b91c1c;
  font-size: 12px;
  font-weight: 700;
  background: #fff7f7;
}

.delete-record-button:disabled {
  cursor: not-allowed;
  opacity: 0.58;
}

.record-card__foods,
.record-card__nutrition {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;

  span {
    padding: 5px 8px;
    border-radius: 8px;
    color: #334155;
    font-size: 12px;
    background: #f1f5f9;
  }
}

.analysis-detail {
  border-top: 1px solid rgba(34, 197, 94, 0.12);
  padding-top: 8px;

  summary {
    cursor: pointer;
    color: #15803d;
    font-size: 13px;
    font-weight: 800;
  }
}

.markdown-body {
  margin-top: 10px;
  color: #334155;
  font-size: 13px;
  line-height: 1.65;
}

.empty-state,
.empty-hero p {
  margin: 0;
  color: #64748b;
  font-size: 13px;
  line-height: 1.6;
}

.empty-hero {
  display: grid;
  justify-items: start;
  gap: 10px;
  padding: 24px;
  border: 1px dashed rgba(34, 197, 94, 0.28);
  border-radius: 8px;
  background: #f8fafc;

  strong {
    color: #14532d;
    font-size: 18px;
  }
}

@media (max-width: 980px) {
  .meal-header,
  .meal-header__actions {
    flex-direction: column;
  }

  .metric-grid,
  .review-grid,
  .history-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 640px) {
  .meal-page {
    padding: 10px;
  }

  .meal-header {
    padding: 16px;

    h1 {
      font-size: 22px;
    }
  }

  .meal-header__actions {
    width: 100%;
  }

  .ghost-action,
  .primary-action {
    width: 100%;
  }
}
</style>
