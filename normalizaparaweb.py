import psycopg2
import json
import os
import re
from datetime import datetime

# ─── Funciones de transformación ───────────────────────────────────────────────

def extraer_tipo_contrato(numero_convocatoria):
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
    if not texto or texto == "N/A":
        return ""
    try:
        return datetime.strptime(str(texto).strip(), "%d/%m/%Y").strftime("%Y-%m-%d")
    except ValueError:
        return ""

def capitalizar(texto):
    if not texto:
        return ""
    return str(texto).strip().title()

def dividir_texto_en_lista(texto):
    if not texto or "NO REQUIERE" in texto.upper():
        return []
    texto_limpio = texto.replace('\n', '. ').replace('•', '-').replace('*', '-')
    partes = re.split(r'\.\s+|\-\s+', texto_limpio)
    lista = [capitalizar(p.strip().rstrip('.')) for p in partes if p.strip() and len(p.strip()) > 5]
    return lista

def inferir_nivel(formacion, especializacion):
    """
    Analiza los textos de formación y especialización para devolver una **lista**
    con todos los niveles detectados.
    """
    f = str(formacion).upper()
    e = str(especializacion).upper()
    niveles = []

    # Buscar cada nivel de forma independiente
    if "MAESTR" in f or "MAESTR" in e:
        niveles.append("Maestría")
    if "DOCTO" in f or "DOCTO" in e:
        niveles.append("Doctorado")
    if "TECNICO" in f or "TECNOLOGO" in f:
        niveles.append("Técnico")
    # Palabras que indican estudios universitarios
    if any(kw in f for kw in ["UNIVERSIT", "BACHILLER", "INGENIER", "LICENCI", "MEDICO", "CIRUJANO"]):
        niveles.append("Universitario")

    # Eliminar duplicados manteniendo el orden
    niveles = list(dict.fromkeys(niveles))

    if not niveles:
        niveles.append("No especificado")
    return niveles

def generar_documentos(niveles):
    """
    Recibe una lista de niveles (p.ej. ["Universitario", "Maestría"])
    y devuelve la lista de documentos requeridos.
    """
    base = ["Curriculum vitae", "Certificados de experiencia"]
    tiene_universitario = any(n in ["Universitario", "Maestría", "Doctorado"] for n in niveles)
    tiene_tecnico = "Técnico" in niveles

    if tiene_universitario:
        base.extend(["Título profesional", "Colegiatura y habilitación"])
    elif tiene_tecnico:
        base.extend(["Título o certificado técnico"])
    return base

# ─── Proceso principal con filtro por fecha actual ─────────────────────────────

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

        print("Extrayendo datos de 'convocatorias' de hoy (estado exitoso)...")
        # 🔽 FILTRO POR FECHA ACTUAL
        cur.execute("""
            SELECT id, detalles_json 
            FROM convocatorias 
            WHERE estado = 'exitoso' 
              AND DATE(timestamp_scraping) = CURRENT_DATE
        """)
        rows = cur.fetchall()
        print(f"Se encontraron {len(rows)} registros de hoy.")

        lista_limpia = []

        for row in rows:
            id_db, blob = row
            data = blob if isinstance(blob, dict) else json.loads(blob)

            titulo = capitalizar(data.get("PUESTO", "Sin título"))
            entidad = capitalizar(data.get("ENTIDAD_AVISO", "Desconocido"))

            # CORRECCIÓN de clave con carácter especial
            ubicacion_raw = data.get("Ubicaci¾n", data.get("Ubicación", "No especificada"))
            ubicacion = capitalizar(ubicacion_raw)

            sueldo = limpiar_sueldo(data.get("REMUNERACIÓN", "0"))
            fecha_pub = formatear_fecha(data.get("FECHA INICIO DE PUBLICACIÓN", ""))
            fecha_limite = formatear_fecha(data.get("FECHA FIN DE PUBLICACIÓN", ""))
            nro_convocatoria = data.get("NÚMERO DE CONVOCATORIA", "")
            tipo_contrato = extraer_tipo_contrato(nro_convocatoria)
            numero_folio = data.get("NUMERO_FOLIO", "N/A")
            link_oficial = data.get("DETALLE", {}).get("url", "#")

            req = data.get("REQUERIMIENTO", {})
            formacion = req.get("FORMACIÓN ACADÉMICA - PERFIL", "")
            especializacion = req.get("ESPECIALIZACIÓN", "")

            # Lista de niveles
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
                "nivel": niveles,
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

        print(f"✅ ¡Éxito! Se han normalizado {len(lista_limpia)} registros (solo los de hoy) en '{ruta_salida}'.")

    except Exception as e:
        print(f"❌ Error al procesar: {e}")

    finally:
        if 'cur' in locals(): cur.close()
        if 'conn' in locals(): conn.close()

if __name__ == "__main__":
    normalizar_y_guardar()