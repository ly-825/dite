import { createApp } from 'vue'

import App from './App.vue'
import router from './router'
import pinia from './stores'
import './styles/global.scss'

// 创建并挂载 Vue 应用。
createApp(App).use(pinia).use(router).mount('#app')

