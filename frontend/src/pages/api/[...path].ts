import type { APIRoute } from 'astro';

// Proxy genérico para los fetch() del navegador a rutas relativas /api/*
// (el reset de contraseña, la confirmación por WhatsApp de reservas y de
// reprogramaciones). En dev, `astro dev` corría sobre Vite y un proxy en
// astro.config.mjs resolvía esto; ese proxy NO existe en el build de
// producción (`node ./dist/server/entry.mjs`), así que sin esta ruta esos
// tres flujos devuelven 404 en Railway. Las llamadas SSR (`apiFetch` en el
// frontmatter de las páginas) van directo a FLASK_URL y no pasan por acá.
const FLASK =
  import.meta.env.FLASK_URL ??
  (typeof process !== 'undefined' ? process.env.FLASK_URL : undefined) ??
  'http://localhost:5001';

export const prerender = false;

const handler: APIRoute = async ({ params, request, url }) => {
  const path = params.path ?? '';
  const target = `${FLASK}/api/${path}${url.search}`;

  const headers = new Headers(request.headers);
  headers.delete('host');
  headers.delete('content-length');

  const init: RequestInit & { duplex?: 'half' } = {
    method: request.method,
    headers,
  };
  if (!['GET', 'HEAD'].includes(request.method) && request.body) {
    init.body = request.body;
    init.duplex = 'half';
  }

  const res = await fetch(target, init);

  const resHeaders = new Headers(res.headers);
  resHeaders.delete('content-encoding');
  resHeaders.delete('transfer-encoding');

  return new Response(res.body, { status: res.status, headers: resHeaders });
};

export const ALL = handler;
