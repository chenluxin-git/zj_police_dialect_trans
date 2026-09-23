import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  build: {
    // 浙警智治上架硬性要求：支持 Chrome 内核浏览器（最低 Chromium 49，实际按 Chrome80 交付）
    // 默认 esbuild target 偏新（es2020+），会让 Chrome80 报语法错误，这里显式降级
    target: 'chrome80',
  },
  server: {
    // 编辑/构建工具写出的临时目录会让 chokidar 抛 EBUSY 并**直接崩掉 dev server**
    // （实测：src 下出现 .Xxx.vue.<pid>.<uuid>.tmpdir 时 vite 进程退出），统一忽略
    watch: {
      ignored: ['**/.*.tmpdir/**', '**/*.tmp', '**/node_modules/**', '**/dist/**'],
    },
    proxy: {
      // 开发期 /api 反代到本地后端（生产由 nginx 反代）
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
