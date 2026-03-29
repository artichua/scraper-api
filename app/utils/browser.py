import requests
import gzip
import logging
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

logger = logging.getLogger("scraper-inteligente")

HEADERS_NAVEGADOR = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-MX,es;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}

try:
    from playwright_stealth import stealth_sync
    def apply_stealth(page): stealth_sync(page)
except ImportError:
    class Stealth:
        def apply_stealth_sync(self, page): pass
    def apply_stealth(page): Stealth().apply_stealth_sync(page)

def obtener_html_requests(url: str):
    try:
        r = requests.get(url, headers=HEADERS_NAVEGADOR, timeout=15)
        if r.status_code == 200:
            if 'gzip' in r.headers.get('Content-Encoding', ''):
                try:
                    html = gzip.decompress(r.content).decode('utf-8')
                except:
                    html = r.text
            else:
                html = r.text
            if len(html) > 5000 and ('<html' in html.lower() or '<div' in html.lower()):
                # Check for cloudflare
                if "Just a moment..." in html or "Checking your browser" in html:
                    return None
                return html
    except:
        pass
    return None

def obtener_html_playwright(url: str, sitio: str = "") -> str:
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=['--disable-blink-features=AutomationControlled', '--no-sandbox']
        )
        context = browser.new_context(
            user_agent=HEADERS_NAVEGADOR["User-Agent"],
            viewport={"width": 1280, "height": 720},
            locale="es-MX",
            ignore_https_errors=True
        )
        page = context.new_page()
        try:
            apply_stealth(page)
        except Exception as e:
            logger.warning(f"Stealth warning: {e}")
        
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        
        # Enhanced Cloudflare detection and wait (e.g. maehwasup, skydemonorder)
        if "skydemonorder.com" in sitio or "maehwasup.com" in sitio or "novelasligera.com" in sitio:
            try:
                # Wait for Cloudflare turnstile if present
                logger.info(f"Esperando bypass de Cloudflare para {sitio}...")
                page.wait_for_function(
                    "document.body.innerText.includes('Checking your browser') === false && document.body.innerText.includes('Just a moment') === false",
                    timeout=45000
                )
                page.wait_for_timeout(3000)
            except Exception as e:
                logger.warning(f"Timeout esperando Cloudflare en {url}: {e}")
        
        try:
            page.wait_for_selector("div.entry-content, article, .post, div.prose, #chapter-content", timeout=15000)
        except:
            pass
        
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(2000)
        
        html = page.content()
        browser.close()
    return html

def obtener_html(url: str, forzar_playwright: bool = False, sitio: str = "") -> str:
    if forzar_playwright:
        return obtener_html_playwright(url, sitio)
    
    html = obtener_html_requests(url)
    if html and len(html) > 5000 and "Checking your browser" not in html and "Just a moment" not in html:
        return html
        
    return obtener_html_playwright(url, sitio)
