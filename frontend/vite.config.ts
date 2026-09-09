import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    host: '127.0.0.1',
    proxy: {
      // 代理后端API
      '/api': {
        target: 'http://127.0.0.1:8686',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: '../dist', // 构建输出到项目根目录的dist文件夹
    emptyOutDir: true,
    sourcemap: false,
  },
})
