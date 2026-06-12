# Webbarber — Agent Guide

## Stack
- **Backend:** Flask 3 + SQLite, port 5001, CORS abierto
- **Frontend:** Astro 6 SSR (`output: 'server'`), Node standalone adapter, Tailwind v4 (vite plugin)
- **No React/Vue/Svelte** — DOM construido con `innerHTML` desde `<script>` vanilla

## Commands

```sh
# backend
cd backend && python app.py

# frontend
cd frontend
pnpm dev          # astro dev
pnpm build        # astro build
pnpm check        # astro check (138 strict TS errors — runtime-safe, no bloquea build)
```

## Quirks

- **`<script>`** sin `lang="ts"` — Astro requiere `<script>` (no `lang="ts"`) para procesar imports. Agregar `lang="ts"` lo trata como `is:inline` y rompe los `import`.
- **Sin TypeScript en scripts inline** — parámetros sin tipo, `catch(e)`, `getElementById()` sin `!`
- **Datos client-side** — SSR solo renderiza el shell HTML. Cada página carga datos vía fetch desde `api.ts` en el `<script>`.
- **API_BASE** centralizada en `frontend/src/lib/api.ts` — CalendarWidget la importa. No duplicar.
- **`[id].astro`** usa `export const prerender = false` para SSR dinámico.
- **DB** se auto-crea y siembra (3 barberos, 5 servicios) en el primer request si está vacía.
- **`PUBLIC_API_URL`** override para API_URL (default `http://localhost:5001/api`).

## Data Flow

```
Page <script> → import { api } from "../../lib/api" → fetch(API_BASE + path) → Flask endpoint → SQLite
CalendarWidget → import { API_BASE } → FullCalendar events feed: `${API_BASE}/turnos/calendario`
```

## API Endpoints (todos bajo `/api/`)

| Resource | Methods |
|----------|---------|
| `/stats` | GET |
| `/clientes`, `/barberos`, `/servicios` | GET, POST, GET/:id, PUT/:id, DELETE/:id |
| `/turnos` | GET (filtros: `?fecha=&barbero_id=&estado=`), POST, GET/:id, PUT/:id, DELETE/:id |
| `/turnos/calendario` | GET (FullCalendar) |
| `/turnos/:id/estado` | PATCH |
