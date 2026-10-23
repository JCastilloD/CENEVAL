"""Cliente personalizado para Negocios S.A. (consigna c).

Aplicacion de escritorio (Tkinter) que permite:
  1. Capturar el modelo en el lenguaje basado en LaTeX.
  2. Validarlo localmente con el mismo analizador (AFD + parser) que usan
     los servicios, reportando errores lexicos, sintacticos y semanticos.
  3. Enviarlo al servicio de compilacion y, con el script firmado que este
     devuelve, solicitar la simulacion al servicio de Monte Carlo.
  4. Graficar en tiempo real el comportamiento de los valores simulados de
     la variable de salida (muestra de valores y promedio acumulado) y
     mostrar los estadisticos solicitados en el modelo.

Los datos del cliente nunca salen de su modelo: solo viaja el texto del
modelo y regresan agregados estadisticos y una muestra de valores.

Ejecucion:
    python cliente.py
(Requiere que los servicios de compilacion y simulacion esten activos.)
"""

import json
import queue
import threading
import tkinter as tk
import urllib.error
import urllib.request
from tkinter import ttk

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from parser_modelo import validar

URL_COMPILACION = "http://127.0.0.1:8451/compilar"
URL_SIMULACION = "http://127.0.0.1:8452/simular"
MAX_PUNTOS_GRAFICA = 4_000

MODELO_EJEMPLO = """{\\model{x = \\frac{-b \\pm \\sqrt{b^2 - 4ac}}{2a}}
\\normal a{10, 0.5}
\\distrib b{{10, 0.5}{15, 0.3}{20, 0.2}}
\\uniform c{-20, 30}
\\iter {1000000}
\\response {avg, min, max}}
"""

ETIQUETAS = {"avg": "Promedio", "min": "Minimo", "max": "Maximo", "std": "Desv. estandar"}


def _post_json(url: str, datos: dict, tiempo_limite: int = 600):
    solicitud = urllib.request.Request(
        url,
        data=json.dumps(datos).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    return urllib.request.urlopen(solicitud, timeout=tiempo_limite)


class Cliente(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Simulaciones de Monte Carlo - Inteligencia Aplicada S.A.")
        self.geometry("1180x680")
        self.cola = queue.Queue()
        self.simulando = False
        self.puntos_x = []
        self.puntos_y = []
        self.promedios = []
        self.promedios_n = []
        self._construir_interfaz()
        self.after(100, self._procesar_cola)

    # -- interfaz -----------------------------------------------------------

    def _construir_interfaz(self):
        panel = ttk.Frame(self, padding=8)
        panel.pack(fill=tk.BOTH, expand=True)
        panel.columnconfigure(0, weight=2)
        panel.columnconfigure(1, weight=3)
        panel.rowconfigure(1, weight=1)

        ttk.Label(panel, text="Modelo (lenguaje basado en LaTeX)").grid(
            row=0, column=0, sticky="w")
        self.editor = tk.Text(panel, width=52, height=14, font=("Consolas", 11),
                              undo=True, wrap="none")
        self.editor.grid(row=1, column=0, sticky="nsew", padx=(0, 8))
        self.editor.insert("1.0", MODELO_EJEMPLO)

        botones = ttk.Frame(panel)
        botones.grid(row=2, column=0, sticky="ew", pady=6)
        self.boton_validar = ttk.Button(botones, text="Validar", command=self.validar)
        self.boton_validar.pack(side=tk.LEFT)
        self.boton_simular = ttk.Button(
            botones, text="Compilar y simular", command=self.simular)
        self.boton_simular.pack(side=tk.LEFT, padx=6)
        ttk.Label(botones, text="Semilla (opcional):").pack(side=tk.LEFT, padx=(12, 2))
        self.entrada_semilla = ttk.Entry(botones, width=12)
        self.entrada_semilla.pack(side=tk.LEFT)

        ttk.Label(panel, text="Mensajes").grid(row=3, column=0, sticky="w")
        self.mensajes = tk.Text(panel, height=9, font=("Consolas", 9),
                                state=tk.DISABLED, wrap="word")
        self.mensajes.grid(row=4, column=0, sticky="nsew", padx=(0, 8))

        # Grafica en tiempo real
        self.figura = Figure(figsize=(6.4, 4.6), dpi=100)
        self.eje_valores = self.figura.add_subplot(211)
        self.eje_promedio = self.figura.add_subplot(212)
        self.figura.subplots_adjust(hspace=0.45, left=0.11, right=0.97, top=0.93)
        self.lienzo = FigureCanvasTkAgg(self.figura, master=panel)
        self.lienzo.get_tk_widget().grid(row=1, column=1, rowspan=4, sticky="nsew")
        self._reiniciar_grafica()

        inferior = ttk.Frame(panel)
        inferior.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        self.barra = ttk.Progressbar(inferior, maximum=100)
        self.barra.pack(fill=tk.X, side=tk.TOP)
        self.etiqueta_estado = ttk.Label(inferior, text="Listo.")
        self.etiqueta_estado.pack(side=tk.LEFT, pady=4)
        self.etiqueta_resultados = ttk.Label(inferior, text="", font=("Consolas", 10))
        self.etiqueta_resultados.pack(side=tk.RIGHT, pady=4)

    def _reiniciar_grafica(self):
        self.puntos_x.clear()
        self.puntos_y.clear()
        self.promedios.clear()
        self.promedios_n.clear()
        self.eje_valores.clear()
        self.eje_valores.set_title("Muestra de valores simulados de x")
        self.eje_valores.set_xlabel("iteracion")
        self.eje_promedio.clear()
        self.eje_promedio.set_title("Promedio acumulado de x")
        self.eje_promedio.set_xlabel("iteraciones completadas")
        self.serie_valores, = self.eje_valores.plot([], [], ".", markersize=2)
        self.serie_promedio, = self.eje_promedio.plot([], [])
        self.lienzo.draw_idle()

    # -- acciones -----------------------------------------------------------

    def _escribir_mensaje(self, texto: str):
        self.mensajes.configure(state=tk.NORMAL)
        self.mensajes.insert(tk.END, texto + "\n")
        self.mensajes.see(tk.END)
        self.mensajes.configure(state=tk.DISABLED)

    def _limpiar_mensajes(self):
        self.mensajes.configure(state=tk.NORMAL)
        self.mensajes.delete("1.0", tk.END)
        self.mensajes.configure(state=tk.DISABLED)

    def validar(self) -> bool:
        self._limpiar_mensajes()
        texto = self.editor.get("1.0", tk.END)
        _, errores = validar(texto)
        if errores:
            for error in errores:
                self._escribir_mensaje(f"[{error['etapa']}] {error['mensaje']}")
            self._escribir_mensaje("El modelo NO es valido.")
            return False
        self._escribir_mensaje("El modelo es valido (lexico, sintaxis y semantica).")
        return True

    def simular(self):
        if self.simulando:
            return
        if not self.validar():
            return
        semilla = self.entrada_semilla.get().strip()
        if semilla and not semilla.lstrip("-").isdigit():
            self._escribir_mensaje("La semilla debe ser un numero entero.")
            return
        self.simulando = True
        self.boton_simular.configure(state=tk.DISABLED)
        self.barra.configure(value=0)
        self._reiniciar_grafica()
        self.etiqueta_resultados.configure(text="")
        self.etiqueta_estado.configure(text="Compilando el modelo...")
        texto = self.editor.get("1.0", tk.END)
        hilo = threading.Thread(
            target=self._trabajo_simulacion,
            args=(texto, int(semilla) if semilla else None),
            daemon=True)
        hilo.start()

    # -- hilo de trabajo (red) ----------------------------------------------

    def _trabajo_simulacion(self, texto: str, semilla):
        try:
            with _post_json(URL_COMPILACION, {"modelo": texto}) as respuesta:
                compilado = json.loads(respuesta.read().decode("utf-8"))
            if not compilado.get("valido"):
                for error in compilado.get("errores", []):
                    self.cola.put(("mensaje", f"[{error['etapa']}] {error['mensaje']}"))
                self.cola.put(("fin", "El servicio de compilacion rechazo el modelo."))
                return
            self.cola.put(("mensaje", "Modelo compilado; iniciando simulacion..."))

            datos = {"script": compilado["script"], "firma": compilado["firma"]}
            if semilla is not None:
                datos["semilla"] = semilla
            with _post_json(URL_SIMULACION, datos) as flujo:
                for cruda in flujo:
                    linea = cruda.decode("utf-8").strip()
                    if linea:
                        self.cola.put(("evento", json.loads(linea)))
            self.cola.put(("fin", "Simulacion terminada."))
        except urllib.error.HTTPError as error:
            self.cola.put(("fin", f"Error del servicio ({error.code}): "
                                  f"{error.read().decode('utf-8', 'ignore')[:300]}"))
        except urllib.error.URLError as error:
            self.cola.put(("fin", f"No fue posible conectar con los servicios: "
                                  f"{error.reason}"))
        except Exception as error:  # red o JSON malformado
            self.cola.put(("fin", f"Error inesperado: {error}"))

    # -- actualizacion de la interfaz ---------------------------------------

    def _procesar_cola(self):
        try:
            while True:
                clase, contenido = self.cola.get_nowait()
                if clase == "mensaje":
                    self._escribir_mensaje(contenido)
                elif clase == "fin":
                    self._escribir_mensaje(contenido)
                    self.etiqueta_estado.configure(text=contenido)
                    self.simulando = False
                    self.boton_simular.configure(state=tk.NORMAL)
                elif clase == "evento":
                    self._aplicar_evento(contenido)
        except queue.Empty:
            pass
        self.after(100, self._procesar_cola)

    def _aplicar_evento(self, evento: dict):
        tipo = evento.get("tipo")
        if tipo == "progreso":
            completadas = evento["completadas"]
            total = evento["total"]
            base = len(self.puntos_x)
            for desplazamiento, valor in enumerate(evento.get("muestra", [])):
                self.puntos_x.append(base + desplazamiento)
                self.puntos_y.append(valor)
            if len(self.puntos_x) > MAX_PUNTOS_GRAFICA:
                self.puntos_x = self.puntos_x[-MAX_PUNTOS_GRAFICA:]
                self.puntos_y = self.puntos_y[-MAX_PUNTOS_GRAFICA:]
            promedio = evento.get("estadisticos", {}).get("avg")
            if promedio is not None:
                self.promedios_n.append(completadas)
                self.promedios.append(promedio)
            self._redibujar()
            self.barra.configure(value=100.0 * completadas / total)
            self.etiqueta_estado.configure(
                text=f"Simulando: {completadas:,} de {total:,} iteraciones")
        elif tipo == "resultado":
            estadisticos = evento.get("estadisticos", {})
            partes = [f"{ETIQUETAS.get(clave, clave)}: {valor:,.4f}"
                      for clave, valor in estadisticos.items() if valor is not None]
            self.etiqueta_resultados.configure(text="   ".join(partes))
            self._escribir_mensaje(
                f"Resultado final ({evento.get('validas', 0):,} iteraciones validas, "
                f"{evento.get('invalidas', 0):,} invalidas, "
                f"{evento.get('duracion_s', 0)} s, semilla {evento.get('semilla')}):")
            for clave, valor in estadisticos.items():
                if valor is not None:
                    self._escribir_mensaje(f"  {ETIQUETAS.get(clave, clave)}: {valor:.6f}")
            self.barra.configure(value=100)
        elif tipo == "error":
            self._escribir_mensaje(f"Error del simulador: {evento.get('mensaje')}")
            for renglon in evento.get("detalle", []):
                self._escribir_mensaje(f"  {renglon}")

    def _redibujar(self):
        self.serie_valores.set_data(self.puntos_x, self.puntos_y)
        self.eje_valores.relim()
        self.eje_valores.autoscale_view()
        self.serie_promedio.set_data(self.promedios_n, self.promedios)
        self.eje_promedio.relim()
        self.eje_promedio.autoscale_view()
        self.lienzo.draw_idle()


if __name__ == "__main__":
    Cliente().mainloop()
