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

MESES_ES = ["enero","febrero","marzo","abril","mayo","junio","julio","agosto","septiembre","octubre","noviembre","diciembre"]

def fecha_larga(fecha_iso):
    if not fecha_iso:
        return ""
    try:
        dt = datetime.strptime(fecha_iso, "%Y-%m-%d")
        return f"{dt.day} de {MESES_ES[dt.month - 1]} de {dt.year}"
    except ValueError:
        return fecha_iso

def capitalizar(texto):
    if not texto:
        return ""
    return str(texto).strip().title()

def sentence_case(texto):
    if not texto:
        return None
    s = str(texto).strip().lower()
    return s[0].upper() + s[1:] if s else None

def parse_campo(texto):
    if not texto or str(texto).strip() == "":
        return None
    if str(texto).strip().strip('-').strip() == "":
        return None
    limpio = re.sub(r'\s+', ' ', str(texto).replace('*', '')).strip()

    items = None
    if '¿' in limpio:
        items = limpio.split('¿')
    elif '•' in limpio:
        items = limpio.split('•')
    elif re.match(r'^-\s', limpio):
        items = re.split(r'\s*-\s+(?=[a-záéíóúñA-ZÁÉÍÓÚÑ0-9])', limpio)

    if items:
        clean = [
            sentence_case(re.sub(r'^[-•¿]\s*', '', s).rstrip('.,').strip())
            for s in items
        ]
        clean = [s for s in clean if s and len(s) > 1]
        return clean[0] if len(clean) == 1 else clean

    return sentence_case(limpio)

def parse_competencias(texto):
    if not texto:
        return []
    items = []
    if '¿' in texto:
        items = texto.split('¿')
    elif '•' in texto:
        items = texto.split('•')
    elif re.search(r' - [A-ZÁÉÍÓÚÑA-Za-z]', texto):
        items = re.split(r' - (?=[A-ZÁÉÍÓÚÑA-Za-záéíóúñ])', texto)
    elif re.search(r'\.\s+[A-ZÁÉÍÓÚÑ]', texto):
        items = re.split(r'\.\s+', texto)
    else:
        items = texto.split(',')

    result = []
    for s in items:
        clean = re.sub(r'[¿•.,]', ' ', s)
        clean = re.sub(r'\s+', ' ', clean).strip()
        clean = capitalizar(clean)
        if len(clean) > 1 and not clean.endswith(':'):
            result.append(clean)
    return result

def dividir_texto_en_lista(texto):
    if not texto or texto.strip().upper() == "NO REQUIERE":
        return []
    texto_limpio = texto.replace('\n', '. ').replace('•', '-').replace('*', '')
    partes = re.split(r'\.\s+|\-\s+', texto_limpio)
    lista = []
    for p in partes:
        item = p.strip()
        if item.startswith('¿'):
            item = item[1:].strip()
        item = capitalizar(item.rstrip('.'))
        if item and len(item) > 5 and not item.endswith(':'):
            lista.append(item)
    return lista

def inferir_nivel(formacion, especializacion):
    f = str(formacion).upper()
    e = str(especializacion).upper()
    niveles = []

    if "MAESTR" in f or "MAESTR" in e:
        niveles.append("Maestría")
    if "DOCTO" in f or "DOCTO" in e:
        niveles.append("Doctorado")
    if "TECNICO" in f or "TECNOLOGO" in f:
        niveles.append("Técnico")
    if any(kw in f for kw in ["UNIVERSIT", "BACHILLER", "INGENIER", "LICENCI", "MEDICO", "CIRUJANO"]):
        niveles.append("Universitario")

    niveles = list(dict.fromkeys(niveles))

    if not niveles:
        niveles.append("No especificado")
    return niveles

def generar_documentos(niveles):
    base = ["Curriculum vitae", "Certificados de experiencia"]
    tiene_universitario = any(n in ["Universitario", "Maestría", "Doctorado"] for n in niveles)
    tiene_tecnico = "Técnico" in niveles

    if tiene_universitario:
        base.extend(["Título profesional", "Colegiatura y habilitación"])
    elif tiene_tecnico:
        base.extend(["Título o certificado técnico"])
    return base

def calcular_indexable(convocatoria):
    FRASES_GENERICAS = [
        "según bases que serán publicadas en el portal institucional"
    ]
    
    descripcion = convocatoria.get("descripcion", "")
    if not descripcion or len(descripcion) <= 50:
        return False
    
    requisitos = convocatoria.get("requisitos", [])
    if not isinstance(requisitos, list):
        return False
    
    requisitos_validos = []
    for req in requisitos:
        req_lower = req.lower()
        es_generico = False
        for frase in FRASES_GENERICAS:
            if frase in req_lower:
                es_generico = True
                break
        if not es_generico:
            requisitos_validos.append(req)
    
    if len(requisitos_validos) < 2:
        return False
    
    sueldo = convocatoria.get("sueldo", 0)
    if not isinstance(sueldo, (int, float)) or sueldo <= 0:
        return False
    
    return True

# ─── NUEVA: Clasificador de errores de sueldo ──────────────────────────────────

def clasificar_error_sueldo(sueldo):
    """
    Retorna un código de error según los umbrales absolutos.
    0 = OK
    1 = Error absoluto bajo: sueldo < 400
    2 = Error absoluto alto: sueldo > 20,000
    """
    if sueldo <= 0:
        return 1  # Sueldo 0 o negativo también es error bajo
    if sueldo < 400:
        return 1
    if sueldo > 20000:
        return 2
    return 0

def obtener_descripcion_error(codigo):
    """Retorna la descripción legible del código de error."""
    descripciones = {
        0: "Sin errores",
        1: "Error absoluto bajo: sueldo < S/ 400",
        2: "Error absoluto alto: sueldo > S/ 20,000"
    }
    return descripciones.get(codigo, "Código desconocido")

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
    ruta_advertencias = "./public/advertencias_sueldos.json"
    os.makedirs(os.path.dirname(ruta_salida), exist_ok=True)

    try:
        print("Conectando a la base de datos 'convocatoria'...")
        conn = psycopg2.connect(**db_config)
        cur = conn.cursor()

        print("Extrayendo datos de 'convocatorias' para la fecha de hoy...")
        cur.execute("""
            SELECT id, detalles_json
            FROM convocatorias
            WHERE estado = 'exitoso'
            AND timestamp_scraping >= NOW() - INTERVAL '3 hours'
            ORDER BY timestamp_scraping DESC
        """)
        rows = cur.fetchall()
        print(f"Se encontraron {len(rows)} registros en total.")

        lista_limpia = []
        advertencias = []  # Lista paralela para el JSON de advertencias

        for row in rows:
            id_db, blob = row
            data = blob if isinstance(blob, dict) else json.loads(blob)

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
            vacantes = data.get("NÚMERO DE VACANTES", data.get("VACANTES", 1))
            link_oficial = data.get("DETALLE", {}).get("url", "#")

            req = data.get("REQUERIMIENTO", {})
            formacion = req.get("FORMACIÓN ACADÉMICA - PERFIL", "")
            especializacion = req.get("ESPECIALIZACIÓN", "")

            niveles = inferir_nivel(formacion, especializacion)

            requisitos = []
            requisitos.extend(dividir_texto_en_lista(formacion))
            requisitos.extend(dividir_texto_en_lista(req.get("EXPERIENCIA", "")))
            requisitos.extend(dividir_texto_en_lista(req.get("CONOCIMIENTO", "")))
            requisitos.extend(dividir_texto_en_lista(req.get("COMPETENCIAS", "")))
            espec_limpia = especializacion.strip().strip('-').strip()
            if espec_limpia and "NO REQUIERE" not in espec_limpia.upper():
                requisitos.append(f"Especialización en {capitalizar(espec_limpia)}")

            visto = set()
            req_dedup = []
            for r in requisitos:
                clave = r.lower()
                if clave not in visto:
                    visto.add(clave)
                    req_dedup.append(r)
            requisitos = req_dedup

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
                "descripcion": f"Convocatoria {tipo_contrato} para {titulo} en {entidad}, sede {ubicacion}. Remuneración mensual S/ {sueldo}. {vacantes} vacante(s). Fecha límite: {fecha_larga(fecha_limite)}.",
                "requisitos": requisitos,
                "requerimientos": {
                    "experiencia": parse_campo(req.get("EXPERIENCIA", "")),
                    "competencias": parse_competencias(req.get("COMPETENCIAS", "")),
                    "conocimientos": parse_campo(req.get("CONOCIMIENTO", "")),
                    "especializacion": parse_campo(req.get("ESPECIALIZACIÓN", "")),
                    "formacion": parse_campo(req.get("FORMACIÓN ACADÉMICA - PERFIL", ""))
                },
                "funciones": funciones if funciones else ["Funciones no especificadas en la convocatoria extraída"],
                "documentos": generar_documentos(niveles),
                "linkOficial": link_oficial,
                "modalidad": "Presencial"
            }
            
            item["indexable"] = calcular_indexable(item)
            
            # ─── CLASIFICACIÓN DE ERROR DE SUELDO ─────────────────────────
            error_code = clasificar_error_sueldo(sueldo)
            item["error_sueldo"] = error_code
            
            lista_limpia.append(item)
            
            # Si tiene error, lo agregamos al JSON de advertencias
            if error_code != 0:
                advertencia = {
                    "id": id_db,
                    "titulo": titulo,
                    "entidad": entidad,
                    "ubicacion": ubicacion,
                    "sueldo": sueldo,
                    "error_code": error_code,
                    "error_descripcion": obtener_descripcion_error(error_code),
                    "fechaLimite": fecha_limite,
                    "nroConvocatoria": nro_convocatoria,
                    "tipoContrato": tipo_contrato,
                    "linkOficial": link_oficial
                }
                advertencias.append(advertencia)

        # ─── GUARDAR DATOS PRINCIPALES ────────────────────────────────────
        with open(ruta_salida, 'w', encoding='utf-8') as f:
            json.dump(lista_limpia, f, ensure_ascii=False, indent=4)
        print(f"✅ Éxito! {len(lista_limpia)} registros normalizados en '{ruta_salida}'.")

        # ─── GUARDAR ADVERTENCIAS ─────────────────────────────────────────
        if advertencias:
            # Ordenar: primero los errores altos (código 2) por sueldo descendente, luego los bajos (código 1)
            advertencias.sort(key=lambda x: (x['error_code'], -x['sueldo']), reverse=True)
            
            resumen = {
                "fecha_generacion": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "total_advertencias": len(advertencias),
                "errores_bajos": sum(1 for a in advertencias if a['error_code'] == 1),
                "errores_altos": sum(1 for a in advertencias if a['error_code'] == 2),
                "advertencias": advertencias
            }
            
            with open(ruta_advertencias, 'w', encoding='utf-8') as f:
                json.dump(resumen, f, ensure_ascii=False, indent=4)
            print(f"⚠️  {len(advertencias)} advertencias de sueldo guardadas en '{ruta_advertencias}'.")
            print(f"   - Errores bajos (< S/ 400): {resumen['errores_bajos']}")
            print(f"   - Errores altos (> S/ 20,000): {resumen['errores_altos']}")
        else:
            print("✅ No se encontraron errores de sueldo. No se generó archivo de advertencias.")

    except Exception as e:
        print(f"❌ Error al procesar: {e}")
        import traceback
        traceback.print_exc()

    finally:
        if 'cur' in locals(): cur.close()
        if 'conn' in locals(): conn.close()

if __name__ == "__main__":
    normalizar_y_guardar()