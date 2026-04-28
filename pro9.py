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
MAX_PAGINAS = 2  # número de páginas a procesar

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
    detalles = {}
    xpath_folio = "/html/body/div[2]/div[2]/div[2]/form/div/div/div/div[2]/div[3]/div"
    try:
        folio_elem = page.locator(f"xpath={xpath_folio}")
        if await folio_elem.count():
            texto = limpiar(await folio_elem.first.inner_text())
            match = re.search(r'N°\s*(\d+)', texto)
            detalles["NUMERO_FOLIO"] = match.group(1) if match else texto
    except:
        pass

    xpath_contenedor = "/html/body/div[2]/div[2]/div[2]/form/div/div/div/div[1]/div[2]/div/div[2]/div"
    try:
        contenedor = page.locator(f"xpath={xpath_contenedor}")
        if await contenedor.count():
            html = await contenedor.first.inner_html()
            from bs4 import BeautifulSoup
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
    # Tabla SIN columnas titulo y entidad
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS convocatorias7 (
            id SERIAL PRIMARY KEY,
            ubicacion TEXT,
            numero_convocatoria TEXT,
            cantidad_vacantes INTEGER,
            remuneracion NUMERIC(10,2),
            fecha_inicio DATE,
            fecha_fin DATE,
            numero_folio TEXT,
            datos_completos JSONB,
            terminal TEXT,
            scraping_id TEXT,
            estado TEXT DEFAULT 'exitoso',
            error TEXT,
            timestamp_scraping TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_ubicacion ON convocatorias7(ubicacion)")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_remuneracion ON convocatorias7(remuneracion)")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_terminal_estado ON convocatorias7(terminal, estado)")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_datos_completos ON convocatorias7 USING GIN (datos_completos)")
    await conn.close()
    print("📦 Tabla e índices listos (sin columnas redundantes).")

async def guardar_vacante(conn, vacante, terminal, scraping_id, estado='exitoso', error_msg=None):
    remun_str = vacante.get("Remuneración", "0")
    try:
        remun_val = float(re.sub(r'[^0-9.-]', '', remun_str))
    except:
        remun_val = 0.0

    cant_str = vacante.get("Cantidad de Vacantes", "0")
    try:
        cant_val = int(cant_str)
    except:
        cant_val = 0

    fecha_inicio = vacante.get("Fecha Inicio de Publicación")
    fecha_fin = vacante.get("Fecha Fin de Publicación")
    if fecha_inicio and re.match(r'\d{2}/\d{2}/\d{4}', fecha_inicio):
        fecha_inicio = datetime.strptime(fecha_inicio, "%d/%m/%Y").date()
    if fecha_fin and re.match(r'\d{2}/\d{2}/\d{4}', fecha_fin):
        fecha_fin = datetime.strptime(fecha_fin, "%d/%m/%Y").date()

    await conn.execute("""
        INSERT INTO convocatorias7 
        (ubicacion, numero_convocatoria, cantidad_vacantes, remuneracion,
         fecha_inicio, fecha_fin, numero_folio, datos_completos,
         terminal, scraping_id, estado, error)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
    """,
        vacante.get("Ubicación"),
        vacante.get("Número de Convocatoria"),
        cant_val,
        remun_val,
        fecha_inicio,
        fecha_fin,
        vacante.get("NUMERO_FOLIO"),
        json.dumps(vacante, ensure_ascii=False),
        terminal,
        scraping_id,
        estado,
        error_msg
    )

async def scrape_rango(inicio_idx, fin_idx, terminal, scraping_id):
    """
    Procesa todas las páginas (hasta MAX_PAGINAS) y en cada página solo las vacantes
    cuyos índices estén en [inicio_idx, fin_idx).
    """
    todas_vacantes = []
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
        while pagina_actual <= MAX_PAGINAS:
            print(f"\n📄 [Rango {inicio_idx}-{fin_idx}] Página {pagina_actual}")
            await page.wait_for_load_state("networkidle")

            content = await page.content()
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(content, "lxml")
            tarjetas = soup.find_all("div", class_="cuadro-vacantes")
            if not tarjetas:
                print(f"   [Rango {inicio_idx}-{fin_idx}] No hay más vacantes.")
                break

            total = len(tarjetas)
            print(f"   [Rango {inicio_idx}-{fin_idx}] Se encontraron {total} vacantes")
            botones_ver_mas = await page.locator("span.ui-button-text.ui-c:has-text('¡Ver más!')").all()

            for idx in range(inicio_idx, min(fin_idx, total)):
                tarjeta = tarjetas[idx]
                print(f"   [Rango {inicio_idx}-{fin_idx}] 🔹 Vacante {idx+1}/{total}")

                # Extraer datos de la tarjeta (título y entidad se guardan solo en el JSON)
                titulo_elem = tarjeta.find("div", class_="titulo-vacante")
                titulo = limpiar(titulo_elem.find("label").text) if titulo_elem and titulo_elem.find("label") else "N/A"
                entidad_elem = tarjeta.find("div", class_="nombre-entidad")
                entidad = "N/A"
                if entidad_elem:
                    span = entidad_elem.find("span", class_="detalle-sp")
                    if span:
                        entidad = limpiar(span.text)
                datos_tarjeta = {}
                for fila in tarjeta.find_all("div", class_="row box-mb"):
                    sub = fila.find("span", class_="sub-titulo")
                    det = fila.find("span", class_="detalle-sp")
                    if sub and det:
                        clave = limpiar(sub.text).rstrip(":")
                        valor = limpiar(det.text)
                        datos_tarjeta[clave] = valor
                vacante = {"Título": titulo, "Entidad": entidad, **datos_tarjeta}

                try:
                    if idx < len(botones_ver_mas):
                        print(f"      [Rango {inicio_idx}-{fin_idx}] 👆 Click en 'Ver más'...")
                        await click_seguro(botones_ver_mas[idx])
                        await page.wait_for_load_state("networkidle")
                        campos_extra = await extraer_detalles_completos(page)
                        vacante.update(campos_extra)
                        try:
                            xp_tit = page.locator("xpath=/html/body/div[2]/div[2]/div[2]/form/div/div/div/div[1]/div[1]/div/div[2]/div/span[1]")
                            vacante["Titulo_Aviso"] = limpiar(await xp_tit.inner_text()) if await xp_tit.count() else "N/A"
                            xp_inst = page.locator("xpath=/html/body/div[2]/div[2]/div[2]/form/div/div/div/div[1]/div[1]/div/div[2]/div/span[2]")
                            vacante["Institucion_Aviso"] = limpiar(await xp_inst.inner_text()) if await xp_inst.count() else "N/A"
                        except:
                            vacante["Titulo_Aviso"] = vacante["Institucion_Aviso"] = "N/A"
                        print(f"      [Rango {inicio_idx}-{fin_idx}] ✅ Extraídos: {list(campos_extra.keys())}")
                        await retroceder(page)
                    else:
                        vacante["Titulo_Aviso"] = vacante["Institucion_Aviso"] = "N/A"

                    await guardar_vacante(conn, vacante, terminal, scraping_id, estado='exitoso')
                except Exception as e:
                    print(f"      [Rango {inicio_idx}-{fin_idx}] ❌ Error: {e}")
                    await retroceder(page)
                    vacante["Titulo_Aviso"] = vacante["Institucion_Aviso"] = "N/A"
                    await guardar_vacante(conn, vacante, terminal, scraping_id, estado='fallido', error_msg=str(e))

                todas_vacantes.append(vacante)
                # Guardado incremental por rango
                with open(f"prueba_rango_{inicio_idx}_{fin_idx}.json", "w", encoding="utf-8") as f:
                    json.dump(todas_vacantes, f, ensure_ascii=False, indent=2)

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
    return todas_vacantes

async def main():
    await setup_database()
    terminal = socket.gethostname()
    scraping_id = str(uuid.uuid4())
    print(f"🖥️ Terminal: {terminal} | ID scraping: {scraping_id}")

    # Lanzamos dos tareas (rangos de índices 0-5 y 5-10)
    tarea1 = asyncio.create_task(scrape_rango(0, 5, terminal, scraping_id))
    tarea2 = asyncio.create_task(scrape_rango(5, 10, terminal, scraping_id))

    resultados1, resultados2 = await asyncio.gather(tarea1, tarea2)

    todas = resultados1 + resultados2
    with open("prueba_completo.json", "w", encoding="utf-8") as f:
        json.dump(todas, f, ensure_ascii=False, indent=2)

    print(f"\n✅ Total de vacantes extraídas: {len(todas)} (Rango1: {len(resultados1)}, Rango2: {len(resultados2)})")
    print(f"💾 Datos guardados en PostgreSQL base '{DB_SCRAPING_NAME}'")

if __name__ == "__main__":
    asyncio.run(main())