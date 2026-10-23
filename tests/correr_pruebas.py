"""Suite de pruebas del compilador y del simulador.

Ejecucion (desde la carpeta raiz del proyecto):
    python -m unittest tests.correr_pruebas -v

Las pruebas cubren:
  * Analisis lexico: tokens validos y rechazo de entradas maliciosas.
  * Analisis sintactico y semantico: modelo de ejemplo y casos de error.
  * Generacion de codigo: el script compila y no interpola texto crudo.
  * Correctitud estadistica: los estadisticos simulados coinciden con los
    valores teoricos de las distribuciones (ley de los grandes numeros).
  * Correctitud del procesamiento concurrente: el resultado es identico
    con 1 y con 4 procesos, y reproducible con la misma semilla.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, "src"))

import firma                                    # noqa: E402
from codegen import generar_script              # noqa: E402
from lexer import analizar                      # noqa: E402
from parser_modelo import validar               # noqa: E402

MODELO_EJEMPLO = r"""{\model{x = \frac{-b \pm \sqrt{b^2 - 4ac}}{2a}}
\normal a{10, 0.5}
\distrib b{{10, 0.5}{15, 0.3}{20, 0.2}}
\uniform c{-20, 30}
\iter {1000000}
\response {avg, min, max}}
"""


def _modelo_simple(expresion, declaraciones, iteraciones=200000,
                   respuestas="avg, min, max, std"):
    return ("{\\model{x = " + expresion + "}\n" + declaraciones +
            "\n\\iter {" + str(iteraciones) + "}\n\\response {" +
            respuestas + "}}")


def _ejecutar_script(script, semilla=12345, procesos=None):
    """Corre un script generado en un subproceso y devuelve la linea final."""
    descriptor, ruta = tempfile.mkstemp(suffix=".py", prefix="prueba_sim_")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as archivo:
            archivo.write(script)
        argumentos = [sys.executable, ruta, str(semilla)]
        if procesos:
            argumentos.append(str(procesos))
        salida = subprocess.run(
            argumentos, capture_output=True, text=True, timeout=240, check=True)
        lineas = [json.loads(l) for l in salida.stdout.splitlines() if l.strip()]
        resultado = lineas[-1]
        assert resultado["tipo"] == "resultado", resultado
        return resultado, lineas
    finally:
        os.unlink(ruta)


class PruebasLexer(unittest.TestCase):
    def test_modelo_ejemplo_sin_errores(self):
        tokens, errores = analizar(MODELO_EJEMPLO)
        self.assertEqual(errores, [])
        comandos = [t.lexema for t in tokens if t.tipo == "COMANDO"]
        self.assertEqual(comandos[:2], ["model", "frac"])
        self.assertIn("pm", comandos)
        self.assertIn("response", comandos)

    def test_rechaza_caracteres_fuera_del_alfabeto(self):
        for entrada in ['"hola"', "os.system('x'); ", "a[1]", "x = 5 % 2", "#!"]:
            _, errores = analizar(entrada)
            self.assertTrue(errores, f"debio rechazar {entrada!r}")
            self.assertTrue(any(e.malicioso for e in errores))

    def test_rechaza_comando_desconocido(self):
        _, errores = analizar(r"\import {os}")
        self.assertTrue(any("comando no reconocido" in e.mensaje for e in errores))

    def test_rechaza_entrada_demasiado_larga(self):
        _, errores = analizar("a" * 20000)
        self.assertTrue(any("limite" in e.mensaje for e in errores))

    def test_numero_mal_formado(self):
        _, errores = analizar("3.")
        self.assertTrue(errores)


class PruebasParser(unittest.TestCase):
    def test_modelo_ejemplo_valido(self):
        modelo, errores = validar(MODELO_EJEMPLO)
        self.assertEqual(errores, [])
        self.assertEqual(modelo.variable_salida, "x")
        self.assertEqual(sorted(modelo.distribuciones), ["a", "b", "c"])
        self.assertEqual(modelo.iteraciones, 1000000)
        self.assertEqual(modelo.respuestas, ["avg", "min", "max"])

    def test_variable_no_declarada(self):
        texto = _modelo_simple("a + z", "\\normal a{10, 0.5}")
        _, errores = validar(texto)
        self.assertTrue(any("'z'" in e["mensaje"] for e in errores))

    def test_probabilidades_no_suman_uno(self):
        texto = _modelo_simple("b", "\\distrib b{{10, 0.5}{20, 0.4}}")
        _, errores = validar(texto)
        self.assertTrue(any("sumar 1" in e["mensaje"] for e in errores))

    def test_uniforme_invertida(self):
        texto = _modelo_simple("c", "\\uniform c{30, -20}")
        _, errores = validar(texto)
        self.assertTrue(any("minimo" in e["mensaje"] for e in errores))

    def test_limite_de_iteraciones(self):
        texto = _modelo_simple("a", "\\normal a{10, 0.5}", iteraciones=10**9)
        _, errores = validar(texto)
        self.assertTrue(any("iteraciones" in e["mensaje"] for e in errores))

    def test_estadistico_no_soportado(self):
        texto = _modelo_simple("a", "\\normal a{10, 0.5}", respuestas="avg, moda")
        _, errores = validar(texto)
        self.assertTrue(any("no soportado" in e["mensaje"] for e in errores))

    def test_rechaza_texto_adicional(self):
        _, errores = validar(MODELO_EJEMPLO + " sobra")
        self.assertTrue(errores)


class PruebasCodegen(unittest.TestCase):
    def test_script_compila(self):
        modelo, _ = validar(MODELO_EJEMPLO)
        script = generar_script(modelo)
        compile(script, "<script-generado>", "exec")
        self.assertIn("multiprocessing", script)
        self.assertIn("SeedSequence", script)
        self.assertIn("signos_0", script)  # el operador \pm genera signos

    def test_firma_detecta_alteraciones(self):
        modelo, _ = validar(MODELO_EJEMPLO)
        script = generar_script(modelo)
        etiqueta = firma.firmar(script)
        self.assertTrue(firma.verificar(script, etiqueta))
        self.assertFalse(firma.verificar(script + "\nimport os", etiqueta))


class PruebasCorrectitud(unittest.TestCase):
    """Validacion estadistica y de concurrencia sobre scripts generados."""

    def _resultado(self, texto, **kwargs):
        modelo, errores = validar(texto)
        self.assertEqual(errores, [])
        return _ejecutar_script(generar_script(modelo), **kwargs)

    def test_normal_converge_a_su_media(self):
        texto = _modelo_simple("a", "\\normal a{10, 0.5}")
        resultado, _ = self._resultado(texto)
        est = resultado["estadisticos"]
        self.assertAlmostEqual(est["avg"], 10.0, delta=0.02)
        self.assertAlmostEqual(est["std"], 0.5, delta=0.02)

    def test_uniforme_converge_a_su_media(self):
        texto = _modelo_simple("c", "\\uniform c{-20, 30}")
        resultado, _ = self._resultado(texto)
        est = resultado["estadisticos"]
        self.assertAlmostEqual(est["avg"], 5.0, delta=0.2)
        self.assertGreaterEqual(est["min"], -20.0)
        self.assertLessEqual(est["max"], 30.0)

    def test_tabla_de_probabilidades(self):
        texto = _modelo_simple("b", "\\distrib b{{10, 0.5}{15, 0.3}{20, 0.2}}")
        resultado, _ = self._resultado(texto)
        est = resultado["estadisticos"]
        # E[b] = 10*0.5 + 15*0.3 + 20*0.2 = 13.5
        self.assertAlmostEqual(est["avg"], 13.5, delta=0.1)
        self.assertEqual(est["min"], 10.0)
        self.assertEqual(est["max"], 20.0)

    def test_mismo_resultado_secuencial_y_paralelo(self):
        texto = _modelo_simple("a + c", "\\normal a{10, 0.5}\n\\uniform c{-20, 30}")
        con_uno, _ = self._resultado(texto, semilla=777, procesos=1)
        con_cuatro, _ = self._resultado(texto, semilla=777, procesos=4)
        self.assertEqual(con_uno["estadisticos"], con_cuatro["estadisticos"])
        self.assertEqual(con_uno["validas"], con_cuatro["validas"])

    def test_reproducible_con_la_misma_semilla(self):
        texto = _modelo_simple("a", "\\normal a{10, 0.5}", iteraciones=100000)
        primero, _ = self._resultado(texto, semilla=42)
        segundo, _ = self._resultado(texto, semilla=42)
        self.assertEqual(primero["estadisticos"], segundo["estadisticos"])

    def test_ejemplo_completo_reporta_invalidas(self):
        # En el modelo de ejemplo el discriminante b^2 - 4ac puede ser
        # negativo (raiz de un numero negativo), por lo que debe haber
        # iteraciones invalidas y estadisticos finitos sobre las validas.
        modelo, errores = validar(MODELO_EJEMPLO)
        self.assertEqual(errores, [])
        modelo.iteraciones = 200000  # version reducida para la prueba
        resultado, lineas = _ejecutar_script(generar_script(modelo), semilla=7)
        self.assertGreater(resultado["invalidas"], 0)
        self.assertGreater(resultado["validas"], 0)
        for clave in ("avg", "min", "max"):
            self.assertIsNotNone(resultado["estadisticos"][clave])
        progresos = [l for l in lineas if l["tipo"] == "progreso"]
        self.assertGreater(len(progresos), 1)
        self.assertTrue(all(p["muestra"] for p in progresos))


if __name__ == "__main__":
    unittest.main(verbosity=2)
