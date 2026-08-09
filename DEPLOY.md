# Deploy en Railway (front + back juntos)

Guía paso a paso para publicar BarberApp. Los dos servicios (backend Flask y
frontend Astro) viven en el **mismo proyecto de Railway**, desde el mismo repo.

---

## 0. Antes de empezar

- Subí el proyecto a un repositorio de GitHub.
- Creá una cuenta en [railway.app](https://railway.app) (podés entrar con GitHub).
- Generá una clave secreta para Flask:
  ```bash
  python -c "import secrets; print(secrets.token_hex(32))"
  ```

---

## 1. Backend (Flask)

1. En Railway: **New Project → Deploy from GitHub repo** → elegí el repo.
2. Railway detecta Python y el `Procfile` → arranca con gunicorn automáticamente.
3. Andá a **Settings** del servicio:
   - **Root Directory**: `/` (la raíz, donde está `app.py`).
4. En **Variables**, cargá:

   | Variable | Valor | Nota |
   |----------|-------|------|
   | `SECRET_KEY` | *(la que generaste)* | Obligatoria |
   | `DATA_DIR` | `/data` | Carpeta del volumen persistente |
   | `COOKIE_SECURE` | `1` | Cookie segura bajo HTTPS |
   | `SENA_ALIAS` | *(alias del cliente)* | ⚠️ NO el tuyo |
   | `SENA_MONTO` | `8000` | Monto de la seña |
   | `ADMIN_EMAIL` | *(email del dueño)* | Login admin |
   | `ADMIN_PASSWORD` | *(contraseña fuerte)* | Login admin |
   | `EMAIL_HOST` | `smtp.gmail.com` | Solo si usás avisos por email |
   | `EMAIL_PORT` | `587` | |
   | `EMAIL_USER` | *(tu Gmail)* | |
   | `EMAIL_PASSWORD` | *(contraseña de aplicación de Gmail)* | No la común |
   | `EMAIL_FROM` | *(tu Gmail)* | |
   | `APP_URL` | *(URL pública del frontend)* | La completás en el paso 3 |

5. En **Settings → Volumes → New Volume**:
   - Mount path: **`/data`**  ← ¡crítico! Sin esto, la base y los comprobantes
     se borran en cada deploy.
6. En **Settings → Networking**, generá un dominio público. Guardalo, es la
   `FLASK_URL` que usa el frontend (ej. `https://barberapp-api.up.railway.app`).

---

## 2. Frontend (Astro)

1. En el **mismo proyecto** de Railway: **New → GitHub Repo** → el mismo repo.
2. En **Settings** de este segundo servicio:
   - **Root Directory**: `frontend`
   - **Build Command**: `npm install && npm run build`
   - **Start Command**: `npm run start`
3. En **Variables**:

   | Variable | Valor |
   |----------|-------|
   | `FLASK_URL` | La URL pública del backend (paso 1.6) |
   | `HOST` | `0.0.0.0` |

4. En **Settings → Networking**, generá el dominio público del frontend.
   Esta es la URL que le pasás al cliente.
5. Volvé al backend y poné esa URL en la variable `APP_URL`.

---

## 3. Dominio propio (opcional)

1. Comprá el dominio en Cloudflare o Namecheap.
2. En Railway, en cada servicio → **Settings → Networking → Custom Domain**:
   - Frontend: `tupeluqueria.com`
   - Backend: `api.tupeluqueria.com`
3. Railway te da los registros DNS (CNAME) para pegar en tu proveedor.
4. Actualizá `FLASK_URL` (frontend) y `APP_URL` (backend) con los dominios finales.

---

## 4. Primer ingreso

- Entrá al frontend con el `ADMIN_EMAIL` / `ADMIN_PASSWORD` que definiste.
- Cargá la disponibilidad (horarios) desde el panel de admin.
- Listo para recibir turnos.

---

## Notas

- **Base de datos**: SQLite en el volumen. Perfecto para una peluquería. Si algún
  día atendés muchas en paralelo, se migra a Postgres.
- **Backups**: descargá periódicamente `peluqueria.db` del volumen, o programá un
  backup. Ahí están todos los turnos y clientes.
- **Costo estimado**: ~USD 5/mes de Railway + dominio (~USD 10/año).
