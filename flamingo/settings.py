import base64
import os
from pathlib import Path

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from google import auth

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve(strict=True).parent.parent
PROJECT_DIR = BASE_DIR / "flamingo"

cred, project_id = auth.default()

FLAMINGO_PROJECT = os.environ.get("FLAMINGO_PROJECT", project_id)
FLAMINGO_LOCATION = os.environ.get("FLAMINGO_LOCATION", "us-east1")
FLAMINGO_GCS_BUCKET = os.environ.get("FLAMINGO_GCS_BUCKET", f"{FLAMINGO_PROJECT}-flamingo")
FLAMINGO_URL = os.environ["FLAMINGO_URL"]  # TODO: Get URL from running container?
FLAMINGO_SERVICE_ACCOUNT = cred.service_account_email

DEFAULT_PROJECT = os.environ.get("DEFAULT_PROJECT", project_id)
DEFAULT_PROJECT_NETWORK = os.environ.get("DEFAULT_PROJECT_NETWORK", DEFAULT_PROJECT)
DEFAULT_DB_VERSION = os.environ.get("DEFAULT_DB_VERSION", "POSTGRES_13")
DEFAULT_DB_TIER = os.environ.get("DEFAULT_DB_TIER", "db-f1-micro")
ORGANIZATION_PREFIX = os.environ.get("ORGANIZATION_PREFIX", "")

STAGE_DIR = Path(BASE_DIR).joinpath("staging")
STAGE_DIR.mkdir(parents=True, exist_ok=True)

# OpenAPI
API_HOST = os.environ.get("API_HOST", None)
API_BASEPATH = "/"
API_TITLE = os.environ.get("API_TITLE", "Flamingo")
API_DESCRIPTION = "Microservices goes serverless"
API_CONTACT_EMAIL = "joao@daher.dev"

GIT_ACCESS_TOKEN = os.environ.get("GIT_ACCESS_TOKEN")  # TODO: Replace with CloudSecrets

# SECURITY
SECRET_KEY = os.environ.get("SECRET_KEY", "abc123")


class Security:
    @classmethod
    def get_fernet(cls):
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=SECRET_KEY.encode(),
            iterations=390000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(SECRET_KEY.encode()))
        return Fernet(key)

    @classmethod
    def encrypt(cls, content: str) -> str:
        return cls.get_fernet().encrypt(content.encode()).decode()

    @classmethod
    def decrypt(cls, content: str) -> str:
        return cls.get_fernet().decrypt(content.encode()).decode()
