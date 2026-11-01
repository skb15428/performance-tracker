import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'
import { VitePWA } from 'vite-plugin-pwa'

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    VitePWA({
      strategies: 'injectManifest',
      srcDir: 'src',
      filename: 'sw.ts',
      registerType: 'autoUpdate',
      injectRegister: false,
      // Only the app itself is kept offline: the diagram library loads when a note needs it
      injectManifest: { globPatterns: ['**/*.{html,css,svg}', 'assets/index-*.js'] },
      devOptions: { enabled: true, type: 'module' },
      manifest: {
        name: 'GoalCoach',
        short_name: 'GoalCoach',
        description: 'Log your day, see which goals you moved, and get a plan for tomorrow.',
        theme_color: '#4f46e5',
        background_color: '#0b0b12',
        display: 'standalone',
        start_url: '/',
        icons: [
          { src: '/icon-192.png', sizes: '192x192', type: 'image/png' },
          { src: '/icon-512.png', sizes: '512x512', type: 'image/png' },
          { src: '/icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
        ],
      },
    }),
  ],
})
