import { defineConfig } from 'vite'
import uni from '@dcloudio/vite-plugin-uni'

export default defineConfig({
  plugins: [uni()],
  server: {
    host: '127.0.0.1',
    port: 5178,
    proxy: {
      // 原后端接口通过 /api 前缀转发，避免 H5 端跨域
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        // 后端接口没有 /api 前缀，转发时去掉
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
