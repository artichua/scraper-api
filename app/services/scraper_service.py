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
    for sel in ["script", "style", "nav", "header", "footer", "aside", ".comments", "#comments", ".sidebar"]:
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
        dominio = obtener_dominio(url)
        sitio_conocido = conocimiento.obtener(dominio)
        
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
        
        if sitio.tipo_paginacion != "ninguno":
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
    
    def _extraer_capitulos_soup(self, soup: BeautifulSoup, url: str, sitio: SitioAprendido) -> List[Dict]:
        capitulos = []
        base = base_origen(url)
        
        palabras_capitulo = ["chapter", "capitulo", "cap", "ch", "episode", "part", "parte", "side story"]
        
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            texto = a.get_text(strip=True)
            
            if not href or not texto or len(texto) > 150:
                continue
            
            if href.startswith("/"):
                url_abs = urljoin(base, href)
            elif href.startswith("http"):
                url_abs = href
            else:
                continue
            
            es_capitulo = False
            texto_lower = texto.lower()
            
            # Si ya tenemos un patrón aprendido, usamos una lógica más estricta guiada por él
            if sitio and sitio.patron_url_capitulo:
                if re.search(sitio.patron_url_capitulo, url_abs, re.IGNORECASE):
                    es_capitulo = True
                elif any(p in texto_lower for p in palabras_capitulo) and len(texto) < 100:
                    es_capitulo = True
            else:
                # Si no hay patrón aprendido, recurrimos a heurísticas generales
                if any(p in texto_lower for p in palabras_capitulo):
                    es_capitulo = True
                elif re.search(r'\d+', texto) and len(texto) < 100:
                    es_capitulo = True
            
            if texto_lower in ["next", "prev", "previous", "anterior", "siguiente", "home", "inicio"]:
                es_capitulo = False
                
            # Excluir URLs que claramente no son capítulos
            url_lower = url_abs.lower()
            exclusiones = [
                "/profile/", "/author/", "/tag/", "/category/", "/login", "/register",
                "javascript:", "mailto:", "wp-login", ".jpg", ".png", "disqus.com", "blogger.com/profile",
                "facebook.com", "twitter.com", "discord.gg"
            ]
            if any(ex in url_lower for ex in exclusiones):
                es_capitulo = False
            
            if es_capitulo:
                obj = {"titulo": texto[:100], "url": url_abs}
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

scraper_inteligente = ScraperInteligente()
