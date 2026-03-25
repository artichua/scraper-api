from fastapi import FastAPI, HTTPException
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth
from bs4 import BeautifulSoup, NavigableString
import time
import re
import requests
import gzip
from urllib.parse import urlparse

app = FastAPI(
    title="Scraper API",
    description="API universal para extraer capítulos de sitios de novelas",
    version="3.4.0"
)

# ─────────────────────────────────────────────────────────────
# REGLAS POR DOMINIO
# ─────────────────────────────────────────────────────────────
SITE_RULES = {
    "skydemonorder.com": {
        "selector": "div.prose",
        "modo": "parrafos",
        "cap_patron": r"/projects/.+/.+",
        "requiere_playwright": True,
    },
    "novelasligera.com": {
        "selector": "div.entry-content, div.texto-capitulo, div#content article",
        "modo": "parrafos",
        "cap_patron": r"/novela/.+/.+",
        "requiere_playwright": True,
    },
    "wuxiaworld.com": {
        "selector": "div.chapter-content, div#chapter-content",
        "modo": "parrafos",
        "cap_patron": r"/novel/.+/chapter-.+",
        "requiere_playwright": True,
    },
    "maehwasup.com": {
        "selector": "div.entry-content, article, .post",
        "modo": "parrafos",
        "cap_patron": r"/\d{4}/\d{2}/\d{2}/.+",
        "requiere_playwright": True,
    },
    "blogspot.com": {
        "selector": "div.post-body, div.entry-content",
        "modo": "parrafos",
        "cap_patron": r"capitulo\s*\d+|ragnarok",
        "requiere_playwright": False,
    },
    "wordpress.com": {
        "selector": "div.entry-content",
        "modo": "parrafos",
        "cap_patron": r"/\d{4}/\d{2}/\d{2}/.+",
        "requiere_playwright": False,
    },
}

SELECTORES_GENERICOS = [
    "div.prose",
    "div.chapter-content",
    "div#chapter-content",
    "div.reading-content",
    "div.texto-capitulo",
    "div.entry-content",
    "div.post-body",
    "div.post-content",
    "div.content-area",
    "div.novel-content",
    "div#content article",
    "article.post",
    "article",
    "main",
]

# ─────────────────────────────────────────────────────────────
# PATRONES DE BASURA (VERSIÓN FINAL MEJORADA)
# ─────────────────────────────────────────────────────────────
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
    r"discord\.gg", r"patreon\.com", r"t\.me/",
    r"novel\s*updates", r"(read|lee)\s*(more|mas)\s*at",
    r"support\s*us", r"donate", r"buy\s*coins",
    r"unlock\s*(chapter|capitulo)",
    r"DIOSMARCIAL", r"widget_id", r"blogthis",
    r"publicado\s*por", r"compartan\s*esta",
    r"^\s*nota:\s*[!]?compartan",
    r"^https?://\S+$",
    r"skydark\s*:", r"traductor\s*:",
    
    # Filtros para comentarios y notas de traductor
    r"si estas leyendo las novelas que traduzco",
    r"puedes «patrocinar capítulos»",
    r"para una traducción más rápida",
    r"no importa si ya a sido pausada",
    r"sera traducida si haces el patrocinio",
    r"no se olviden de dejar la sigla",
    r"si patrocinan algunos capítulo",
    r"o déjenme alguna reseña",
    r"os agradezco demasiado",
    r"nt:\s*la moneda es dolares",
    r"más conocidos como gringos",
    r"patrocinio\s*5\$?\s*=\s*4\s*cap",
    r"invitame\s*un\s*cafe",
    r"^comentarios?\s*\d*\s*$",
    r"^\d+\s*(respuestas?|replies?)\s*$",
    r"like\s*\d+",
    r"recomendar\s*\d*",
    r"compartir\s*\d*",
    r"twitter\s*$",
    r"facebook\s*$",
    r"whatsapp\s*$",
    r"telegram\s*$",
    
    # Filtros para menús y navegación
    r"^(rotmhs\s*glossary|about\s*page|home\s*page)$",
    r"\|\|",
    r"^(first|previous|next|last)\s+(part|chapter|page)",
    r"(part|cap[i]tulo)\s+(i|ii|iii|iv|v|vi|vii|viii|ix|x)\s*(>>>|<<<)",
    r">>>\s*$",
    r"<<<\s*$",
    r"^\s*❀\s*$",
    r"^_{10,}$",
    r"^\s*[-=*]{10,}\s*$",
    
    # Líneas vacías o solo espacios
    r"^\s*$",
]]

NAV_RE = re.compile(
    r'^\s*(anterior|siguiente|indice|index|next|prev|previous'
    r'|next\s*chapter|previous\s*chapter|table\s*of\s*contents'
    r'|cap[i]tulo\s*anterior|siguiente\s*cap[i]tulo'
    r'|pagina\s*anterior|pagina\s*siguiente)\s*$',
    re.IGNORECASE
)

TEXTOS_NAV_IGNORADOS = {
    "start reading", "read now", "start", "leer", "home",
    "login", "register", "privacy", "dmca", "faq",
    "inicio", "inicio de sesion", "registrarse",
    "next page", "previous page", "siguiente pagina", "pagina anterior",
    "saltar al contenido", "skip to content",
    "about", "glossary", "contact", "cookie policy",
    "report this content", "view site in reader",
    "manage subscriptions", "blog at wordpress.com",
    "subscribe", "subscribed", "sign me up", "log in now",
    "sign up", "log in", "collapse this bar",
    "menu", "reclutamiento", "contacto",
    "novelas chinas", "novelas coreanas", "novelas japonesas",
    "novelas +18", "donativo",
}

NEXT_PAGE_RE = re.compile(
    r'^(next\s*page|siguiente\s*p[a]gina|p[a]gina\s*siguiente|>|>|>>)\s*$',
    re.IGNORECASE
)


def es_basura(texto: str) -> bool:
    """Filtra líneas de basura, comentarios, notas de traductor y menús"""
    t = texto.strip()
    if not t or len(t) < 3:
        return True
    
    # Limpiar números de likes/comentarios
    t_clean = re.sub(r'^\d+\s*', '', t)
    
    # Filtrar líneas que parecen menús (con ||)
    if "||" in t_clean:
        return True
    
    # Filtrar líneas que son solo enlaces de navegación
    if re.match(r'^(first|previous|next|last)\s+(chapter|page|part)$', t_clean, re.IGNORECASE):
        return True
    
    # Filtrar decoraciones
    if re.match(r'^[❀☆★✦✧✿🌸]+$', t_clean):
        return True
    
    if t_clean.lower() in BASURA_EXACTA:
        return True
    if NAV_RE.match(t_clean):
        return True
    for pat in BASURA_RE:
        if pat.search(t_clean):
            return True
    
    # Filtrar líneas que son solo números
    if re.match(r'^\d+$', t):
        return True
    
    return False


# ─────────────────────────────────────────────────────────────
# OBTENER HTML (CON MANEJO DE GZIP Y CLOUDFLARE)
# ─────────────────────────────────────────────────────────────
HEADERS_NAVEGADOR = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-MX,es;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

def obtener_html_requests(url: str):
    try:
        r = requests.get(url, headers=HEADERS_NAVEGADOR, timeout=15)
        if r.status_code == 200:
            # Manejar contenido comprimido
            if 'gzip' in r.headers.get('Content-Encoding', ''):
                try:
                    html = gzip.decompress(r.content).decode('utf-8')
                except:
                    html = r.text
            else:
                html = r.text
            
            # Verificar que es HTML válido
            if len(html) > 5000 and ('<html' in html.lower() or '<div' in html.lower()):
                return html
    except Exception as e:
        print(f"Error en requests: {e}")
    return None

def obtener_html_playwright(url: str, sitio: str = "") -> str:
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--no-sandbox',
                '--disable-web-security'
            ]
        )
        context = browser.new_context(
            user_agent=HEADERS_NAVEGADOR["User-Agent"],
            viewport={"width": 1280, "height": 720},
            locale="es-MX",
            extra_http_headers={"Accept-Language": "es-MX,es;q=0.9,en;q=0.8"},
            ignore_https_errors=True
        )
        page = context.new_page()
        
        try:
            Stealth().apply_stealth_sync(page)
        except:
            pass
        
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        
        # Manejo específico para Cloudflare
        if "maehwasup.com" in sitio or "novelasligera.com" in sitio:
            try:
                page.wait_for_function(
                    "document.body.innerText.includes('Checking your browser') === false",
                    timeout=45000
                )
                page.wait_for_timeout(3000)
            except:
                pass
        
        # Esperar a que aparezca el contenido
        try:
            page.wait_for_selector("div.entry-content, article, .post, div.prose, div.texto-capitulo", timeout=15000)
        except:
            pass
        
        # Scroll para lazy loading
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(2000)
        
        html = page.content()
        browser.close()
    return html

def obtener_html(url: str, forzar_playwright: bool = False, sitio: str = "") -> str:
    if forzar_playwright:
        return obtener_html_playwright(url, sitio)
    
    html = obtener_html_requests(url)
    if html and len(html) > 5000 and not "Checking your browser" in html:
        return html
    
    return obtener_html_playwright(url, sitio)


# ─────────────────────────────────────────────────────────────
# EXTRACCION DE TEXTO
# ─────────────────────────────────────────────────────────────
def extraer_modo_parrafos(elemento) -> list:
    parrafos = []
    vistos = set()
    for p in elemento.find_all("p"):
        texto = re.sub(r'\s+', ' ', p.get_text(separator=" ")).strip()
        if texto and texto not in vistos and not es_basura(texto) and len(texto) >= 5:
            vistos.add(texto)
            parrafos.append(texto)
    return parrafos

def extraer_modo_spans(elemento) -> list:
    parrafos = []
    vistos = set()
    linea_actual = []

    def guardar():
        if linea_actual:
            texto = re.sub(r'\s+', ' ', " ".join(linea_actual)).strip()
            if texto and texto not in vistos and not es_basura(texto):
                vistos.add(texto)
                parrafos.append(texto)
            linea_actual.clear()

    for hijo in elemento.descendants:
        nombre = getattr(hijo, 'name', None)
        if isinstance(hijo, NavigableString):
            t = str(hijo).strip()
            if t:
                linea_actual.append(t)
        elif nombre == "br":
            guardar()
        elif nombre in ["div", "blockquote", "hr"]:
            guardar()

    guardar()
    return parrafos

def extraer_modo_generico(elemento) -> list:
    texto_crudo = elemento.get_text(separator="\n")
    parrafos = []
    vistos = set()
    for linea in texto_crudo.splitlines():
        t = re.sub(r'\s+', ' ', linea).strip()
        if t and t not in vistos and not es_basura(t) and len(t) >= 5:
            vistos.add(t)
            parrafos.append(t)
    return parrafos

def limpiar_elemento(elemento):
    """Limpia elementos no deseados del contenido"""
    for sel in [
        "script", "style", "iframe", "noscript", "button",
        "nav", "header", "footer", "aside", "form", "ins",
        ".comments", ".comment-thread", ".share-buttons",
        ".post-share", ".related-posts", ".navigation",
        ".nav-links", ".wp-block-buttons", ".author-box",
        "#disqus_thread", ".comment-list", ".comment-respond",
        ".post-navigation", ".page-navigation", ".pagination",
        ".menu", ".navbar", ".sidebar", ".widget",
        ".breadcrumbs", ".breadcrumb", ".post-meta",
    ]:
        for tag in elemento.select(sel):
            tag.decompose()
    
    # Eliminar elementos <a> que contengan texto de navegación
    for a in elemento.find_all("a"):
        texto = a.get_text(strip=True).lower()
        if texto in ["next", "prev", "previous", "next chapter", "previous chapter", "next page", "previous page", "first", "last"]:
            a.decompose()
        elif re.match(r'^(first|previous|next|last)\s+(chapter|page|part)$', texto, re.IGNORECASE):
            a.decompose()
        elif "||" in texto:
            a.decompose()

def unir_parrafos(parrafos: list) -> str:
    resultado = []
    FIN = re.compile(r'[.!?>\)\]"\']\s*$')
    for texto in parrafos:
        if resultado and not FIN.search(resultado[-1]):
            resultado[-1] = resultado[-1].rstrip() + " " + texto
        else:
            resultado.append(texto)
    return "\n\n".join(resultado)

def procesar_contenido(elemento, modo: str = "auto") -> str:
    limpiar_elemento(elemento)
    if modo == "spans":
        parrafos = extraer_modo_spans(elemento)
    elif modo == "parrafos":
        parrafos = extraer_modo_parrafos(elemento)
    else:
        num_p = len(elemento.find_all("p"))
        num_br = len(elemento.find_all("br"))
        num_span = len(elemento.find_all("span"))
        if num_p >= 3:
            parrafos = extraer_modo_parrafos(elemento)
        elif num_br >= 3 and num_span >= 3:
            parrafos = extraer_modo_spans(elemento)
        else:
            parrafos = extraer_modo_generico(elemento)
    if not parrafos:
        parrafos = extraer_modo_generico(elemento)
    return unir_parrafos(parrafos)


# ─────────────────────────────────────────────────────────────
# DETECCION DE DOMINIO Y CONTENIDO
# ─────────────────────────────────────────────────────────────
def obtener_dominio(url: str) -> str:
    hostname = (urlparse(url).hostname or "").lstrip("www.")
    partes = hostname.split(".")
    if len(partes) >= 2:
        sufijo = partes[-2]
        if sufijo in ("blogspot", "wordpress", "tumblr"):
            return sufijo + ".com"
        return ".".join(partes[-2:])
    return hostname

def get_regla(url: str) -> dict:
    return SITE_RULES.get(obtener_dominio(url), {})

def encontrar_elemento(soup, url: str):
    regla = get_regla(url)
    
    # Selector específico
    if regla.get("selector"):
        for sel in regla["selector"].split(","):
            el = soup.select_one(sel.strip())
            if el and len(el.get_text(strip=True)) > 50:
                return el, regla.get("modo", "auto")
    
    # Selectores genéricos
    for selector in SELECTORES_GENERICOS:
        el = soup.select_one(selector)
        if el and len(el.get_text(strip=True)) > 100:
            return el, "auto"
    
    # Fallback: div con más texto
    mejor, mejor_len = None, 0
    for div in soup.find_all("div"):
        t = div.get_text(strip=True)
        if len(t) > mejor_len and len(t) > 200:
            mejor_len = len(t)
            mejor = div
    
    return mejor, "auto" if mejor else None


# ─────────────────────────────────────────────────────────────
# DETECCION DE CAPITULOS
# ─────────────────────────────────────────────────────────────
WP_DATE_RE = re.compile(r'/\d{4}/\d{2}/\d{2}/.+')

EXCLUIDOS_SEGMENTOS = {
    "privacy", "dmca", "faq", "login", "register", "products",
    "subscriptions", "discord", "search", "unlocker", "genres",
    "novelupdates", "about", "glossary", "contact", "tag",
    "category", "author", "feed", "page", "wp-content",
    "wp-admin", "cdn-cgi", "reclutamiento", "novelas-chinas",
    "novelas-coreanas", "novelas-japonesas", "novelas-18",
}

CAP_TEXTO_RE = re.compile(
    r'(chapter|ch\.?\s*\d|cap[i]tulo|cap\.?\s*\d|episode|ep\.?\s*\d'
    r'|part\s*\d|vol\.?\s*\d|prologue|prologo|preface'
    r'|epilogo|epilogue|side\s*stor|historia\s*lateral'
    r'|extra|\b\d{1,4}\b)',
    re.IGNORECASE
)

def es_capitulo_por_url(href_norm: str, base: str, patron_re=None) -> bool:
    if not href_norm.startswith(base):
        return False
    parte = href_norm[len(base):].strip("/")
    if not parte:
        return False
    if patron_re:
        return bool(patron_re.search(href_norm))
    if WP_DATE_RE.search(href_norm):
        return True
    segmentos = [s for s in parte.lower().split("/") if s]
    if any(s in EXCLUIDOS_SEGMENTOS for s in segmentos):
        return False
    return len(segmentos) >= 2

def es_capitulo_por_texto(texto: str) -> bool:
    return bool(CAP_TEXTO_RE.search(texto))

def base_origen(url: str) -> str:
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}"

def extraer_capitulos_soup(soup, base: str, patron_re=None, sitio: str = ""):
    caps = []
    vistos = set()
    siguiente = None

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        texto = re.sub(r'\s+', ' ', a.get_text()).strip()

        # Filtros básicos
        if not href or not texto or len(texto) > 150:
            continue
        if href.startswith(("#", "javascript:", "mailto:")):
            continue
        if texto.lower() in TEXTOS_NAV_IGNORADOS:
            continue
        if es_basura(texto):
            continue
        
        # FILTRO ESPECIAL PARA BLOGSPOT: ignorar enlaces que parecen comentarios o fechas
        if "blogspot.com" in sitio:
            # Ignorar líneas que son fechas (patrón de mes/día/año)
            if re.match(r'^[A-Za-z]+ \d{1,2},? \d{4}', texto):
                continue
            # Ignorar líneas que son nombres de comentaristas
            if re.match(r'^[A-Za-z\u00C0-\u00FF]+(?: [A-Za-z\u00C0-\u00FF]+)?\s*(?:dijo|said|replied|respondió)', texto, re.IGNORECASE):
                continue
            # Ignorar "Reply", "Delete", etc.
            if texto.lower() in ["reply", "delete", "responder", "eliminar"]:
                continue
            # Ignorar enlaces de comentarios numerados
            if re.match(r'^#\d+$', texto):
                continue
            # Ignorar enlaces que contienen "comments" o "comentarios"
            if "comments" in texto.lower() or "comentarios" in texto.lower():
                continue

        # Construir URL absoluta
        if href.startswith("/"):
            url_abs = base + href
        elif href.startswith("http"):
            url_abs = href
        else:
            continue

        url_norm = url_abs.rstrip("/")
        
        if not url_norm.startswith(base):
            continue

        # Detectar paginación
        if NEXT_PAGE_RE.match(texto) or re.search(r'/page/\d+/?$', url_norm):
            if url_norm not in vistos:
                siguiente = url_abs
            continue

        if url_norm in vistos:
            continue

        # Verificar si es un capítulo
        es_capitulo = False
        if patron_re:
            if es_capitulo_por_url(url_norm, base, patron_re):
                es_capitulo = True
        else:
            if es_capitulo_por_url(url_norm, base, None) or es_capitulo_por_texto(texto):
                es_capitulo = True
        
        # FILTRO ESPECIAL PARA BLOGSPOT: solo aceptar si el texto contiene "Capitulo" o "Ragnarok"
        if "blogspot.com" in sitio:
            if "capitulo" in texto.lower() or "chapter" in texto.lower() or "ragnarok" in texto.lower():
                es_capitulo = True
            else:
                es_capitulo = False

        if es_capitulo:
            caps.append({"titulo": texto[:100], "url": url_abs})
            vistos.add(url_norm)

    return caps, siguiente


# ─────────────────────────────────────────────────────────────
# ENDPOINTS
# ─────────────────────────────────────────────────────────────
@app.get("/")
def inicio():
    return {
        "estado": "activo",
        "version": "3.4.0",
        "sitios_soportados": list(SITE_RULES.keys()),
        "endpoints": {
            "listar_capitulos": "GET /capitulos?url=<url>&paginas=5",
            "leer_capitulo": "GET /leer?url=<url>",
            "debug": "GET /debug?url=<url>",
        }
    }

@app.get("/capitulos")
def listar_capitulos(url: str, paginas: int = 5):
    regla = get_regla(url)
    forzar_pw = regla.get("requiere_playwright", False)
    patron_str = regla.get("cap_patron")
    patron_re = re.compile(patron_str) if patron_str else None
    sitio = obtener_dominio(url)

    base = base_origen(url)
    todos = []
    vistos_global = set()
    pagina_actual = url
    paginas_vistas = set()

    for _ in range(max(1, paginas)):
        if not pagina_actual or pagina_actual in paginas_vistas:
            break
        paginas_vistas.add(pagina_actual)

        try:
            html = obtener_html(pagina_actual, forzar_playwright=forzar_pw, sitio=sitio)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error cargando {pagina_actual}: {e}")

        soup = BeautifulSoup(html, "html.parser")
        caps, siguiente = extraer_capitulos_soup(soup, base, patron_re, sitio=sitio)

        for cap in caps:
            norm = cap["url"].rstrip("/")
            if norm not in vistos_global:
                vistos_global.add(norm)
                todos.append(cap)

        pagina_actual = siguiente

    return {
        "total": len(todos),
        "paginas_recorridas": len(paginas_vistas),
        "capitulos": todos,
    }

@app.get("/leer")
def leer_capitulo(url: str):
    regla = get_regla(url)
    forzar_pw = regla.get("requiere_playwright", False)
    sitio = obtener_dominio(url)

    try:
        html = obtener_html(url, forzar_playwright=forzar_pw, sitio=sitio)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error cargando pagina: {e}")

    soup = BeautifulSoup(html, "html.parser")
    elemento, modo = encontrar_elemento(soup, url)

    if elemento:
        texto = procesar_contenido(elemento, modo)
        if len(texto) > 50:
            return {"url": url, "acceso": "libre", "contenido": texto}

    texto_visible = re.sub(r'\s+', ' ', soup.get_text(separator=" ")).strip()
    return {
        "url": url,
        "acceso": "bloqueado_o_diferente",
        "mensaje": "No se encontró contenido. Puede necesitar pago o estructura no soportada.",
        "contenido_visible": texto_visible[:3000],
    }

@app.get("/debug")
def debug(url: str):
    regla = get_regla(url)
    forzar_pw = regla.get("requiere_playwright", False)
    sitio = obtener_dominio(url)
    
    try:
        html = obtener_html(url, forzar_playwright=forzar_pw, sitio=sitio)
        metodo = "playwright (forzado)" if forzar_pw else "requests/playwright"
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    soup = BeautifulSoup(html, "html.parser")
    base = base_origen(url)
    dominio = obtener_dominio(url)

    elemento, modo = encontrar_elemento(soup, url)
    contenido_preview = ""
    if elemento:
        contenido_preview = elemento.get_text()[:500]

    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        texto = re.sub(r'\s+', ' ', a.get_text()).strip()
        if not href or not texto or len(texto) > 150:
            continue
        if href.startswith("/"):
            href_abs = base + href
        elif href.startswith("http"):
            href_abs = href
        else:
            continue
        links.append({"texto": texto[:80], "url": href_abs})

    return {
        "url": url,
        "dominio_detectado": dominio,
        "regla_aplicada": regla,
        "metodo_usado": metodo,
        "html_bytes": len(html),
        "contenido_encontrado": elemento is not None,
        "modo_usado": modo if elemento else None,
        "preview_contenido": contenido_preview[:500] if contenido_preview else "No encontrado",
        "total_links": len(links),
        "links_muestra": links[:30],
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)