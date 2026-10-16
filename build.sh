#!/usr/bin/env bash
set -o errexit
apt-get update && apt-get install -y binutils libproj-dev gdal-bin libgdal-dev
pip install -r requirements.txt
python manage.py collectstatic --noinput
python manage.py migrate