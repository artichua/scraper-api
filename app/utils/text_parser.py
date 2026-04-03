import re
from urllib.parse import urlparse
from bs4 import BeautifulSoup

BASURA_EXACTA = {
    "anterior", "siguiente", "indice", "index",
    "next", "prev", "previous", "next chapter", "previous chapter",
    "table of contents", "compartir", "share", "tweet",
    "pagina anterior", "pagina siguiente", "inicio", "home",
    "privacy", "dmca", "faq", "login", "register",
    "responder", "reply", "delete", "like", "recomendar",
    "comentarios", "comments", "glossary", "about",
}

BASURA_RE = [re.compile(p, re.IGNORECASE) for p in [
    r"discord\.gg", r"patreon\.com", r"t\.me/", r"github\.com",
    r"novel\s*updates", r"(read|lee)\s*(more|mas)\s*at",
    r"support\s*us", r"donate", r"buy\s*coins",
    r"si estas leyendo las novelas que traduzco",
    r"puedes «patrocinar capítulos»",
    r"os agradezco demasiado",
    r"invitame\s*un\s*cafe",
    r"^comentarios?\s*\d*\s*$",
    r"\|\|",
    r"^\s*❀\s*$",
    r"edit this page", r"download full epub", r"formatting guide",
    r"contribution guide", r"report issues on our discord",
    r"connect with the community", r"join discord", r"how to format text",
    r"read this first before doing anything"
]]

SELECTORES_GENERICOS = [
    "div.prose", "div.chapter-content", "div#chapter-content",
    "div.reading-content", "div.texto-capitulo", "div.entry-content",
    "div.post-body", "div.post-content", "article.post", "article", "main"
]

def base_origen(url: str) -> str:
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}"

def obtener_dominio(url: str) -> str:
    hostname = (urlparse(url).hostname or "").lstrip("www.")
    partes = hostname.split(".")
    if len(partes) >= 2:
        sufijo = partes[-2]
        if sufijo in ("blogspot", "wordpress", "tumblr"):
            return sufijo + ".com"
        return ".".join(partes[-2:])
    return hostname

def es_basura(texto: str) -> bool:
    t = texto.strip()
    if not t or len(t) < 3:
        return True
    t_clean = re.sub(r'^\d+\s*', '', t)
    if "||" in t_clean:
        return True
    if t_clean.lower() in BASURA_EXACTA:
        return True
    for pat in BASURA_RE:
        if pat.search(t_clean):
            return True
    return False

def encontrar_mejor_contenedor_texto(soup: BeautifulSoup):
    # Función heurística para encontrar el contenedor principal del texto
    mejor_elemento = None
    mejor_puntaje = 0
    
    for elem in soup.find_all(['div', 'article', 'main', 'section']):
        textos_p = elem.find_all('p')
        texto_limpio = elem.get_text(strip=True)
        # Ignorar contenedores muy pequeños
        if len(texto_limpio) < 300:
            continue
            
        puntaje = len(texto_limpio) + (len(textos_p) * 100)
        
        # Penalizar si tiene muchos enlaces
        links = elem.find_all('a')
        if len(links) > 10:
            puntaje -= len(links) * 50
            
        if puntaje > mejor_puntaje:
            mejor_puntaje = puntaje
            mejor_elemento = elem
            
    # Si la heurística no halla nada contundente, usar selectores genéricos de respaldo
    if not mejor_elemento or mejor_puntaje < 1000:
        for selector in SELECTORES_GENERICOS:
            candidato = soup.select_one(selector)
            if candidato and len(candidato.get_text(strip=True)) > 200:
                mejor_elemento = candidato
                break
                
    return mejor_elemento
