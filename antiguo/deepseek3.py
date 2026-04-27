from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import json
from datetime import datetime
import time

URL = "https://app.servir.gob.pe/DifusionOfertasExterno/faces/consultas/ofertas_laborales.xhtml"

def retroceder(page):
    """Retrocede después de ver los detalles"""
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

def extraer_detalles_completos(page):
    """
    Extrae TODOS los pares clave-valor del contenedor de detalles
    (incluyendo la sección que falta: div[3]/div).
    Retorna un diccionario con los campos encontrados.
    """
    detalles = {}
    
    # Esperar a que cargue el contenido (opcional)
    try:
        page.wait_for_selector("span.sub-titulo-2, span.sub-titulo", timeout=5000)
    except:
        return detalles
    
    # Obtener el HTML del contenedor principal de requerimientos
    xpath_contenedor = "/html/body/div[2]/div[2]/div[2]/form/div/div/div/div[1]/div[2]/div/div[2]/div"
    try:
        contenedor = page.locator(f"xpath={xpath_contenedor}")
        if contenedor.count():
            html_contenedor = contenedor.first.inner_html()
            soup = BeautifulSoup(html_contenedor, "lxml")
            
            # 1. Procesar la sección de REQUERIMIENTO (lista con sub-titulo-2)
            # Buscamos el div que contiene la lista de requerimientos
            ul_requisitos = soup.find("ul")
            if ul_requisitos:
                requerimientos = {}
                for li in ul_requisitos.find_all("li"):
                    clave_span = li.find("span", class_="sub-titulo-2")
                    valor_span = li.find("span", class_="detalle-sp")
                    if clave_span and valor_span:
                        clave = clave_span.get_text(strip=True).rstrip(":")
                        valor = valor_span.get_text(strip=True)
                        requerimientos[clave] = valor
                if requerimientos:
                    detalles["REQUERIMIENTO"] = requerimientos
            
            # 2. Procesar todas las filas (div.row) que contienen span.sub-titulo
            for row in soup.find_all("div", class_="row"):
                # Buscar si tiene span.sub-titulo (no el de la lista, que ya se procesó)
                sub = row.find("span", class_="sub-titulo")
                if not sub:
                    continue
                # Evitar duplicados con lo que ya tenemos
                clave = sub.get_text(strip=True).rstrip(":")
                if clave == "REQUERIMIENTO":
                    continue
                
                # Valor: puede estar en span.detalle-sp o en un enlace dentro
                detalle = row.find("span", class_="detalle-sp")
                if detalle:
                    enlace = detalle.find("a")
                    if enlace:
                        valor = {
                            "texto": enlace.get_text(strip=True),
                            "url": enlace.get("href")
                        }
                    else:
                        valor = detalle.get_text(strip=True)
                    detalles[clave] = valor
                else:
                    # Si no hay span.detalle-sp, tomar todo el texto de la fila después de la clave
                    texto_fila = row.get_text(separator=" ", strip=True)
                    if clave in texto_fila:
                        valor = texto_fila.replace(clave, "", 1).strip(":").strip()
                        detalles[clave] = valor
            
            # 3. Extraer la sección adicional que faltaba (div[3]/div)
            # Buscamos el contenedor principal y accedemos al tercer div hijo
            divs_hijos = soup.find_all("div", recursive=False)
            if len(divs_hijos) >= 3:
                tercer_div = divs_hijos[2]
                # Buscar un div dentro de ese tercer div (puede ser directo o anidado)
                div_extra = tercer_div.find("div")
                if div_extra:
                    contenido_extra = div_extra.get_text(strip=True)
                    if contenido_extra:
                        detalles["SECCION_ADICIONAL"] = contenido_extra
                else:
                    # Si no hay div, tomar todo el texto del tercer div
                    texto_extra = tercer_div.get_text(strip=True)
                    if texto_extra:
                        detalles["SECCION_ADICIONAL"] = texto_extra
    
    except Exception as e:
        print(f"      ⚠️ Error extrayendo detalles: {e}")
    
    return detalles

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False, args=["--disable-blink-features=AutomationControlled"])
    page = browser.new_page()
    
    print(f"📍 Navegando a {URL}...")
    page.goto(URL)
    page.wait_for_load_state("networkidle")
    time.sleep(2)
    
    todas_vacantes = []
    pagina = 0
    sin_mas_vacantes = False
    max_paginas = 3  # Ajusta según necesites
    
    while not sin_mas_vacantes and pagina < max_paginas:
        print(f"\n📄 Página {pagina}...")
        
        try:
            page.wait_for_load_state("networkidle")
            time.sleep(1)
            
            content = page.content()
            soup = BeautifulSoup(content, "lxml")
            vacantes_divs = soup.find_all("div", {"class": "cuadro-vacantes"})
            
            if not vacantes_divs:
                print(f"   ⚠️ No hay más vacantes, finalizando...")
                sin_mas_vacantes = True
                continue
            
            print(f"   ✓ Se encontraron {len(vacantes_divs)} vacantes")
            botones_ver_mas = page.locator("span.ui-button-text.ui-c:has-text('¡Ver más!')").all()
            
            for idx in range(len(vacantes_divs)):
                print(f"   🔹 Vacante {idx+1}/{len(vacantes_divs)}")
                
                # ---- Datos de la tarjeta (sin clic) ----
                vacante_div = vacantes_divs[idx]
                
                # Título
                titulo_label = vacante_div.find("div", {"class": "titulo-vacante"})
                titulo = titulo_label.find("label").text.strip() if titulo_label else "N/A"
                
                # Entidad
                nombre_entidad_div = vacante_div.find("div", {"class": "nombre-entidad"})
                entidad = "N/A"
                if nombre_entidad_div:
                    span = nombre_entidad_div.find("span", {"class": "detalle-sp"})
                    entidad = span.text.strip() if span else "N/A"
                
                # Datos de las filas (Ubicación, convocatoria, etc.)
                datos_tarjeta = {}
                filas_datos = vacante_div.find_all("div", {"class": "row box-mb"})
                for fila in filas_datos:
                    sub_titulo = fila.find("span", {"class": "sub-titulo"})
                    detalle = fila.find("span", {"class": "detalle-sp"})
                    if sub_titulo and detalle:
                        clave = sub_titulo.text.strip().rstrip(":").strip()
                        valor = detalle.text.strip()
                        datos_tarjeta[clave] = valor
                
                # Crear objeto base con lo que ya tenemos
                vacante_obj = {
                    "Título": titulo,
                    "Entidad": entidad,
                    **datos_tarjeta   # incluye Ubicación, Convocatoria, Vacantes, Remuneración, Fechas
                }
                
                # ---- Hacer clic en "Ver más" y extraer detalles dinámicos ----
                try:
                    botones_actualizados = page.locator("span.ui-button-text.ui-c:has-text('¡Ver más!')").all()
                    if idx < len(botones_actualizados):
                        boton = botones_actualizados[idx]
                        print(f"      👆 Haciendo click...")
                        boton.click()
                        page.wait_for_load_state("networkidle", timeout=5000)
                        time.sleep(1)
                        
                        # Extraer todos los campos de la vista detallada
                        campos_detalle = extraer_detalles_completos(page)
                        
                        # Fusionar (sin sobrescribir los campos base)
                        for k, v in campos_detalle.items():
                            if k not in vacante_obj:
                                vacante_obj[k] = v
                        
                        # También extraer Título_Aviso e Institución_Aviso si quieres conservarlos
                        try:
                            tit_aviso = page.locator("xpath=/html/body/div[2]/div[2]/div[2]/form/div/div/div/div[1]/div[1]/div/div[2]/div/span[1]")
                            if tit_aviso.count():
                                vacante_obj["Titulo_Aviso"] = tit_aviso.inner_text().strip()
                        except:
                            pass
                        
                        try:
                            inst_aviso = page.locator("xpath=/html/body/div[2]/div[2]/div[2]/form/div/div/div/div[1]/div[1]/div/div[2]/div/span[2]")
                            if inst_aviso.count():
                                vacante_obj["Institucion_Aviso"] = inst_aviso.inner_text().strip()
                        except:
                            pass
                        
                        print(f"      📝 Campos capturados: {list(campos_detalle.keys())}")
                        
                        # Retroceder
                        print(f"      ↩️  Retrocediendo...")
                        retroceder(page)
                    else:
                        print(f"      ⚠️ No se encontró botón 'Ver más'")
                except Exception as e:
                    print(f"      ❌ Error: {e}")
                    retroceder(page)
                
                todas_vacantes.append(vacante_obj)
            
            # ---- Navegar a la siguiente página ----
            try:
                next_button = page.locator("button:has-text('Siguiente')")
                if next_button.is_visible():
                    next_button.click()
                    page.wait_for_load_state("networkidle")
                    time.sleep(2)
                    pagina += 1
                else:
                    sin_mas_vacantes = True
            except:
                sin_mas_vacantes = True
        
        except Exception as e:
            print(f"   ❌ Error en página: {e}")
            sin_mas_vacantes = True
    
    browser.close()

# ---- Guardar resultados en JSON ----
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
filename = f"vacantes_{timestamp}.json"

with open(filename, "w", encoding="utf-8") as f:
    json.dump(todas_vacantes, f, ensure_ascii=False, indent=2)

print(f"\n✅ Total de vacantes: {len(todas_vacantes)}")
print(f"📁 Datos guardados en: {filename}")