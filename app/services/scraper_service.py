import re
import logging
from typing import Dict, List, Optional
from urllib.parse import urljoin
from bs4 import BeautifulSoup

from app.core.knowledge import conocimiento, SitioAprendido
from app.services.detector_service import DetectorInteligente
from app.utils.browser import obtener_html
from app.utils.text_parser import base_origen, obtener_dominio, encontrar_mejor_contenedor_texto, es_basura

logger = logging.getLogger("scraper-inteligente")

def extraer_texto_dinamico(url: str, dominio: str, forzar_pw: bool = False) -> dict:
    try:
        html = obtener_html(url, forzar_playwright=forzar_pw, sitio=dominio)
    except Exception as e:
        return {"url": url, "acceso": "bloqueado", "mensaje": f"Error: {e}"}
    
    if not html:
        return {"url": url, "acceso": "bloqueado", "mensaje": "No se pudo obtener el HTML (posible bloqueo)"}
        
    soup = BeautifulSoup(html, "html.parser")
    
    # Eliminar basura
    for sel in ["script", "style", "nav", "header", "footer", "aside", ".comments", "#comments", ".sidebar", ".navigation", "#navigation", ".footer", "#footer", ".header", "#header", ".menu", "#menu", ".top-bar", ".bottom-bar"]:
        for tag in soup.select(sel):
            tag.decompose()
            
    mejor_elemento = encontrar_mejor_contenedor_texto(soup)
                
    if mejor_elemento:
        texto = mejor_elemento.get_text(separator="\n")
        lineas = []
        for linea in texto.splitlines():
            t = re.sub(r'\s+', ' ', linea).strip()
            if t and not es_basura(t) and len(t) > 5:
                lineas.append(t)
        
        contenido = "\n\n".join(lineas)
        if len(contenido) > 100:
            return {"url": url, "acceso": "libre", "contenido": contenido}
            
    return {
        "url": url,
        "acceso": "bloqueado",
        "mensaje": "No se encontró contenido",
        "contenido_visible": soup.get_text()[:1000]
    }

class ScraperInteligente:
    """Scraper que usa aprendizaje automático y mejora con el tiempo"""
    
    def __init__(self):
        self.detector = DetectorInteligente()
    
    def extraer_capitulos(self, url: str, max_paginas: int = 10, extraer_texto: bool = False, max_textos: int = 3) -> Dict:
        # Normalizar URL móvil de webnovel a la versión escritorio
        url = self._normalizar_url(url)

        dominio = obtener_dominio(url)
        sitio_conocido = conocimiento.obtener(dominio)

        # Soporte especial para webnovel.com: usar su API JSON de capítulos
        if "webnovel.com" in url:
            resultado = self._extraer_webnovel(url, max_paginas)
            if resultado:
                return resultado

        if sitio_conocido and sitio_conocido.confianza > 0.5:
            resultado = self._extraer_con_conocimiento(url, sitio_conocido, max_paginas)
        else:
            resultado = self._extraer_y_aprender(url, max_paginas)
            
        if extraer_texto and resultado.get("capitulos"):
            count = 0
            for cap in resultado["capitulos"]:
                if count >= max_textos:
                    break
                # Validar capítulos de paga antes de intentar extraer
                if cap.get("es_paga"):
                    cap["contenido_error"] = cap.get("mensaje")
                    continue
                try:
                    contenido_res = extraer_texto_dinamico(cap["url"], dominio, sitio_conocido.requiere_playwright if sitio_conocido else False)
                    if contenido_res.get("acceso") == "libre":
                        cap["contenido"] = contenido_res.get("contenido")
                    else:
                        cap["contenido_error"] = contenido_res.get("mensaje")
                except Exception as e:
                    cap["contenido_error"] = str(e)
                count += 1
                
        return resultado
    
    def _extraer_con_conocimiento(self, url: str, sitio: SitioAprendido, max_paginas: int) -> Dict:
        logger.info(f"Usando conocimiento previo para {sitio.dominio} (confianza: {sitio.confianza:.2f})")
        
        todos_capitulos = []
        vistos = set()
        
        forzar_pw = sitio.requiere_playwright
        html = obtener_html(url, forzar_playwright=forzar_pw, sitio=sitio.dominio)
        if not html:
             return {"total": 0, "error": "No se pudo obtener la URL principal, posible bloqueo persistente"}
        
        soup = BeautifulSoup(html, "html.parser")
        
        caps = self._extraer_capitulos_soup(soup, url, sitio)
        for cap in caps:
            if cap["url"] not in vistos:
                vistos.add(cap["url"])
                todos_capitulos.append(cap)
        
        # Intentar paginación via API de catálogo (ej. buenovela: /book_catalog/{ID}/{pagina})
        id_libro = self._extraer_id_libro(url)
        if id_libro:
            caps_catalogo = self._extraer_catalogo_paginado(url, id_libro, forzar_pw, sitio, max_paginas)
            for cap in caps_catalogo:
                if cap["url"] not in vistos:
                    vistos.add(cap["url"])
                    todos_capitulos.append(cap)
        elif sitio.tipo_paginacion != "ninguno":
            pagina_actual = url
            for _ in range(max_paginas - 1):
                siguiente = self._obtener_siguiente_pagina(soup, pagina_actual, sitio)
                if not siguiente or siguiente in vistos:
                    break
                
                html = obtener_html(siguiente, forzar_playwright=forzar_pw, sitio=sitio.dominio)
                if not html: break
                soup = BeautifulSoup(html, "html.parser")
                caps = self._extraer_capitulos_soup(soup, siguiente, sitio)
                
                nuevos = 0
                for cap in caps:
                    if cap["url"] not in vistos:
                        vistos.add(cap["url"])
                        todos_capitulos.append(cap)
                        nuevos += 1
                
                if nuevos == 0:
                    break
                pagina_actual = siguiente
        
        sitio.actualizar_confianza(len(todos_capitulos) > 0)
        conocimiento.guardar()
        
        return {
            "total": len(todos_capitulos),
            "capitulos": todos_capitulos,
            "aprendido_de": sitio.dominio,
            "confianza": sitio.confianza
        }
    
    def _extraer_y_aprender(self, url: str, max_paginas: int) -> Dict:
        logger.info(f"Aprendiendo de nuevo sitio: {url}")
        
        html = obtener_html(url, forzar_playwright=True, sitio="nuevo")
        if not html:
             return {"total": 0, "error": "No se pudo obtener la URL principal para aprender, posible bloqueo persistente"}
        
        sitio = self.detector.aprender_de_sitio(url, html, exito=True)
        return self._extraer_con_conocimiento(url, sitio, max_paginas)
    
    def _es_capitulo_paga(self, elemento_a) -> bool:
        """Determina si un capítulo requiere pago verificando íconos, texto o clases"""
        indicios_texto = ["premium", "locked", "advanced chapter", "buy", "coin", "patreon", "🔒", "🪙", "🔐", "privilege", "unlock", "subscription"]
        
        texto_link = elemento_a.get_text(strip=True).lower()
        clases_link = " ".join(elemento_a.get("class", [])).lower()
        
        padre = elemento_a.parent
        texto_padre = padre.get_text(strip=True).lower() if padre else ""
        clases_padre = " ".join(padre.get("class", [])).lower() if padre else ""
        
        texto_total = texto_link + " " + texto_padre + " " + clases_link + " " + clases_padre
        
        return any(indicio in texto_total for indicio in indicios_texto)
    
    def _titulo_desde_url(self, url_abs: str) -> str:
        """Extrae un título legible desde el slug de la URL cuando el texto del enlace es un preview largo."""
        from urllib.parse import urlparse, unquote
        path = unquote(urlparse(url_abs).path)
        # Tomar el último segmento del path y limpiar
        slug = path.rstrip("/").split("/")[-1]
        # Eliminar ID numérico al final (ej. _8161529)
        slug = re.sub(r'_\d+$', '', slug)
        # Reemplazar guiones por espacios y capitalizar
        return slug.replace("-", " ").replace("_", " ").strip()
    
    def _extraer_capitulos_soup(self, soup: BeautifulSoup, url: str, sitio: SitioAprendido) -> List[Dict]:
        capitulos = []
        vistos_hrefs = set()
        
        palabras_capitulo = ["chapter", "capitulo", "cap", "ch", "episode", "part", "parte", "side story"]
        
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            texto = a.get_text(strip=True)
            
            if not href or not texto:
                continue
            
            if href.startswith("javascript:") or href.startswith("mailto:") or href.startswith("#"):
                continue
            
            url_abs = urljoin(url, href)
            
            # Evitar duplicados por href
            if url_abs in vistos_hrefs:
                continue
            
            es_capitulo = False
            url_lower = url_abs.lower()
            
            # Detectar si el texto es un preview largo: extraer título desde URL en ese caso
            texto_es_preview = len(texto) > 150
            texto_titulo = self._titulo_desde_url(url_abs) if texto_es_preview else texto
            texto_lower = texto_titulo.lower()
            
            # Si ya tenemos un patrón aprendido, usamos una lógica más estricta guiada por él
            if sitio and sitio.patron_url_capitulo:
                if re.search(sitio.patron_url_capitulo, url_abs, re.IGNORECASE):
                    es_capitulo = True
                elif any(p in texto_lower for p in palabras_capitulo) and len(texto_titulo) < 100:
                    es_capitulo = True
            else:
                # Heurísticas generales: texto del título o URL contienen palabras de capítulo
                if any(p in texto_lower for p in palabras_capitulo):
                    es_capitulo = True
                elif any(p in url_lower for p in ["capitulo", "chapter", "cap%c3%adtulo", "continua"]):
                    es_capitulo = True
                elif re.search(r'\d+', texto_titulo) and len(texto_titulo) < 100:
                    es_capitulo = True
            
            if texto_lower in ["next", "prev", "previous", "anterior", "siguiente", "home", "inicio",
                               "leer más", "leer mas", "read more", "continua", "ver más"]:
                es_capitulo = False
                
            # Excluir URLs que claramente no son capítulos
            exclusiones = [
                "/profile/", "/author/", "/tag/", "/category/", "/login", "/register",
                "javascript:", "mailto:", "wp-login", ".jpg", ".png", "disqus.com", "blogger.com/profile",
                "facebook.com", "twitter.com", "discord.gg", "/book_catalog/",
            ]
            # Excluir links que apuntan a la página del libro (misma URL base sin subcapítulo)
            if url_abs.rstrip("/") == url.rstrip("/"):
                es_capitulo = False
            if any(ex in url_lower for ex in exclusiones):
                es_capitulo = False
            
            if es_capitulo:
                vistos_hrefs.add(url_abs)
                obj = {"titulo": texto_titulo[:120], "url": url_abs}
                if self._es_capitulo_paga(a):
                    obj["es_paga"] = True
                    obj["mensaje"] = "Este capítulo aparentemente es de paga o requiere acceso premium."
                
                capitulos.append(obj)
        
        return capitulos
    
    def _obtener_siguiente_pagina(self, soup: BeautifulSoup, url_actual: str, sitio: SitioAprendido) -> Optional[str]:
        base = base_origen(url_actual)
        
        if sitio.tipo_paginacion == "boton":
            textos = ["next", "siguiente", "older", "→", "»", "›"]
            for texto in textos:
                btn = soup.find("a", string=re.compile(texto, re.IGNORECASE))
                if btn and btn.get("href"):
                    return urljoin(base, btn["href"])
        
        elif sitio.tipo_paginacion == "url" and sitio.patron_paginacion:
            for a in soup.find_all("a", href=True):
                if re.search(sitio.patron_paginacion, a["href"]):
                    return urljoin(base, a["href"])
        
        return None

    def _normalizar_url(self, url: str) -> str:
        """Normaliza URLs de variantes móviles o con parámetros de tracking."""
        # webnovel: m.webnovel.com → www.webnovel.com
        url = re.sub(r'https?://m\.webnovel\.com', 'https://www.webnovel.com', url)
        return url

    def _extraer_webnovel(self, url: str, max_paginas: int) -> Optional[Dict]:
        """
        Extrae capítulos de webnovel.com usando su API interna JSON.
        Endpoint: /go/pcm/novel/chapter-list?bookId={id}&pageIndex={n}&pageSize=100
        """
        import requests
        from urllib.parse import urlparse, unquote

        # Extraer el book ID desde la URL (último segmento numérico)
        # Patrón: /book/{titulo}_{id}  o  /book/{id}
        path = unquote(urlparse(url).path)
        match = re.search(r'_(\d{10,})$|/(\d{10,})', path)
        if not match:
            logger.warning(f"webnovel: no se pudo extraer book ID de {url}")
            return None

        book_id = match.group(1) or match.group(2)

        # Extraer título del libro desde la URL para construir URLs de capítulos
        slug_match = re.search(r'/book/([^/]+)_\d+', path)
        book_slug = slug_match.group(1) if slug_match else "book"

        # Detectar idioma desde la URL (/es/, /pt/, etc.)
        lang_match = re.search(r'webnovel\.com/([a-z]{2})/', url)
        lang = lang_match.group(1) if lang_match else None
        base_chapter_url = f"https://www.webnovel.com/book/{book_slug}_{book_id}"

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
            "Accept": "application/json, */*",
            "Referer": "https://www.webnovel.com/",
            "Cookie": "_csrfToken=dummy",
        }

        todos_capitulos = []
        vistos = set()

        for pagina in range(max_paginas):
            api_url = (
                f"https://www.webnovel.com/go/pcm/novel/chapter-list"
                f"?bookId={book_id}&pageIndex={pagina}&pageSize=100"
            )
            logger.info(f"webnovel API: {api_url}")
            try:
                r = requests.get(api_url, headers=headers, timeout=15)
                if r.status_code != 200:
                    logger.warning(f"webnovel API respondió {r.status_code}")
                    break

                data = r.json()
                items = []

                # La respuesta puede estar en data.data.items o con distintas claves
                inner = data.get("data", data)
                if isinstance(inner, dict):
                    for key in ("chapterItems", "items", "chapters", "volumeItems"):
                        if key in inner:
                            raw = inner[key]
                            # volumeItems agrupa capítulos por volumen
                            if isinstance(raw, list) and raw and isinstance(raw[0], dict) and "chapterItems" in raw[0]:
                                for vol in raw:
                                    items.extend(vol.get("chapterItems", []))
                            else:
                                items = raw
                            break
                elif isinstance(inner, list):
                    items = inner

                if not items:
                    logger.info(f"webnovel: sin capítulos en página {pagina}, terminando")
                    break

                nuevos = 0
                for item in items:
                    cap_id = str(item.get("id") or item.get("chapterId") or "")
                    titulo = (
                        item.get("name")
                        or item.get("chapterName")
                        or item.get("title")
                        or f"Capítulo {cap_id}"
                    )
                    if not cap_id or cap_id in vistos:
                        continue
                    vistos.add(cap_id)

                    # Construir URL del capítulo
                    cap_url = f"{base_chapter_url}/{cap_id}"

                    cap_obj = {"titulo": str(titulo)[:120], "url": cap_url}

                    # Detectar capítulo de paga
                    is_locked = item.get("isLocked") or item.get("isVip") or item.get("isPay")
                    if is_locked:
                        cap_obj["es_paga"] = True
                        cap_obj["mensaje"] = "Capítulo premium/VIP de webnovel."

                    todos_capitulos.append(cap_obj)
                    nuevos += 1

                logger.info(f"webnovel: {nuevos} capítulos en página {pagina}")
                if nuevos < 100:
                    # Última página (menos de pageSize resultados)
                    break

            except Exception as e:
                logger.warning(f"webnovel API error en página {pagina}: {e}")
                break

        if not todos_capitulos:
            logger.warning("webnovel: API no devolvió capítulos, intentando con Playwright")
            return None  # Fallback al scraper general

        return {
            "total": len(todos_capitulos),
            "capitulos": todos_capitulos,
            "fuente": "webnovel_api",
            "book_id": book_id,
        }

    def _extraer_id_libro(self, url: str) -> Optional[str]:
        """Detecta si la URL contiene un ID de libro numérico (patrón buenovela: _31000746512)."""
        match = re.search(r'_(\d{8,})', url)
        return match.group(1) if match else None

    def _extraer_catalogo_paginado(
        self, url_libro: str, id_libro: str, forzar_pw: bool,
        sitio: SitioAprendido, max_paginas: int
    ) -> list:
        """
        Obtiene capítulos desde la API de catálogo paginado.
        Patrón: https://dominio.com/book_catalog/{id}/{pagina}
        Soporta respuesta JSON y HTML.
        """
        from urllib.parse import urlparse
        parsed = urlparse(url_libro)
        base = f"{parsed.scheme}://{parsed.netloc}"

        caps_catalogo = []
        vistos = set()

        for pagina in range(1, max_paginas + 1):
            api_url = f"{base}/book_catalog/{id_libro}/{pagina}"
            logger.info(f"Consultando catálogo paginado: {api_url}")

            try:
                import requests
                r = requests.get(api_url, headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
                    "Accept": "application/json, text/html, */*",
                    "Referer": url_libro,
                }, timeout=15)

                if r.status_code != 200:
                    break

                content_type = r.headers.get("Content-Type", "")
                if "json" in content_type:
                    data = r.json()
                    # Intentar extraer capítulos del JSON (estructura variable según el sitio)
                    items = []
                    if isinstance(data, list):
                        items = data
                    elif isinstance(data, dict):
                        for key in ("chapters", "capitulos", "items", "data", "list"):
                            if key in data and isinstance(data[key], list):
                                items = data[key]
                                break
                    
                    nuevos = 0
                    for item in items:
                        cap_url = item.get("url") or item.get("link") or item.get("href", "")
                        if cap_url and not cap_url.startswith("http"):
                            cap_url = base + cap_url
                        titulo = item.get("titulo") or item.get("title") or item.get("name", cap_url)
                        if cap_url and cap_url not in vistos:
                            vistos.add(cap_url)
                            caps_catalogo.append({"titulo": str(titulo)[:120], "url": cap_url})
                            nuevos += 1
                    
                    if nuevos == 0:
                        break

                else:
                    # Respuesta HTML — parsear con BeautifulSoup
                    html = r.text
                    if not html or len(html) < 200:
                        break
                    soup_pag = BeautifulSoup(html, "html.parser")
                    caps = self._extraer_capitulos_soup(soup_pag, url_libro, sitio)
                    nuevos = 0
                    for cap in caps:
                        if cap["url"] not in vistos:
                            vistos.add(cap["url"])
                            caps_catalogo.append(cap)
                            nuevos += 1
                    if nuevos == 0:
                        break

            except Exception as e:
                logger.warning(f"Error consultando catálogo página {pagina}: {e}")
                break

        logger.info(f"Catálogo paginado encontró {len(caps_catalogo)} capítulos para libro {id_libro}")
        return caps_catalogo

scraper_inteligente = ScraperInteligente()
