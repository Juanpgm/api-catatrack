"""
Script para configurar automáticamente el .env desde el service account JSON
"""
import json
import os
from pathlib import Path

def main():
    print("\n🔧 Configurando variables de entorno desde service account JSON\n")
    print("="*70)
    
    # Leer el archivo JSON
    json_path = Path("env/dagma-85aad-b7afe1c0f77f.json")
    
    if not json_path.exists():
        print(f"❌ Error: No se encontró el archivo {json_path}")
        return
    
    print(f"✅ Leyendo: {json_path}")
    
    with open(json_path, 'r') as f:
        service_account = json.load(f)
    
    # Convertir a una sola línea
    json_oneline = json.dumps(service_account, separators=(',', ':'))
    
    # Información del proyecto
    project_id = service_account['project_id']
    client_email = service_account['client_email']
    
    print(f"✅ Project ID: {project_id}")
    print(f"✅ Client Email: {client_email}")
    
    # Leer .env actual
    env_path = Path(".env")
    if env_path.exists():
        with open(env_path, 'r', encoding='utf-8') as f:
            env_content = f.read()
    else:
        env_content = ""
    
    # Actualizar o agregar FIREBASE_SERVICE_ACCOUNT_JSON
    if 'FIREBASE_SERVICE_ACCOUNT_JSON=' in env_content:
        # Reemplazar la línea existente
        lines = env_content.split('\n')
        new_lines = []
        for line in lines:
            if line.startswith('FIREBASE_SERVICE_ACCOUNT_JSON='):
                new_lines.append(f'FIREBASE_SERVICE_ACCOUNT_JSON={json_oneline}')
                print("✅ Actualizando FIREBASE_SERVICE_ACCOUNT_JSON existente")
            else:
                new_lines.append(line)
        env_content = '\n'.join(new_lines)
    else:
        # Agregar la nueva línea
        if env_content and not env_content.endswith('\n'):
            env_content += '\n'
        env_content += f'\n# Firebase Admin SDK\n'
        env_content += f'FIREBASE_SERVICE_ACCOUNT_JSON={json_oneline}\n'
        print("✅ Agregando FIREBASE_SERVICE_ACCOUNT_JSON")
    
    # Guardar .env
    with open(env_path, 'w', encoding='utf-8') as f:
        f.write(env_content)
    
    print(f"✅ Archivo .env actualizado correctamente")
    
    # Mostrar resumen
    print("\n" + "="*70)
    print("📋 RESUMEN DE CONFIGURACIÓN")
    print("="*70)
    
    print(f"""
BACKEND (Ya configurado en .env):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ FIREBASE_SERVICE_ACCOUNT_JSON configurado
   Project ID: {project_id}
   Client Email: {client_email}

FRONTEND (Para tu proyecto Vite/React):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Estos valores debes agregarlos en el .env del frontend:

VITE_FIREBASE_PROJECT_ID={project_id}
VITE_FIREBASE_AUTH_DOMAIN={project_id}.firebaseapp.com
VITE_FIREBASE_STORAGE_BUCKET={project_id}.appspot.com

Para obtener API_KEY, MESSAGING_SENDER_ID y APP_ID:
👉 Ve a: https://console.firebase.google.com/project/{project_id}/settings/general
👉 Sección "Your apps" > Config de tu app web
""")
    
    print("="*70)
    print("🔍 VERIFICAR CONFIGURACIÓN")
    print("="*70)
    print("\nEjecuta para verificar:")
    print("  python verify_config.py")
    print()

if __name__ == "__main__":
    main()
