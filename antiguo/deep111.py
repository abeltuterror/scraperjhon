import asyncio
import json
import os
import re
from datetime import datetime
from playwright.async_api import async_playwright

URL = "https://app.servir.gob.pe/DifusionOfertasExterno/faces/consultas/ofertas_laborales.xhtml"
ARCHIVO_INDEX = "indice_vacantes.json"
ARCHIVO_DETALLES = "vacantes_completas.json"
MAX_CONCURRENT = 5  # Número de pestañas simultáneas para extraer detalles

def limpiar(texto):
    return re.sub(r'\s+', ' ', texto).strip() if texto else ""

async def extraer_detalles_completos(page, url_modal=None):
    """Extrae los detalles del modal actual (ya abierto)."""
    detalles = {}
    # Esperar a que cargue el contenido del modal
    try:
        await page.wait_for_selector("ul.lista-requerimiento", timeout=5000)
    except:
        pass
    # Extraer requerimientos del <ul>
    ul = await page.query_selector("ul.lista-requerimiento")
    if ul:
        reqs = {}
        items = await ul.query_selector_all("li")
        for li in items:
            clave_span = await li.query_selector("span.sub-titulo-2")
            valor_span = await li.query_selector("span.detalle-sp")
            if clave_span and valor_span:
                clave = limpiar(await clave_span.inner_text()).rstrip(":")
                valor = limpiar(await valor_span.inner_text())
                reqs[clave] = valor
        if reqs:
            detalles["REQUERIMIENTO"] = reqs
    # Extraer otros campos (detalle-sp)
    rows = await page.query_selector_all("div.row")
    for row in rows:
        sub = await row.query_selector("span.sub-titulo")
        if not sub:
            continue
        clave = limpiar(await sub.inner_text()).rstrip(":")
        if clave == "REQUERIMIENTO":
            continue
        detalle = await row.query_selector("span.detalle-sp")
        if detalle:
            enlace = await detalle.query_selector("a")
            if enlace:
                valor = {
                    "texto": limpiar(await enlace.inner_text()),
                    "url": await enlace.get_attribute("href")
                }
            else:
                valor = limpiar(await detalle.inner_text())
            detalles[clave] = valor
    # Número de folio
    folio_elem = await page.query_selector("div:has-text('N°')")
    if folio_elem:
        texto = limpiar(await folio_elem.inner_text())
        match = re.search(r'N°\s*(\d+)', texto)
        if match:
            detalles["NUMERO_FOLIO"] = match.group(1)
    return detalles

async def obtener_lista_paginas(context):
    """Extrae índice de todas las páginas (sin abrir modales). Rápido."""
    page = await context.new_page()
    vacantes = []
    pagina_actual = 0
    print("🔍 Obteniendo lista de vacantes (índice)...")
    await page.goto(URL)
    await page.wait_for_load_state("networkidle")
    
    while True:
        print(f"📄 Escaneando página {pagina_actual+1}...")
        await page.wait_for_selector("div.cuadro-vacantes", timeout=10000)
        tarjetas = await page.query_selector_all("div.cuadro-vacantes")
        if not tarjetas:
            break
        for idx, tarjeta in enumerate(tarjetas):
            # Título
            titulo_elem = await tarjeta.query_selector("div.titulo-vacante label")
            titulo = limpiar(await titulo_elem.inner_text()) if titulo_elem else "N/A"
            # Entidad
            entidad_elem = await tarjeta.query_selector("div.nombre-entidad span.detalle-sp")
            entidad = limpiar(await entidad_elem.inner_text()) if entidad_elem else "N/A"
            # Datos de la tarjeta (ubicación, remuneración, etc.)
            datos_tarjeta = {}
            filas = await tarjeta.query_selector_all("div.row.box-mb")
            for fila in filas:
                sub = await fila.query_selector("span.sub-titulo")
                det = await fila.query_selector("span.detalle-sp")
                if sub and det:
                    clave = limpiar(await sub.inner_text()).rstrip(":")
                    valor = limpiar(await det.inner_text())
                    datos_tarjeta[clave] = valor
            vacante = {
                "Título": titulo,
                "Entidad": entidad,
                "pagina": pagina_actual,
                "posicion_pagina": idx,
                **datos_tarjeta
            }
            vacantes.append(vacante)
        # Siguiente página
        next_btn = page.locator("button:has-text('Sig.')").last
        if await next_btn.is_visible() and await next_btn.is_enabled():
            await next_btn.click()
            await page.wait_for_load_state("networkidle")
            pagina_actual += 1
        else:
            break
    await page.close()
    # Guardar índice
    with open(ARCHIVO_INDEX, "w", encoding="utf-8") as f:
        json.dump(vacantes, f, ensure_ascii=False, indent=2)
    print(f"✅ Índice guardado: {len(vacantes)} vacantes en {ARCHIVO_INDEX}")
    return vacantes

async def procesar_vacante(semaphore, browser, vacante, index, total):
    """Procesa una vacante: abre modal y extrae detalles completo."""
    async with semaphore:
        # Crear un nuevo contexto (pestaña) por cada vacante para evitar conflictos
        context = await browser.new_context()
        page = await context.new_page()
        try:
            # Navegar a la página donde está la vacante
            pagina_necesaria = vacante.get("pagina", 0)
            await page.goto(URL)
            await page.wait_for_load_state("networkidle")
            # Avanzar hasta la página requerida
            for _ in range(pagina_necesaria):
                next_btn = page.locator("button:has-text('Sig.')").last
                if await next_btn.is_visible() and await next_btn.is_enabled():
                    await next_btn.click()
                    await page.wait_for_load_state("networkidle")
                else:
                    break
            # Obtener todas las tarjetas de la página
            tarjetas = await page.query_selector_all("div.cuadro-vacantes")
            pos = vacante.get("posicion_pagina", 0)
            if pos >= len(tarjetas):
                print(f"⚠️ Vacante {vacante['Título']} no encontrada en página {pagina_necesaria}")
                return None
            tarjeta = tarjetas[pos]
            # Click en "Ver más"
            btn_ver_mas = await tarjeta.query_selector("span.ui-button-text:has-text('¡Ver más!')")
            if not btn_ver_mas:
                print(f"⚠️ Botón no encontrado para {vacante['Título']}")
                return None
            await btn_ver_mas.click()
            await page.wait_for_load_state("networkidle")
            # Extraer detalles del modal
            detalles = await extraer_detalles_completos(page)
            # Combinar con datos existentes
            vacante_completa = {**vacante, **detalles}
            # Eliminar campos temporales
            vacante_completa.pop("pagina", None)
            vacante_completa.pop("posicion_pagina", None)
            print(f"✅ [{index+1}/{total}] Procesada: {vacante['Título'][:50]}")
            return vacante_completa
        except Exception as e:
            print(f"❌ Error en {vacante['Título']}: {e}")
            return None
        finally:
            await context.close()

async def main():
    # Cargar o generar índice
    if not os.path.exists(ARCHIVO_INDEX):
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()
            vacantes_index = await obtener_lista_paginas(context)
            await browser.close()
    else:
        with open(ARCHIVO_INDEX, "r", encoding="utf-8") as f:
            vacantes_index = json.load(f)
        print(f"📂 Cargado índice existente: {len(vacantes_index)} vacantes")
    
    # Cargar progreso previo de detalles
    if os.path.exists(ARCHIVO_DETALLES):
        with open(ARCHIVO_DETALLES, "r", encoding="utf-8") as f:
            vacantes_completas = json.load(f)
        procesados = {v.get("NUMERO_FOLIO") for v in vacantes_completas if v.get("NUMERO_FOLIO")}
        print(f"📌 Progreso anterior: {len(vacantes_completas)} vacantes completas")
    else:
        vacantes_completas = []
        procesados = set()
    
    # Filtrar las que faltan procesar
    pendientes = []
    for vac in vacantes_index:
        # Usamos una clave única (podría ser combinación de título + entidad si no hay folio aún)
        clave = vac.get("NUMERO_FOLIO") or f"{vac['Título']}_{vac['Entidad']}"
        if clave not in procesados:
            pendientes.append(vac)
    print(f"⏳ Vacantes pendientes: {len(pendientes)}")
    
    if not pendientes:
        print("🎉 Todas las vacantes ya están completas.")
        return
    
    # Procesar en paralelo con semáforo
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        tasks = []
        for i, vac in enumerate(pendientes):
            task = procesar_vacante(semaphore, browser, vac, i, len(pendientes))
            tasks.append(task)
        resultados = await asyncio.gather(*tasks)
        await browser.close()
    
    # Añadir resultados no nulos y guardar
    nuevas = [r for r in resultados if r is not None]
    vacantes_completas.extend(nuevas)
    with open(ARCHIVO_DETALLES, "w", encoding="utf-8") as f:
        json.dump(vacantes_completas, f, ensure_ascii=False, indent=2)
    print(f"\n✅ Proceso completado. Total final: {len(vacantes_completas)} vacantes con detalles.")
    print(f"📁 Archivo: {ARCHIVO_DETALLES}")

if __name__ == "__main__":
    asyncio.run(main())