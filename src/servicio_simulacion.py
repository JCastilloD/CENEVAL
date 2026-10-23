"""Servicio de simulacion de Monte Carlo (consigna e).

Representa el "shell de Python" de Inteligencia Aplicada: recibe un script
de Python generado por el servicio de compilacion, verifica su firma HMAC
(solo se ejecuta codigo emitido por el compilador, nunca codigo arbitrario)
y lo corre en un subproceso aislado con limite de tiempo. La salida del
script (lineas JSON de progreso y el resultado final) se retransmite al
cliente en flujo continuo (ndjson), lo que permite graficar en tiempo real.

La concurrencia de la simulacion vive dentro del script generado
(multiprocessing.Pool con semillas independientes por bloque); este
servicio aporta el aislamiento, el control de recursos y la transmision
de resultados.

Ejecucion:
    python servicio_simulacion.py
(escucha en el puerto 8452, configurable con la variable de entorno
PUERTO_SIMULACION)
"""

import json
import os
import subprocess
import sys
import tempfile
import threading

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import firma

TIEMPO_LIMITE_S = 300

app = FastAPI(
    title="Servicio de simulacion de Monte Carlo",
    description="Ejecuta scripts de simulacion firmados y transmite los "
                "resultados en tiempo real.",
)


class SolicitudSimulacion(BaseModel):
    script: str
    firma: str
    semilla: int | None = None
    procesos: int | None = None


@app.get("/salud")
def salud():
    return {"servicio": "simulacion", "estado": "activo"}


@app.post("/simular")
def simular(solicitud: SolicitudSimulacion):
    if not firma.verificar(solicitud.script, solicitud.firma):
        raise HTTPException(
            status_code=403,
            detail="Firma invalida: el script no proviene del servicio de "
                   "compilacion y no sera ejecutado.")

    descriptor, ruta = tempfile.mkstemp(suffix=".py", prefix="simulacion_")
    with os.fdopen(descriptor, "w", encoding="utf-8") as archivo:
        archivo.write(solicitud.script)

    argumentos = [sys.executable, ruta,
                  str(solicitud.semilla) if solicitud.semilla is not None else "-"]
    if solicitud.procesos:
        argumentos.append(str(solicitud.procesos))

    def flujo():
        proceso = subprocess.Popen(
            argumentos, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8")
        cronometro = threading.Timer(TIEMPO_LIMITE_S, proceso.kill)
        cronometro.start()
        try:
            for linea in proceso.stdout:
                yield linea
            proceso.wait()
            if proceso.returncode != 0:
                detalle = (proceso.stderr.read() or "").strip().splitlines()
                yield json.dumps({
                    "tipo": "error",
                    "mensaje": "la simulacion termino con errores o excedio "
                               f"el limite de {TIEMPO_LIMITE_S} s",
                    "detalle": detalle[-3:],
                }) + "\n"
        finally:
            cronometro.cancel()
            proceso.kill()
            try:
                os.unlink(ruta)
            except OSError:
                pass

    return StreamingResponse(flujo(), media_type="application/x-ndjson")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1",
                port=int(os.environ.get("PUERTO_SIMULACION", "8452")))
