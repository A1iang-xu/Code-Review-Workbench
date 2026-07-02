import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: '127.0.0.1',
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    rollupOptions: {
      output: {
        // 代码分割：将重型依赖拆为独立 chunk，避免首屏加载 Monaco/recharts
        // 使用函数形式避免对象 key 含特殊字符（如 monaco-editor）的类型限制
        manualChunks(id) {
          if (id.includes('node_modules')) {
            if (id.includes('@monaco-editor') || id.includes('monaco-editor')) {
              return 'monaco';
            }
            if (id.includes('recharts') || id.includes('d3-')) {
              return 'charts';
            }
            if (id.includes('react-router') || id.includes('react-dom') || id.includes('/react/')) {
              return 'react-vendor';
            }
            if (id.includes('@tanstack') || id.includes('axios')) {
              return 'query-vendor';
            }
          }
        },
      },
    },
  },
})
