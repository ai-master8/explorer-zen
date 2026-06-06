@echo off
cls
title AI Explorer Character

:: Задайте OPENROUTER_API_KEY в окружении (например, через системные настройки
:: Windows или `setx OPENROUTER_API_KEY <ваш-ключ>` в cmd перед запуском).
:: Не вставляйте ключ прямо сюда — этот файл может попасть в публичный репозиторий.
python G:\Projects\explorer-zen\explorer_zen.py

pause