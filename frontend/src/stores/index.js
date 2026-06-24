import { createPinia } from 'pinia'

// 单独导出 pinia，便于在路由守卫里复用。
const pinia = createPinia()

export default pinia

