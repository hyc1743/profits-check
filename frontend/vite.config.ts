import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

const allowedHosts = (process.env.PROFITS_CHECK_ALLOWED_HOSTS ?? '')
  .split(',')
  .map((host) => host.trim())
  .filter(Boolean)

export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 8300,
    strictPort: true,
    allowedHosts,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8200',
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
    globals: true,
    css: true,
    coverage: {
      reporter: ['text', 'html'],
    },
  },
})
