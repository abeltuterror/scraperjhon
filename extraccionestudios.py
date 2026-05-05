import psycopg2
import json
import os
import re
from datetime import datetime

# ─── Funciones de transformación ───────────────────────────────────────────────

def extraer_tipo_contrato(numero_convocatoria):
    """Extrae el tipo de contrato del número de convocatoria"""
    if not numero_convocatoria:
        return "CAS"
    texto = str(numero_convocatoria).strip().upper()
    if "D.LEG 1057" in texto:
        return "CAS"
    elif "728" in texto:
        return "728"
    elif "276" in texto:
        return "276"
    else:
        return "CAS"

def limpiar_sueldo(texto):
    """Convierte 'S/. 2,296.00' a 2296 (int)"""
    if not texto:
        return 0
    limpio = str(texto).replace("S/.", "").replace("S/", "").replace(",", "").strip()
    if '.' in limpio:
        limpio = limpio.split('.')[0]
    try:
        return int(limpio)
    except ValueError:
        return 0

def formatear_fecha(texto):
    """Convierte '24/04/2026' a '2026-04-24'"""
    if not texto or texto == "N/A":
        return ""
    try:
        return datetime.strptime(str(texto).strip(), "%d/%m/%Y").strftime("%Y-%m-%d")
    except ValueError:
        return ""

def capitalizar(texto):
    """Pasa 'TÉCNICO MECÁNICO' a 'Técnico Mecánico'"""
    if not texto:
        return ""
    return str(texto).strip().title()

def dividir_texto_en_lista(texto):
    """Convierte un texto de requerimientos largos en una lista de strings limpios"""
    if not texto or "NO REQUIERE" in texto.upper():
        return []
    texto_limpio = texto.replace('\n', '. ').replace('•', '-').replace('*', '-')
    partes = re.split(r'\.\s+|\-\s+', texto_limpio)
    lista = [capitalizar(p.strip().rstrip('.')) for p in partes if p.strip() and len(p.strip()) > 5]
    return lista

def inferir_nivel(formacion, especializacion):
    """
    Devuelve una lista con TODOS los niveles educativos detectados en la formación y especialización.
    Ejemplo: ['Universitario', 'Bachiller Universitario']
    """
    niveles = set()
    f = str(formacion).upper()
    e = str(especializacion).upper()

    # Doctorado tiene prioridad semántica pero lo añadimos igual
    if "DOCTO" in e or "DOCTO" in f:
        niveles.add("Doctorado")
    if "MAESTR" in e or "MAESTR" in f:
        niveles.add("Maestría")
    if "UNIVERSIT" in f or "INGENIER" in f or "LICENCI" in f or "MEDICO" in f or "CIRUJANO" in f:
        niveles.add("Universitario")
    if "BACHILLER" in f:
        niveles.add("Bachiller Universitario")
    if "TECNICO" in f or "TECNOLOGO" in f:
        niveles.add("Técnico")

    if not niveles:
        niveles.add("No especificado")

    # Convertir a lista ordenada (opcional)
    return list(niveles)

def generar_documentos(niveles_lista):
    """
    Genera la lista de documentos estándar según la lista de niveles detectados.
    Acumula documentos sin duplicar.
    """
    base = ["Curriculum vitae", "Certificados de experiencia"]
    if not isinstance(niveles_lista, list):
        niveles_lista = [niveles_lista]

    if any(n in ["Universitario", "Bachiller Universitario", "Maestría", "Doctorado"] for n in niveles_lista):
        if "Título profesional" not in base:
            base.append("Título profesional")
        if "Colegiatura y habilitación" not in base:
            base.append("Colegiatura y habilitación")
    if any(n == "Técnico" for n in niveles_lista):
        if "Título o certificado técnico" not in base:
            base.append("Título o certificado técnico")
    return base

# ─── Proceso principal ─────────────────────────────────────────────────────────

def normalizar_y_guardar():
    db_config = {
        "dbname": "convocatoria",
        "user": "postgres",
        "password": "artemisa99",
        "host": "localhost",
        "port": "5433"
    }

    ruta_salida = "./public/datos.json"
    os.makedirs(os.path.dirname(ruta_salida), exist_ok=True)

    try:
        print("Conectando a la base de datos 'convocatoria'...")
        conn = psycopg2.connect(**db_config)
        cur = conn.cursor()

        # Ajusta el nombre de tu tabla (puede ser convocatorias o detalles_scraping)
        cur.execute("SELECT id, detalles_json FROM convocatorias WHERE estado = 'exitoso'")
        rows = cur.fetchall()
        print(f"Se encontraron {len(rows)} registros.")

        lista_limpia = []

        for row in rows:
            id_db, blob = row
            data = blob if isinstance(blob, dict) else json.loads(blob)

            # ── Claves de la nueva estructura ──
            titulo = capitalizar(data.get("PUESTO", "Sin título"))
            entidad = capitalizar(data.get("ENTIDAD_AVISO", "Desconocido"))
            ubicacion_raw = data.get("Ubicaci¾n", data.get("Ubicación", "No especificada"))
            ubicacion = capitalizar(ubicacion_raw)

            sueldo = limpiar_sueldo(data.get("REMUNERACIÓN", "0"))
            fecha_pub = formatear_fecha(data.get("FECHA INICIO DE PUBLICACIÓN", ""))
            fecha_limite = formatear_fecha(data.get("FECHA FIN DE PUBLICACIÓN", ""))
            nro_convocatoria = data.get("NÚMERO DE CONVOCATORIA", "")
            tipo_contrato = extraer_tipo_contrato(nro_convocatoria)
            numero_folio = data.get("NUMERO_FOLIO", "N/A")
            link_oficial = data.get("DETALLE", {}).get("url", "#")

            # ── Requerimientos ──
            req = data.get("REQUERIMIENTO", {})
            formacion = req.get("FORMACIÓN ACADÉMICA - PERFIL", "")
            especializacion = req.get("ESPECIALIZACIÓN", "")

            # Ahora nivel es una LISTA de niveles detectados
            niveles = inferir_nivel(formacion, especializacion)

            # Construir requisitos unificados
            requisitos = []
            if formacion and "NO REQUIERE" not in formacion.upper():
                requisitos.append(capitalizar(formacion.strip().rstrip('.')))
            requisitos.extend(dividir_texto_en_lista(req.get("EXPERIENCIA", "")))
            requisitos.extend(dividir_texto_en_lista(req.get("CONOCIMIENTO", "")))
            requisitos.extend(dividir_texto_en_lista(req.get("COMPETENCIAS", "")))
            if especializacion and "NO REQUIERE" not in especializacion.upper():
                requisitos.append(f"Especialización en {capitalizar(especializacion.strip())}")

            funciones = dividir_texto_en_lista(data.get("FUNCIONES", ""))

            # ── Objeto de salida ──
            item = {
                "id": id_db,
                "titulo": titulo,
                "entidad": entidad,
                "ubicacion": ubicacion,
                "sueldo": sueldo,
                "fechaPub": fecha_pub,
                "fechaLimite": fecha_limite,
                "nroConvocatoria": nro_convocatoria,
                "tipoContrato": tipo_contrato,
                "numero_folio": numero_folio,
                "nivel": niveles,   # lista de niveles (ej: ["Universitario", "Bachiller Universitario"])
                "descripcion": f"{entidad} requiere {titulo.lower()} para su sede en {ubicacion}.",
                "requisitos": requisitos,
                "requerimientos": {
                    "experiencia": req.get("EXPERIENCIA", ""),
                    "competencias": req.get("COMPETENCIAS", ""),
                    "conocimientos": req.get("CONOCIMIENTO", ""),
                    "especializacion": req.get("ESPECIALIZACIÓN", ""),
                    "formacion": req.get("FORMACIÓN ACADÉMICA - PERFIL", "")
                },
                "funciones": funciones if funciones else ["Funciones no especificadas en la convocatoria extraída"],
                "documentos": generar_documentos(niveles),
                "linkOficial": link_oficial,
                "modalidad": "Presencial"
            }
            lista_limpia.append(item)

        with open(ruta_salida, 'w', encoding='utf-8') as f:
            json.dump(lista_limpia, f, ensure_ascii=False, indent=4)

        print(f"✅ ¡Éxito! Se han normalizado {len(lista_limpia)} registros en '{ruta_salida}'.")

    except Exception as e:
        print(f"❌ Error al procesar: {e}")

    finally:
        if 'cur' in locals(): cur.close()
        if 'conn' in locals(): conn.close()

if __name__ == "__main__":
    normalizar_y_guardar()