from fastapi import APIRouter, HTTPException, Query
from typing import Optional

from app.core.knowledge import conocimiento
from app.services.scraper_service import scraper_inteligente, extraer_texto_dinamico
from app.utils.browser import obtener_html
from app.utils.text_parser import obtener_dominio
from bs4 import BeautifulSoup

router = APIRouter()

# Algunas reglas fallback como en la v anterior (opcionales)
SITE_RULES = {}

@router.get("/")
def inicio():
    return {
        "estado": "activo",
        "version": "6.0.0-clean",
        "tipo": "scraper inteligente (clean architecture)",
        "sitios_aprendidos": len(conocimiento.sitios),
        "endpoints": {
            "listar_capitulos_inteligente": "GET /capitulos/inteligente?url=<url>&extraer_texto=true",
            "conocimiento": "GET /conocimiento",
            "leer_capitulo": "GET /leer?url=<url>",
            "debug": "GET /debug?url=<url>",
        }
    }

@router.get("/capitulos/inteligente")
def listar_capitulos_inteligente(
    url: str, 
    max_paginas: int = 10, 
    extraer_texto: bool = Query(False, description="Extraer texto de los primeros capítulos"), 
    max_textos: int = Query(3, description="Máximo de capítulos a extraer texto completo")
):
    try:
        resultado = scraper_inteligente.extraer_capitulos(url, max_paginas, extraer_texto, max_textos)
        return resultado
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")

@router.get("/conocimiento")
def ver_conocimiento():
    return {
        "total_sitios_aprendidos": len(conocimiento.sitios),
        "sitios": [
            {
                "dominio": s.dominio,
                "selector_contenido": s.selector_contenido,
                "patron_capitulo": s.patron_url_capitulo,
                "tipo_paginacion": s.tipo_paginacion,
                "requiere_js": s.requiere_playwright,
                "confianza": s.confianza,
                "veces_usado": s.veces_usado,
                "veces_exitoso": s.veces_exitoso,
                "ejemplos": s.ejemplos_urls[:3]
            }
            for s in conocimiento.sitios.values()
        ]
    }

@router.get("/leer")
def leer_capitulo(url: str):
    sitio = obtener_dominio(url)
    regla = SITE_RULES.get(sitio, {})
    forzar_pw = regla.get("requiere_playwright", False)
    
    res = extraer_texto_dinamico(url, sitio, forzar_pw)
    if res.get("acceso") != "libre":
        res["mensaje"] = "Posible fallo en la extracción inteligente o bloqueo detectado."
    return res

@router.get("/debug")
def debug(url: str):
    sitio = obtener_dominio(url)
    regla = SITE_RULES.get(sitio, {})
    
    try:
        html = obtener_html(url, forzar_playwright=regla.get("requiere_playwright", False), sitio=sitio)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
        
    if not html:
        return {"error": "HTML bloqueado o nulo"}
    
    soup = BeautifulSoup(html, "html.parser")
    
    return {
        "url": url,
        "dominio": sitio,
        "tiene_regla": bool(regla),
        "html_bytes": len(html),
        "titulo": soup.title.string if soup.title else None,
        "primeros_500_caracteres": html[:500]
    }
