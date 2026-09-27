#!/bin/sh
set -e

echo "Applying database migrations..."
python manage.py migrate --noinput

echo "Seeding fixtures..."
python manage.py seed_fixtures

if [ "$#" -eq 0 ] || [ "$1" = "./entrypoint.sh" ] || [ "$1" = "/app/entrypoint.sh" ]; then
    echo "Starting Django development server on 0.0.0.0:8080..."
    exec python manage.py runserver 0.0.0.0:8080
else
    exec "$@"
fi
