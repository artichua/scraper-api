from fastapi import FastAPI, HTTPException
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth
from bs4 import BeautifulSoup, NavigableString
import time
import re
import requests
from urllib.parse import urlparse

app = FastAPI(
    title="Scraper API",
    description="API universal para extraer capítulos de sitios de novelas",
    version="3.0.0"
)

# ─────────────────────────────────────────────────────────────
# REGLAS POR DOMINIO
# ─────────────────────────────────────────────────────────────
SITE_RULES = {
    "skydemonorder.com": {
        "selector": "div.prose",
        "modo": "parrafos",
        "cap_patron": r"/projects/.+/.+",
    },
    "novelasligera.com": {
        "selector": "div.entry-content, div.texto-capitulo, div#content article",
        "modo": "parrafos",
        "cap_patron": r"/novela/.+/.+",
    },
    "wuxiaworld.com": {
        "selector": "div.chapter-content, div#chapter-content",
        "modo": "parrafos",
        "cap_patron": r"/novel/.+/chapter-.+",
        "requiere_playwright": True,
    },
    "maehwasup.com": {
        "selector": "div.entry-content",
        "modo": "parrafos",
        "cap_patron": r"/\d{4}/\d{2}/\d{2}/.+",
        "requiere_playwright": True,   # bloquea requests, necesita browser real
    },
    "blogspot.com": {
        "selector": "div.post-body",
        "modo": "spans",
    },
    "wordpress.com": {
        "selector": "div.entry-content",
        "modo": "parrafos",
        "cap_patron": r"/\d{4}/\d{2}/\d{2}/.+",
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
# PATRONES DE BASURA
# ─────────────────────────────────────────────────────────────
BASURA_EXACTA = {
    "anterior", "siguiente", "indice", "index",
    "next", "prev", "previous", "next chapter", "previous chapter",
    "table of contents", "compartir", "share", "tweet",
    "pagina anterior", "pagina siguiente",
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
    r"^\d+\s*$",
    r"skydark\s*:", r"traductor\s*:",
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
    t = texto.strip()
    if not t:
        return True
    if t.lower() in BASURA_EXACTA:
        return True
    if NAV_RE.match(t):
        return True
    for pat in BASURA_RE:
        if pat.search(t):
            return True
    if len(t) < 80:
        lower = t.lower()
        for pal in ("anterior", "siguiente", "pagina anterior", "pagina siguiente"):
            if lower == pal:
                return True
    return False


# ─────────────────────────────────────────────────────────────
# OBTENER HTML
# ─────────────────────────────────────────────────────────────
HEADERS_NAVEGADOR = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-MX,es;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}


def obtener_html_requests(url: str):
    try:
        r = requests.get(url, headers=HEADERS_NAVEGADOR, timeout=15)
        if r.status_code == 200 and len(r.text) > 5000:
            return r.text
    except Exception:
        pass
    return None


def obtener_html_playwright(url: str) -> str:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=HEADERS_NAVEGADOR["User-Agent"],
            viewport={"width": 1280, "height": 720},
            locale="es-MX",
            extra_http_headers={"Accept-Language": "es-MX,es;q=0.9,en;q=0.8"},
        )
        page = context.new_page()
        try:
            Stealth().apply_stealth_sync(page)
        except Exception:
            pass
        page.goto(url, wait_until="networkidle", timeout=35000)
        page.wait_for_timeout(2500)
        html = page.content()
        browser.close()
    return html


def obtener_html(url: str, forzar_playwright: bool = False) -> str:
    if not forzar_playwright:
        html = obtener_html_requests(url)
        if html:
            return html
    return obtener_html_playwright(url)


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
    for sel in [
        "script", "style", "iframe", "noscript", "button",
        "nav", "header", "footer", "aside", "form", "ins",
        ".comments", ".comment-thread", ".share-buttons",
        ".post-share", ".related-posts", ".navigation",
        ".nav-links", ".wp-block-buttons", ".author-box",
        "#disqus_thread",
    ]:
        for tag in elemento.select(sel):
            tag.decompose()


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
    if regla.get("selector"):
        for sel in regla["selector"].split(","):
            el = soup.select_one(sel.strip())
            if el and len(el.get_text(strip=True)) > 100:
                return el, regla.get("modo", "auto")

    for selector in SELECTORES_GENERICOS:
        el = soup.select_one(selector)
        if el and len(el.get_text(strip=True)) > 200:
            return el, "auto"

    mejor, mejor_len = None, 0
    for div in soup.find_all("div"):
        t = div.get_text(strip=True)
        if 200 < len(t) < 200000 and len(t) > mejor_len:
            mejor_len = len(t)
            mejor = div
    return mejor, "auto"


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
    "novelas-chinas", "novela",  # "novela" solo es el índice raíz
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
    # Si hay patron especifico, es el UNICO criterio de URL para ese dominio.
    # Si no matchea, rechazar — evita falsos positivos como /announcements/...
    if patron_re:
        return bool(patron_re.search(href_norm))
    # WordPress con fecha
    if WP_DATE_RE.search(href_norm):
        return True
    # Generico: multiples segmentos sin palabras excluidas
    segmentos = [s for s in parte.lower().split("/") if s]
    if any(s in EXCLUIDOS_SEGMENTOS for s in segmentos):
        return False
    return len(segmentos) >= 2


def es_capitulo_por_texto(texto: str) -> bool:
    return bool(CAP_TEXTO_RE.search(texto))


def base_origen(url: str) -> str:
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}"


def extraer_capitulos_soup(soup, base: str, patron_re=None):
    caps = []
    vistos = set()
    siguiente = None

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        texto = re.sub(r'\s+', ' ', a.get_text()).strip()

        if not href or not texto or len(texto) > 150:
            continue
        if href.startswith(("#", "javascript:", "mailto:")):
            continue
        if texto.lower() in TEXTOS_NAV_IGNORADOS:
            continue

        if href.startswith("/"):
            url_abs = base + href
        elif href.startswith("http"):
            url_abs = href
        else:
            continue

        url_norm = url_abs.rstrip("/")

        if not url_norm.startswith(base):
            continue

        if NEXT_PAGE_RE.match(texto) or re.search(r'/page/\d+/?$', url_norm):
            if url_norm not in vistos:
                siguiente = url_abs
            continue

        if url_norm in vistos:
            continue

        # Si el dominio tiene patron especifico, la URL es el criterio definitivo.
        # El texto solo se usa como criterio cuando NO hay patron (deteccion generica).
        if patron_re:
            if es_capitulo_por_url(url_norm, base, patron_re):
                caps.append({"titulo": texto, "url": url_abs})
                vistos.add(url_norm)
        else:
            if es_capitulo_por_url(url_norm, base, None) or es_capitulo_por_texto(texto):
                caps.append({"titulo": texto, "url": url_abs})
                vistos.add(url_norm)

    return caps, siguiente


# ─────────────────────────────────────────────────────────────
# ENDPOINTS
# ─────────────────────────────────────────────────────────────
@app.get("/")
def inicio():
    return {
        "estado": "activo",
        "version": "3.0.0",
        "sitios_con_soporte_explicito": list(SITE_RULES.keys()),
        "endpoints": {
            "listar_capitulos": "GET /capitulos?url=<url>&paginas=5",
            "leer_capitulo":    "GET /leer?url=<url>",
            "debug":            "GET /debug?url=<url>",
            "docs":             "GET /docs",
        }
    }


@app.get("/capitulos")
def listar_capitulos(url: str, paginas: int = 5):
    """
    Lista todos los capitulos de una novela.
    paginas = cuantas paginas de indice recorrer (default 5).
    """
    regla = get_regla(url)
    forzar_pw = regla.get("requiere_playwright", False)
    patron_str = regla.get("cap_patron")
    patron_re = re.compile(patron_str) if patron_str else None

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
            html = obtener_html(pagina_actual, forzar_playwright=forzar_pw)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error cargando {pagina_actual}: {e}")

        soup = BeautifulSoup(html, "html.parser")
        caps, siguiente = extraer_capitulos_soup(soup, base, patron_re)

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
    """
    Lee y extrae el texto limpio de un capitulo.
    Detecta automaticamente la estructura del sitio.
    """
    regla = get_regla(url)
    forzar_pw = regla.get("requiere_playwright", False)

    try:
        html = obtener_html(url, forzar_playwright=forzar_pw)
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
        "mensaje": "No se encontro contenido. Puede necesitar pago o estructura no soportada.",
        "contenido_visible": texto_visible[:3000],
    }


@app.get("/debug")
def debug(url: str):
    """
    Diagnostico: muestra metodo HTML usado, bytes recibidos y links encontrados.
    Util para entender por que un sitio da 0 resultados.
    """
    html_req = obtener_html_requests(url)
    metodo = "requests" if html_req else "playwright"
    try:
        html = html_req or obtener_html_playwright(url)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    soup = BeautifulSoup(html, "html.parser")
    base = base_origen(url)
    dominio = obtener_dominio(url)
    regla = get_regla(url)

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
        "metodo_html": metodo,
        "html_bytes": len(html),
        "total_links_encontrados": len(links),
        "links_muestra": links[:40],
    }