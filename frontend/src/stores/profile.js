import { defineStore } from 'pinia'

import {
  confirmMemory,
  createRecipeFeedback,
  getProfileBundle,
  rejectMemory,
  updateProfile
} from '../api/profile'

const emptyBundle = () => ({
  profile: {
    age: null,
    gender: '',
    height_cm: null,
    weight_kg: null,
    goal: '',
    allergies: [],
    taboos: [],
    preferences: [],
    health_concerns: [],
    has_medical_report: false,
    medical_report_text: ''
  },
  pending_memories: [],
  confirmed_memories: [],
  recipe_plans: [],
  recipe_feedbacks: []
})

function resolveErrorMessage(error, fallback) {
  return error?.response?.data?.detail || error?.message || fallback
}

export const useProfileStore = defineStore('profile', {
  state: () => ({
    bundle: emptyBundle(),
    loading: false,
    saving: false,
    errorMessage: ''
  }),
  getters: {
    profile: (state) => state.bundle.profile,
    pendingMemories: (state) => state.bundle.pending_memories,
    confirmedMemories: (state) => state.bundle.confirmed_memories,
    recipePlans: (state) => state.bundle.recipe_plans,
    recipeFeedbacks: (state) => state.bundle.recipe_feedbacks
  },
  actions: {
    applyBundle(bundle) {
      this.bundle = {
        ...emptyBundle(),
        ...bundle,
        profile: {
          ...emptyBundle().profile,
          ...(bundle?.profile || {})
        }
      }
    },
    async fetchBundle() {
      this.loading = true
      this.errorMessage = ''

      try {
        const response = await getProfileBundle()
        this.applyBundle(response.data)
        return this.bundle
      } catch (error) {
        this.errorMessage = resolveErrorMessage(error, '加载营养画像失败')
        throw error
      } finally {
        this.loading = false
      }
    },
    async saveProfile(profile) {
      this.saving = true
      this.errorMessage = ''

      try {
        const response = await updateProfile(profile)
        this.applyBundle(response.data)
        return this.bundle
      } catch (error) {
        this.errorMessage = resolveErrorMessage(error, '保存营养画像失败')
        throw error
      } finally {
        this.saving = false
      }
    },
    async confirmMemory(memoryId) {
      const response = await confirmMemory(memoryId)
      this.applyBundle(response.data)
      return this.bundle
    },
    async rejectMemory(memoryId) {
      const response = await rejectMemory(memoryId)
      this.applyBundle(response.data)
      return this.bundle
    },
    async sendRecipeFeedback(payload) {
      const response = await createRecipeFeedback(payload)
      this.bundle.recipe_feedbacks = [response.data, ...this.bundle.recipe_feedbacks]
      return response.data
    }
  }
})
