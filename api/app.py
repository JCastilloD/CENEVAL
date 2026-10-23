import math
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import servicio_compilacion
import servicio_simulacion

# Azure corta las peticiones a los 240 s
servicio_simulacion.TIEMPO_LIMITE_S = int(os.environ.get("TIEMPO_LIMITE_S", "200"))


def nucleos_disponibles():
    if os.environ.get("PROCESOS_SIMULACION"):
        return int(os.environ["PROCESOS_SIMULACION"])
    try:
        cuota, periodo = Path("/sys/fs/cgroup/cpu.max").read_text().split()
        if cuota != "max":
            return max(1, math.ceil(int(cuota) / int(periodo)))
    except (OSError, ValueError):
        pass
    return os.cpu_count() or 1


PROCESOS = nucleos_disponibles()

simulacion = FastAPI(title="Servicio de simulacion de Monte Carlo")


@simulacion.get("/salud")
def salud_simulacion():
    return servicio_simulacion.salud()


@simulacion.post("/simular")
def simular(solicitud: servicio_simulacion.SolicitudSimulacion):
    if not solicitud.procesos:
        solicitud.procesos = PROCESOS
    return servicio_simulacion.simular(solicitud)


class LimiteSimulaciones:
    def __init__(self, app, maximo=2):
        self.app = app
        self.maximo = maximo
        self.activas = 0

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].endswith("/simular"):
            await self.app(scope, receive, send)
            return
        if self.activas >= self.maximo:
            respuesta = JSONResponse(
                {"detail": f"Ya hay {self.maximo} simulaciones en curso, intenta en unos segundos."},
                status_code=429)
            await respuesta(scope, receive, send)
            return
        self.activas += 1
        try:
            await self.app(scope, receive, send)
        finally:
            self.activas -= 1


origenes = [o.strip() for o in os.environ.get("ORIGENES", "*").split(",") if o.strip()]

app = FastAPI(title="Simulaciones de Monte Carlo")
app.add_middleware(LimiteSimulaciones,
                   maximo=int(os.environ.get("SIMULACIONES_SIMULTANEAS", "2")))
app.add_middleware(CORSMiddleware, allow_origins=origenes,
                   allow_methods=["GET", "POST"], allow_headers=["Content-Type"])


@app.get("/")
def inicio():
    return {"compilacion": "/compilacion", "simulacion": "/simulacion",
            "procesos": PROCESOS}


app.mount("/compilacion", servicio_compilacion.app)
app.mount("/simulacion", simulacion)
