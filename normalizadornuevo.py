import json
import re
from datetime import datetime

ENTRADA = "./detalles_normalizado.json"
SALIDA  = "./datos_normalizado.json"

PLACEHOLDER_PATTERNS = [
    "SEGÚN BASES", "SEGUN BASES", "POR DETERMINAR",
    "NO APLICA", "NO REQUIERE", "PROPIAS AL CARGO",
    "PROPIOS AL CARGO", "VER BASES", "A DETERMINAR"
]

def es_placeholder(texto: str) -> bool:
    t = texto.upper().strip()
    return any(p in t for p in PLACEHOLDER_PATTERNS)

def capitalizar(texto: str) -> str:
    if not texto:
        return ""
    return str(texto).strip().title()

def limpiar_texto(texto: str) -> str:
    return str(texto).strip().strip('•').strip('-').strip('*').strip()

def a_lista(valor) -> list[str]:
    """Convierte string o lista a lista limpia de strings."""
    if not valor:
        return []
    if isinstance(valor, list):
        items = []
        for v in valor:
            items.extend(a_lista(v))
        return items
    # Es string — dividir por saltos, bullets o puntos seguidos de mayúscula
    texto = str(valor).replace('•', '\n').replace('\r', '\n')
    partes = re.split(r'\n+', texto)
    resultado = []
    for p in partes:
        p = limpiar_texto(p)
        if p and len(p) > 8 and not p.endswith(':'):
            resultado.append(capitalizar(p))
    return resultado

def deduplicar(lista: list[str]) -> list[str]:
    visto = set()
    resultado = []
    for item in lista:
        clave = item.upper().strip()
        if clave not in visto:
            visto.add(clave)
            resultado.append(item)
    return resultado

def filtrar_placeholders(lista: list[str]) -> list[str]:
    return [item for item in lista if not es_placeholder(item)]

def inferir_tipo_contrato(convocatoria: str) -> str:
    if not convocatoria:
        return "CAS"
    texto = convocatoria.upper()
    if "D.LEG 1057" in texto or "DL 1057" in texto:
        return "CAS"
    if "728" in texto:
        return "D.L. 728"
    if "276" in texto:
        return "D.L. 276"
    return "CAS"

def inferir_nivel(formacion) -> list[str]:
    texto = " ".join(a_lista(formacion)).upper() if isinstance(formacion, list) else str(formacion).upper()
    niveles = []
    if any(k in texto for k in ["MAESTR", "MAGIST"]):
        niveles.append("Maestría")
    if "DOCTO" in texto:
        niveles.append("Doctorado")
    if any(k in texto for k in ["TECNIC", "TECNOLOG", "TÉCNIC", "TECNÓLOG"]):
        niveles.append("Técnico")
    if any(k in texto for k in ["UNIVERSIT", "BACHILLER", "INGENIER", "LICENCI",
                                  "MÉDICO", "MEDICO", "CIRUJANO", "TÍTULO PROFESIONAL",
                                  "TITULO PROFESIONAL", "ABOGAD", "ECONOMIS",
                                  "CONTADOR", "PSICOLOG", "ENFERM"]):
        niveles.append("Universitario")
    niveles = list(dict.fromkeys(niveles))
    return niveles if niveles else ["No especificado"]

def generar_documentos(niveles: list[str]) -> list[str]:
    base = ["Curriculum vitae", "Certificados de experiencia"]
    if any(n in ["Universitario", "Maestría", "Doctorado"] for n in niveles):
        base += ["Título profesional", "Colegiatura y habilitación"]
    elif "Técnico" in niveles:
        base += ["Título o certificado técnico"]
    return base

def generar_descripcion(titulo, entidad, ubicacion, sueldo, tipo_contrato, fecha_limite, vacantes) -> str:
    partes = [f"Convocatoria {tipo_contrato} para {titulo} en {entidad}, sede {ubicacion}."]
    partes.append(f"Remuneración mensual S/ {sueldo:,.0f}.")
    if vacantes and vacantes > 1:
        partes.append(f"{vacantes} vacantes disponibles.")
    if fecha_limite:
        try:
            fecha_fmt = datetime.strptime(fecha_limite, "%Y-%m-%d").strftime("%-d de %B de %Y")
            partes.append(f"Fecha límite de postulación: {fecha_fmt}.")
        except ValueError:
            pass
    return " ".join(partes)

def construir_requisitos(req: dict) -> list[str]:
    requisitos = []

    formacion   = filtrar_placeholders(a_lista(req.get("formacion", "")))
    experiencia = filtrar_placeholders(a_lista(req.get("experiencia", "")))
    conocimiento= filtrar_placeholders(a_lista(req.get("conocimientos", "")))
    competencias= filtrar_placeholders(a_lista(req.get("competencias", "")))
    especializac= req.get("especializacion", "")

    requisitos.extend(formacion)
    requisitos.extend(experiencia)
    requisitos.extend(conocimiento)
    requisitos.extend(competencias)

    if especializac and not es_placeholder(str(especializac)):
        texto_esp = capitalizar(str(especializac).strip())
        requisitos.append(f"Especialización en {texto_esp}")

    return deduplicar(requisitos)

def generar_req_preview(requisitos: list[str]) -> list[str]:
    cortos = [r for r in requisitos if len(r) <= 80]
    return cortos[:3] if cortos else requisitos[:2]

def limpiar_competencias(competencias) -> list[str]:
    items = a_lista(competencias)
    resultado = []
    for item in items:
        # Separar si vienen juntas con coma o punto y coma
        sub = re.split(r'[,;]', item)
        for s in sub:
            s = capitalizar(limpiar_texto(s))
            if s and len(s) > 3:
                resultado.append(s)
    return deduplicar(resultado)

# ─── Proceso principal ────────────────────────────────────────────────────────

def normalizar():
    with open(ENTRADA, encoding="utf-8") as f:
        datos = json.load(f)

    print(f"Procesando {len(datos)} registros...")
    salida = []

    for raw in datos:
        req = raw.get("requerimiento", {})

        # Campos base
        id_conv     = raw.get("id", "")
        titulo      = capitalizar(raw.get("puesto", "Sin título"))
        entidad     = capitalizar(raw.get("entidad", "Desconocido"))
        vacantes    = raw.get("vacantes", 1)
        convocatoria= raw.get("convocatoria", "")
        tipo_contrato = inferir_tipo_contrato(convocatoria)

        # Ubicacion: objeto { region, ciudad } → "Region - Ciudad"
        ubic_raw = raw.get("ubicacion", {})
        if isinstance(ubic_raw, dict):
            region = capitalizar(ubic_raw.get("region", ""))
            ciudad = capitalizar(ubic_raw.get("ciudad", ""))
            ubicacion = f"{region} - {ciudad}" if ciudad else region
        else:
            ubicacion = capitalizar(str(ubic_raw))

        # Remuneracion: objeto { monto, moneda } → number
        rem_raw = raw.get("remuneracion", {})
        if isinstance(rem_raw, dict):
            sueldo = float(rem_raw.get("monto", 0))
        else:
            sueldo = float(rem_raw or 0)

        fecha_pub    = raw.get("fechaInicio", "")
        fecha_limite = raw.get("fechaFin", "")
        link_oficial = raw.get("url", "#")

        # Nivel
        niveles = inferir_nivel(req.get("formacion", ""))

        # Requisitos
        requisitos  = construir_requisitos(req)
        req_preview = generar_req_preview(requisitos)

        # Requerimientos limpios
        comp_limpias = limpiar_competencias(req.get("competencias", []))
        requerimientos = {
            "formacion":      " ".join(filtrar_placeholders(a_lista(req.get("formacion", "")))) or "Ver bases",
            "experiencia":    " ".join(filtrar_placeholders(a_lista(req.get("experiencia", "")))) or "Ver bases",
            "especializacion":capitalizar(str(req.get("especializacion", ""))) if not es_placeholder(str(req.get("especializacion", ""))) else "Ver bases",
            "conocimientos":  " ".join(filtrar_placeholders(a_lista(req.get("conocimientos", "")))) or "Ver bases",
            "competencias":   comp_limpias,
        }

        # Descripcion rica
        descripcion = generar_descripcion(titulo, entidad, ubicacion, sueldo, tipo_contrato, fecha_limite, vacantes)

        # Documentos auto-generados
        documentos = generar_documentos(niveles)

        item = {
            "id":            id_conv,
            "titulo":        titulo,
            "entidad":       entidad,
            "ubicacion":     ubicacion,
            "sueldo":        sueldo,
            "fechaPub":      fecha_pub,
            "fechaLimite":   fecha_limite,
            "tipoContrato":  tipo_contrato,
            "modalidad":     "Presencial",
            "vacantes":      vacantes,
            "nivel":         niveles,
            "descripcion":   descripcion,
            "requisitos":    requisitos,
            "reqPreview":    req_preview,
            "requerimientos":requerimientos,
            "documentos":    documentos,
            "linkOficial":   link_oficial,
        }
        salida.append(item)

    with open(SALIDA, "w", encoding="utf-8") as f:
        json.dump(salida, f, ensure_ascii=False, indent=2)

    print(f"✅ {len(salida)} registros normalizados → '{SALIDA}'")

if __name__ == "__main__":
    normalizar()
