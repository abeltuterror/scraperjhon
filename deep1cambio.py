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

# Configuración PostgreSQL (para conectar al servidor)
DB_CONFIG = {
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "host": os.getenv("DB_HOST"),
    "port": int(os.getenv("DB_PORT")),
    "database": os.getenv("DB_NAME"),          # 'postgres' por defecto (para crear la DB)
    "server_settings": {"client_encoding": "UTF8"}  # Forzar UTF-8
}
DB_SCRAPING_NAME = os.getenv("DB_SCRAPING_NAME", "convocatoria")  # nombre de la base destino

URL = "https://app.servir.gob.pe/DifusionOfertasExterno/faces/consultas/ofertas_laborales.xhtml"

def limpiar(texto):
    """Limpia espacios múltiples sin tocar codificación (preserva acentos)."""
    if not texto:
        return ""
    return re.sub(r'\s+', ' ', texto).strip()

async def click_seguro(locator, timeout=15000, force=False):
    """Hace clic esperando que desaparezcan los overlays."""
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
    """Extrae REQUERIMIENTO, número de folio, etc. usando BeautifulSoup."""
    detalles = {}
    # Número de folio
    xpath_folio = "/html/body/div[2]/div[2]/div[2]/form/div/div/div/div[2]/div[3]/div"
    try:
        folio_elem = page.locator(f"xpath={xpath_folio}")
        if await folio_elem.count():
            texto = limpiar(await folio_elem.first.inner_text())
            match = re.search(r'N°\s*(\d+)', texto)
            if match:
                detalles["NUMERO_FOLIO"] = match.group(1)
            else:
                detalles["NUMERO_FOLIO"] = texto
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
                        valor = {
                            "texto": limpiar(enlace.get_text(strip=True)),
                            "url": enlace.get("href")
                        }
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
    """Crea la base de datos destino con UTF-8 y locale C.UTF-8, luego la tabla."""
    # Conectar al servidor (base por defecto)
    conn = await asyncpg.connect(**DB_CONFIG)
    # Verificar si la base destino existe
    exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", DB_SCRAPING_NAME)
    if not exists:
        # Usamos C.UTF-8 (funciona en Windows y evita problemas de acentos)
        await conn.execute(f"""
            CREATE DATABASE {DB_SCRAPING_NAME}
            ENCODING 'UTF8'
            LC_COLLATE 'C.UTF-8'
            LC_CTYPE 'C.UTF-8'
            TEMPLATE template0
        """)
        print(f"✅ Base de datos '{DB_SCRAPING_NAME}' creada con UTF-8 y C.UTF-8.")
    else:
        print(f"ℹ️ Base de datos '{DB_SCRAPING_NAME}' ya existe.")
    await conn.close()
    
    # Conectar a la base destino (con client_encoding UTF-8)
    config = DB_CONFIG.copy()
    config["database"] = DB_SCRAPING_NAME
    conn = await asyncpg.connect(**config)

    # Crear tabla si no existe
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS convocatorias (
            id SERIAL PRIMARY KEY,
            titulo TEXT,
            entidad TEXT,
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
            timestamp_scraping TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(numero_convocatoria, terminal)
        )
    """)
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_ubicacion ON convocatorias(ubicacion)")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_remuneracion ON convocatorias(remuneracion)")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_terminal_estado ON convocatorias(terminal, estado)")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_datos_completos ON convocatorias USING GIN (datos_completos)")
    await conn.close()
    print("📦 Tabla e índices listos.")

async def guardar_vacante(conn, vacante, terminal, scraping_id, estado='exitoso', error_msg=None):
    """Inserta o actualiza una vacante en PostgreSQL."""
    # Limpiar y convertir campos
    remun_str = vacante.get("Remuneración", "0")
    try:
        remun_val = float(re.sub(r'[^0-9.]', '', remun_str))
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
        INSERT INTO convocatorias 
        (titulo, entidad, ubicacion, numero_convocatoria, cantidad_vacantes,
         remuneracion, fecha_inicio, fecha_fin, numero_folio, datos_completos,
         terminal, scraping_id, estado, error)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
        ON CONFLICT (numero_convocatoria, terminal) DO UPDATE SET
            titulo = EXCLUDED.titulo,
            entidad = EXCLUDED.entidad,
            ubicacion = EXCLUDED.ubicacion,
            cantidad_vacantes = EXCLUDED.cantidad_vacantes,
            remuneracion = EXCLUDED.remuneracion,
            fecha_inicio = EXCLUDED.fecha_inicio,
            fecha_fin = EXCLUDED.fecha_fin,
            numero_folio = EXCLUDED.numero_folio,
            datos_completos = EXCLUDED.datos_completos,
            timestamp_scraping = CURRENT_TIMESTAMP,
            estado = EXCLUDED.estado,
            error = EXCLUDED.error
    """,
        vacante.get("Título"),
        vacante.get("Entidad"),
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

async def main():
    # Crear base de datos y tabla con encoding correcto
    await setup_database()

    # Conectar a la base destino
    config = DB_CONFIG.copy()
    config["database"] = DB_SCRAPING_NAME
    conn = await asyncpg.connect(**config)

    terminal = socket.gethostname()
    scraping_id = str(uuid.uuid4())
    print(f"🖥️ Terminal: {terminal} | ID scraping: {scraping_id}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, args=["--disable-blink-features=AutomationControlled"])
        page = await browser.new_page()
        print(f"📍 Navegando a {URL}...")
        await page.goto(URL)
        await page.wait_for_load_state("networkidle")

        todas_vacantes = []
        pagina_actual = 0
        sin_mas_vacantes = False

        while not sin_mas_vacantes:
            print(f"\n📄 Procesando página {pagina_actual + 1}")
            await page.wait_for_load_state("networkidle")

            content = await page.content()
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(content, "lxml")
            tarjetas = soup.find_all("div", class_="cuadro-vacantes")
            if not tarjetas:
                print("   No hay más vacantes.")
                break

            print(f"   Se encontraron {len(tarjetas)} vacantes")
            botones_ver_mas = await page.locator("span.ui-button-text.ui-c:has-text('¡Ver más!')").all()
            vacantes_procesadas = 0

            for idx, tarjeta in enumerate(tarjetas):
                print(f"   🔹 Vacante {idx+1}/{len(tarjetas)}")
                # Datos de la tarjeta
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
                        print(f"      👆 Click en 'Ver más'...")
                        await click_seguro(botones_ver_mas[idx])
                        await page.wait_for_load_state("networkidle")
                        campos_extra = await extraer_detalles_completos(page)
                        vacante.update(campos_extra)
                        # Título e institución del aviso
                        try:
                            xp_tit = page.locator("xpath=/html/body/div[2]/div[2]/div[2]/form/div/div/div/div[1]/div[1]/div/div[2]/div/span[1]")
                            vacante["Titulo_Aviso"] = limpiar(await xp_tit.inner_text()) if await xp_tit.count() else "N/A"
                        except:
                            vacante["Titulo_Aviso"] = "N/A"
                        try:
                            xp_inst = page.locator("xpath=/html/body/div[2]/div[2]/div[2]/form/div/div/div/div[1]/div[1]/div/div[2]/div/span[2]")
                            vacante["Institucion_Aviso"] = limpiar(await xp_inst.inner_text()) if await xp_inst.count() else "N/A"
                        except:
                            vacante["Institucion_Aviso"] = "N/A"
                        print(f"      ✅ Extraídos: {list(campos_extra.keys())}")
                        await retroceder(page)
                    else:
                        vacante["Titulo_Aviso"] = vacante["Institucion_Aviso"] = "N/A"

                    # Guardar en base de datos
                    await guardar_vacante(conn, vacante, terminal, scraping_id, estado='exitoso')
                    vacantes_procesadas += 1
                except Exception as e:
                    print(f"      ❌ Error: {e}")
                    await retroceder(page)
                    vacante["Titulo_Aviso"] = vacante["Institucion_Aviso"] = "N/A"
                    await guardar_vacante(conn, vacante, terminal, scraping_id, estado='fallido', error_msg=str(e))
                    vacantes_procesadas += 1

                todas_vacantes.append(vacante)

            # Paginación
            if vacantes_procesadas == 0:
                break
            else:
                try:
                    print(f"\n   ➡️ Buscando botón 'Sig.' para avanzar...")
                    next_btn = page.locator("button:has-text('Sig.')").last
                    if await next_btn.count() and await next_btn.is_visible() and await next_btn.is_enabled():
                        await click_seguro(next_btn)
                        await page.wait_for_load_state("networkidle")
                        pagina_actual += 1
                        print(f"   ✓ Pasando a página {pagina_actual + 1}")
                    else:
                        print("   ⚠️ Botón 'Sig.' no habilitado. Fin de paginación.")
                        sin_mas_vacantes = True
                except Exception as e:
                    print(f"   ⚠️ Error al buscar botón siguiente: {e}")
                    sin_mas_vacantes = True

        await browser.close()

    await conn.close()
    todas_vacantes.append(vacante)

    with open("prueba.json", "w", encoding="utf-8") as f:
        json.dump(todas_vacantes, f, ensure_ascii=False, indent=2)
    print(f"📄 Copia JSON guardada en 'prueba.json' ({len(todas_vacantes)} registros)")

    print(f"\n✅ Total de vacantes extraídas: {len(todas_vacantes)}")
    print(f"💾 Datos guardados en PostgreSQL base '{DB_SCRAPING_NAME}'")
    print(f"\n✅ Total de vacantes extraídas: {len(todas_vacantes)}")
    print(f"💾 Datos guardados en PostgreSQL base '{DB_SCRAPING_NAME}'")

if __name__ == "__main__":
    asyncio.run(main())