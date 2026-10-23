"""Firma HMAC-SHA256 de los scripts generados.

El servicio de simulacion ejecuta codigo Python, de modo que solo debe
aceptar scripts producidos por el servicio de compilacion (que a su vez
solo genera codigo a partir de modelos validados). Para garantizarlo, el
compilador firma cada script con HMAC-SHA256 usando una clave compartida
entre ambos servicios, y el simulador verifica la firma antes de ejecutar.

En un despliegue real la clave debe provenir de un gestor de secretos y
rotarse periodicamente; aqui se toma de la variable de entorno
CLAVE_SERVICIOS, con un valor de demostracion como respaldo.
"""

import hashlib
import hmac
import os

_CLAVE = os.environ.get("CLAVE_SERVICIOS", "clave-demo-cambiar-en-produccion").encode()


def firmar(script: str) -> str:
    return hmac.new(_CLAVE, script.encode("utf-8"), hashlib.sha256).hexdigest()


def verificar(script: str, firma: str) -> bool:
    return hmac.compare_digest(firmar(script), firma)
