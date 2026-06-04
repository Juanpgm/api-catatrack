# 🔐 Guía de Configuración de Variables de Entorno

## 📋 Tabla de Contenidos

1. [Variables del Backend (API)](#variables-del-backend-api)
2. [Variables del Frontend (Vite/React)](#variables-del-frontend-vitereact)
3. [Cómo Obtener las Credenciales](#cómo-obtener-las-credenciales)
4. [Seguridad y Buenas Prácticas](#seguridad-y-buenas-prácticas)

---

## 🔧 Variables del Backend (API)

### 📍 Ubicación

Archivo: `.env` en la raíz del proyecto (este repositorio)

### ⚙️ Variables Requeridas

#### 1. Firebase Admin SDK (Obligatorio)

```bash
FIREBASE_SERVICE_ACCOUNT_JSON={"type":"service_account","project_id":"unidad-cumplimiento-aa245",...}
```

**¿Cómo obtenerla?**

1. Ve a [Firebase Console](https://console.firebase.google.com/)
2. Selecciona tu proyecto: `unidad-cumplimiento-aa245`
3. Ve a **Project Settings** ⚙️ > **Service Accounts**
4. Click en **"Generate New Private Key"**
5. Se descargará un archivo JSON
6. Copia TODO el contenido del archivo en una sola línea
7. Pégalo en tu `.env` como valor de `FIREBASE_SERVICE_ACCOUNT_JSON`

**Ejemplo del JSON (NO USES ESTE, ES DE EJEMPLO):**

```json
{
  "type": "service_account",
  "project_id": "unidad-cumplimiento-aa245",
  "private_key_id": "abc123...",
  "private_key": "-----BEGIN PRIVATE KEY-----\nMIIEvQ...\n-----END PRIVATE KEY-----\n",
  "client_email": "firebase-adminsdk-xxx@unidad-cumplimiento-aa245.iam.gserviceaccount.com",
  "client_id": "123456789",
  "auth_uri": "https://accounts.google.com/o/oauth2/auth",
  "token_uri": "https://oauth2.googleapis.com/token",
  "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
  "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/..."
}
```

#### 2. AWS S3 (Opcional - para fotos)

```bash
AWS_ACCESS_KEY_ID=tu_access_key
AWS_SECRET_ACCESS_KEY=tu_secret_key
AWS_REGION=us-east-1
S3_BUCKET_NAME=360-dagma-photos
```

#### 3. Configuración de la API

```bash
API_ENV=development
API_HOST=0.0.0.0
API_PORT=8000
```

### 📝 Archivo .env Completo del Backend

```bash
# ⚠️ NO SUBIR ESTE ARCHIVO A GITHUB

# Firebase Admin SDK
FIREBASE_SERVICE_ACCOUNT_JSON={"type":"service_account",...TODO_EL_JSON_AQUI...}

# AWS S3 (opcional)
AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE
AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
AWS_REGION=us-east-1
S3_BUCKET_NAME=360-dagma-photos

# API Configuration
API_ENV=development
API_HOST=0.0.0.0
API_PORT=8000

# Railway (producción)
RAILWAY_ENVIRONMENT=production
```

---

## 🌐 Variables del Frontend (Vite/React)

### 📍 Ubicación

**Archivo diferente en tu proyecto frontend:** `.env` en la raíz del proyecto Vite/React

### ⚙️ Variables Requeridas

```bash
# ⚠️ Este archivo va en el proyecto FRONTEND, no en este backend

# URL de la API Backend
VITE_API_URL=https://web-production-2d737.up.railway.app

# Configuración de autenticación
VITE_USE_FIREBASE=false

# Firebase Client Configuration (PÚBLICAS - Seguro compartir)
VITE_FIREBASE_API_KEY=AIzaSyCQRFYX84gaSzWcOIsT6bGvMGNG1P0I0QI
VITE_FIREBASE_AUTH_DOMAIN=unidad-cumplimiento-aa245.firebaseapp.com
VITE_FIREBASE_PROJECT_ID=unidad-cumplimiento-aa245
VITE_FIREBASE_STORAGE_BUCKET=unidad-cumplimiento-aa245.appspot.com
VITE_FIREBASE_MESSAGING_SENDER_ID=574623423766
VITE_FIREBASE_APP_ID=1:574623423766:web:f8e3a47e947fb64b25bfe9
```

### ℹ️ Nota sobre variables VITE

**¿Son seguras estas variables?**
✅ **SÍ** - Estas variables son la configuración PÚBLICA del cliente de Firebase.

- Se envían al navegador del usuario
- Son seguras de compartir públicamente
- Firebase las protege con reglas de seguridad en el backend
- **NO contienen credenciales privadas**

❌ **NO compartas:** El Service Account JSON del backend

---

## 🔑 Cómo Obtener las Credenciales

### Firebase Service Account (Backend)

1. **Ve a Firebase Console**

   ```
   https://console.firebase.google.com/
   ```

2. **Selecciona tu proyecto**
   - Proyecto: `unidad-cumplimiento-aa245`

3. **Navega a Service Accounts**
   - Click en ⚙️ (Settings) > Project Settings
   - Tab "Service Accounts"

4. **Genera una nueva clave**
   - Click "Generate New Private Key"
   - Confirma la descarga
   - Se descargará: `unidad-cumplimiento-aa245-xxxxx.json`

5. **Copia el contenido**

   ```bash
   # Windows PowerShell
   Get-Content unidad-cumplimiento-aa245-xxxxx.json | Set-Clipboard

   # Linux/Mac
   cat unidad-cumplimiento-aa245-xxxxx.json | pbcopy
   ```

6. **Pega en .env**
   ```bash
   FIREBASE_SERVICE_ACCOUNT_JSON={"type":"service_account",...}
   ```

### Firebase Client Config (Frontend)

**Ya las tienes:**

```javascript
const firebaseConfig = {
  apiKey: "AIzaSyCQRFYX84gaSzWcOIsT6bGvMGNG1P0I0QI",
  authDomain: "unidad-cumplimiento-aa245.firebaseapp.com",
  projectId: "unidad-cumplimiento-aa245",
  storageBucket: "unidad-cumplimiento-aa245.appspot.com",
  messagingSenderId: "574623423766",
  appId: "1:574623423766:web:f8e3a47e947fb64b25bfe9",
};
```

Estas se obtienen en Firebase Console > Project Settings > General > Your apps

---

## 🔒 Seguridad y Buenas Prácticas

### ✅ LO QUE DEBES HACER

1. **Crear archivo .env local**

   ```bash
   # Copiar plantilla
   cp .env.example .env

   # Editar con tus credenciales reales
   nano .env
   ```

2. **Verificar .gitignore**

   ```bash
   # Verificar que .env está ignorado
   cat .gitignore | grep .env
   ```

   Debe contener:

   ```
   .env
   .venv
   env/
   venv/
   ```

3. **Nunca commitear credenciales**

   ```bash
   # Verificar que .env no se va a subir
   git status

   # .env NO debe aparecer en la lista
   ```

4. **Variables en producción (Railway)**
   - Ve a tu proyecto en Railway
   - Variables > Add Variable
   - Agrega `FIREBASE_SERVICE_ACCOUNT_JSON` con el JSON completo
   - Agrega las demás variables necesarias

### ❌ LO QUE NO DEBES HACER

1. ❌ **Nunca subir .env a GitHub**
2. ❌ **No hardcodear credenciales en el código**
3. ❌ **No compartir Service Account JSON públicamente**
4. ❌ **No commitear archivos .json de Firebase**

### 🔍 Verificar que no has expuesto credenciales

```bash
# Verificar historial de git
git log --all --full-history -- .env

# Si aparece .env en el historial, debes:
# 1. Regenerar credenciales en Firebase
# 2. Hacer history rewrite de git (avanzado)
```

---

## 📂 Estructura de Archivos

```
📁 api-artefacto-360-dagma/ (Backend)
├── .env                      ← TUS CREDENCIALES (NO SUBIR)
├── .env.example              ← Plantilla (SÍ SUBIR)
├── .gitignore                ← Debe incluir .env
├── app/
│   ├── firebase_config.py    ← Lee FIREBASE_SERVICE_ACCOUNT_JSON
│   └── routes/
└── requirements.txt

📁 frontend-dagma/ (Frontend - otro repo)
├── .env                      ← Variables VITE (NO SUBIR)
├── .env.example              ← Plantilla (SÍ SUBIR)
├── src/
│   ├── firebase.js           ← Usa variables VITE_FIREBASE_*
│   └── config/
└── package.json
```

---

## 🚀 Pasos Rápidos de Configuración

### Backend (Este Repositorio)

```bash
# 1. Crear archivo .env desde plantilla
cp .env.example .env

# 2. Obtener Service Account JSON de Firebase
# Ir a: https://console.firebase.google.com/ > Service Accounts

# 3. Editar .env y pegar el JSON completo
nano .env
# FIREBASE_SERVICE_ACCOUNT_JSON={"type":"service_account",...}

# 4. Instalar dependencias
pip install -r requirements.txt

# 5. Ejecutar API
python run.py

# 6. Verificar
curl http://localhost:8000/health
```

### Frontend (Proyecto Separado)

```bash
# 1. Crear .env en el proyecto frontend
cd ../frontend-dagma
nano .env

# 2. Agregar variables
VITE_API_URL=http://localhost:8000
VITE_FIREBASE_API_KEY=AIzaSyCQRFYX84gaSzWcOIsT6bGvMGNG1P0I0QI
VITE_FIREBASE_AUTH_DOMAIN=unidad-cumplimiento-aa245.firebaseapp.com
VITE_FIREBASE_PROJECT_ID=unidad-cumplimiento-aa245
VITE_FIREBASE_STORAGE_BUCKET=unidad-cumplimiento-aa245.appspot.com
VITE_FIREBASE_MESSAGING_SENDER_ID=574623423766
VITE_FIREBASE_APP_ID=1:574623423766:web:f8e3a47e947fb64b25bfe9

# 3. Ejecutar frontend
npm run dev
```

---

## ❓ Preguntas Frecuentes

### ¿Puedo compartir las variables VITE*FIREBASE*\*?

✅ **SÍ** - Son configuraciones públicas del cliente. Firebase las protege con reglas de seguridad.

### ¿Puedo compartir FIREBASE_SERVICE_ACCOUNT_JSON?

❌ **NO** - Esta es la credencial privada del backend. Da acceso completo a Firebase.

### ¿Qué hago si subí .env por error?

1. Regenera las credenciales en Firebase
2. Actualiza tu .env local
3. Borra el archivo del historial de git (busca "git filter-branch")
4. Actualiza credenciales en Railway

### ¿Dónde pongo las variables en Railway?

1. Ve a tu proyecto en Railway
2. Click en tu servicio
3. Tab "Variables"
4. Add variable: `FIREBASE_SERVICE_ACCOUNT_JSON`
5. Pega el JSON completo

---

## 📞 Soporte

Si tienes problemas con la configuración:

1. Verifica que .env existe: `Test-Path .env` (PowerShell)
2. Verifica que el formato JSON es válido
3. Revisa los logs: `tail -f audit.log`
4. Verifica Firebase Console para credenciales válidas

---

**Última actualización:** 2026-02-04  
**Proyecto:** API Artefacto 360 DAGMA


## Web Push (VAPID) � iOS 16.4+ PWA notifications

Required for the /push/* endpoints. Generate one key pair per environment:

`ash
python -c "from py_vapid import Vapid01; v=Vapid01(); v.generate_keys(); v.save_key('priv.pem'); print('PUB', v.public_key_as_base64()); print('PRIV', v.private_key_as_base64())"
`

| Variable           | Required | Description                                              |
|--------------------|----------|----------------------------------------------------------|
| VAPID_PUBLIC_KEY   | yes      | Base64url ECDSA P-256 public key                         |
| VAPID_PRIVATE_KEY  | yes      | Base64url ECDSA P-256 private key                        |
| VAPID_SUBJECT      | yes      | mailto:contact@... or https://app-url                    |

Keep VAPID_PRIVATE_KEY in your secret manager (Railway secret, not in repo).
