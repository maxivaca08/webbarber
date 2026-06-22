import { defineConfig } from 'astro/config';
import node from '@astrojs/node';

export default defineConfig({
  output: 'server',
  adapter: node({ mode: 'standalone' }),
  server: { port: 4321 },
  vite: {
    server: {
      proxy: {
        '/api': { target: 'http://localhost:5001', changeOrigin: true }
      }
    }
  },
  devToolbar: {
    enabled: false
  }
});
