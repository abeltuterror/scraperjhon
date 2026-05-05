import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()

DB_CONFIG = {
    "dbname": os.getenv("DB_NAME", "postgres"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "host": os.getenv("DB_HOST"),
    "port": int(os.getenv("DB_PORT", 5432))
}
DB_SCRAPING_NAME = os.getenv("DB_SCRAPING_NAME", "convocatoria")

def ver_columnas():
    # Conectar a la base de datos que contiene la tabla
    config = DB_CONFIG.copy()
    config["dbname"] = DB_SCRAPING_NAME
    conn = psycopg2.connect(**config)
    cur = conn.cursor()

    print(f"=== TABLA: detalles_scraping (base: {DB_SCRAPING_NAME}) ===\n")

    # 1. Listar columnas de la tabla
    cur.execute("""
        SELECT column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_name = 'detalles_scraping'
        ORDER BY ordinal_position;
    """)
    columnas = cur.fetchall()
    print("COLUMNAS DE LA TABLA:")
    print(f"{'Nombre':<25} {'Tipo':<20} {'Nullable':<10}")
    print("-" * 55)
    for col, tipo, nullable in columnas:
        print(f"{col:<25} {tipo:<20} {nullable:<10}")

    # 2. Ver algunos registros y la ubicación extraída del JSON
    print("\n" + "="*55)
    print("MUESTRA DE REGISTROS (UBICACIÓN DESDE JSON):")
    cur.execute("""
        SELECT id, detalles_json->>'UBICACION' AS ubicacion,
               detalles_json->>'PUESTO' AS puesto,
               detalles_json->>'ENTIDAD_AVISO' AS entidad
        FROM detalles_scraping
        WHERE estado = 'exitoso'
        LIMIT 5;
    """)
    muestras = cur.fetchall()
    if muestras:
        print(f"{'ID':<6} {'UBICACION':<35} {'PUESTO':<30} {'ENTIDAD'}")
        print("-" * 100)
        for row in muestras:
            print(f"{row[0]:<6} {str(row[1])[:35]:<35} {str(row[2])[:30]:<30} {str(row[3])[:30]}")
    else:
        print("No hay registros exitosos en la tabla.")

    cur.close()
    conn.close()

if __name__ == "__main__":
    ver_columnas()