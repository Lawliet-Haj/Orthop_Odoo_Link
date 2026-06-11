# Image de l'app de synchro Orthop -> Odoo (suivi_stock)
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Europe/Paris

WORKDIR /app

# Dépendances (couche cache séparée)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Code applicatif (le .env n'est PAS copié — voir .dockerignore ; il est fourni
# au runtime via env_file / variables d'environnement).
COPY stock_app.py .

EXPOSE 5000

# Serveur WSGI de production. Timeout large car les synchros (conso 90 j, parc,
# catalogue) peuvent être longues. 2 workers suffisent pour un usage déclenché.
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", \
     "--timeout", "1800", "--graceful-timeout", "60", \
     "--access-logfile", "-", "--error-logfile", "-", \
     "stock_app:app"]
