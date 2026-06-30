# Conexión y Lectura de Cámaras

## Resumen General

El sistema captura frames de 7 cámaras USB conectadas y las sirve en tiempo real a través de un servidor Flask. Cada cámara corre en su propio thread para permitir captura simultánea sin bloqueos.

## Conexión Física

- **7 cámaras USB** conectadas a través de AnywhereUSB o directamente al puerto USB
- Las cámaras se detectan automáticamente en Windows con índices secuenciales

## Detección de Cámaras

### Índices de Dispositivo

En `camera_manager.py`:
```python
CAMERA_INDICES = [0, 1, 2, 3, 4, 5, 6]
NUM_CAMERAS = len(CAMERA_INDICES)
```

- Cada cámara USB recibe un índice de dispositivo (0-6)
- Estos índices se detectan en Windows usando `cv2.VideoCapture(index, cv2.CAP_DSHOW)`
- El script `find_cameras.py` escanea automáticamente qué índices están disponibles

### Cómo encontrar nuevos índices

Si agregas cámaras, ejecuta:
```bash
python find_cameras.py
```

Esto escanea índices del 0-29 y reporta cuáles cámaras responden. Actualiza `CAMERA_INDICES` con los resultados.

## Lectura de Frames

### Arquitectura

```
┌─────────────────────────────────────────────────────────┐
│                   SERVIDOR FLASK                         │
├─────────────────────────────────────────────────────────┤
│  ┌──────────┐  ┌──────────┐  ┌──────────┐               │
│  │ Thread 0 │  │ Thread 1 │  │ Thread N │ (7 threads)   │
│  │ Camera 0 │  │ Camera 1 │  │ Camera N │               │
│  └──────────┘  └──────────┘  └──────────┘               │
│       ↓             ↓              ↓                      │
│  ┌────────────────────────────────────────┐              │
│  │   Estado de Cámaras (CameraState)      │              │
│  │  - frame (bytes JPEG)                  │              │
│  │  - fps, bitrate_kbps                   │              │
│  │  - status (OK/LENTO/DESCONECTADA)      │              │
│  └────────────────────────────────────────┘              │
│       ↑             ↑              ↑                      │
│  /stream/0    /stream/1      /stream/N  (MJPEG)         │
│  /api/stats   /api/events              (JSON)           │
└─────────────────────────────────────────────────────────┘
```

### Proceso de Captura (por cada thread)

1. **Abrir cámara**
   ```python
   cap = cv2.VideoCapture(state.device_index, cv2.CAP_DSHOW)
   cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
   cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
   ```
   - Se abre el dispositivo usando el índice específico
   - Se configura resolución (640x480 por defecto)

2. **Leer frames continuamente**
   ```python
   ret, frame = state.cap.read()
   ```
   - Loop infinito leyendo frames a máxima velocidad
   - Si hay error (ret=False), intenta reconectar

3. **Codificar a JPEG**
   ```python
   _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
   encoded = buf.tobytes()
   ```
   - Convierte cada frame a JPEG para reducir tamaño
   - Calidad 70 (balance entre tamaño y claridad)

4. **Calcular métricas**
   ```python
   fps = (frames_capturados - 1) / tiempo_transcurrido
   bitrate = fps * frame_size_kb * 8
   ```
   - FPS se calcula con ventana deslizante de 30 frames
   - Bitrate se estima basado en tamaño del frame JPEG

5. **Guardar en cola (no bloqueante)**
   ```python
   _metrics_queue.put(("metric", camera_id, fps, bitrate, status))
   ```
   - Las escrituras a BD van a una cola de fondo
   - Los threads de captura nunca se bloquean esperando BD

## Streaming a Navegador

### MJPEG (Motion JPEG)

```
GET /stream/0
─────────────────
Content-Type: multipart/x-mixed-replace; boundary=frame

--frame
Content-Type: image/jpeg

[JPEG BYTES]
--frame
Content-Type: image/jpeg

[JPEG BYTES]
...
```

- Cada frame JPEG se envía secuencialmente
- El navegador decodifica y muestra automáticamente
- Se actualiza ~1-11 FPS por cámara (según hardware)

### API JSON

```
GET /api/stats
─────────────────────────────────────────
[
  {"id": 0, "fps": 1.0, "bitrate_kbps": 249.4, "status": "OK"},
  {"id": 1, "fps": 10.9, "bitrate_kbps": 602.6, "status": "OK"},
  ...
]
```

- Se actualiza cada 2 segundos en el cliente
- Sin locks (lectura directa de estados, segura en Python)

## Estados de Cámara

| Estado | Significado | Condición |
|--------|-------------|-----------|
| **OK** | Funcionando normal | FPS >= 70% del baseline |
| **LENTO** | Rendimiento degradado | FPS < 70% del baseline |
| **DESCONECTADA** | Sin señal | Sin frames por 3+ segundos |

## Troubleshooting

### "Se ven solo en negro"
- Verifica que las cámaras están conectadas: `find_cameras.py`
- Verifica que `CAMERA_INDICES` tiene los índices correctos
- Reinicia las cámaras físicamente

### "Fetch pending en navegador"
- Abre Console (F12) y busca errores CORS
- Asegúrate que `flask-cors` está instalado
- Verifica con `curl http://localhost:5000/api/stats`

### "Baja velocidad (FPS bajo)"
- Cámaras USB tienen limitaciones de ancho de banda compartido
- 7 cámaras simultáneas pueden saturar el bus USB
- Reduce resolución o aumenta compresión JPEG si es necesario

### "Database bloqueada"
- El worker thread `_db_worker()` guarda métricas de forma asincrónica
- Si aún así hay problemas, aumenta `METRICS_SAVE_INTERVAL`

## Archivos Clave

| Archivo | Propósito |
|---------|-----------|
| `camera_manager.py` | Captura de frames, threads, estado |
| `app.py` | Servidor Flask, rutas HTTP |
| `db.py` | Almacenamiento de métricas/eventos |
| `templates/dashboard.html` | UI del navegador |
| `find_cameras.py` | Script para detectar índices de cámaras |

## Ejemplo: Agregar una 8ª Cámara

1. Ejecuta `find_cameras.py` para encontrar el índice disponible
2. Actualiza `CAMERA_INDICES`:
   ```python
   CAMERA_INDICES = [0, 1, 2, 3, 4, 5, 6, 7]  # Agrega el índice
   ```
3. La aplicación se ajusta automáticamente (`NUM_CAMERAS = len(CAMERA_INDICES)`)
4. Reinicia el servidor
