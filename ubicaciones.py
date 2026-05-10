import psycopg2
import json

def obtener_ubicaciones_unicas():
    db_config = {
        "dbname": "convocatoria",
        "user": "postgres",
        "password": "artemisa99",
        "host": "localhost",
        "port": "5433"
    }

    try:
        conn = psycopg2.connect(**db_config)
        cur = conn.cursor()

        # Extraer todas las convocatorias exitosas
        cur.execute("""
            SELECT detalles_json
            FROM convocatorias
            WHERE estado = 'exitoso'
        """)
        rows = cur.fetchall()

        ubicaciones = set()

        for row in rows:
            blob = row[0]
            data = blob if isinstance(blob, dict) else json.loads(blob)

            # Misma lógica que en el script original
            ubicacion_raw = data.get("Ubicaci¾n", data.get("Ubicación", "No especificada"))
            # Capitalizar y limpiar
            if ubicacion_raw and ubicacion_raw != "No especificada":
                ubicacion_limpia = str(ubicacion_raw).strip().title()
                ubicaciones.add(ubicacion_limpia)

        # Mostrar resultados
        print("📍 Ubicaciones únicas encontradas:\n")
        for i, ub in enumerate(sorted(ubicaciones), 1):
            print(f"{i}. {ub}")

        print(f"\nTotal: {len(ubicaciones)} ubicaciones distintas.")

    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        if 'cur' in locals():
            cur.close()
        if 'conn' in locals():
            conn.close()

if __name__ == "__main__":
    obtener_ubicaciones_unicas()