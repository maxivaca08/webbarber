import { defineConfig } from 'astro/config';
import node from '@astrojs/node';

export default defineConfig({
  output: 'server',
  adapter: node({ mode: 'standalone' }),
  server: { port: 4321 },
  // Detrás del proxy de Railway, Astro ve un host interno distinto al público
  // y su chequeo de origen bloquea los POST de los formularios (login/registro)
  // con "Cross-site POST form submissions are forbidden". Lo desactivamos: el
  // acceso ya está protegido por la sesión del backend Flask.
  security: { checkOrigin: false },
  devToolbar: {
    enabled: false
  }
});
