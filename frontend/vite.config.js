import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'
import { fileURLToPath } from 'node:url'

export default defineConfig({
  plugins: [react()],
  server: {
    allowedHosts: ['.trycloudflare.com'],
    fs: {
      allow: [fileURLToPath(new URL('.', import.meta.url))],
    },
    proxy: {
      '/auth': 'http://127.0.0.1:8000',
      '/memories': 'http://127.0.0.1:8000',
      '/conversations': 'http://127.0.0.1:8000',
      '/session': 'http://127.0.0.1:8000',
      '/chat': 'http://127.0.0.1:8000',
      '/documents': 'http://127.0.0.1:8000',
      '/retrieval': 'http://127.0.0.1:8000',
      '/task': 'http://127.0.0.1:8000',
      '/history': 'http://127.0.0.1:8000',
    },
  },
})
