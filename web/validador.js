// Corre lexer.py y parser_modelo.py en el navegador con Pyodide,
// asi la validacion es local igual que en el cliente de escritorio.

const PYODIDE = "https://cdn.jsdelivr.net/npm/pyodide@0.29.5/";
let promesa = null;

function cargarScript(src) {
  return new Promise((ok, falla) => {
    const s = document.createElement("script");
    s.src = src;
    s.onload = ok;
    s.onerror = () => falla(new Error("no se pudo descargar " + src));
    document.head.appendChild(s);
  });
}

async function iniciar() {
  await cargarScript(PYODIDE + "pyodide.js");
  const py = await loadPyodide({ indexURL: PYODIDE });
  py.FS.mkdir("/analizador");
  for (const archivo of ["lexer.py", "parser_modelo.py"]) {
    const r = await fetch("py/" + archivo, { cache: "no-cache" });
    if (!r.ok) throw new Error("falta " + archivo);
    py.FS.writeFile("/analizador/" + archivo, await r.text());
  }
  await py.runPythonAsync(`
import sys, json
sys.path.insert(0, "/analizador")
from parser_modelo import validar

def validar_json(texto):
    _, errores = validar(texto)
    return json.dumps(errores)
`);
  return py.globals.get("validar_json");
}

export function cargarValidador() {
  if (!promesa) promesa = iniciar();
  return promesa;
}

export async function validarLocal(texto) {
  const validar = await cargarValidador();
  return JSON.parse(validar(texto));
}
