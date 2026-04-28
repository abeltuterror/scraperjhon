import asyncio
import json
import re
import os
import socket
import uuid
from datetime import datetime
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
import asyncpg
from dotenv import load_dotenv
from bs4 import BeautifulSoup

load_dotenv()

DB_CONFIG = {
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "host": os.getenv("DB_HOST"),
    "port": int(os.getenv("DB_PORT")),
    "database": os.getenv("DB_NAME"),
    "server_settings": {"client_encoding": "UTF8"}
}
DB_SCRAPING_NAME = os.getenv("DB_SCRAPING_NAME", "convocatoria")
URL = "https://app.servir.gob.pe/DifusionOfertasExterno/faces/consultas/ofertas_laborales.xhtml"
MAX_PAGINAS = 2


def limpiar(texto):
    if not texto:
        return ""
    return re.sub(r'\s+', ' ', texto).strip()


async def click_seguro(locator, timeout=15000, force=False):
    try:
        overlay = locator.page.locator(".ui-widget-overlay")
        if await overlay.count() > 0:
            await overlay.first.wait_for(state="hidden", timeout=timeout)
        await locator.click(timeout=timeout, force=force)
        return True
    except PlaywrightTimeoutError:
        try:
            await locator.click(timeout=5000, force=True)
            return True
        except:
            return False


async def retroceder(page):
    try:
        XPath_retroceder = "/html/body/div[2]/div[2]/div[2]/div[1]/div/ol/li[3]/form/button"
        btn = page.locator(f"xpath={XPath_retroceder}")
        await click_seguro(btn)
        await page.wait_for_load_state("networkidle")
        return True
    except Exception as e:
        print(f"   ⚠️ Error al retroceder: {str(e)}")
        return False


# ──────────────────────────────────────────────────────────────
# NUEVA FUNCIÓN: navegar a una página específica del paginador
# ──────────────────────────────────────────────────────────────
async def navegar_a_pagina(page, pagina_destino):
    """
    Desde la página 1 (donde siempre cae tras retroceder),
    avanza con 'Sig.' hasta llegar a la página indicada.
    """
    for _ in range(pagina_destino - 1):
        try:
            next_btn = page.locator("button:has-text('Sig.')").last
            if await next_btn.count() and await next_btn.is_visible() and await next_btn.is_enabled():
                await click_seguro(next_btn)
                await page.wait_for_load_state("networkidle")
                await page.wait_for_timeout(1500)   # espera extra para PrimeFaces AJAX
            else:
                print(f"      ⚠️ No se pudo avanzar más allá de la página actual")
                break
        except Exception as e:
            print(f"      ⚠️ Error navegando a página {pagina_destino}: {e}")
            break


# ──────────────────────────────────────────────────────────────
# NUEVA FUNCIÓN: extraer ubicación desde la PÁGINA DE DETALLE
# ──────────────────────────────────────────────────────────────
async def extraer_ubicacion_desde_detalle(page):
    """
    Extrae la ubicación desde la vista de detalle (después de clic en 'Ver más').
    Es mucho más confiable que extraerla desde la tarjeta del listado.
    """
    try:
        # Método 1: fila que contiene el label "Ubicación:"
        fila = page.locator("div.row:has(span.sub-titulo:has-text('Ubicación:'))")
        if await fila.count() > 0:
            ubicacion_span = fila.first.locator("span.detalle-sp")
            if await ubicacion_span.count() > 0:
                ubicacion = limpiar(await ubicacion_span.first.text_content())
                if ubicacion:
                    print(f"      ✅ Ubicación desde detalle (fila): '{ubicacion}'")
                    return ubicacion

        # Método 2: sibling del span que dice "Ubicación"
        label = page.locator("span.sub-titulo:has-text('Ubicación')")
        if await label.count() > 0:
            sibling = label.first.locator("xpath=following-sibling::span[@class='detalle-sp']")
            if await sibling.count() > 0:
                ubicacion = limpiar(await sibling.first.text_content())
                if ubicacion:
                    print(f"      ✅ Ubicación desde detalle (sibling): '{ubicacion}'")
                    return ubicacion

        # Método 3: regex en el HTML completo de la página
        html = await page.content()
        match = re.search(r'Ubicación:\s*</span>\s*<span[^>]*class="detalle-sp"[^>]*>([^<]+)', html)
        if match:
            ubicacion = limpiar(match.group(1))
            print(f"      ✅ Ubicación desde detalle (regex): '{ubicacion}'")
            return ubicacion

    except Exception as e:
        print(f"      ⚠️ Error extrayendo ubicación desde detalle: {e}")

    return "No especificada"


async def extraer_ubicacion_desde_tarjeta(boton, pagina_actual, idx):
    """
    Extrae la ubicación desde la tarjeta contenedora del botón "Ver más".
    """
    print(f"      🔍 Extrayendo ubicación para botón {idx+1} (página {pagina_actual})")
    try:
        tarjeta = boton.locator("xpath=ancestor::div[contains(@class,'cuadro-vacantes')]")
        if await tarjeta.count() == 0:
            print(f"      ❌ No se encontró tarjeta para el botón {idx+1}")
            return "No especificada"

        # Método 1: span.detalle-sp hermano de "Ubicación:"
        ubicacion = await tarjeta.locator(
            "xpath=.//span[contains(text(),'Ubicación:')]/following-sibling::span[@class='detalle-sp']"
        ).first.text_content()

        if not ubicacion:
            fila = tarjeta.locator("div.row:has(span.sub-titulo:has-text('Ubicación:'))")
            if await fila.count():
                ubicacion = await fila.locator("span.detalle-sp").first.text_content()

        if ubicacion:
            ubicacion_limpia = limpiar(ubicacion)
            print(f"      ✅ Ubicación obtenida: '{ubicacion_limpia}'")
            return ubicacion_limpia

        # Método 3: regex en HTML de la tarjeta
        html = await tarjeta.inner_html()
        match = re.search(r'Ubicación:\s*</span>\s*<span[^>]*class="detalle-sp"[^>]*>([^<]+)', html)
        if match:
            ubicacion_limpia = limpiar(match.group(1))
            print(f"      ✅ Ubicación obtenida (regex): '{ubicacion_limpia}'")
            return ubicacion_limpia

        print(f"      ❌ No se pudo extraer ubicación para botón {idx+1}")
        return "No especificada"
    except Exception as e:
        print(f"      ⚠️ Error extrayendo ubicación: {e}")
        return "No especificada"


async def extraer_detalles_completos(page):
    detalles = {}

    # Número de folio
    try:
        folio_span = page.locator("div.cuadro-seccion-lat span.sub-titulo-2")
        if await folio_span.count():
            texto = limpiar(await folio_span.first.inner_text())
            match = re.search(r'N°\s*(\d+)', texto)
            detalles["NUMERO_FOLIO"] = match.group(1) if match else texto
    except:
        pass

    # PUESTO y ENTIDAD_AVISO
    try:
        puesto_elem = page.locator("span.sp-aviso0")
        if await puesto_elem.count():
            detalles["PUESTO"] = limpiar(await puesto_elem.first.inner_text())
        entidad_elem = page.locator("span.sp-aviso")
        if await entidad_elem.count():
            detalles["ENTIDAD_AVISO"] = limpiar(await entidad_elem.first.inner_text())
    except:
        pass

    # Contenedor principal
    xpath_contenedor = "/html/body/div[2]/div[2]/div[2]/form/div/div/div/div[1]/div[2]/div/div[2]/div"
    try:
        contenedor = page.locator(f"xpath={xpath_contenedor}")
        if await contenedor.count():
            html = await contenedor.first.inner_html()
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


async def setup_database():
    conn = await asyncpg.connect(**DB_CONFIG)
    exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", DB_SCRAPING_NAME)
    if not exists:
        await conn.execute(f"""
            CREATE DATABASE {DB_SCRAPING_NAME}
            ENCODING 'UTF8'
            LC_COLLATE 'C.UTF-8'
            LC_CTYPE 'C.UTF-8'
            TEMPLATE template0
        """)
        print(f"✅ Base de datos '{DB_SCRAPING_NAME}' creada.")
    else:
        print(f"ℹ️ Base de datos '{DB_SCRAPING_NAME}' ya existe.")
    await conn.close()

    config = DB_CONFIG.copy()
    config["database"] = DB_SCRAPING_NAME
    conn = await asyncpg.connect(**config)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS detalles_scraping (
            id SERIAL PRIMARY KEY,
            detalles_json JSONB NOT NULL,
            terminal TEXT,
            scraping_id TEXT,
            estado TEXT DEFAULT 'exitoso',
            error TEXT,
            timestamp_scraping TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_detalles_json ON detalles_scraping USING GIN (detalles_json)")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_terminal_estado ON detalles_scraping(terminal, estado)")
    await conn.close()
    print("📦 Tabla 'detalles_scraping' e índices listos.")


async def guardar_detalle(conn, detalles, terminal, scraping_id, estado='exitoso', error_msg=None):
    await conn.execute("""
        INSERT INTO detalles_scraping (detalles_json, terminal, scraping_id, estado, error)
        VALUES ($1, $2, $3, $4, $5)
    """,
        json.dumps(detalles, ensure_ascii=False),
        terminal,
        scraping_id,
        estado,
        error_msg
    )


# ──────────────────────────────────────────────────────────────
# FUNCIÓN CORREGIDA: scrape_rango
# ──────────────────────────────────────────────────────────────
async def scrape_rango(inicio_idx, fin_idx, terminal, scraping_id):
    config = DB_CONFIG.copy()
    config["database"] = DB_SCRAPING_NAME
    conn = await asyncpg.connect(**config)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"]
        )
        page = await browser.new_page()
        print(f"📍 [Rango {inicio_idx}-{fin_idx}] Navegando a {URL}...")
        await page.goto(URL)
        await page.wait_for_load_state("networkidle")

        pagina_actual = 1
        todas_las_vacantes_rango = []

        while pagina_actual <= MAX_PAGINAS:
            print(f"\n📄 [Rango {inicio_idx}-{fin_idx}] Página {pagina_actual}")
            await page.wait_for_load_state("networkidle")

            # ── Capturar botones de esta página ──
            botones_ver_mas = await page.locator(
                "span.ui-button-text.ui-c:has-text('¡Ver más!')"
            ).all()
            total_botones = len(botones_ver_mas)
            print(f"   [Rango {inicio_idx}-{fin_idx}] Se encontraron {total_botones} botones")

            for idx in range(inicio_idx, min(fin_idx, total_botones)):
                print(f"   [Rango {inicio_idx}-{fin_idx}] 🔹 Procesando botón {idx+1}/{total_botones}")
                try:
                    # ────────────────────────────────────────────────────────
                    # CAMBIO 1: Re-obtener los botones ANTES de cada iteración
                    # porque retroceder() re-renderiza el DOM completo y las
                    # referencias anteriores quedan huérfanas / desactualizadas.
                    # ────────────────────────────────────────────────────────
                    botones_frescos = await page.locator(
                        "span.ui-button-text.ui-c:has-text('¡Ver más!')"
                    ).all()

                    if idx >= len(botones_frescos):
                        print(f"      ⚠️ Índice {idx} fuera de rango tras re-fetch ({len(botones_frescos)} botones)")
                        break

                    boton = botones_frescos[idx]

                    # Extraer ubicación desde la tarjeta (método original)
                    ubicacion = await extraer_ubicacion_desde_tarjeta(boton, pagina_actual, idx)

                    # Hacer clic en "Ver más"
                    await click_seguro(boton)
                    await page.wait_for_load_state("networkidle")

                    # ────────────────────────────────────────────────────────
                    # CAMBIO 2: Extraer ubicación desde la PÁGINA DE DETALLE
                    # como fuente principal (más confiable que la tarjeta).
                    # Solo se usa la de la tarjeta como respaldo.
                    # ────────────────────────────────────────────────────────
                    detalles = await extraer_detalles_completos(page)

                    # Si la ubicación ya fue extraída por extraer_detalles_completos
                    # (aparece en el contenedor principal), usar esa.
                    # Si no, intentar extraerla de la página de detalle directamente.
                    if "Ubicación" in detalles:
                        ubicacion = detalles["Ubicación"]
                        print(f"      ✅ Ubicación tomada del detalle: '{ubicacion}'")
                    elif ubicacion == "No especificada":
                        ubicacion = await extraer_ubicacion_desde_detalle(page)

                    detalles["UBICACION"] = ubicacion

                    # Guardar
                    await guardar_detalle(
                        conn, detalles, terminal, scraping_id, estado='exitoso'
                    )
                    todas_las_vacantes_rango.append(detalles)
                    with open(
                        f"detalles_rango_{inicio_idx}_{fin_idx}.json",
                        "w", encoding="utf-8"
                    ) as f:
                        json.dump(todas_las_vacantes_rango, f, ensure_ascii=False, indent=2)
                    print(f"      ✅ Extracción completa. Claves: {list(detalles.keys())}")

                    # ────────────────────────────────────────────────────────
                    # CAMBIO 3: Después de retroceder, la paginación siempre
                    # vuelve a página 1. Hay que navegar de vuelta a la página
                    # que estábamos procesando.
                    # ────────────────────────────────────────────────────────
                    await retroceder(page)

                    if pagina_actual > 1:
                        print(f"      🔄 Restaurando página {pagina_actual}...")
                        await navegar_a_pagina(page, pagina_actual)

                except Exception as e:
                    print(f"      ❌ Error: {e}")
                    try:
                        await retroceder(page)
                        if pagina_actual > 1:
                            await navegar_a_pagina(page, pagina_actual)
                    except:
                        pass
                    await guardar_detalle(
                        conn, {}, terminal, scraping_id,
                        estado='fallido', error_msg=str(e)
                    )

            # ── Avanzar página ──
            try:
                next_btn = page.locator("button:has-text('Sig.')").last
                if (await next_btn.count()
                        and await next_btn.is_visible()
                        and await next_btn.is_enabled()):
                    await click_seguro(next_btn)
                    await page.wait_for_load_state("networkidle")
                    await page.wait_for_timeout(1500)  # espera extra para AJAX PrimeFaces
                    pagina_actual += 1
                else:
                    print(f"   [Rango {inicio_idx}-{fin_idx}] No se pudo avanzar. Fin.")
                    break
            except Exception as e:
                print(f"   Error al avanzar: {e}")
                break

        await browser.close()
    await conn.close()
    return todas_las_vacantes_rango


async def main():
    await setup_database()
    terminal = socket.gethostname()
    scraping_id = str(uuid.uuid4())
    print(f"🖥️ Terminal: {terminal} | ID scraping: {scraping_id}")

    rangos = [(0, 2), (2, 4), (4, 6), (6, 8), (8, 10)]
    tareas = [
        asyncio.create_task(scrape_rango(inicio, fin, terminal, scraping_id))
        for inicio, fin in rangos
    ]
    resultados = await asyncio.gather(*tareas)

    todas = []
    for res in resultados:
        todas.extend(res)

    with open("detalles_completo.json", "w", encoding="utf-8") as f:
        json.dump(todas, f, ensure_ascii=False, indent=2)

    print(f"\n✅ Total de detalles extraídos: {len(todas)}")
    for i, (inicio, fin) in enumerate(rangos, 1):
        print(f"   Worker {i} (rangos {inicio}-{fin}): {len(resultados[i-1])} extracciones")
    print(f"💾 Datos guardados en PostgreSQL base '{DB_SCRAPING_NAME}', tabla 'detalles_scraping'")


if __name__ == "__main__":
    asyncio.run(main())