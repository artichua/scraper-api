import re
from typing import Dict, Any
from bs4 import BeautifulSoup

from app.core.knowledge import conocimiento, SitioAprendido
from app.utils.text_parser import obtener_dominio

class DetectorInteligente:
    """Aprende automáticamente cómo funciona un sitio web"""
    
    def __init__(self):
        self.patrones_aprendidos = {}
    
    def analizar_estructura(self, soup: BeautifulSoup, url: str) -> Dict[str, Any]:
        """Analiza la estructura del sitio y extrae patrones"""
        
        analisis = {
            "selectores_probables": [],
            "patrones_url": [],
            "tipo_paginacion": "ninguno",
            "requiere_js": False,
            "confianza": 0.0
        }
        
        # 1. ANALIZAR SELECTORES DE CONTENIDO
        candidatos_contenido = []
        for elem in soup.find_all(["div", "article", "main", "section"]):
            texto = elem.get_text(strip=True)
            if len(texto) < 500:
                continue
            
            parrafos = len(elem.find_all("p"))
            links = len(elem.find_all("a"))
            
            puntuacion = 0
            # Más párrafos = mejor contenido
            if parrafos > 5:
                puntuacion += 30
            # Texto largo = buen contenido
            if len(texto) > 2000:
                puntuacion += 20
            # Clases indicativas
            clases = " ".join(elem.get("class", [])).lower()
            palabras_clave = ["content", "entry", "post", "chapter", "article", "texto", "capitulo", "novel"]
            for palabra in palabras_clave:
                if palabra in clases:
                    puntuacion += 15
            # Penalizar muchos links (probablemente menú)
            if links > 50:
                puntuacion -= 20
            
            if puntuacion > 20:
                selector = self._generar_selector(elem)
                candidatos_contenido.append((puntuacion, selector, elem))
        
        if candidatos_contenido:
            mejor = max(candidatos_contenido, key=lambda x: x[0])
            analisis["selectores_probables"].append({
                "selector": mejor[1],
                "confianza": min(mejor[0] / 100, 0.9)
            })
            analisis["confianza"] = mejor[0] / 100
        
        # 2. ANALIZAR PATRONES DE URL DE CAPÍTULOS
        from urllib.parse import urlparse
        urls_capitulos = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            texto = a.get_text(strip=True).lower()
            
            # Palabras FUERTES que indican capítulo para usar en el aprendizaje
            palabras_capitulo = ["chapter", "capitulo", "episode", "part", "parte"]
            if any(p in texto for p in palabras_capitulo):
                urls_capitulos.append(href)
        
        if urls_capitulos:
            # Aprendizaje Dinámico de Patrones URL: buscar la ruta base más común
            paths = []
            for u in urls_capitulos:
                try:
                    parsed = urlparse(u)
                    path = parsed.path
                    if path:
                        base_path = path.rsplit('/', 1)[0] + '/'
                        if base_path != '/' and len(base_path) > 2:
                            paths.append(base_path)
                except:
                    pass
            
            if paths:
                from collections import Counter
                mas_comun, frecuencias = Counter(paths).most_common(1)[0]
                if frecuencias > len(urls_capitulos) * 0.3:  # Al menos 30% comparten la ruta
                    patron_dinamico = re.escape(mas_comun) + r".*"
                    analisis["patrones_url"].append({
                        "patron": patron_dinamico,
                        "coincidencias": frecuencias,
                        "confianza": frecuencias / len(urls_capitulos)
                    })

            # Aprender usando los patrones fijos de respaldo
            for patron in [r'/chapter[\-/_]?\d+', r'/capitulo[\-/_]?\d+', r'/ch[\-/_]?\d+', r'/\d{4}/\d{2}/\d{2}/']:
                coincidencias = [u for u in urls_capitulos if re.search(patron, u, re.IGNORECASE)]
                if len(coincidencias) > len(urls_capitulos) * 0.3:  # 30% coinciden
                    analisis["patrones_url"].append({
                        "patron": patron,
                        "coincidencias": len(coincidencias),
                        "confianza": len(coincidencias) / len(urls_capitulos)
                    })
        
        # 3. ANALIZAR PAGINACIÓN
        textos_navegacion = ["next", "siguiente", "older", "→", "»", "›"]
        for texto in textos_navegacion:
            btn = soup.find("a", string=re.compile(texto, re.IGNORECASE))
            if btn and btn.get("href"):
                analisis["tipo_paginacion"] = "boton"
                analisis["boton_paginacion"] = texto
                break
        
        if analisis["tipo_paginacion"] == "ninguno":
            patrones_paginacion = [r'/page/\d+', r'/paginapage=\d+', r'/\?page=\d+', r'/pagina/\d+']
            for a in soup.find_all("a", href=True):
                for patron in patrones_paginacion:
                    if re.search(patron, a["href"]):
                        analisis["tipo_paginacion"] = "url"
                        analisis["patron_paginacion"] = patron
                        break
                if analisis["tipo_paginacion"] != "ninguno":
                    break
        
        # 4. DETECTAR SI REQUIERE JAVASCRIPT
        if soup.find("div", {"id": "root"}) or soup.find("div", {"id": "app"}):
            analisis["requiere_js"] = True
        if "Loading" in soup.get_text() and len(soup.get_text()) < 1000:
            analisis["requiere_js"] = True
        if "Checking your browser" in soup.get_text() or "Just a moment" in soup.get_text():
            analisis["requiere_js"] = True
        
        return analisis
    
    def _generar_selector(self, elemento) -> str:
        if elemento.get("id"):
            return f"#{elemento.get('id')}"
        elif elemento.get("class"):
            return f"{elemento.name}.{'.'.join(elemento.get('class')[:2])}"
        else:
            return elemento.name
    
    def aprender_de_sitio(self, url: str, html: str, exito: bool = True) -> SitioAprendido:
        """Aprende de un sitio y guarda el conocimiento"""
        dominio = obtener_dominio(url)
        soup = BeautifulSoup(html, "html.parser")
        
        analisis = self.analizar_estructura(soup, url)
        
        sitio = conocimiento.obtener(dominio)
        if sitio is None:
            sitio = SitioAprendido(dominio=dominio)
        
        if analisis["selectores_probables"]:
            mejor_selector = max(analisis["selectores_probables"], key=lambda x: x["confianza"])
            if mejor_selector["confianza"] > sitio.confianza:
                sitio.selector_contenido = mejor_selector["selector"]
                sitio.confianza = mejor_selector["confianza"]
        
        if analisis["patrones_url"]:
            mejor_patron = max(analisis["patrones_url"], key=lambda x: x["confianza"])
            sitio.patron_url_capitulo = mejor_patron["patron"]
        
        sitio.tipo_paginacion = analisis["tipo_paginacion"]
        if analisis.get("patron_paginacion"):
            sitio.patron_paginacion = analisis["patron_paginacion"]
        
        sitio.requiere_playwright = analisis["requiere_js"]
        
        if url not in sitio.ejemplos_urls:
            sitio.ejemplos_urls.append(url)
            if len(sitio.ejemplos_urls) > 10:
                sitio.ejemplos_urls.pop(0)
        
        sitio.actualizar_confianza(exito)
        conocimiento.guardar_aprendizaje(dominio, sitio)
        
        return sitio
