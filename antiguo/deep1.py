from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import json
import re
import time
from datetime import datetime

URL = "https://app.servir.gob.pe/DifusionOfertasExterno/faces/consultas/ofertas_laborales.xhtml"

def limpiar(texto):
    if not texto:
        return ""
    return re.sub(r'\s+', ' ', texto).strip()

def retroceder(page):
    try:
        XPath_retroceder = "/html/body/div[2]/div[2]/div[2]/div[1]/div/ol/li[3]/form/button"
        page.locator(f"xpath={XPath_retroceder}").click()
        page.wait_for_load_state("networkidle", timeout=5000)
        time.sleep(1)
        return True
    except Exception as e:
        print(f"   ⚠️ Error al retroceder: {str(e)}")
        return False

def extraer_detalles_completos(page):
    detalles = {}
    # Número de folio
    xpath_folio = "/html/body/div[2]/div[2]/div[2]/form/div/div/div/div[2]/div[3]/div"
    try:
        folio_elem = page.locator(f"xpath={xpath_folio}")
        if folio_elem.count():
            texto = limpiar(folio_elem.first.inner_text())
            match = re.search(r'N°\s*(\d+)', texto)
            detalles["NUMERO_FOLIO"] = match.group(1) if match else texto
    except:
        pass

    xpath_contenedor = "/html/body/div[2]/div[2]/div[2]/form/div/div/div/div[1]/div[2]/div/div[2]/div"
    try:
        contenedor = page.locator(f"xpath={xpath_contenedor}")
        if contenedor.count():
            html = contenedor.first.inner_html()
            soup = BeautifulSoup(html, "lxml")
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
                        valor = {"texto": limpiar(enlace.get_text(strip=True)), "url": enlace.get("href")}
                    else:
                        valor = limpiar(detalle.get_text(strip=True))
                    if clave not in ["CANTIDAD DE VACANTES", "NÚMERO DE CONVOCATORIA", "REMUNERACIÓN",
                                     "FECHA INICIO DE PUBLICACIÓN", "FECHA FIN DE PUBLICACIÓN"]:
                        detalles[clave] = valor
            divs_hijos = soup.find_all("div", recursive=False)
            if len(divs_hijos) >= 3:
                tercer_div = divs_hijos[2]
                div_extra = tercer_div.find("div")
                if div_extra:
                    contenido = limpiar(div_extra.get_text(strip=True))
                    if contenido:
                        detalles["SECCION_ADICIONAL"] = contenido
    except Exception as e:
        print(f"      ⚠️ Error en contenedor: {e}")
    return detalles

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False, args=["--disable-blink-features=AutomationControlled"])
    page = browser.new_page()
    print(f"📍 Navegando a {URL}...")
    page.goto(URL)
    page.wait_for_load_state("networkidle")
    time.sleep(2)

    todas_vacantes = []
    pagina_actual = 0
    max_paginas = 1
    sin_mas_vacantes = False

    while not sin_mas_vacantes and pagina_actual < max_paginas:
        print(f"\n📄 Procesando página {pagina_actual + 1}")
        page.wait_for_load_state("networkidle")
        time.sleep(1)

        content = page.content()
        soup = BeautifulSoup(content, "lxml")
        tarjetas = soup.find_all("div", class_="cuadro-vacantes")
        if not tarjetas:
            print("   No hay más vacantes.")
            break

        print(f"   Se encontraron {len(tarjetas)} vacantes")
        botones_ver_mas = page.locator("span.ui-button-text.ui-c:has-text('¡Ver más!')").all()
        vacantes_procesadas = 0

        for idx, tarjeta in enumerate(tarjetas):
            print(f"   🔹 Vacante {idx+1}/{len(tarjetas)}")
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
            filas_tarjeta = tarjeta.find_all("div", class_="row box-mb")
            for fila in filas_tarjeta:
                sub = fila.find("span", class_="sub-titulo")
                det = fila.find("span", class_="detalle-sp")
                if sub and det:
                    clave = limpiar(sub.text).rstrip(":")
                    valor = limpiar(det.text)
                    datos_tarjeta[clave] = valor
            vacante = {"Título": titulo, "Entidad": entidad, **datos_tarjeta}

            try:
                if idx < len(botones_ver_mas):
                    print(f"      👆 Click en 'Ver más'...")
                    botones_ver_mas[idx].click()
                    page.wait_for_load_state("networkidle", timeout=5000)
                    time.sleep(1)
                    campos_extra = extraer_detalles_completos(page)
                    for k, v in campos_extra.items():
                        if k not in vacante:
                            vacante[k] = v
                    try:
                        xp_tit = page.locator("xpath=/html/body/div[2]/div[2]/div[2]/form/div/div/div/div[1]/div[1]/div/div[2]/div/span[1]")
                        vacante["Titulo_Aviso"] = limpiar(xp_tit.inner_text()) if xp_tit.count() else "N/A"
                    except:
                        vacante["Titulo_Aviso"] = "N/A"
                    try:
                        xp_inst = page.locator("xpath=/html/body/div[2]/div[2]/div[2]/form/div/div/div/div[1]/div[1]/div/div[2]/div/span[2]")
                        vacante["Institucion_Aviso"] = limpiar(xp_inst.inner_text()) if xp_inst.count() else "N/A"
                    except:
                        vacante["Institucion_Aviso"] = "N/A"
                    print(f"      ✅ Extraídos: {list(campos_extra.keys())}")
                    retroceder(page)
                else:
                    vacante["Titulo_Aviso"] = vacante["Institucion_Aviso"] = "N/A"
                vacantes_procesadas += 1
            except Exception as e:
                print(f"      ❌ Error: {e}")
                retroceder(page)
                vacante["Titulo_Aviso"] = vacante["Institucion_Aviso"] = "N/A"
                vacantes_procesadas += 1
            todas_vacantes.append(vacante)

        # ---------- CORRECCIÓN DE PAGINACIÓN ----------
        if vacantes_procesadas == 0:
            break
        else:
            try:
                print(f"\n   ➡️ Buscando botón 'Sig.' para avanzar...")
                # Hay dos botones con texto "Sig.": el último es el que avanza (siguiente)
                next_btn = page.locator("button:has-text('Sig.')").last
                if next_btn.count() and next_btn.is_visible() and next_btn.is_enabled():
                    next_btn.click()
                    page.wait_for_load_state("networkidle")
                    time.sleep(2)
                    pagina_actual += 1
                    print(f"   ✓ Pasando a página {pagina_actual + 1}")
                else:
                    print("   ⚠️ Botón 'Sig.' no habilitado. Fin de paginación.")
                    sin_mas_vacantes = True
            except Exception as e:
                print(f"   ⚠️ Error al buscar botón siguiente: {e}")
                sin_mas_vacantes = True

    browser.close()

timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
nombre_archivo = f"servir_vacantes_completas_{timestamp}.json"
with open(nombre_archivo, "w", encoding="utf-8") as f:
    json.dump(todas_vacantes, f, ensure_ascii=False, indent=2)

print(f"\n✅ Total de vacantes extraídas: {len(todas_vacantes)}")
print(f"📁 Archivo guardado en: {nombre_archivo}")