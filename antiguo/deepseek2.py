from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import csv
from datetime import datetime
import time

URL = "https://app.servir.gob.pe/DifusionOfertasExterno/faces/consultas/ofertas_laborales.xhtml"

def retroceder(page):
    """Vuelve a la lista de ofertas después de ver los detalles."""
    try:
        # Selector genérico para el botón de retroceso
        back_btn = page.locator("button:has-text('Retroceder'), button:has-text('Volver')")
        if back_btn.count() == 0:
            back_btn = page.locator("xpath=/html/body/div[2]/div[2]/div[2]/div[1]/div/ol/li[3]/form/button")
        back_btn.click()
        page.wait_for_load_state("networkidle", timeout=5000)
        time.sleep(1)
        return True
    except:
        # Fallback: recargar la página principal
        page.goto(URL)
        page.wait_for_load_state("networkidle")
        time.sleep(2)
        return True

def extraer_todos_requerimientos(page):
    """
    Extrae todos los bloques de requerimientos de la vista detallada.
    Devuelve un diccionario con:
        - Claves estándar (EXPERIENCIA, FORMACIÓN, etc.)
        - Una clave especial 'Seccion_Adicional' con el contenido de div[3]/div
    """
    reqs = {}
    
    # Esperar a que aparezca al menos un elemento de detalles
    try:
        page.wait_for_selector("span.sub-titulo-2, div.requisitos", timeout=5000)
    except:
        return reqs
    
    # 1. Extraer pares estándar (span.sub-titulo-2 + span.detalle-sp)
    items = page.locator("li:has(span.sub-titulo-2)").all()
    for item in items:
        try:
            clave = item.locator("span.sub-titulo-2").first.inner_text().strip().rstrip(':')
            valor = item.locator("span.detalle-sp").first.inner_text().strip()
            reqs[clave.upper()] = valor
        except:
            pass
    
    # 2. Extraer otras filas (div.row con estructura similar)
    filas = page.locator("div.row:has(span.sub-titulo)").all()
    for fila in filas:
        try:
            texto = fila.inner_text()
            if ':' in texto:
                k, v = texto.split(':', 1)
                reqs[k.strip().upper()] = v.strip()
        except:
            pass
    
    # 3. Extraer ESPECÍFICAMENTE la sección /div[3]/div
    # Buscamos el contenedor principal de requerimientos usando un selector estable
    # (podemos usar el div que contiene todos los detalles)
    contenedor = page.locator("div[class*='ui-panel-content'], div:has(span.sub-titulo-2)").first
    if contenedor.count():
        # Usamos XPath relativo para obtener el tercer div hijo y su subdiv
        div_extra = contenedor.locator("xpath=div[3]/div")
        if div_extra.count():
            contenido = div_extra.first.inner_text().strip()
            if contenido:
                reqs['SECCION_ADICIONAL'] = contenido
                print(f"      📌 Sección adicional capturada (largo: {len(contenido)} chars)")
        else:
            # Alternativa: buscar cualquier div que contenga texto y no esté en los pares anteriores
            otros_divs = contenedor.locator("div:not(:has(span.sub-titulo-2))")
            for i in range(otros_divs.count()):
                texto = otros_divs.nth(i).inner_text().strip()
                if texto and len(texto) > 20:
                    reqs[f'BLOQUE_{i+1}'] = texto[:500]
    
    return reqs

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False, args=["--disable-blink-features=AutomationControlled"])
    page = browser.new_page()
    
    print("🌐 Cargando página principal...")
    page.goto(URL)
    page.wait_for_load_state("networkidle")
    time.sleep(2)
    
    todas_vacantes = []
    pagina_actual = 0
    max_paginas = 3  # Aumenta si quieres más páginas, o usa None para todas
    
    while pagina_actual < max_paginas:
        print(f"\n📄 Procesando página {pagina_actual + 1}")
        page.wait_for_load_state("networkidle")
        time.sleep(1)
        
        # Obtener el HTML y parsear con BeautifulSoup (para info superficial)
        html = page.content()
        soup = BeautifulSoup(html, "lxml")
        tarjetas = soup.find_all("div", class_="cuadro-vacantes")
        
        if not tarjetas:
            print("   No se encontraron más ofertas. Fin del proceso.")
            break
        
        print(f"   Encontradas {len(tarjetas)} ofertas en esta página.")
        
        # Procesar cada tarjeta
        for idx, tarjeta in enumerate(tarjetas):
            print(f"   🔍 Oferta {idx+1}/{len(tarjetas)}")
            
            # --- Datos visibles sin hacer clic ---
            titulo = "N/A"
            titulo_div = tarjeta.find("div", class_="titulo-vacante")
            if titulo_div and titulo_div.find("label"):
                titulo = titulo_div.find("label").get_text(strip=True)
            
            entidad = "N/A"
            entidad_div = tarjeta.find("div", class_="nombre-entidad")
            if entidad_div and entidad_div.find("span", class_="detalle-sp"):
                entidad = entidad_div.find("span", class_="detalle-sp").get_text(strip=True)
            
            # Campos de las filas (Ubicación, convocatoria, etc.)
            info_basica = {}
            filas_info = tarjeta.find_all("div", class_="row box-mb")
            for fila in filas_info:
                subtitulo = fila.find("span", class_="sub-titulo")
                detalle = fila.find("span", class_="detalle-sp")
                if subtitulo and detalle:
                    clave = subtitulo.get_text(strip=True).rstrip(':')
                    valor = detalle.get_text(strip=True)
                    info_basica[clave] = valor
            
            vacante = {
                "Título": titulo,
                "Entidad": entidad,
                "Ubicación": info_basica.get("Ubicación", "N/A"),
                "Convocatoria": info_basica.get("Número de Convocatoria", "N/A"),
                "Vacantes": info_basica.get("Cantidad de Vacantes", "N/A"),
                "Remuneración": info_basica.get("Remuneración", "N/A"),
                "Fecha Inicio": info_basica.get("Fecha Inicio de Publicación", "N/A"),
                "Fecha Fin": info_basica.get("Fecha Fin de Publicación", "N/A"),
            }
            
            # --- Hacer clic en "¡Ver más!" ---
            try:
                # Localizar todos los botones "Ver más" actualizados
                botones_ver_mas = page.locator("span.ui-button-text.ui-c:has-text('¡Ver más!')").all()
                if idx < len(botones_ver_mas):
                    print(f"      👆 Haciendo clic en 'Ver más'...")
                    botones_ver_mas[idx].click()
                    page.wait_for_load_state("networkidle", timeout=5000)
                    time.sleep(1)
                    
                    # Extraer Título_Aviso e Institución_Aviso (XPath original, pero con fallback)
                    try:
                        tit_aviso = page.locator("xpath=/html/body/div[2]/div[2]/div[2]/form/div/div/div/div[1]/div[1]/div/div[2]/div/span[1]")
                        vacante["Titulo_Aviso"] = tit_aviso.inner_text().strip() if tit_aviso.count() else "N/A"
                    except:
                        vacante["Titulo_Aviso"] = "N/A"
                    
                    try:
                        inst_aviso = page.locator("xpath=/html/body/div[2]/div[2]/div[2]/form/div/div/div/div[1]/div[1]/div/div[2]/div/span[2]")
                        vacante["Institucion_Aviso"] = inst_aviso.inner_text().strip() if inst_aviso.count() else "N/A"
                    except:
                        vacante["Institucion_Aviso"] = "N/A"
                    
                    # Extraer TODOS los requerimientos (incluyendo la sección que faltaba)
                    reqs_detalle = extraer_todos_requerimientos(page)
                    
                    vacante["Experiencia"] = reqs_detalle.get("EXPERIENCIA", "N/A")
                    vacante["Formacion_Academica"] = reqs_detalle.get("FORMACIÓN ACADÉMICA", "N/A")
                    vacante["Especializacion"] = reqs_detalle.get("ESPECIALIZACIÓN", "N/A")
                    vacante["Conocimiento"] = reqs_detalle.get("CONOCIMIENTOS", "N/A")
                    vacante["Competencias"] = reqs_detalle.get("COMPETENCIAS", "N/A")
                    vacante["Seccion_Adicional"] = reqs_detalle.get("SECCION_ADICIONAL", "N/A")
                    
                    # Opcional: guardar todo el diccionario por si acaso
                    vacante["Reqs_Completos"] = str(reqs_detalle)[:1000]
                    
                    # Retroceder
                    print(f"      ↩️  Retrocediendo...")
                    retroceder(page)
                else:
                    # Rellenar con N/A si no se pudo hacer clic
                    vacante["Titulo_Aviso"] = vacante["Institucion_Aviso"] = "N/A"
                    vacante["Experiencia"] = vacante["Formacion_Academica"] = "N/A"
                    vacante["Especializacion"] = vacante["Conocimiento"] = "N/A"
                    vacante["Competencias"] = vacante["Seccion_Adicional"] = "N/A"
                    vacante["Reqs_Completos"] = "N/A"
            except Exception as e:
                print(f"      ❌ Error al procesar detalle: {e}")
                # Rellenar con N/A en caso de error
                for campo in ["Titulo_Aviso", "Institucion_Aviso", "Experiencia", "Formacion_Academica",
                              "Especializacion", "Conocimiento", "Competencias", "Seccion_Adicional", "Reqs_Completos"]:
                    vacante[campo] = "N/A"
                try:
                    retroceder(page)
                except:
                    pass
            
            todas_vacantes.append(vacante)
        
        # --- Navegar a la siguiente página ---
        try:
            siguiente = page.locator("button:has-text('Siguiente')")
            if siguiente.count() and siguiente.is_visible():
                siguiente.click()
                page.wait_for_load_state("networkidle")
                time.sleep(2)
                pagina_actual += 1
            else:
                print("   No hay más páginas. Fin de la recolección.")
                break
        except Exception as e:
            print(f"   Error al avanzar de página: {e}")
            break
    
    browser.close()

# ========================
# GUARDAR RESULTADOS
# ========================
print(f"\n✅ Total de vacantes recolectadas: {len(todas_vacantes)}")
if todas_vacantes:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archivo_csv = f"servir_vacantes_completas_{timestamp}.csv"
    
    columnas = ["Título", "Entidad", "Ubicación", "Convocatoria", "Vacantes", "Remuneración",
                "Fecha Inicio", "Fecha Fin", "Titulo_Aviso", "Institucion_Aviso",
                "Experiencia", "Formacion_Academica", "Especializacion", "Conocimiento",
                "Competencias", "Seccion_Adicional", "Reqs_Completos"]
    
    with open(archivo_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columnas)
        writer.writeheader()
        writer.writerows(todas_vacantes)
    
    print(f"📁 Datos guardados en: {archivo_csv}")
    
    # Mostrar un ejemplo de la primera vacante con la nueva sección
    print("\n📌 Ejemplo de la primera vacante (Sección Adicional):")
    primera = todas_vacantes[0]
    print(f"   Título: {primera['Título']}")
    print(f"   Sección Adicional: {primera['Seccion_Adicional'][:200]}..." if len(primera['Seccion_Adicional']) > 200 else primera['Seccion_Adicional'])
else:
    print("⚠️ No se encontraron vacantes. Verifica la conexión o la estructura de la página.")