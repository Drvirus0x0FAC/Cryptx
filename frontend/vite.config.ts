import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  build: {
    // Vendor code-splitting: pages are already lazy-loaded (route-level chunks);
    // this splits the heavyweight libraries out of the entry bundle so the
    // first paint ships only React + the shell.
    rollupOptions: {
      output: {
        manualChunks: {
          'vendor-react': ['react', 'react-dom', 'react-router-dom'],
          'vendor-charts': ['recharts'],
          'vendor-icons': ['lucide-react'],
          'vendor-data': ['axios', '@tanstack/react-query', 'd3-force'],
        },
      },
    },
    chunkSizeWarningLimit: 900,
  },
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/health': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        proxyTimeout: 30_000,
        timeout: 30_000,
      },
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        proxyTimeout: 360_000,   // 6 min — covers nexus analyze + AI
        timeout: 360_000,
      },
    },
  },
})
