@echo off
cd /d "C:\Users\damn\Desktop\Red-Aechives-Agent"
"venv\Scripts\python.exe" src\web\app.py >> app.log 2>&1
