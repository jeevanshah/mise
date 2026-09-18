import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { VitePWA } from 'vite-plugin-pwa'

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['favicon.svg'],
      manifest: {
        name: 'Mise — Head Chef OS',
        short_name: 'Mise',
        description: 'A Head Chef Operating System: prep, roster, orders, and handover in one place.',
        theme_color: '#111827',
        background_color: '#111827',
        display: 'standalone',
        orientation: 'portrait',
        icons: [
          { src: 'pwa-192.png', sizes: '192x192', type: 'image/png' },
          { src: 'pwa-512.png', sizes: '512x512', type: 'image/png' },
          { src: 'pwa-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
        ],
      },
      workbox: {
        // Never cache API calls — this is a live kitchen ops tool; a stale
        // cached GET of "today's prep list" is actively dangerous. Only the
        // app shell (HTML/JS/CSS) is precached for install/offline-launch.
        navigateFallbackDenylist: [/^\/api\//],
      },
    }),
  ],
  server: {
    host: true,
    port: 5173,
  },
})
