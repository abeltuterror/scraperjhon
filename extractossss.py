import psycopg2
import json
import os
import re
from datetime import datetime

def extraer_tipo_contrato(numero_convocatoria):
    """Extrae el tipo de contrato del número de convocatoria"""
    if not numero_convocatoria:
        return "CAS"
    
    numero_str = str(numero_convocatoria).strip().upper()
    
    if "1057" in numero_str:
        return "CAS"
    elif "728" in numero_str:
        return "D.L. 728"
    elif "276" in numero_str:
        return "276"
    else:
        return "CAS"

def limpiar_sueldo(texto):
    """Convierte 'S/. 2,296.00' a 2296 (int)"""
    if not texto or texto == "No especificado":
        return 0
    # Eliminar 'S/.', 'S/', comas y espacios
    limpio = str(texto).replace("S/.", "").replace("S/", "").replace(",", "").strip()
    try:
        return int(float(limpio))
    except ValueError:
        return 0

def formatear_fecha(texto):
    """Convierte '24/04/2026' a '2026-04-24'"""
    if not texto or texto == "N/A":
        return ""
    try:
        return datetime.strptime(str(texto).strip(), "%d/%m/%Y").strftime("%Y-%m-%d")
    except ValueError:
        return str(texto)

def capitalizar(texto):
    """Pasa 'TÉCNICO MECÁNICO' a 'Técnico Mecánico'"""
    if not texto:
        return ""
    return str(texto).strip().title()

def dividir_texto_en_lista(texto):
    """Convierte un texto de requerimientos largos en una lista de strings limpios"""
    if not texto or "NO REQUIERE" in texto.upper():
        return []
    
    # Reemplazar saltos de línea y viñetas por un separador uniforme
    texto_limpio = texto.replace('\n', '. ').replace('•', '-').replace('*', '-')
    
    # Separar por puntos o guiones seguidos de espacio
    partes = re.split(r'\.\s+|\-\s+', texto_limpio)
    
    # Limpiar, capitalizar y filtrar vacíos
    lista = [capitalizar(p.strip().rstrip('.')) for p in partes if p.strip() and len(p.strip()) > 5]
    return lista

def inferir_nivel(formacion, especializacion):
    """Infiere el nivel educativo basado en el texto de formación"""
    f = str(formacion).upper()
    e = str(especializacion).upper()
    
    if "MAESTR" in e or "MAESTR" in f: return "Maestría"
    if "DOCTO" in e or "DOCTO" in f: return "Doctorado"
    if "TECNICO" in f or "TECNOLOGO" in f: return "Técnico"
    if "UNIVERSIT" in f or "BACHILLER" in f or "INGENIER" in f or "LICENCI" in f or "MEDICO" in f or "CIRUJANO" in f: return "Universitario"
    return "No especificado"

def generar_documentos(nivel):
    """Genera la lista de documentos estándar según el nivel"""
    base = ["Curriculum vitae", "Certificados de experiencia"]
    if nivel in ["Universitario", "Maestría", "Doctorado"]:
        base.extend(["Título profesional", "Colegiatura y habilitación"])
    elif nivel == "Técnico":
        base.extend(["Título o certificado técnico"])
    return base

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

        print("Extrayendo datos de la tabla 'convocatorias6'...")
        cur.execute("SELECT id, datos_completos FROM convocatorias6")
        rows = cur.fetchall()

        lista_limpia = []

        for row in rows:
            id_db, blob = row
            data = blob if isinstance(blob, dict) else json.loads(blob)
            req = data.get("REQUERIMIENTO", {})
            numero_convocatoria = data.get("Número de Convocatoria", "")
            
            # Variables base
            entidad = capitalizar(data.get("Entidad", "Desconocido"))
            titulo = capitalizar(data.get("Título", "Sin título"))
            ubicacion = capitalizar(data.get("Ubicación", "Sin ubicación"))
            formacion = req.get("FORMACIÓN ACADÉMICA - PERFIL", "")
            especializacion = req.get("ESPECIALIZACIÓN", "")
            nivel = inferir_nivel(formacion, especializacion)
            
            # Construir requisitos unificados (Formación + Experiencia + Conocimientos)
            requisitos = []
            if formacion and "NO REQUIERE" not in formacion.upper():
                requisitos.append(capitalizar(formacion.strip().rstrip('.')))
            requisitos.extend(dividir_texto_en_lista(req.get("EXPERIENCIA", "")))
            requisitos.extend(dividir_texto_en_lista(req.get("CONOCIMIENTO", "")))
            requisitos.extend(dividir_texto_en_lista(req.get("COMPETENCIAS", "")))
            
            # Si hay especialización que no sea "NO REQUIERE", añadirla
            if especializacion and "NO REQUIERE" not in especializacion.upper():
                requisitos.append(f"Especialización en {capitalizar(especializacion.strip())}")

            # Construir funciones (Si existiera en el JSON, si no, lista vacía o inferir de experiencia)
            # Asumiendo que a veces viene en "DETALLE" o no viene, dejamos lógica preparada
            funciones = dividir_texto_en_lista(data.get("FUNCIONES", ""))

            item = {
                "id": id_db,
                "titulo": titulo,
                "entidad": entidad,
                "ubicacion": ubicacion,
                "sueldo": limpiar_sueldo(data.get("Remuneración", "0")),
                "fechaPub": formatear_fecha(data.get("Fecha Inicio de Publicación", "")),
                "fechaLimite": formatear_fecha(data.get("Fecha Fin de Publicación", "")),
                "tipoContrato": extraer_tipo_contrato(numero_convocatoria),
                "nivel": nivel,
                "descripcion": f"{entidad} requiere {titulo.lower()} para su sede en {ubicacion}.", # Generada dinámicamente
                "requisitos": requisitos,
                "funciones": funciones if funciones else ["Funciones no especificadas en la convocatoria extraída"],
                "documentos": generar_documentos(nivel),
                "linkOficial": data.get("DETALLE", {}).get("url", "#"),
                "modalidad": "Presencial" # Por defecto en convocatorias públicas CAS
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