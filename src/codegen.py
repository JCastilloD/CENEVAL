"""Generador de codigo: traduce el AST de un modelo validado a un script de
Python autocontenido que ejecuta la simulacion de Monte Carlo.

El script generado:
  * Divide las iteraciones en bloques y los reparte entre procesos
    trabajadores (multiprocessing.Pool), de modo que la simulacion es
    concurrente y aprovecha todos los nucleos disponibles.
  * Usa numpy.random.SeedSequence.spawn para derivar una semilla
    independiente por bloque; esto garantiza flujos de numeros aleatorios
    estadisticamente independientes entre procesos y ademas hace la
    simulacion reproducible: con la misma semilla maestra el resultado
    final es identico sin importar cuantos procesos se usen ni en que
    orden terminen (la reduccion final se hace ordenando los bloques por
    indice).
  * Emite por la salida estandar una linea JSON por bloque terminado
    (tipo "progreso", con estadisticos parciales y una muestra de valores
    para graficar) y una linea final (tipo "resultado").
  * Filtra las iteraciones cuyo resultado no es un numero finito (por
    ejemplo, cuando el discriminante de una raiz cuadrada es negativo) y
    las reporta como iteraciones invalidas.

Nota de seguridad: este generador solo emite codigo construido a partir de
nodos del AST tipados; en ningun punto se interpola texto crudo del
usuario dentro del script, por lo que un modelo que haya pasado la
validacion no puede inyectar codigo arbitrario.
"""

from parser_modelo import (
    Modelo, Num, Var, OpBin, OpUnaria, Raiz,
    DistNormal, DistTabla, DistUniforme,
)

TAM_BLOQUE_PREDETERMINADO = 50_000
TAM_MUESTRA_POR_BLOQUE = 120  # valores enviados al cliente para graficar


class _GeneradorExpresion:
    """Traduce el AST de la expresion a una expresion vectorizada de numpy."""

    def __init__(self):
        self.contador_pm = 0  # cuantos operadores \pm aparecen en el modelo

    def generar(self, nodo) -> str:
        if isinstance(nodo, Num):
            return repr(float(nodo.valor))
        if isinstance(nodo, Var):
            return f"v_{nodo.nombre}"
        if isinstance(nodo, OpUnaria):
            return f"(-{self.generar(nodo.operando)})"
        if isinstance(nodo, Raiz):
            return f"np.sqrt({self.generar(nodo.operando)})"
        if isinstance(nodo, OpBin):
            izq = self.generar(nodo.izq)
            der = self.generar(nodo.der)
            if nodo.op == "pm":
                indice = self.contador_pm
                self.contador_pm += 1
                return f"({izq} + signos_{indice} * {der})"
            if nodo.op == "^":
                return f"({izq} ** {der})"
            return f"({izq} {nodo.op} {der})"
        raise TypeError(f"nodo de AST no reconocido: {type(nodo).__name__}")


def _lineas_de_muestreo(modelo: Modelo) -> list:
    lineas = []
    for nombre, dist in modelo.distribuciones.items():
        if isinstance(dist, DistNormal):
            lineas.append(
                f"v_{nombre} = rng.normal({dist.media!r}, {dist.desviacion!r}, n)")
        elif isinstance(dist, DistUniforme):
            lineas.append(
                f"v_{nombre} = rng.uniform({dist.minimo!r}, {dist.maximo!r}, n)")
        elif isinstance(dist, DistTabla):
            valores = [float(v) for v, _ in dist.pares]
            probabilidades = [float(p) for _, p in dist.pares]
            lineas.append(
                f"v_{nombre} = rng.choice(np.array({valores!r}), size=n, "
                f"p=np.array({probabilidades!r}))")
    return lineas


def generar_script(modelo: Modelo, tam_bloque: int = TAM_BLOQUE_PREDETERMINADO) -> str:
    generador = _GeneradorExpresion()
    expresion = generador.generar(modelo.expresion)

    lineas_muestreo = _lineas_de_muestreo(modelo)
    for indice in range(generador.contador_pm):
        lineas_muestreo.append(
            f"signos_{indice} = rng.choice(np.array([-1.0, 1.0]), size=n)")
    cuerpo_muestreo = "\n    ".join(lineas_muestreo)

    return PLANTILLA.format(
        variable_salida=modelo.variable_salida,
        iteraciones=modelo.iteraciones,
        respuestas=repr(list(modelo.respuestas)),
        tam_bloque=tam_bloque,
        tam_muestra=TAM_MUESTRA_POR_BLOQUE,
        cuerpo_muestreo=cuerpo_muestreo,
        expresion=expresion,
    )


PLANTILLA = '''\
# Script de simulacion generado por el servicio de compilacion de modelos.
# Uso: python <script>.py [semilla] [procesos]
# Emite lineas JSON por la salida estandar: una por bloque terminado
# (tipo "progreso") y una final (tipo "resultado").

import json
import math
import sys
import time
from multiprocessing import Pool

import numpy as np

ITERACIONES = {iteraciones}
RESPUESTAS = {respuestas}
TAM_BLOQUE = {tam_bloque}
TAM_MUESTRA = {tam_muestra}


def ejecutar_bloque(argumentos):
    """Simula un bloque de n iteraciones y devuelve sus agregados parciales."""
    indice, semilla, n = argumentos
    rng = np.random.default_rng(semilla)
    {cuerpo_muestreo}
    with np.errstate(invalid="ignore", divide="ignore", over="ignore"):
        salida = {expresion}
    salida = np.asarray(salida, dtype=float)
    if salida.ndim == 0:
        salida = np.full(n, float(salida))
    validos = salida[np.isfinite(salida)]
    return {{
        "indice": indice,
        "n": int(n),
        "validas": int(validos.size),
        "suma": float(validos.sum()) if validos.size else 0.0,
        "suma_cuadrados": float((validos * validos).sum()) if validos.size else 0.0,
        "minimo": float(validos.min()) if validos.size else None,
        "maximo": float(validos.max()) if validos.size else None,
        "muestra": [float(v) for v in validos[:TAM_MUESTRA]],
    }}


def _estadisticos(validas, suma, suma_cuadrados, minimo, maximo):
    disponibles = {{}}
    if validas:
        promedio = suma / validas
        varianza = max(suma_cuadrados / validas - promedio * promedio, 0.0)
        disponibles = {{
            "avg": promedio,
            "min": minimo,
            "max": maximo,
            "std": math.sqrt(varianza),
        }}
    return {{clave: disponibles.get(clave) for clave in RESPUESTAS}}


def main():
    semilla_maestra = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1] != "-" else None
    procesos = int(sys.argv[2]) if len(sys.argv) > 2 else None

    inicio = time.perf_counter()
    n_bloques = math.ceil(ITERACIONES / TAM_BLOQUE)
    secuencia = np.random.SeedSequence(semilla_maestra)
    semillas = secuencia.spawn(n_bloques)
    tareas = []
    restantes = ITERACIONES
    for indice in range(n_bloques):
        n = min(TAM_BLOQUE, restantes)
        restantes -= n
        tareas.append((indice, semillas[indice], n))

    resultados = []
    completadas = 0
    suma = suma_cuadrados = 0.0
    validas = 0
    minimo = maximo = None

    with Pool(processes=procesos) as pool:
        for parcial in pool.imap_unordered(ejecutar_bloque, tareas):
            resultados.append(parcial)
            completadas += parcial["n"]
            validas += parcial["validas"]
            suma += parcial["suma"]
            suma_cuadrados += parcial["suma_cuadrados"]
            if parcial["minimo"] is not None:
                minimo = parcial["minimo"] if minimo is None else min(minimo, parcial["minimo"])
                maximo = parcial["maximo"] if maximo is None else max(maximo, parcial["maximo"])
            print(json.dumps({{
                "tipo": "progreso",
                "completadas": completadas,
                "total": ITERACIONES,
                "validas": validas,
                "estadisticos": _estadisticos(validas, suma, suma_cuadrados, minimo, maximo),
                "muestra": parcial["muestra"],
            }}), flush=True)

    # Reduccion final determinista: se agrega en orden de indice de bloque,
    # de modo que el resultado no depende del orden de terminacion de los
    # procesos (demostracion de correctitud del procesamiento concurrente).
    resultados.sort(key=lambda parcial: parcial["indice"])
    suma = sum(parcial["suma"] for parcial in resultados)
    suma_cuadrados = sum(parcial["suma_cuadrados"] for parcial in resultados)
    validas = sum(parcial["validas"] for parcial in resultados)
    minimos = [parcial["minimo"] for parcial in resultados if parcial["minimo"] is not None]
    maximos = [parcial["maximo"] for parcial in resultados if parcial["maximo"] is not None]
    minimo = min(minimos) if minimos else None
    maximo = max(maximos) if maximos else None

    print(json.dumps({{
        "tipo": "resultado",
        "variable": {variable_salida!r},
        "iteraciones": ITERACIONES,
        "validas": validas,
        "invalidas": ITERACIONES - validas,
        "estadisticos": _estadisticos(validas, suma, suma_cuadrados, minimo, maximo),
        "bloques": n_bloques,
        "semilla": secuencia.entropy,
        "duracion_s": round(time.perf_counter() - inicio, 3),
    }}), flush=True)


if __name__ == "__main__":
    main()
'''
