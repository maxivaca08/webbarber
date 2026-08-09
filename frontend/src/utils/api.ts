// URL del backend Flask. En local usa el valor por defecto; en producción
// se define con la variable de entorno FLASK_URL (p. ej. en Railway/Vercel).
const FLASK =
  import.meta.env.FLASK_URL ??
  (typeof process !== 'undefined' ? process.env.FLASK_URL : undefined) ??
  'http://localhost:5001';

export async function apiFetch(path: string, request: Request, init: RequestInit = {}) {
  const cookie = request.headers.get('cookie') ?? '';
  const headers: Record<string, string> = {
    cookie,
    ...(init.headers as Record<string, string> ?? {}),
  };
  if (init.body && typeof init.body === 'string') {
    headers['Content-Type'] = 'application/json';
  }
  return fetch(`${FLASK}${path}`, { ...init, headers });
}
