from fastapi import FastAPI, HTTPException
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth
from bs4 import BeautifulSoup
import time
import re

app = FastAPI(
    title="Scraper API",
    description="API para extraer capítulos y contenido de sitios de novelas",
    version="1.0.0"
)

# ─────────────────────────────────────────────
# Obtener HTML sin abrir ventana visible
# ─────────────────────────────────────────────
def obtener_html(url: str) -> str:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 720},
            locale="en-US",
        )
        page = context.new_page()
        Stealth().apply_stealth_sync(page)
        page.goto(url, wait_until="networkidle")
        time.sleep(3)
        html = page.content()
        browser.close()
    return html

# ─────────────────────────────────────────────
# Limpiar contenido del capítulo
# ─────────────────────────────────────────────
def limpiar_contenido(soup_elemento) -> str:
    tags_basura = [
        "script", "style", "nav", "header", "footer",
        "aside", "form", "button", "iframe", "noscript",
        "[class*='ad']", "[class*='banner']", "[class*='popup']",
        "[class*='comment']", "[class*='social']", "[class*='share']",
        "[class*='related']", "[class*='recommend']", "[class*='sidebar']",
        "[id*='ad']", "[id*='banner']", "[id*='comment']",
    ]
    for selector in tags_basura:
        for tag in soup_elemento.select(selector):
            tag.decompose()

    parrafos = []
    for p in soup_elemento.find_all(["p", "div"], recursive=True):
        texto = p.get_text(separator=" ").strip()
        if len(texto) < 10:
            continue
        palabras_basura = [
            "advertisement", "subscribe", "patreon", "donate",
            "click here", "sponsored", "follow us", "join our",
            "discord", "novel updates", "read more at", "translated by",
            "support us", "buy coins", "unlock", "purchase"
        ]
        if any(w in texto.lower() for w in palabras_basura):
            continue
        parrafos.append(texto)

    vistos = set()
    resultado = []
    for p in parrafos:
        if p not in vistos:
            vistos.add(p)
            resultado.append(p)

    return "\n\n".join(resultado)

# ─────────────────────────────────────────────
# Detectar capítulo por URL
# ─────────────────────────────────────────────
def es_capitulo_por_url(href: str, base_url: str) -> bool:
    if not href.startswith(base_url):
        return False
    parte_extra = href[len(base_url):].strip("/")
    if not parte_extra:
        return False
    excluidos = [
        "privacy", "dmca", "faq", "login", "register",
        "products", "subscriptions", "discord", "#", "search",
        "unlocker", "genres", "bl", "projects?", "novelupdates"
    ]
    return not any(x in parte_extra for x in excluidos)

# ─────────────────────────────────────────────
# Detectar capítulo por texto
# ─────────────────────────────────────────────
def es_capitulo_por_texto(texto: str) -> bool:
    patron = re.compile(
        r'(chapter|ch\.|capítulo|cap\.|episode|ep\.|part|vol|prologue|preface|\d+)',
        re.IGNORECASE
    )
    return bool(patron.search(texto))

# ─────────────────────────────────────────────
# GET /
# ─────────────────────────────────────────────
@app.get("/", tags=["Info"])
def inicio():
    return {
        "estado": "activo",
        "endpoints": {
            "capitulos": "GET /capitulos?url=<url>",
            "leer": "GET /leer?url=<url>",
            "docs": "GET /docs"
        }
    }

# ─────────────────────────────────────────────
# GET /capitulos?url=<url>
# ─────────────────────────────────────────────
@app.get("/capitulos", tags=["Scraping"])
def listar_capitulos(url: str):
    """
    Extrae la lista de capítulos de cualquier sitio de novelas.
    """
    try:
        html = obtener_html(url)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al cargar la página: {str(e)}")

    soup = BeautifulSoup(html, "html.parser")
    base = "/".join(url.split("/")[:3])

    titulos_ignorados = [
        "start reading", "read now", "start", "leer",
        "home", "login", "register", "privacy", "dmca", "faq"
    ]

    capitulos = []
    vistos = set()

    for enlace in soup.find_all("a", href=True):
        href = enlace["href"]
        texto = enlace.text.strip()

        if not href or not texto:
            continue

        if texto.lower() in titulos_ignorados:
            continue

        if href.startswith("/"):
            url_completa = base + href
        elif href.startswith("http"):
            url_completa = href
        else:
            continue

        if url_completa in vistos:
            continue

        if es_capitulo_por_url(url_completa, url):
            capitulos.append({"titulo": texto, "url": url_completa})
            vistos.add(url_completa)
            continue

        if es_capitulo_por_texto(texto):
            capitulos.append({"titulo": texto, "url": url_completa})
            vistos.add(url_completa)

    return {"total": len(capitulos), "capitulos": capitulos}

# ─────────────────────────────────────────────
# GET /leer?url=<url>
# ─────────────────────────────────────────────
@app.get("/leer", tags=["Scraping"])
def leer_capitulo(url: str):
    """
    Extrae el contenido limpio de un capítulo.
    Filtra anuncios y elementos que no pertenecen al capítulo.
    Si está bloqueado, devuelve el aviso de la página.
    """
    try:
        html = obtener_html(url)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al cargar la página: {str(e)}")

    soup = BeautifulSoup(html, "html.parser")

    selectores = [
        "div.prose",
        "div.chapter-content",
        "div.entry-content",
        "div.post-content",
        "div.content-area",
        "article",
        "main",
    ]

    contenido_elemento = None
    for selector in selectores:
        elemento = soup.select_one(selector)
        if elemento:
            contenido_elemento = elemento
            break

    if contenido_elemento:
        texto_limpio = limpiar_contenido(contenido_elemento)
        if len(texto_limpio) > 100:
            return {
                "url": url,
                "acceso": "libre",
                "contenido": texto_limpio
            }

    texto_visible = soup.get_text(separator=" ").strip()
    texto_visible = re.sub(r'\s+', ' ', texto_visible)
    return {
        "url": url,
        "acceso": "bloqueado_o_diferente",
        "mensaje": "No se encontró contenido principal. Puede requerir pago o tener estructura diferente.",
        "contenido_visible": texto_visible[:2000]
    }