export const API_BASE = import.meta.env.PUBLIC_API_URL || 'http://localhost:5001/api'

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options?.headers },
    ...options,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: res.statusText }))
    throw new Error(err.error || `HTTP ${res.status}`)
  }
  return res.json()
}

export interface Cliente {
  id: number; nombre: string; apellido: string; telefono: string; email: string; creado_en: string
}

export interface Barbero {
  id: number; nombre: string; apellido: string; especialidad: string; activo: number
}

export interface Servicio {
  id: number; nombre: string; descripcion: string; duracion_minutos: number; precio: number
}

export interface Turno {
  id: number; cliente_id: number; barbero_id: number; servicio_id: number
  fecha_hora: string; estado: string; notas: string; creado_en: string
  cliente: string; barbero: string; servicio: string; precio: number; duracion_minutos: number
}

export interface TurnoCreate {
  cliente_id: number; barbero_id: number; servicio_id: number
  fecha_hora: string; notas?: string
}

export interface CalendarEvent {
  id: number; title: string; start: string; end: string
  backgroundColor: string; borderColor: string
}

export interface Stats {
  stats: { total_clientes: number; total_barberos: number; turnos_hoy: number; turnos_pendientes: number }
  turnos_hoy: Turno[]
}

export const api = {
  stats: { get: () => request<Stats>('/stats') },
  clientes: {
    list: () => request<Cliente[]>('/clientes'),
    get: (id: number) => request<Cliente>(`/clientes/${id}`),
    create: (data: Partial<Cliente>) => request<Cliente>('/clientes', { method: 'POST', body: JSON.stringify(data) }),
    update: (id: number, data: Partial<Cliente>) => request<Cliente>(`/clientes/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
    delete: (id: number) => request<{ mensaje: string }>(`/clientes/${id}`, { method: 'DELETE' }),
  },
  barberos: {
    list: () => request<Barbero[]>('/barberos'),
    get: (id: number) => request<Barbero>(`/barberos/${id}`),
    create: (data: Partial<Barbero>) => request<Barbero>('/barberos', { method: 'POST', body: JSON.stringify(data) }),
    update: (id: number, data: Partial<Barbero>) => request<Barbero>(`/barberos/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
    delete: (id: number) => request<{ mensaje: string }>(`/barberos/${id}`, { method: 'DELETE' }),
  },
  servicios: {
    list: () => request<Servicio[]>('/servicios'),
    get: (id: number) => request<Servicio>(`/servicios/${id}`),
    create: (data: Partial<Servicio>) => request<Servicio>('/servicios', { method: 'POST', body: JSON.stringify(data) }),
    update: (id: number, data: Partial<Servicio>) => request<Servicio>(`/servicios/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
    delete: (id: number) => request<{ mensaje: string }>(`/servicios/${id}`, { method: 'DELETE' }),
  },
  turnos: {
    list: (params?: string) => request<Turno[]>(`/turnos${params || ''}`),
    calendario: () => request<CalendarEvent[]>('/turnos/calendario'),
    get: (id: number) => request<Turno>(`/turnos/${id}`),
    create: (data: TurnoCreate) => request<Turno>('/turnos', { method: 'POST', body: JSON.stringify(data) }),
    update: (id: number, data: Partial<Turno>) => request<Turno>(`/turnos/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
    cambiarEstado: (id: number, estado: string) => request<Turno>(`/turnos/${id}/estado`, { method: 'PATCH', body: JSON.stringify({ estado }) }),
    delete: (id: number) => request<{ mensaje: string }>(`/turnos/${id}`, { method: 'DELETE' }),
  },
}
