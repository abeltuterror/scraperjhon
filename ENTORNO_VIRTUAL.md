# 📚 Guía de Entorno Virtual - Git & Python

## 1️⃣ Crear Entorno Virtual

```bash
python -m venv venv
```

## 2️⃣ Activar Entorno Virtual

# 2️⃣ Activar en Git Bash (NO PowerShell)
```bash
source venv/Scripts/activate

### Windows (CMD)
```bash
.\venv\Scripts\activate
```

### Linux / macOS
```bash
source venv/bin/activate
```

**✓ Señal de activación:** Verás `(venv)` al inicio de la línea de comandos

---

## 3️⃣ Instalar Dependencias

Una vez activado el entorno virtual:

```bash
pip install -r requirements.txt
```

---

## 4️⃣ Desactivar Entorno Virtual

```bash
deactivate
```

---

## 5️⃣ Configurar Git (Ignorar venv)

Asegúrate que `.gitignore` contenga:

```
venv/
__pycache__/
*.pyc
.env
```

Luego:

```bash
git add .gitignore
git commit -m "Agregar gitignore"
```

---

## 6️⃣ Flujo Completo Recomendado

```bash
# 1. Clonar o navegar al proyecto
cd c:\Users\User\Desktop\luxus\jhon2

# 2. Crear entorno virtual
python -m venv venv

# 3. Activar entorno virtual
.\venv\Scripts\activate  # Windows CMD/PowerShell

# 4. Instalar dependencias
pip install -r requirements.txt

# 5. Trabajar con Git
git status
git add .
git commit -m "Tu mensaje"
git push

# 6. Desactivar cuando termines
deactivate
```

---

## 7️⃣ Verificar que está Activado

```bash
# Ver ruta de Python
which python  # Linux/macOS
where python  # Windows

# Debe mostrar la ruta dentro de venv/
```

---

## ⚠️ Solución de Problemas

### "No se reconoce el comando"
- Asegúrate de estar en la carpeta correcta
- Verifica que Python esté instalado: `python --version`

### "No puedo ejecutar scripts en PowerShell"
- Ejecuta: `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser`

### Dependencias no se instalan
- Verifica que el entorno esté activado `(venv)` antes de pip install
- Intenta: `pip install --upgrade pip`

---

## 📝 Resumen Rápido (Windows)

```bash
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
python scraper.py
deactivate
```


## Este es el que vale
```bash

python pro.py

```
