"""Object Storage (almacenamiento no relacional clave/valor) para PDF originales y extracciones JSON.

Dos implementaciones con la misma interfaz:
  - LocalStorage: carpeta del disco (desarrollo y pruebas).
  - S3Storage: bucket compatible con S3 (AWS S3, MinIO, etc.), para el despliegue en la nube.
Se elige con la variable NUAM_STORAGE = local | s3.
"""
import os
import re

_CLAVE_OK = re.compile(r"^[A-Za-z0-9_\-]+\.(pdf|json|csv)$")


def _validar_clave(clave):
    if not _CLAVE_OK.match(clave):           # evita rutas como ../../etc/passwd
        raise ValueError("Clave de almacenamiento inválida")


class LocalStorage:
    def __init__(self, raiz):
        self.raiz = raiz
        os.makedirs(raiz, exist_ok=True)

    def put(self, clave, datos, content_type="application/octet-stream"):
        _validar_clave(clave)
        with open(os.path.join(self.raiz, clave), "wb") as f:
            f.write(datos)

    def get(self, clave):
        _validar_clave(clave)
        with open(os.path.join(self.raiz, clave), "rb") as f:
            return f.read()

    def existe(self, clave):
        _validar_clave(clave)
        return os.path.exists(os.path.join(self.raiz, clave))


class S3Storage:
    def __init__(self, bucket, endpoint_url=None, region="us-east-1"):
        import boto3
        self.bucket = bucket
        self.s3 = boto3.client("s3", endpoint_url=endpoint_url, region_name=region)

    def put(self, clave, datos, content_type="application/octet-stream"):
        _validar_clave(clave)
        self.s3.put_object(Bucket=self.bucket, Key=clave, Body=datos, ContentType=content_type,
                           ServerSideEncryption="AES256")          # cifrado en reposo

    def get(self, clave):
        _validar_clave(clave)
        return self.s3.get_object(Bucket=self.bucket, Key=clave)["Body"].read()

    def existe(self, clave):
        _validar_clave(clave)
        try:
            self.s3.head_object(Bucket=self.bucket, Key=clave)
            return True
        except Exception:
            return False


def crear_storage():
    if os.environ.get("NUAM_STORAGE", "local").lower() == "s3":
        return S3Storage(os.environ["NUAM_S3_BUCKET"], os.environ.get("NUAM_S3_ENDPOINT") or None)
    return LocalStorage(os.environ.get("NUAM_STORAGE_DIR", os.path.join(os.path.dirname(__file__), "data", "object_storage")))
