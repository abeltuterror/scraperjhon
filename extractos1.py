import psycopg2
import json
import os
import re
from datetime import datetime

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
        conn = psycopg2.connect(**db_config)
        cur = conn.cursor()
        cur.execute("SELECT id, detalles_json FROM convocatoriabien WHERE estado = 'exitoso'")
        rows = cur.fetchall()
        print(f"Se encontraron {len(rows)} registros.")

        lista_limpia = []

        for row in rows:
            id_db, blob = row
            data = blob if isinstance(blob, dict) else json.loads(blob)

            # Usar las claves exactas que aparecen en el diagnóstico
            titulo = data.get("PUESTO", "Sin título")
            entidad = data.get("ENTIDAD_AVISO", "Desconocido")
            ubicacion = "No especificada"
            sueldo = limpiar_sueldo(data.get("REMUNERACIÓN", "0"))   # clave corregida
            fecha_pub = formatear_fecha(data.get("FECHA INICIO DE PUBLICACIÓN", ""))
            fecha_limite = formatear_fecha(data.get("FECHA FIN DE PUBLICACIÓN", ""))
            nro_convocatoria = data.get("NÚMERO DE CONVOCATORIA", "")
            tipo_contrato = extraer_tipo_contrato(nro_convocatoria)
            numero_folio = data.get("NUMERO_FOLIO", "N/A")
            link_oficial = data.get("DETALLE", {}).get("url", "#")

            req = data.get("REQUERIMIENTO", {})

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
                "requerimientos": {
                    "experiencia": req.get("EXPERIENCIA", ""),
                    "competencias": req.get("COMPETENCIAS", ""),
                    "conocimientos": req.get("CONOCIMIENTO", ""),
                    "especializacion": req.get("ESPECIALIZACIÓN", ""),
                    "formacion": req.get("FORMACIÓN ACADÉMICA - PERFIL", "")
                },
                "linkOficial": link_oficial
            }
            lista_limpia.append(item)

        with open(ruta_salida, 'w', encoding='utf-8') as f:
            json.dump(lista_limpia, f, ensure_ascii=False, indent=4)

        print(f"✅ Normalizados {len(lista_limpia)} registros en '{ruta_salida}'.")

    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        if 'cur' in locals(): cur.close()
        if 'conn' in locals(): conn.close()

if __name__ == "__main__":
    normalizar_y_guardar()