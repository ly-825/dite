import { defineStore } from 'pinia'

import { getMealRecords, getMealReview } from '../api/meals'

const emptyHistory = () => ({
  days: 7,
  records: [],
  daily_summaries: [],
  totals: {
    calories_kcal: 0,
    protein_g: 0,
    carbohydrate_g: 0,
    fat_g: 0
  },
  recent_foods: []
})

const emptyReview = () => ({
  days: 7,
  record_count: 0,
  days_with_records: 0,
  totals: {
    calories_kcal: 0,
    protein_g: 0,
    carbohydrate_g: 0,
    fat_g: 0
  },
  average_daily_calories_kcal: 0,
  average_daily_protein_g: 0,
  average_daily_carbohydrate_g: 0,
  average_daily_fat_g: 0,
  recent_foods: [],
  problems: [],
  suggestions: []
})

function resolveErrorMessage(error, fallback) {
  return error?.response?.data?.detail || error?.message || fallback
}

export const useMealsStore = defineStore('meals', {
  state: () => ({
    history: emptyHistory(),
    review: emptyReview(),
    loading: false,
    errorMessage: ''
  }),
  actions: {
    async fetchMealDashboard(days = 7) {
      this.loading = true
      this.errorMessage = ''

      try {
        const [historyResponse, reviewResponse] = await Promise.all([
          getMealRecords({ days }),
          getMealReview({ days })
        ])
        this.history = {
          ...emptyHistory(),
          ...historyResponse.data
        }
        this.review = {
          ...emptyReview(),
          ...reviewResponse.data
        }
        return {
          history: this.history,
          review: this.review
        }
      } catch (error) {
        this.errorMessage = resolveErrorMessage(error, '加载餐食历史失败')
        throw error
      } finally {
        this.loading = false
      }
    }
  }
})
