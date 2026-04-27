from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import csv
from datetime import datetime
import time
from collections import defaultdict

# URL base
URL = "https://app.servir.gob.pe/DifusionOfertasExterno/faces/consultas/ofertas_laborales.xhtml"

# -------------------------
# Función para retroceder (volver atrás)
# -------------------------
def retroceder(page):
    """Retrocede/vuelve atrás después de ver los detalles"""
    try:
        XPath_retroceder = "/html/body/div[2]/div[2]/div[2]/div[1]/div/ol/li[3]/form/button"
        button_retroceder = page.locator(f"xpath={XPath_retroceder}")
        button_retroceder.click()
        page.wait_for_load_state("networkidle", timeout=5000)
        time.sleep(1)
        return True
    except Exception as e:
        print(f"   ⚠️ Error al retroceder: {str(e)}")
        return False

# -------------------------
# Función para extraer TODOS los pares clave-valor de la vista detallada
# -------------------------
def extraer_todos_los_campos(page):
    """
    Extrae dinámicamente cualquier pareja (clave: valor) que aparezca
    en el contenedor de requerimientos de la página de detalle.
    Retorna un diccionario con todos los campos encontrados.
    """
    campos = {}
    
    # Esperar a que cargue el contenido de los detalles (opcional)
    try:
        page.wait_for_selector("span.sub-titulo-2, span.sub-titulo", timeout=5000)
    except:
        return campos
    
    # Obtener el HTML del contenedor principal de requerimientos (XPath original)
    xpath_contenedor = "/html/body/div[2]/div[2]/div[2]/form/div/div/div/div[1]/div[2]/div/div[2]/div"
    try:
        contenedor = page.locator(f"xpath={xpath_contenedor}")
        if contenedor.count():
            html_contenedor = contenedor.first.inner_html()
            soup = BeautifulSoup(html_contenedor, "lxml")
            
            # 1. Buscar todos los <li> con <span class="sub-titulo-2"> y <span class="detalle-sp">
            for li in soup.find_all("li"):
                sub = li.find("span", class_="sub-titulo-2")
                det = li.find("span", class_="detalle-sp")
                if sub and det:
                    clave = sub.get_text(strip=True).rstrip(":")
                    valor = det.get_text(strip=True)
                    campos[clave] = valor
            
            # 2. Buscar filas sueltas con <span class="sub-titulo"> y <span class="detalle-sp">
            #    (ejemplo: DETALLE, CANTIDAD DE VACANTES, etc., aunque estos ya están en la tarjeta,
            #     pero pueden aparecer también aquí)
            for div_row in soup.find_all("div", class_="row"):
                sub = div_row.find("span", class_="sub-titulo")
                det = div_row.find("span", class_="detalle-sp")
                if sub and det:
                    clave = sub.get_text(strip=True).rstrip(":")
                    # Si el detalle contiene un <a>, extraer texto y URL
                    enlace = det.find("a")
                    if enlace:
                        valor = {
                            "texto": enlace.get_text(strip=True),
                            "url": enlace.get("href")
                        }
                    else:
                        valor = det.get_text(strip=True)
                    campos[clave] = valor
            
            # 3. Extraer la sección adicional del div[3]/div (la que te faltaba)
            #    Buscamos dentro del contenedor el tercer div hijo y su subdiv
            div_extra = soup.find_all("div", recursive=False)
            if len(div_extra) >= 3:
                tercer_div = div_extra[2]  # índice 2 = tercer div hijo
                subdiv_extra = tercer_div.find("div")
                if subdiv_extra:
                    contenido_extra = subdiv_extra.get_text(strip=True)
                    if contenido_extra:
                        campos["SECCION_ADICIONAL"] = contenido_extra
    except Exception as e:
        print(f"      ⚠️ Error extrayendo campos dinámicos: {e}")
    
    return campos

# -------------------------
# MAIN: Usar Playwright
# -------------------------
todas_vacantes = []

print("🔄 Iniciando navegador con Playwright...")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False, args=["--disable-blink-features=AutomationControlled"])
    page = browser.new_page()
    
    print(f"📍 Navegando a {URL}...")
    page.goto(URL)
    page.wait_for_load_state("networkidle")
    time.sleep(2)
    
    pagina = 0
    sin_mas_vacantes = False
    max_paginas = 3  # Ajusta según necesites
    
    while not sin_mas_vacantes and pagina < max_paginas:
        print(f"\n📄 Página {pagina}...")
        
        try:
            page.wait_for_load_state("networkidle")
            time.sleep(1)
            
            # Obtener el HTML actual para contar vacantes
            content = page.content()
            soup = BeautifulSoup(content, "lxml")
            vacantes_divs = soup.find_all("div", {"class": "cuadro-vacantes"})
            
            if not vacantes_divs:
                print(f"   ⚠️ No hay más vacantes en página {pagina}, finalizando...")
                sin_mas_vacantes = True
                continue
            
            print(f"   ✓ Se encontraron {len(vacantes_divs)} vacantes en página {pagina}")
            
            # Obtener todos los botones "¡Ver más!"
            botones_ver_mas = page.locator("span.ui-button-text.ui-c:has-text('¡Ver más!')").all()
            print(f"   ✓ Se encontraron {len(botones_ver_mas)} botones '¡Ver más!'")
            
            vacantes_nuevas_en_pagina = 0
            
            # Procesar cada vacante
            for idx in range(len(vacantes_divs)):
                print(f"   🔹 Procesando vacante {idx + 1}/{len(vacantes_divs)}...")
                
                # --- Extraer información básica del cuadro (sin clic) ---
                vacante_div = vacantes_divs[idx]
                
                titulo_label = vacante_div.find("div", {"class": "titulo-vacante"})
                titulo = titulo_label.find("label").text.strip() if titulo_label else "N/A"
                
                nombre_entidad_div = vacante_div.find("div", {"class": "nombre-entidad"})
                if nombre_entidad_div:
                    span = nombre_entidad_div.find("span", {"class": "detalle-sp"})
                    entidad = span.text.strip() if span else "N/A"
                else:
                    entidad = "N/A"
                
                datos = {}
                filas_datos = vacante_div.find_all("div", {"class": "row box-mb"})
                for fila in filas_datos:
                    sub_titulo = fila.find("span", {"class": "sub-titulo"})
                    detalle = fila.find("span", {"class": "detalle-sp"})
                    if sub_titulo and detalle:
                        clave = sub_titulo.text.strip().rstrip(":")
                        clave = " ".join(clave.split())
                        valor = detalle.text.strip()
                        valor = " ".join(valor.split())
                        datos[clave] = valor
                
                vacante_info = {
                    "Título": titulo,
                    "Entidad": entidad,
                    "Ubicación": datos.get("Ubicación", "N/A"),
                    "Convocatoria": datos.get("Número de Convocatoria", "N/A"),
                    "Vacantes": datos.get("Cantidad de Vacantes", "N/A"),
                    "Remuneración": datos.get("Remuneración", "N/A"),
                    "Fecha Inicio": datos.get("Fecha Inicio de Publicación", "N/A"),
                    "Fecha Fin": datos.get("Fecha Fin de Publicación", "N/A"),
                }
                
                # --- Hacer clic en "¡Ver más!" y extraer todos los campos dinámicos ---
                try:
                    botones_actualizados = page.locator("span.ui-button-text.ui-c:has-text('¡Ver más!')").all()
                    
                    if idx < len(botones_actualizados):
                        boton = botones_actualizados[idx]
                        print(f"      👆 Haciendo click en el botón '¡Ver más!'...")
                        boton.click()
                        page.wait_for_load_state("networkidle", timeout=5000)
                        time.sleep(1)
                        
                        # Extraer TODOS los campos de la vista detallada (dinámicos)
                        campos_detalle = extraer_todos_los_campos(page)
                        
                        # Agregar esos campos al diccionario de la vacante
                        # (evitamos sobrescribir los campos básicos ya obtenidos)
                        for clave, valor in campos_detalle.items():
                            if clave not in vacante_info:  # no sobrescribir Título, Entidad, etc.
                                vacante_info[clave] = valor
                        
                        # También extraemos Título_Aviso e Institución_Aviso (XPaths originales)
                        xpath_titulo = "/html/body/div[2]/div[2]/div[2]/form/div/div/div/div[1]/div[1]/div/div[2]/div/span[1]"
                        xpath_institucion = "/html/body/div[2]/div[2]/div[2]/form/div/div/div/div[1]/div[1]/div/div[2]/div/span[2]"
                        
                        try:
                            elem_titulo = page.locator(f"xpath={xpath_titulo}")
                            if elem_titulo.is_visible():
                                vacante_info['Titulo_Aviso'] = elem_titulo.text_content().strip()
                            else:
                                vacante_info['Titulo_Aviso'] = "N/A"
                        except:
                            vacante_info['Titulo_Aviso'] = "N/A"
                        
                        try:
                            elem_institucion = page.locator(f"xpath={xpath_institucion}")
                            if elem_institucion.is_visible():
                                vacante_info['Institucion_Aviso'] = elem_institucion.text_content().strip()
                            else:
                                vacante_info['Institucion_Aviso'] = "N/A"
                        except:
                            vacante_info['Institucion_Aviso'] = "N/A"
                        
                        print(f"      📝 Campos extraídos: {list(campos_detalle.keys())}")
                        
                        # Retroceder
                        print(f"      ↩️  Retrocediendo...")
                        retroceder(page)
                        print(f"      ✓ Retrocedido")
                    else:
                        print(f"      ⚠️ No se encontró botón para este índice")
                        # Rellenar campos por defecto
                        vacante_info['Titulo_Aviso'] = "N/A"
                        vacante_info['Institucion_Aviso'] = "N/A"
                
                except Exception as e:
                    print(f"      ⚠️ Error en click/extracción: {str(e)}")
                    vacante_info['Titulo_Aviso'] = "N/A"
                    vacante_info['Institucion_Aviso'] = "N/A"
                    try:
                        retroceder(page)
                    except:
                        pass
                
                todas_vacantes.append(vacante_info)
                vacantes_nuevas_en_pagina += 1
            
            # Navegar a siguiente página si hay más
            if vacantes_nuevas_en_pagina == 0:
                sin_mas_vacantes = True
            else:
                try:
                    print(f"\n   ➡️  Buscando botón 'Siguiente'...")
                    next_button = page.locator("button:has-text('Siguiente')")
                    if next_button.is_visible():
                        next_button.click()
                        page.wait_for_load_state("networkidle")
                        time.sleep(2)
                        pagina += 1
                        print(f"   ✓ Pasando a página {pagina}...")
                    else:
                        print(f"   ⚠️ No se encontró botón 'Siguiente', finalizando...")
                        sin_mas_vacantes = True
                except Exception as e:
                    print(f"   ⚠️ Error al buscar botón siguiente: {str(e)}")
                    sin_mas_vacantes = True
        
        except Exception as e:
            print(f"   ❌ Error en página {pagina}: {str(e)}")
            import traceback
            traceback.print_exc()
            sin_mas_vacantes = True
    
    browser.close()

print(f"\n{'='*60}")
print(f"✓ TOTAL DE VACANTES ENCONTRADAS: {len(todas_vacantes)}")
print(f"{'='*60}\n")

# --- Guardar resultados en CSV con columnas dinámicas ---
if todas_vacantes:
    # Recolectar todas las claves únicas que aparecen en todas las vacantes
    todas_las_claves = set()
    for vacante in todas_vacantes:
        todas_las_claves.update(vacante.keys())
    
    # Definir un orden predecible: poner primero los campos básicos y luego el resto
    campos_basicos = ["Título", "Entidad", "Ubicación", "Convocatoria", "Vacantes", 
                      "Remuneración", "Fecha Inicio", "Fecha Fin", "Titulo_Aviso", "Institucion_Aviso"]
    otros_campos = sorted([c for c in todas_las_claves if c not in campos_basicos])
    fieldnames = campos_basicos + otros_campos
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"vacantes_{timestamp}.csv"
    
    try:
        with open(filename, "w", newline="", encoding="utf-8") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(todas_vacantes)
        print(f"\n✓ Datos guardados en: {filename}")
        print(f"✓ Columnas del CSV: {fieldnames}")
    except Exception as e:
        print(f"❌ Error al guardar CSV: {e}")
else:
    print("⚠️ No se encontraron vacantes")