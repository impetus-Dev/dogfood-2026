#!/bin/sh
set -e

if [ -z "$SECRET_KEY" ]; then
    echo "SECRET_KEY not set; generating a runtime secret key..."
    export SECRET_KEY="$(python -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())')"
fi
echo "$SECRET_KEY" > /tmp/.container_secret_key

echo "Collecting static files..."
python manage.py collectstatic --noinput

echo "Applying database migrations..."
python manage.py migrate --noinput

echo "Seeding fixtures..."
python manage.py seed_fixtures

if [ "$#" -eq 0 ] || [ "$1" = "./entrypoint.sh" ] || [ "$1" = "/app/entrypoint.sh" ]; then
    echo "Starting Django server on 0.0.0.0:8080..."
    exec python manage.py runserver 0.0.0.0:8080
else
    exec "$@"
fi
