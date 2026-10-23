"""Servicio de compilacion de modelos (consigna d).

Servicio web que recibe el texto de un modelo, lo somete a las tres fases
de analisis (lexica con el AFD, sintactica con el parser por descenso
recursivo y semantica) y, si el modelo es valido, genera el script de
Python para la simulacion y lo firma con HMAC para que el servicio de
simulacion pueda confiar en el.

Ejecucion:
    python servicio_compilacion.py
(escucha en el puerto 8451, configurable con la variable de entorno
PUERTO_COMPILACION)
"""

import os

from fastapi import FastAPI
from pydantic import BaseModel

import firma
from codegen import generar_script
from parser_modelo import validar

app = FastAPI(
    title="Servicio de compilacion de modelos",
    description="Valida modelos de simulacion y genera el script de Python "
                "correspondiente.",
)


class SolicitudCompilacion(BaseModel):
    modelo: str


@app.get("/salud")
def salud():
    return {"servicio": "compilacion", "estado": "activo"}


@app.post("/compilar")
def compilar(solicitud: SolicitudCompilacion):
    modelo, errores = validar(solicitud.modelo)
    if errores:
        return {"valido": False, "errores": errores}
    script = generar_script(modelo)
    return {
        "valido": True,
        "errores": [],
        "variable": modelo.variable_salida,
        "iteraciones": modelo.iteraciones,
        "respuestas": modelo.respuestas,
        "script": script,
        "firma": firma.firmar(script),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1",
                port=int(os.environ.get("PUERTO_COMPILACION", "8451")))
