from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import json
from datetime import datetime
import time
import re

URL = "https://app.servir.gob.pe/DifusionOfertasExterno/faces/consultas/ofertas_laborales.xhtml"

def limpiar(texto):
    """Elimina saltos de línea, tabulaciones y espacios redundantes."""
    if not texto:
        return ""
    # Reemplazar \n y \t por espacio, luego reducir múltiples espacios
    return re.sub(r'\s+', ' ', texto).strip()

def retroceder(page):
    try:
        XPath_retroceder = "/html/body/div[2]/div[2]/div[2]/div[1]/div/ol/li[3]/form/button"
        page.locator(f"xpath={XPath_retroceder}").click()
        page.wait_for_load_state("networkidle", timeout=5000)
        time.sleep(1)
        return True
    except Exception as e:
        print(f"   ⚠️ Error al retroceder: {e}")
        return False

def extraer_todo_el_detalle(page):
    """
    Extrae TODOS los pares clave-valor del contenedor de detalles,
    incluyendo el número de folio que está fuera del contenedor principal.
    Retorna un diccionario con todos los campos nuevos.
    """
    detalles = {}
    
    # Esperar a que cargue la página de detalle
    try:
        page.wait_for_selector("span.sub-titulo-2, span.sub-titulo", timeout=5000)
    except:
        return detalles
    
    # --- 1. Buscar el número de folio (N° 780308) que está en un span.sub-titulo-2 ---
    # Posible selector: cualquier span.sub-titulo-2 que contenga "N°" y un número
    folio_spans = page.locator("span.sub-titulo-2:has-text('N°')").all()
    for span in folio_spans:
        texto = limpiar(span.inner_text())
        if texto.startswith("N°") or "N°" in texto:
            # Extraer el número (puede ser "N° 780308" o "N°780308")
            numero = re.search(r'N°\s*(\d+)', texto)
            if numero:
                detalles["NUMERO_FOLIO"] = numero.group(1)  # solo el número
            else:
                detalles["NUMERO_FOLIO"] = texto
            break  # tomar el primero encontrado
    
    # --- 2. Contenedor principal de requerimientos (el que ya tenías) ---
    xpath_contenedor = "/html/body/div[2]/div[2]/div[2]/form/div/div/div/div[1]/div[2]/div/div[2]/div"
    try:
        contenedor = page.locator(f"xpath={xpath_contenedor}")
        if contenedor.count():
            html = contenedor.first.inner_html()
            soup = BeautifulSoup(html, "lxml")
            
            # REQUERIMIENTO: lista con sub-titulo-2 y detalle-sp
            ul = soup.find("ul")
            if ul:
                reqs = {}
                for li in ul.find_all("li"):
                    clave_span = li.find("span", class_="sub-titulo-2")
                    valor_span = li.find("span", class_="detalle-sp")
                    if clave_span and valor_span:
                        clave = limpiar(clave_span.get_text(strip=True)).rstrip(":")
                        valor = limpiar(valor_span.get_text(strip=True))
                        reqs[clave] = valor
                if reqs:
                    detalles["REQUERIMIENTO"] = reqs
            
            # Otras filas con sub-titulo y detalle-sp (DETALLE, etc.)
            for row in soup.find_all("div", class_="row"):
                sub = row.find("span", class_="sub-titulo")
                if not sub:
                    continue
                clave = limpiar(sub.get_text(strip=True)).rstrip(":")
                if clave == "REQUERIMIENTO":
                    continue
                detalle = row.find("span", class_="detalle-sp")
                if detalle:
                    enlace = detalle.find("a")
                    if enlace:
                        valor = {
                            "texto": limpiar(enlace.get_text(strip=True)),
                            "url": enlace.get("href")
                        }
                    else:
                        valor = limpiar(detalle.get_text(strip=True))
                    # No agregar si ya existe en datos básicos de la tarjeta
                    if clave not in ["CANTIDAD DE VACANTES", "NÚMERO DE CONVOCATORIA", "REMUNERACIÓN",
                                     "FECHA INICIO DE PUBLICACIÓN", "FECHA FIN DE PUBLICACIÓN"]:
                        detalles[clave] = valor
            
            # Sección adicional (div[3]/div)
            divs_hijos = soup.find_all("div", recursive=False)
            if len(divs_hijos) >= 3:
                tercer_div = divs_hijos[2]
                div_extra = tercer_div.find("div")
                if div_extra:
                    contenido = limpiar(div_extra.get_text(strip=True))
                    if contenido:
                        detalles["SECCION_ADICIONAL"] = contenido
    except Exception as e:
        print(f"      ⚠️ Error extrayendo del contenedor: {e}")
    
    return detalles

# -------------------------
# MAIN
# -------------------------
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
    max_paginas = 3
    
    while not sin_mas_vacantes and pagina < max_paginas:
        print(f"\n📄 Página {pagina}")
        page.wait_for_load_state("networkidle")
        time.sleep(1)
        
        content = page.content()
        soup = BeautifulSoup(content, "lxml")
        vacantes_divs = soup.find_all("div", class_="cuadro-vacantes")
        
        if not vacantes_divs:
            print("   No hay más vacantes.")
            break
        
        print(f"   Vacantes encontradas: {len(vacantes_divs)}")
        botones = page.locator("span.ui-button-text.ui-c:has-text('¡Ver más!')").all()
        
        for idx in range(len(vacantes_divs)):
            print(f"   🔹 Vacante {idx+1}/{len(vacantes_divs)}")
            tarjeta = vacantes_divs[idx]
            
            # ---- Datos de la tarjeta (limpios) ----
            titulo = "N/A"
            tit_elem = tarjeta.find("div", class_="titulo-vacante")
            if tit_elem and tit_elem.find("label"):
                titulo = limpiar(tit_elem.find("label").text)
            
            entidad = "N/A"
            ent_elem = tarjeta.find("div", class_="nombre-entidad")
            if ent_elem:
                span = ent_elem.find("span", class_="detalle-sp")
                if span:
                    entidad = limpiar(span.text)
            
            datos_tarjeta = {}
            filas = tarjeta.find_all("div", class_="row box-mb")
            for fila in filas:
                sub = fila.find("span", class_="sub-titulo")
                det = fila.find("span", class_="detalle-sp")
                if sub and det:
                    clave = limpiar(sub.text).rstrip(":")
                    valor = limpiar(det.text)
                    datos_tarjeta[clave] = valor
            
            vacante = {
                "Título": titulo,
                "Entidad": entidad,
                **datos_tarjeta   # Ubicación, Convocatoria, Vacantes, Remuneración, Fechas
            }
            
            # ---- Hacer clic en "Ver más" y extraer detalles extra ----
            try:
                if idx < len(botones):
                    print(f"      👆 Click en 'Ver más'...")
                    botones[idx].click()
                    page.wait_for_load_state("networkidle", timeout=5000)
                    time.sleep(1)
                    
                    # Extraer todo (incluye NUMERO_FOLIO, REQUERIMIENTO, DETALLE, etc.)
                    detalles_extra = extraer_todo_el_detalle(page)
                    
                    # Fusionar sin sobrescribir los campos ya existentes de la tarjeta
                    for k, v in detalles_extra.items():
                        if k not in vacante:  # evitar duplicados
                            vacante[k] = v
                    
                    # También extraer Título_Aviso e Institución_Aviso (si quieres)
                    try:
                        xp_tit = page.locator("xpath=/html/body/div[2]/div[2]/div[2]/form/div/div/div/div[1]/div[1]/div/div[2]/div/span[1]")
                        if xp_tit.count():
                            vacante["Titulo_Aviso"] = limpiar(xp_tit.inner_text())
                    except:
                        pass
                    try:
                        xp_inst = page.locator("xpath=/html/body/div[2]/div[2]/div[2]/form/div/div/div/div[1]/div[1]/div/div[2]/div/span[2]")
                        if xp_inst.count():
                            vacante["Institucion_Aviso"] = limpiar(xp_inst.inner_text())
                    except:
                        pass
                    
                    print(f"      ✅ Extraídos: {list(detalles_extra.keys())}")
                    retroceder(page)
                else:
                    print("      ⚠️ No hay botón 'Ver más' para este índice")
            except Exception as e:
                print(f"      ❌ Error: {e}")
                retroceder(page)
            
            todas_vacantes.append(vacante)
        
        # ---- Página siguiente ----
        if vacantes_nuevas_en_pagina == 0:
                sin_mas_vacantes = True
        else:
            try:
                print(f"\n   ➡️ Buscando botón 'Sig.'...")
                next_button = page.locator("button:has-text('Sig.')")
                if next_button.count() and next_button.is_visible() and next_button.is_enabled():
                    next_button.click()
                    page.wait_for_load_state("networkidle")
                    time.sleep(2)
                    pagina += 1
                    print(f"   ✓ Pasando a página {pagina}...")
                else:
                    print("   ⚠️ No se encontró botón 'Sig.' habilitado, finalizando...")
                    sin_mas_vacantes = True
            except Exception as e:
                print(f"   ⚠️ Error al buscar botón siguiente: {str(e)}")
                sin_mas_vacantes = True
    
    browser.close()

# ---- Guardar JSON ----
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
filename = f"vacantes_sin_tabulaciones_{timestamp}.json"
with open(filename, "w", encoding="utf-8") as f:
    json.dump(todas_vacantes, f, ensure_ascii=False, indent=2)

print(f"\n✅ Total: {len(todas_vacantes)} vacantes")
print(f"📁 Archivo: {filename}")