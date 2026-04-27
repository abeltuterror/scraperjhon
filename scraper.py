from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import csv
from datetime import datetime
import time

URL = "https://app.servir.gob.pe/DifusionOfertasExterno/faces/consultas/ofertas_laborales.xhtml"

def extraer_detalles_vacante(soup_detalle):
    """Extrae dinámicamente toda la información del cuadro de detalle."""
    datos = {}
    contenedor = soup_detalle.find("div", {"class": "cuadro-seccion"})
    
    if not contenedor:
        return datos

    # 1. Procesar elementos estándar (divs con clase row box-mb)
    for fila in contenedor.find_all("div", {"class": "row box-mb"}):
        sub_titulo = fila.find("span", {"class": "sub-titulo"})
        if not sub_titulo: sub_titulo = fila.find("p", {"class": "sub-titulo"})
        
        detalle_sp = fila.find("span", {"class": "detalle-sp"})
        
        if sub_titulo and detalle_sp:
            clave = sub_titulo.get_text(strip=True).replace(":", "").strip()
            valor = detalle_sp.get_text(strip=True).strip()
            datos[clave] = valor

    # 2. Procesar la lista de requerimientos (ul/li)
    lista_req = contenedor.find("ul")
    if lista_req:
        for li in lista_req.find_all("li"):
            label = li.find("span", {"class": "sub-titulo-2"})
            valor = li.find("span", {"class": "detalle-sp"})
            if label and valor:
                clave = label.get_text(strip=True).replace(":", "").strip()
                contenido = valor.get_text(strip=True).strip()
                datos[clave] = contenido
                
    return datos

def run_scraper():
    todas_vacantes = []
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        page.goto(URL)
        page.wait_for_load_state("networkidle")
        
        sin_mas_vacantes = False
        while not sin_mas_vacantes:
            # Parsear la lista principal
            soup = BeautifulSoup(page.content(), "lxml")
            divs_vacantes = soup.find_all("div", {"class": "cuadro-vacantes"})
            
            # Necesitamos los elementos interactivos para hacer click
            botones = page.locator("span.ui-button-text.ui-c:has-text('¡Ver más!')")
            num_botones = botones.count()
            
            print(f"📄 Procesando {num_botones} vacantes en esta página...")

            for i in range(num_botones):
                # Recargar elementos cada vez para evitar "Stale Element Reference"
                botones_actualizados = page.locator("span.ui-button-text.ui-c:has-text('¡Ver más!')")
                botones_actualizados.nth(i).click()
                page.wait_for_selector(".cuadro-seccion") # Esperar que cargue el detalle
                
                # Extraer info
                soup_detalle = BeautifulSoup(page.content(), "lxml")
                info = extraer_detalles_vacante(soup_detalle)
                todas_vacantes.append(info)
                
                print(f"  ✅ Procesada: {info.get('NÚMERO DE CONVOCATORIA', 'N/A')}")
                
                # Retroceder
                page.locator("button:has-text('Volver')").click()
                page.wait_for_load_state("networkidle")
            
            # Paginación
            next_btn = page.locator("button:has-text('Siguiente')")
            if next_btn.is_visible():
                next_btn.click()
                page.wait_for_load_state("networkidle")
                time.sleep(2)
            else:
                sin_mas_vacantes = True
        
        browser.close()
    return todas_vacantes

# Ejecución y Guardado
vacantes = run_scraper()

if vacantes:
    # Identificar todas las columnas posibles (para evitar errores en CSV si una fila tiene más campos que otra)
    keys = set().union(*(d.keys() for d in vacantes))
    
    filename = f"vacantes_servir_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=sorted(list(keys)))
        writer.writeheader()
        writer.writerows(vacantes)
    print(f"\n🚀 Extracción finalizada. {len(vacantes)} registros guardados en {filename}")