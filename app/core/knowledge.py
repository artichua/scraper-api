import json
import os
import logging
from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict

logger = logging.getLogger("scraper-inteligente")

@dataclass
class SitioAprendido:
    """Almacena lo que el sistema ha aprendido sobre un sitio"""
    dominio: str
    selector_contenido: Optional[str] = None
    selector_capitulos: Optional[str] = None
    patron_url_capitulo: Optional[str] = None
    tipo_paginacion: str = "auto"  # url, boton, infinite, ninguno
    patron_paginacion: Optional[str] = None
    requiere_playwright: bool = False
    confianza: float = 0.0  # 0-1, qué tan seguro está el sistema
    veces_usado: int = 0
    veces_exitoso: int = 0
    ultimo_acceso: Optional[str] = None
    ejemplos_urls: List[str] = None
    errores_comunes: List[str] = None
    
    def __post_init__(self):
        if self.ejemplos_urls is None:
            self.ejemplos_urls = []
        if self.errores_comunes is None:
            self.errores_comunes = []
    
    def actualizar_confianza(self, exito: bool):
        """Actualiza la confianza basado en resultados"""
        self.veces_usado += 1
        if exito:
            self.veces_exitoso += 1
        self.confianza = self.veces_exitoso / self.veces_usado if self.veces_usado > 0 else 0
        self.ultimo_acceso = datetime.now().isoformat()

class BaseConocimiento:
    """Almacena y recupera lo aprendido sobre sitios web"""
    
    def __init__(self, archivo: str = "conocimiento_scraper.json"):
        self.archivo = archivo
        self.sitios: Dict[str, SitioAprendido] = {}
        self.cargar()
    
    def cargar(self):
        """Carga el conocimiento guardado"""
        if os.path.exists(self.archivo):
            try:
                with open(self.archivo, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for dominio, datos in data.items():
                        self.sitios[dominio] = SitioAprendido(**datos)
                logger.info(f"Cargado conocimiento para {len(self.sitios)} sitios")
            except Exception as e:
                logger.error(f"Error cargando conocimiento: {e}")
    
    def guardar(self):
        """Guarda el conocimiento aprendido"""
        try:
            data = {}
            for dominio, sitio in self.sitios.items():
                data[dominio] = asdict(sitio)
            with open(self.archivo, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            logger.info(f"Guardado conocimiento para {len(self.sitios)} sitios")
        except Exception as e:
            logger.error(f"Error guardando conocimiento: {e}")
    
    def obtener(self, dominio: str) -> Optional[SitioAprendido]:
        """Obtiene lo aprendido para un dominio"""
        return self.sitios.get(dominio)
    
    def guardar_aprendizaje(self, dominio: str, aprendizaje: SitioAprendido):
        """Guarda lo aprendido para un dominio"""
        self.sitios[dominio] = aprendizaje
        self.guardar()

# Instancia global de la base de conocimiento
conocimiento = BaseConocimiento()
