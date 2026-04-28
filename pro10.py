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
MAX_PAGINAS = 2  # Número de páginas a procesar (ajústalo según necesites)

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

async def extraer_detalles_completos(page):
    """
    Extrae TODA la información visible tras hacer clic en 'Ver más'.
    Incluye: PUESTO, ENTIDAD_AVISO, NUMERO_FOLIO, REQUERIMIENTO,
    DETALLE, CANTIDAD DE VACANTES, NÚMERO DE CONVOCATORIA,
    REMUNERACIÓN, FECHAS y cualquier sección adicional.
    """
    detalles = {}

    # 1. Número de folio (XPath fijo)
    xpath_folio = "/html/body/div[2]/div[2]/div[2]/form/div/div/div/div[2]/div[3]/div"
    try:
        folio_elem = page.locator(f"xpath={xpath_folio}")
        if await folio_elem.count():
            texto = limpiar(await folio_elem.first.inner_text())
            match = re.search(r'N°\s*(\d+)', texto)
            detalles["NUMERO_FOLIO"] = match.group(1) if match else texto
    except:
        pass

    # 2. PUESTO y ENTIDAD_AVISO (directamente con Playwright, seguro)
    try:
        puesto_elem = page.locator("span.sp-aviso0")
        if await puesto_elem.count():
            detalles["PUESTO"] = limpiar(await puesto_elem.first.inner_text())
        entidad_elem = page.locator("span.sp-aviso")
        if await entidad_elem.count():
            detalles["ENTIDAD_AVISO"] = limpiar(await entidad_elem.first.inner_text())
    except Exception as e:
        print(f"      ⚠️ Error extrayendo spans de aviso: {e}")

    # 3. Contenedor principal de la convocatoria (para REQUERIMIENTO, DETALLE, etc.)
    xpath_contenedor = "/html/body/div[2]/div[2]/div[2]/form/div/div/div/div[1]/div[2]/div/div[2]/div"
    try:
        contenedor = page.locator(f"xpath={xpath_contenedor}")
        if await contenedor.count():
            html = await contenedor.first.inner_html()
            soup = BeautifulSoup(html, "lxml")

            # --- REQUERIMIENTO (lista) ---
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

            # --- Otros campos (DETALLE, vacantes, convocatoria, remuneración, fechas) ---
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

            # --- Sección adicional (si existe) ---
            divs_hijos = soup.find_all("div", recursive=False)
            if len(divs_hijos) >= 3:
                tercer_div = divs_hijos[2]
                div_extra = tercer_div.find("div")
                if div_extra:
                    contenido = limpiar(div_extra.get_text(strip=True))
                    if contenido:
                        detalles["SECCION_ADICIONAL"] = contenido
    except Exception as e:
        print(f"      ⚠️ Error extrayendo detalles del contenedor: {e}")

    return detalles

async def setup_database():
    """Crea la base de datos y la tabla detalles_scraping."""
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
    """Guarda el JSON de detalles en la tabla."""
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

async def scrape_rango(inicio_idx, fin_idx, terminal, scraping_id):
    """
    Procesa todas las páginas (hasta MAX_PAGINAS) y en cada página solo las vacantes
    cuyos índices estén en [inicio_idx, fin_idx). Extrae TODO tras clic en 'Ver más'.
    """
    config = DB_CONFIG.copy()
    config["database"] = DB_SCRAPING_NAME
    conn = await asyncpg.connect(**config)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, args=["--disable-blink-features=AutomationControlled"])
        page = await browser.new_page()
        print(f"📍 [Rango {inicio_idx}-{fin_idx}] Navegando a {URL}...")
        await page.goto(URL)
        await page.wait_for_load_state("networkidle")

        pagina_actual = 1
        todas_las_vacantes_rango = []

        while pagina_actual <= MAX_PAGINAS:
            print(f"\n📄 [Rango {inicio_idx}-{fin_idx}] Página {pagina_actual}")
            await page.wait_for_load_state("networkidle")

            # Obtener todos los botones "¡Ver más!" de la página actual
            botones_ver_mas = await page.locator("span.ui-button-text.ui-c:has-text('¡Ver más!')").all()
            total_botones = len(botones_ver_mas)
            print(f"   [Rango {inicio_idx}-{fin_idx}] Se encontraron {total_botones} botones 'Ver más'")

            # Procesar solo el rango de índices
            for idx in range(inicio_idx, min(fin_idx, total_botones)):
                print(f"   [Rango {inicio_idx}-{fin_idx}] 🔹 Procesando botón {idx+1}/{total_botones}")

                try:
                    # Hacer clic en el botón correspondiente
                    await click_seguro(botones_ver_mas[idx])
                    await page.wait_for_load_state("networkidle")

                    # Extraer TODOS los detalles de la vista expandida
                    detalles = await extraer_detalles_completos(page)

                    # Guardar en PostgreSQL
                    await guardar_detalle(conn, detalles, terminal, scraping_id, estado='exitoso')

                    # Guardar en JSON local (opcional)
                    todas_las_vacantes_rango.append(detalles)
                    with open(f"detalles_rango_{inicio_idx}_{fin_idx}.json", "w", encoding="utf-8") as f:
                        json.dump(todas_las_vacantes_rango, f, ensure_ascii=False, indent=2)

                    print(f"      ✅ Extracción completa: {list(detalles.keys())}")

                    # Retroceder para volver a la lista principal
                    await retroceder(page)

                except Exception as e:
                    print(f"      ❌ Error procesando botón {idx+1}: {e}")
                    await retroceder(page)
                    await guardar_detalle(conn, {}, terminal, scraping_id, estado='fallido', error_msg=str(e))

            # Avanzar a la siguiente página
            try:
                next_btn = page.locator("button:has-text('Sig.')").last
                if await next_btn.count() and await next_btn.is_visible() and await next_btn.is_enabled():
                    await click_seguro(next_btn)
                    await page.wait_for_load_state("networkidle")
                    pagina_actual += 1
                else:
                    print(f"   [Rango {inicio_idx}-{fin_idx}] No se pudo avanzar más. Fin.")
                    break
            except Exception as e:
                print(f"   [Rango {inicio_idx}-{fin_idx}] Error al avanzar: {e}")
                break

        await browser.close()
    await conn.close()
    return todas_las_vacantes_rango

async def main():
    await setup_database()
    terminal = socket.gethostname()
    scraping_id = str(uuid.uuid4())
    print(f"🖥️ Terminal: {terminal} | ID scraping: {scraping_id}")

    # Ajusta los rangos según el número de botones por página (ejemplo: 0-5 y 5-10)
    tarea1 = asyncio.create_task(scrape_rango(0, 5, terminal, scraping_id))
    tarea2 = asyncio.create_task(scrape_rango(5, 10, terminal, scraping_id))

    resultados1, resultados2 = await asyncio.gather(tarea1, tarea2)

    todas = resultados1 + resultados2
    with open("detalles_completo.json", "w", encoding="utf-8") as f:
        json.dump(todas, f, ensure_ascii=False, indent=2)

    print(f"\n✅ Total de detalles extraídos: {len(todas)} (Rango1: {len(resultados1)}, Rango2: {len(resultados2)})")
    print(f"💾 Datos guardados en PostgreSQL base '{DB_SCRAPING_NAME}', tabla 'detalles_scraping'")

if __name__ == "__main__":
    asyncio.run(main())