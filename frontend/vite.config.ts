import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/auth': 'http://127.0.0.1:8000',
      '/recommend': 'http://127.0.0.1:8000',
      '/wantlist': 'http://127.0.0.1:8000',
    },
  },
})
