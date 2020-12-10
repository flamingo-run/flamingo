import os
from pathlib import Path

from google import auth
from google.cloud import datastore

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve(strict=True).parent.parent
PROJECT_DIR = BASE_DIR / 'flamingo'

cred, _ = auth.default()
db = datastore.Client()

FLAMINGO_PROJECT = os.environ.get('FLAMINGO_PROJECT', cred.project_id)
FLAMINGO_GCS_BUCKET = os.environ.get('FLAMINGO_GCS_BUCKET', f'{FLAMINGO_PROJECT}-flamingo')

DEFAULT_PROJECT = os.environ.get('DEFAULT_PROJECT', cred.project_id)
DEFAULT_PROJECT_NETWORK = os.environ.get('DEFAULT_PROJECT_NETWORK', DEFAULT_PROJECT)
DEFAULT_REGION = os.environ.get('DEFAULT_REGION', 'us-east1')
DEFAULT_DB_VERSION = os.environ.get('DEFAULT_DB_VERSION', 'POSTGRES_12')
DEFAULT_DB_TIER = os.environ.get('DEFAULT_DB_TIER', 'db-f1-micro')
DEFAULT_ROLE = os.environ.get('DEFAULT_ROLE', None)

STAGE_DIR = Path(BASE_DIR).joinpath('staging')
STAGE_DIR.mkdir(parents=True, exist_ok=True)

# OpenAPI
API_HOST = os.environ.get('API_HOST', None)
API_BASEPATH = "/"
API_TITLE = os.environ.get('API_TITLE', "Flamingo")
API_DESCRIPTION = "Microservices goes serverless"
API_CONTACT_EMAIL = "joao@daher.dev"
