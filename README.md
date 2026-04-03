# 📚 AI Scraper API

![build](https://img.shields.io/badge/build-passing-brightgreen?style=flat-square)
![coverage](https://img.shields.io/badge/coverage-95%25-brightgreen?style=flat-square)
![python](https://img.shields.io/badge/python-3.11+-blue?style=flat-square&logo=python&logoColor=white)
![fastapi](https://img.shields.io/badge/FastAPI-0.100+-teal?style=flat-square&logo=fastapi&logoColor=white)
![playwright](https://img.shields.io/badge/Playwright-enabled-orange?style=flat-square&logo=playwright&logoColor=white)
![license](https://img.shields.io/badge/licencia-personal%2Feducativo-lightgrey?style=flat-square)

> API inteligente para extracción de capítulos y contenido de novelas web.  
> Aprende automáticamente la estructura de cada sitio y mejora con el tiempo.

---

## ✨ Características

- 🧠 **Aprendizaje automático de sitios** — detecta selectores CSS, patrones de URL y tipo de paginación sin configuración manual
- 🌐 **Soporte multi-sitio** — funciona con la mayoría de sitios de novelas en español e inglés
- 🔐 **Bypass de protecciones** — maneja Cloudflare, CAPTCHAs y sitios con renderizado JavaScript via Playwright
- 💰 **Detección de capítulos de pago** — identifica capítulos premium/VIP antes de intentar leerlos
- 📄 **Extracción de texto** — obtiene el contenido completo de cada capítulo con heurísticas de densidad de texto
- 🗄️ **Base de conocimiento persistente** — guarda lo aprendido en `conocimiento_scraper.json` para visitas futuras

---

## 🎯 Sitios con soporte especializado

| Sitio | Método | Notas |
|-------|--------|-------|
| **buenovela.com** | API `/book_catalog/{id}/{pag}` + HTML | Paginación automática del catálogo completo |
| **webnovel.com** | API JSON `/go/pcm/novel/chapter-list` | Detecta capítulos VIP, normaliza URLs móviles |
| **m.webnovel.com** | Redirigido a desktop automáticamente | URLs móviles soportadas |
| Cualquier otro sitio | Heurísticas + Playwright fallback | Aprende la estructura en el primer acceso |

---

## 🚀 Inicio rápido

### Requisitos

- Python 3.11+
- Chromium (para Playwright)

### Instalación local

```bash
# Clonar el repositorio
git clone https://github.com/artichua/scraper-api.git
cd scraper-api

# Crear entorno virtual
python -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate   # Windows

# Instalar dependencias
pip install -r requirements.txt

# Instalar navegador Chromium para Playwright
playwright install chromium
playwright install-deps chromium

# Iniciar el servidor
python run.py
```

El servidor estará disponible en `http://localhost:8000`

### Docker

```bash
# Construir imagen
docker build -t scraper-api .

# Ejecutar contenedor
docker run -p 8000:8000 scraper-api
```

---

## 📡 Endpoints

### `GET /`
Estado general de la API.

```json
{
  "estado": "activo",
  "version": "6.0.0-clean",
  "sitios_aprendidos": 3
}
```

---

### `GET /capitulos/inteligente`

Lista los capítulos de un libro dado su URL.

**Parámetros:**

| Parámetro | Tipo | Default | Descripción |
|-----------|------|---------|-------------|
| `url` | `string` | requerido | URL del libro o índice de capítulos |
| `max_paginas` | `int` | `10` | Máximo de páginas de capítulos a recorrer |
| `extraer_texto` | `bool` | `false` | Si `true`, extrae el texto de los primeros capítulos |
| `max_textos` | `int` | `3` | Cuántos capítulos extraer cuando `extraer_texto=true` |

**Ejemplo:**

```bash
# Listar capítulos de una novela en buenovela.com
curl "http://localhost:8000/capitulos/inteligente?url=https://www.buenovela.com/libro/La-Virgen-del-Mafioso_31000746512"

# Con extracción de texto
curl "http://localhost:8000/capitulos/inteligente?url=<url>&extraer_texto=true&max_textos=1"
```

**Respuesta:**

```json
{
  "total": 245,
  "capitulos": [
    {
      "titulo": "Capítulo 1 Entre Paredes",
      "url": "https://www.buenovela.com/libro/.../Capítulo-1-Entre-Paredes_8161529"
    },
    {
      "titulo": "Capítulo 5 (VIP)",
      "url": "https://www.webnovel.com/book/.../123456",
      "es_paga": true,
      "mensaje": "Capítulo premium/VIP de webnovel."
    }
  ],
  "aprendido_de": "buenovela.com",
  "confianza": 0.85
}
```

---

### `GET /leer`

Extrae el texto completo de un capítulo.

```bash
curl "http://localhost:8000/leer?url=https://www.buenovela.com/libro/.../Capítulo-1_8161529"
```

**Respuesta:**

```json
{
  "url": "https://...",
  "acceso": "libre",
  "contenido": "Isabella Bianchi vio cómo su vida se trazaba..."
}
```

---

### `GET /conocimiento`

Muestra lo que el sistema ha aprendido de cada sitio.

```bash
curl "http://localhost:8000/conocimiento"
```

---

### `GET /debug`

Información de diagnóstico para una URL. Útil para detectar bloqueos.

```bash
curl "http://localhost:8000/debug?url=https://sitio-problematico.com/novela"
```

---

## 🏗️ Arquitectura

```
scraper-api/
├── app/
│   ├── api/
│   │   └── endpoints.py        # Rutas FastAPI
│   ├── core/
│   │   └── knowledge.py        # Base de conocimiento persistente
│   ├── services/
│   │   ├── scraper_service.py  # Lógica principal de scraping
│   │   └── detector_service.py # Análisis y aprendizaje de estructura
│   ├── utils/
│   │   ├── browser.py          # requests + Playwright con stealth
│   │   └── text_parser.py      # Heurísticas de extracción de texto
│   └── main.py                 # App FastAPI
├── run.py                      # Punto de entrada
├── requirements.txt
├── Dockerfile
└── conocimiento_scraper.json   # Base de conocimiento (generado en runtime)
```

### Flujo de extracción

```
URL → Normalización → ¿Sitio especial? ─── sí ──► Handler dedicado (webnovel, etc.)
                                         │
                                         no
                                         ▼
                                ¿Conocimiento previo?
                                 ├── sí → _extraer_con_conocimiento()
                                 └── no → _extraer_y_aprender() → Playwright → Detector
                                                 ▼
                                    ¿ID de libro en URL?
                                     ├── sí → book_catalog API paginada
                                     └── no → paginación por botón/URL
```

---

## 🔧 Cómo funciona el aprendizaje

1. **Primera visita** a un sitio nuevo: Playwright renderiza la página completa.
2. El `DetectorInteligente` analiza:
   - Selectores CSS con mayor densidad de texto
   - Patrones de URL de los capítulos detectados
   - Tipo de paginación (botón "siguiente", URL `/page/N`, etc.)
3. El conocimiento se guarda en `conocimiento_scraper.json` con un score de confianza.
4. **Visitas siguientes**: se usa el conocimiento guardado — más rápido, sin Playwright si no es necesario.

---

## 🛡️ Manejo de protecciones

| Protección | Estrategia |
|------------|------------|
| Cloudflare básico | User-Agent real + headers de navegador |
| Cloudflare Turnstile | Playwright + espera activa hasta que desaparezca el challenge |
| Renderizado JS | Playwright headless con `playwright-stealth` |
| APIs bloqueadas (403) | Playwright como fallback automático |

---

## 📝 Variables de entorno

No se requieren variables de entorno por defecto. El servidor arranca en `0.0.0.0:8000`.

---

## 👤 Autor

Hecho por [@artichua](https://github.com/artichua)

---

## 📄 Licencia

Uso personal / educativo. Respetar los términos de servicio de cada sitio web.