import requests
from bs4 import BeautifulSoup
import csv
from datetime import datetime

# URL base
URL = "https://app.servir.gob.pe/DifusionOfertasExterno/faces/consultas/ofertas_laborales.xhtml"

# Crear sesión (MUY IMPORTANTE para cookies)
session = requests.Session()

# Headers para simular navegador
headers = {
    "User-Agent": "Mozilla/5.0",
}

# -------------------------
# 1️⃣ GET inicial (obtener ViewState)
# -------------------------
response = session.get(URL, headers=headers)
soup = BeautifulSoup(response.text, "lxml")

# Buscar el ViewState
view_state = soup.find("input", {"name": "javax.faces.ViewState"})["value"]

print("ViewState:", view_state)

# -------------------------
# 2️⃣ Preparar POST inicial (simular filtro)
# -------------------------
payload_initial = {
    "javax.faces.partial.ajax": "true",
    "javax.faces.source": "frmLstOfertsLabo:j_idt42",
    "javax.faces.partial.execute": "@all",
    "javax.faces.partial.render": "frmLstOfertsLabo:mensaje frmLstOfertsLabo",
    
    "frmLstOfertsLabo:j_idt42": "frmLstOfertsLabo:j_idt42",
    "frmLstOfertsLabo": "frmLstOfertsLabo",

    # 👇 AQUÍ cambias filtros
    "frmLstOfertsLabo:modalidadAcceso": "03",
    # frmLstOfertsLabo:cboDep_input variará de 0 a 25

    # 👇 ViewState obligatorio
    "javax.faces.ViewState": view_state
}

# Payload para hacer clic en botón "Siguiente"
payload_next = {
    "javax.faces.partial.ajax": "true",
    "javax.faces.source": "frmLstOfertsLabo:j_idt82",  # 👈 Este es el botón SIGUIENTE
    "javax.faces.partial.execute": "@all",
    "javax.faces.partial.render": "frmLstOfertsLabo:mensaje frmLstOfertsLabo",
    
    "frmLstOfertsLabo:j_idt82": "frmLstOfertsLabo:j_idt82",  # 👈 Click en botón siguiente
    "frmLstOfertsLabo": "frmLstOfertsLabo",
    
    "frmLstOfertsLabo:modalidadAcceso": "03",
    "javax.faces.ViewState": view_state
}

# -------------------------
# 3️⃣ Iterar sobre departamentos (Todo Perú) y paginas
# -------------------------
todas_vacantes = []

print("🔄 Obteniendo vacantes de todo Perú...\n")

for departamento in [0]:  # 0 = Todos los departamentos
    print(f"⏳ Procesando departamento {departamento}...")
    
    # Actualizar el payload con el departamento actual
    payload_initial["frmLstOfertsLabo:cboDep_input"] = str(departamento)
    payload_next["frmLstOfertsLabo:cboDep_input"] = str(departamento)
    
    pagina = 0  # Comenzar en página 0
    sin_mas_vacantes = False
    max_paginas = 99999  # Límite muy alto para que confíe en la detección de fin de datos
    primera_pagina = True  # Bandera para distinguir primer request
    
    while not sin_mas_vacantes and pagina < max_paginas:
        print(f"   📄 Página {pagina}...")
        
        try:
            # Usar payload_initial para el primer request, payload_next para el resto
            if primera_pagina:
                payload = payload_initial.copy()
                primera_pagina = False
            else:
                payload = payload_next.copy()
                # Actualizar ViewState si cambia (algunos sitios lo hacen)
                # Podrías agregar lógica aquí para extraer el ViewState del response anterior
            
            # POST para este departamento y página
            post_response = session.post(URL, data=payload, headers=headers)
            
            # 1. Parsear como XML
            xml_soup = BeautifulSoup(post_response.text, "xml")
            
            # 2. Buscar el update correcto
            updates = xml_soup.find_all("update")
            
            html_content = None
            
            for u in updates:
                if "frmLstOfertsLabo" in u.get("id", ""):
                    html_content = u.text
                    break
            
            if not html_content:
                print(f"   ⚠️ No hay respuesta para página {pagina}, finalizando...")
                sin_mas_vacantes = True
                continue
            
            # 3. Parsear el HTML interno
            soup_post = BeautifulSoup(html_content, "lxml")
            
            # 4. Buscar vacantes
            vacantes_divs = soup_post.find_all("div", {"class": "cuadro-vacantes"})
            
            if not vacantes_divs:
                print(f"   ⚠️ No hay más vacantes en página {pagina}, finalizando...")
                sin_mas_vacantes = True
                continue
            
            print(f"   ✓ Se encontraron {len(vacantes_divs)} vacantes en página {pagina}")
            
            # 5. Procesar cada vacante
            vacantes_nuevas_en_pagina = 0
            for vacante_div in vacantes_divs:
                # Extraer título
                titulo_label = vacante_div.find("div", {"class": "titulo-vacante"})
                titulo = titulo_label.find("label").text.strip() if titulo_label else "N/A"
                
                # Extraer nombre de la entidad
                nombre_entidad_div = vacante_div.find("div", {"class": "nombre-entidad"})
                if nombre_entidad_div:
                    span = nombre_entidad_div.find("span", {"class": "detalle-sp"})
                    entidad = span.text.strip() if span else "N/A"
                else:
                    entidad = "N/A"
                
                # Extraer datos
                datos = {}
                filas_datos = vacante_div.find_all("div", {"class": "row box-mb"})
                
                for fila in filas_datos:
                    sub_titulo = fila.find("span", {"class": "sub-titulo"})
                    detalle = fila.find("span", {"class": "detalle-sp"})
                    
                    if sub_titulo and detalle:
                        clave = sub_titulo.text.strip().rstrip(":")
                        # Normalizar: remover saltos de línea y espacios extras
                        clave = " ".join(clave.split())
                        valor = detalle.text.strip()
                        # Normalizar valor también
                        valor = " ".join(valor.split())
                        datos[clave] = valor
                
                # Usar convocatoria como ID único
                convocatoria = datos.get("Número de Convocatoria", "N/A")
                
                # Armar diccionario
                vacante_info = {
                    "Título": titulo,
                    "Entidad": entidad,
                    "Ubicación": datos.get("Ubicación", "N/A"),
                    "Convocatoria": convocatoria,
                    "Vacantes": datos.get("Cantidad de Vacantes", "N/A"),
                    "Remuneración": datos.get("Remuneración", "N/A"),
                    "Fecha Inicio": datos.get("Fecha Inicio de Publicación", "N/A"),
                    "Fecha Fin": datos.get("Fecha Fin de Publicación", "N/A"),
                    "Departamento": departamento
                }
                
                todas_vacantes.append(vacante_info)
                vacantes_nuevas_en_pagina += 1
            
            if sin_mas_vacantes or vacantes_nuevas_en_pagina == 0:
                sin_mas_vacantes = True
            else:
                pagina += 1  # Ir a siguiente página
        
        except Exception as e:
            print(f"   ❌ Error en página {pagina}: {str(e)}")
            import traceback
            traceback.print_exc()
            sin_mas_vacantes = True
            break
    
    if pagina >= max_paginas:
        print(f"   ⚠️ Se alcanzó el límite máximo de páginas ({max_paginas})")

print(f"\n{'='*60}")
print(f"✓ TOTAL DE VACANTES ENCONTRADAS: {len(todas_vacantes)}")
print(f"{'='*60}\n")

# -------------------------
# 4️⃣ Mostrar y guardar resultados
# -------------------------

# Mostrar primeras vacantes encontradas
if todas_vacantes:
    print("📋 Primeras 10 vacantes encontradas:\n")
    for i, vacante in enumerate(todas_vacantes[:10], 1):
        print(f"{i}. {vacante['Título']}")
        print(f"   Entidad: {vacante['Entidad']}")
        print(f"   Ubicación: {vacante['Ubicación']}")
        print(f"   Remuneración: {vacante['Remuneración']}")
        print()

# -------------------------
# 5️⃣ Guardar en CSV
# -------------------------
if todas_vacantes:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"vacantes_{timestamp}.csv"
    
    try:
        with open(filename, "w", newline="", encoding="utf-8") as csvfile:
            fieldnames = ["Título", "Entidad", "Ubicación", "Convocatoria", "Vacantes", "Remuneración", "Fecha Inicio", "Fecha Fin", "Departamento"]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            
            writer.writeheader()
            writer.writerows(todas_vacantes)
        
        print(f"\n✓ Datos guardados en: {filename}")
    except Exception as e:
        print(f"❌ Error al guardar CSV: {e}")
else:
    print("⚠️ No se encontraron vacantes")
