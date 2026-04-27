import psycopg2
import json
import os

def extraer_tipo_contrato(numero_convocatoria):
    """Extrae el tipo de contrato del número de convocatoria"""
    if not numero_convocatoria:
        return "CAS"  # valor por defecto
    
    numero_str = str(numero_convocatoria).strip().upper()
    
    # Si comienza con D.LEG 1057 → CAS
    if numero_str.startswith("D.LEG 1057"):
        return "CAS"
    # Si comienza con 728 → 728
    elif numero_str.startswith("728"):
        return "728"
    # Si comienza con 276 → 276
    elif numero_str.startswith("276"):
        return "276"
    else:
        return "CAS"  # valor por defecto

def normalizar_y_guardar():
    # Configuración desde tus variables
    db_config = {
        "dbname": "convocatoria", # Usamos la base de datos donde está tu tabla
        "user": "postgres",
        "password": "artemisa99",
        "host": "localhost",
        "port": "5433"
    }
    
    # Ruta donde se guardará el JSON (dentro de tu proyecto frontend)
    ruta_salida = "./public/datos.json"
    os.makedirs(os.path.dirname(ruta_salida), exist_ok=True)

    try:
        # Conectar a la base de datos
        print("Conectando a la base de datos 'convocatoria'...")
        conn = psycopg2.connect(**db_config)
        cur = conn.cursor()

        # Extraer los datos
        print("Extrayendo datos de la tabla 'convocatorias'...")
        cur.execute("SELECT id, datos_completos FROM convocatorias6")
        rows = cur.fetchall()

        lista_limpia = []

        # Normalización
        for row in rows:
            id_db, blob = row
            # Si el JSON viene como string, lo parseamos
            data = blob if isinstance(blob, dict) else json.loads(blob)
            req = data.get("REQUERIMIENTO", {})
            numero_convocatoria = data.get("Número de Convocatoria", "")

            # Mapeo a estructura limpia
            item = {
                "id": id_db,
                "titulo": data.get("Título", "Sin título"),
                "entidad": data.get("Entidad", "Desconocido"),
                "ubicacion": data.get("Ubicación", "Sin ubicación"),
                "sueldo": data.get("Remuneración", "No especificado"),
                "fechaPub": data.get("Fecha Inicio de Publicación", "N/A"),
                "fechaLimite": data.get("Fecha Fin de Publicación", "N/A"),
                "nroConvocatoria": numero_convocatoria,
                "tipoContrato": extraer_tipo_contrato(numero_convocatoria),
                "numero_folio": data.get("NUMERO_FOLIO", "N/A"),
                "requerimientos": {
                    "experiencia": req.get("EXPERIENCIA", ""),
                    "competencias": req.get("COMPETENCIAS", ""),
                    "conocimientos": req.get("CONOCIMIENTO", ""),
                    "especializacion": req.get("ESPECIALIZACIÓN", ""),
                    "formacion": req.get("FORMACIÓN ACADÉMICA - PERFIL", "")
                },
                "linkOficial": data.get("DETALLE", {}).get("url", "#")
            }
            lista_limpia.append(item)

        # Guardar en archivo JSON
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