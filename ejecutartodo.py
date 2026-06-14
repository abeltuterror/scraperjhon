import subprocess
import sys

# 1. Primero se ejecuta este script
print("1. Ejecutando buenoscraperfolio1.py...")
subprocess.run([sys.executable, "buenoscraperfolio1.py"], check=True)

# 2. Cuando el primero termina, se ejecuta este
print("2. Ejecutando erroresnormalizados.py...")
subprocess.run([sys.executable, "erroresnormalizados.py"], check=True)

print("Listo. Se ejecutaron en orden.")