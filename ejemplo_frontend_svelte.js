/**
 * Ejemplo de uso del endpoint /registrar-requerimiento desde Svelte
 * 
 * Este archivo muestra cómo implementar el formulario y la lógica
 * para enviar datos al endpoint POST /registrar-requerimiento
 */

// ============ EJEMPLO DE COMPONENTE SVELTE ============

/*
<script>
  import { onMount } from 'svelte';
  
  // Variables del formulario
  let vid = '';
  let centro_gestor_solicitante = '';
  let solicitante_contacto = '';
  let requerimiento = '';
  let observaciones = '';
  let direccion = '';
  let barrio_vereda = '';
  let comuna_corregimiento = '';
  let telefono = '';
  let email_solicitante = '';
  let organismos_seleccionados = [];
  let nota_voz_file = null;
  
  // Coordenadas GPS
  let coords = { lat: null, lng: null };
  
  // Estado del formulario
  let loading = false;
  let error = '';
  let success = false;
  let resultadoRid = '';
  
  // Lista de organismos disponibles
  const organismosDisponibles = [
    'DAGMA',
    'Secretaría de Obras Públicas',
    'Planeación Municipal',
    'Secretaría de Salud',
    'Alcaldía Municipal',
    'EMCALI',
    'Bomberos'
  ];
  
  // Obtener ubicación GPS al cargar el componente
  onMount(() => {
    obtenerUbicacionGPS();
  });
  
  // Función para obtener ubicación GPS
  function obtenerUbicacionGPS() {
    if ('geolocation' in navigator) {
      navigator.geolocation.getCurrentPosition(
        (position) => {
          coords.lat = position.coords.latitude;
          coords.lng = position.coords.longitude;
          console.log('Ubicación obtenida:', coords);
        },
        (error) => {
          console.error('Error obteniendo ubicación:', error);
          alert('No se pudo obtener la ubicación GPS. Por favor, habilita los permisos de ubicación.');
        }
      );
    } else {
      alert('Tu navegador no soporta geolocalización');
    }
  }
  
  // Manejar selección de archivo de audio
  function handleNotaVozChange(event) {
    const file = event.target.files[0];
    if (file) {
      // Validar tipo de archivo
      const validTypes = ['audio/mpeg', 'audio/mp3', 'audio/wav', 'audio/ogg', 'audio/webm', 'audio/m4a'];
      if (!validTypes.includes(file.type)) {
        alert('Por favor, selecciona un archivo de audio válido (MP3, WAV, OGG, WEBM, M4A)');
        event.target.value = '';
        return;
      }
      nota_voz_file = file;
    }
  }
  
  // Función para enviar el formulario
  async function registrarRequerimiento() {
    // Validar campos requeridos
    if (!vid || !centro_gestor_solicitante || !solicitante_contacto || 
        !requerimiento || !observaciones || !direccion || 
        !barrio_vereda || !comuna_corregimiento || !telefono || 
        !email_solicitante || organismos_seleccionados.length === 0) {
      error = 'Por favor, completa todos los campos requeridos';
      return;
    }
    
    // Validar email
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!emailRegex.test(email_solicitante)) {
      error = 'Por favor, ingresa un email válido';
      return;
    }
    
    // Validar que se haya obtenido la ubicación GPS
    if (!coords.lat || !coords.lng) {
      error = 'Esperando ubicación GPS. Por favor, permite el acceso a tu ubicación.';
      obtenerUbicacionGPS(); // Intentar obtener nuevamente
      return;
    }
    
    loading = true;
    error = '';
    success = false;
    
    try {
      // Crear FormData
      const formData = new FormData();
      formData.append('vid', vid);
      formData.append('centro_gestor_solicitante', centro_gestor_solicitante);
      formData.append('solicitante_contacto', solicitante_contacto);
      formData.append('requerimiento', requerimiento);
      formData.append('observaciones', observaciones);
      formData.append('direccion', direccion);
      formData.append('barrio_vereda', barrio_vereda);
      formData.append('comuna_corregimiento', comuna_corregimiento);
      formData.append('coords', JSON.stringify(coords));
      formData.append('telefono', telefono);
      formData.append('email_solicitante', email_solicitante);
      formData.append('organismos_encargados', JSON.stringify(organismos_seleccionados));
      
      // Agregar archivo de audio si existe
      if (nota_voz_file) {
        formData.append('nota_voz', nota_voz_file);
      }
      
      // Enviar petición
      const response = await fetch('http://localhost:8000/registrar-requerimiento', {
        method: 'POST',
        body: formData
      });
      
      const data = await response.json();
      
      if (response.ok) {
        success = true;
        resultadoRid = data.rid;
        console.log('Requerimiento registrado:', data);
        
        // Limpiar formulario
        limpiarFormulario();
        
        alert(`¡Requerimiento registrado exitosamente! RID: ${data.rid}`);
      } else {
        error = data.detail || 'Error al registrar el requerimiento';
      }
    } catch (err) {
      console.error('Error:', err);
      error = 'Error de conexión con el servidor';
    } finally {
      loading = false;
    }
  }
  
  // Función para limpiar el formulario
  function limpiarFormulario() {
    centro_gestor_solicitante = '';
    solicitante_contacto = '';
    requerimiento = '';
    observaciones = '';
    direccion = '';
    barrio_vereda = '';
    comuna_corregimiento = '';
    telefono = '';
    email_solicitante = '';
    organismos_seleccionados = [];
    nota_voz_file = null;
    // Mantener vid y coords
  }
  
  // Manejar selección de organismos
  function toggleOrganismo(organismo) {
    const index = organismos_seleccionados.indexOf(organismo);
    if (index > -1) {
      organismos_seleccionados = organismos_seleccionados.filter(o => o !== organismo);
    } else {
      organismos_seleccionados = [...organismos_seleccionados, organismo];
    }
  }
</script>

<style>
  .form-container {
    max-width: 800px;
    margin: 0 auto;
    padding: 20px;
  }
  
  .form-group {
    margin-bottom: 20px;
  }
  
  label {
    display: block;
    margin-bottom: 5px;
    font-weight: bold;
  }
  
  input, textarea, select {
    width: 100%;
    padding: 10px;
    border: 1px solid #ccc;
    border-radius: 4px;
    font-size: 14px;
  }
  
  textarea {
    min-height: 100px;
    resize: vertical;
  }
  
  .organismos-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
    gap: 10px;
    margin-top: 10px;
  }
  
  .organismo-checkbox {
    display: flex;
    align-items: center;
    gap: 8px;
  }
  
  .organismo-checkbox input[type="checkbox"] {
    width: auto;
  }
  
  .btn {
    padding: 12px 24px;
    border: none;
    border-radius: 4px;
    font-size: 16px;
    cursor: pointer;
    font-weight: bold;
  }
  
  .btn-primary {
    background-color: #007bff;
    color: white;
  }
  
  .btn-primary:hover {
    background-color: #0056b3;
  }
  
  .btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
  
  .error {
    background-color: #f8d7da;
    color: #721c24;
    padding: 12px;
    border-radius: 4px;
    margin-bottom: 20px;
  }
  
  .success {
    background-color: #d4edda;
    color: #155724;
    padding: 12px;
    border-radius: 4px;
    margin-bottom: 20px;
  }
  
  .gps-status {
    background-color: #d1ecf1;
    color: #0c5460;
    padding: 10px;
    border-radius: 4px;
    margin-bottom: 20px;
  }
</style>

<div class="form-container">
  <h1>Registrar Requerimiento</h1>
  
  <!-- Mensajes de error/éxito -->
  {#if error}
    <div class="error">{error}</div>
  {/if}
  
  {#if success}
    <div class="success">
      ¡Requerimiento registrado exitosamente! RID: {resultadoRid}
    </div>
  {/if}
  
  <!-- Estado GPS -->
  <div class="gps-status">
    📍 Ubicación GPS: 
    {#if coords.lat && coords.lng}
      ✅ {coords.lat.toFixed(6)}, {coords.lng.toFixed(6)}
    {:else}
      ⏳ Obteniendo ubicación...
    {/if}
  </div>
  
  <form on:submit|preventDefault={registrarRequerimiento}>
    <!-- VID -->
    <div class="form-group">
      <label for="vid">ID de Visita (VID) *</label>
      <input 
        type="text" 
        id="vid" 
        bind:value={vid} 
        placeholder="Ej: VID-1" 
        required 
      />
    </div>
    
    <!-- Centro Gestor Solicitante -->
    <div class="form-group">
      <label for="centro_gestor">Centro Gestor Solicitante *</label>
      <input 
        type="text" 
        id="centro_gestor" 
        bind:value={centro_gestor_solicitante} 
        placeholder="Ej: DAGMA" 
        required 
      />
    </div>
    
    <!-- Solicitante Contacto -->
    <div class="form-group">
      <label for="solicitante">Nombre del Solicitante *</label>
      <input 
        type="text" 
        id="solicitante" 
        bind:value={solicitante_contacto} 
        placeholder="Ej: María López García" 
        required 
      />
    </div>
    
    <!-- Teléfono -->
    <div class="form-group">
      <label for="telefono">Teléfono *</label>
      <input 
        type="tel" 
        id="telefono" 
        bind:value={telefono} 
        placeholder="Ej: +57 300 1234567" 
        required 
      />
    </div>
    
    <!-- Email -->
    <div class="form-group">
      <label for="email">Email del Solicitante *</label>
      <input 
        type="email" 
        id="email" 
        bind:value={email_solicitante} 
        placeholder="email@example.com" 
        required 
      />
    </div>
    
    <!-- Requerimiento -->
    <div class="form-group">
      <label for="requerimiento">Requerimiento *</label>
      <textarea 
        id="requerimiento" 
        bind:value={requerimiento} 
        placeholder="Describe el requerimiento..." 
        required
      ></textarea>
    </div>
    
    <!-- Observaciones -->
    <div class="form-group">
      <label for="observaciones">Observaciones *</label>
      <textarea 
        id="observaciones" 
        bind:value={observaciones} 
        placeholder="Observaciones adicionales..." 
        required
      ></textarea>
    </div>
    
    <!-- Dirección -->
    <div class="form-group">
      <label for="direccion">Dirección *</label>
      <input 
        type="text" 
        id="direccion" 
        bind:value={direccion} 
        placeholder="Ej: Calle 5 # 40-20" 
        required 
      />
    </div>
    
    <!-- Barrio/Vereda -->
    <div class="form-group">
      <label for="barrio">Barrio/Vereda *</label>
      <input 
        type="text" 
        id="barrio" 
        bind:value={barrio_vereda} 
        placeholder="Ej: San Fernando" 
        required 
      />
    </div>
    
    <!-- Comuna/Corregimiento -->
    <div class="form-group">
      <label for="comuna">Comuna/Corregimiento *</label>
      <input 
        type="text" 
        id="comuna" 
        bind:value={comuna_corregimiento} 
        placeholder="Ej: Comuna 3" 
        required 
      />
    </div>
    
    <!-- Organismos Encargados -->
    <div class="form-group">
      <label>Organismos Encargados * (selecciona al menos uno)</label>
      <div class="organismos-grid">
        {#each organismosDisponibles as organismo}
          <div class="organismo-checkbox">
            <input 
              type="checkbox" 
              id={`org-${organismo}`}
              checked={organismos_seleccionados.includes(organismo)}
              on:change={() => toggleOrganismo(organismo)}
            />
            <label for={`org-${organismo}`}>{organismo}</label>
          </div>
        {/each}
      </div>
      <small>Seleccionados: {organismos_seleccionados.length}</small>
    </div>
    
    <!-- Nota de Voz (opcional) -->
    <div class="form-group">
      <label for="nota_voz">Nota de Voz (opcional)</label>
      <input 
        type="file" 
        id="nota_voz" 
        accept="audio/*" 
        on:change={handleNotaVozChange}
      />
      <small>Formatos permitidos: MP3, WAV, OGG, WEBM, M4A</small>
    </div>
    
    <!-- Botón de envío -->
    <button 
      type="submit" 
      class="btn btn-primary" 
      disabled={loading || !coords.lat || !coords.lng}
    >
      {loading ? 'Registrando...' : 'Registrar Requerimiento'}
    </button>
  </form>
</div>
*/

// ============ EJEMPLO DE FUNCIÓN JAVASCRIPT PURA ============

/**
 * Función para registrar un requerimiento (sin Svelte)
 * @param {Object} datos - Objeto con todos los datos del requerimiento
 * @param {File|null} archivoAudio - Archivo de audio opcional
 * @returns {Promise<Object>} - Respuesta del servidor
 */
async function registrarRequerimientoJS(datos, archivoAudio = null) {
  const API_BASE_URL = 'http://localhost:8000';
  
  // Crear FormData
  const formData = new FormData();
  formData.append('vid', datos.vid);
  formData.append('centro_gestor_solicitante', datos.centro_gestor_solicitante);
  formData.append('solicitante_contacto', datos.solicitante_contacto);
  formData.append('requerimiento', datos.requerimiento);
  formData.append('observaciones', datos.observaciones);
  formData.append('direccion', datos.direccion);
  formData.append('barrio_vereda', datos.barrio_vereda);
  formData.append('comuna_corregimiento', datos.comuna_corregimiento);
  formData.append('coords', JSON.stringify(datos.coords));
  formData.append('telefono', datos.telefono);
  formData.append('email_solicitante', datos.email_solicitante);
  formData.append('organismos_encargados', JSON.stringify(datos.organismos_encargados));
  
  // Agregar archivo de audio si existe
  if (archivoAudio) {
    formData.append('nota_voz', archivoAudio);
  }
  
  try {
    const response = await fetch(`${API_BASE_URL}/registrar-requerimiento`, {
      method: 'POST',
      body: formData
    });
    
    const data = await response.json();
    
    if (!response.ok) {
      throw new Error(data.detail || 'Error al registrar el requerimiento');
    }
    
    return {
      success: true,
      data: data
    };
  } catch (error) {
    console.error('Error:', error);
    return {
      success: false,
      error: error.message
    };
  }
}

/**
 * Función para obtener ubicación GPS
 * @returns {Promise<Object>} - Objeto con lat y lng
 */
function obtenerUbicacionGPSJS() {
  return new Promise((resolve, reject) => {
    if ('geolocation' in navigator) {
      navigator.geolocation.getCurrentPosition(
        (position) => {
          resolve({
            lat: position.coords.latitude,
            lng: position.coords.longitude
          });
        },
        (error) => {
          reject(error);
        }
      );
    } else {
      reject(new Error('Geolocalización no soportada'));
    }
  });
}

// ============ EJEMPLO DE USO ============

/*
// Uso básico (JavaScript puro)
async function ejemplo() {
  try {
    // Obtener ubicación GPS
    const coords = await obtenerUbicacionGPSJS();
    
    // Preparar datos
    const datos = {
      vid: 'VID-1',
      centro_gestor_solicitante: 'DAGMA',
      solicitante_contacto: 'María López',
      requerimiento: 'Solicitud de mejoramiento vial',
      observaciones: 'Urgente',
      direccion: 'Calle 5 # 40-20',
      barrio_vereda: 'San Fernando',
      comuna_corregimiento: 'Comuna 3',
      coords: coords,
      telefono: '+57 300 1234567',
      email_solicitante: 'maria.lopez@example.com',
      organismos_encargados: ['DAGMA', 'Secretaría de Obras']
    };
    
    // Registrar requerimiento
    const resultado = await registrarRequerimientoJS(datos);
    
    if (resultado.success) {
      console.log('Requerimiento registrado:', resultado.data);
      alert(`¡Éxito! RID: ${resultado.data.rid}`);
    } else {
      console.error('Error:', resultado.error);
      alert(`Error: ${resultado.error}`);
    }
  } catch (error) {
    console.error('Error:', error);
  }
}
*/
