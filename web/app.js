import { Figura } from "./grafica.js";
import { cargarValidador, validarLocal } from "./validador.js";

const API = (window.CONFIG && window.CONFIG.api || "").replace(/\/$/, "");
const URL_COMPILACION = API + "/compilacion/compilar";
const URL_SIMULACION = API + "/simulacion/simular";
const MAX_PUNTOS_GRAFICA = 4000;

const MODELO_EJEMPLO = String.raw`{\model{x = \frac{-b \pm \sqrt{b^2 - 4ac}}{2a}}
\normal a{10, 0.5}
\distrib b{{10, 0.5}{15, 0.3}{20, 0.2}}
\uniform c{-20, 30}
\iter {1000000}
\response {avg, min, max}}
`;

const ETIQUETAS = { avg: "Promedio", min: "Minimo", max: "Maximo", std: "Desv. estandar" };

const $ = id => document.getElementById(id);
const editor = $("editor");
const mensajes = $("mensajes");
const botonValidar = $("validar");
const botonSimular = $("simular");
const semillaEntrada = $("semilla");
const barra = $("barra");
const estado = $("estado");
const resultados = $("resultados");

const figura = new Figura($("figura"));
let simulando = false;
let puntosX = [], puntosY = [], promedios = [], promediosN = [];

const miles = n => Number(n).toLocaleString("en-US");
const fijo = (n, d) => Number(n).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d, useGrouping: true });
const pyFloat = n => Number.isInteger(n) ? n.toFixed(1) : String(n);

function escribir(texto) {
  mensajes.value += texto + "\n";
  mensajes.scrollTop = mensajes.scrollHeight;
}

function limpiar() {
  mensajes.value = "";
}

function ponerEstado(texto) {
  estado.textContent = texto;
}

function progreso(valor) {
  barra.style.setProperty("--avance", Math.max(0, Math.min(100, valor)) + "%");
}

function reiniciarGrafica() {
  puntosX = []; puntosY = []; promedios = []; promediosN = [];
  redibujar();
}

function redibujar() {
  figura.datos(0, puntosX, puntosY);
  figura.datos(1, promediosN, promedios);
}

async function postJson(url, datos) {
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(datos),
  });
  if (!r.ok) {
    const texto = (await r.text()).slice(0, 300);
    const e = new Error(texto);
    e.codigo = r.status;
    throw e;
  }
  return r;
}

async function obtenerErrores(texto) {
  const previo = estado.textContent;
  try {
    if (!window.pyodideListo) ponerEstado("Cargando el analizador...");
    const errores = await validarLocal(texto);
    window.pyodideListo = true;
    return errores;
  } catch (e) {
    // sin Pyodide se valida con el servicio de compilacion
    const r = await postJson(URL_COMPILACION, { modelo: texto });
    return (await r.json()).errores || [];
  } finally {
    ponerEstado(previo);
  }
}

async function validar() {
  limpiar();
  const texto = editor.value + "\n";
  let errores;
  try {
    errores = await obtenerErrores(texto);
  } catch (e) {
    escribir("No fue posible validar el modelo: " + (e.message || e));
    return false;
  }
  if (errores.length) {
    for (const error of errores) escribir(`[${error.etapa}] ${error.mensaje}`);
    escribir("El modelo NO es valido.");
    return false;
  }
  escribir("El modelo es valido (lexico, sintaxis y semantica).");
  return true;
}

function terminar(texto) {
  escribir(texto);
  ponerEstado(texto);
  simulando = false;
  botonSimular.disabled = false;
}

async function simular() {
  if (simulando) return;
  if (!(await validar())) return;
  const semilla = semillaEntrada.value.trim();
  if (semilla && !/^-?\d+$/.test(semilla)) {
    escribir("La semilla debe ser un numero entero.");
    return;
  }
  simulando = true;
  botonSimular.disabled = true;
  progreso(0);
  reiniciarGrafica();
  resultados.textContent = "";
  ponerEstado("Compilando el modelo...");
  const texto = editor.value + "\n";

  try {
    const compilado = await (await postJson(URL_COMPILACION, { modelo: texto })).json();
    if (!compilado.valido) {
      for (const error of compilado.errores || []) escribir(`[${error.etapa}] ${error.mensaje}`);
      terminar("El servicio de compilacion rechazo el modelo.");
      return;
    }
    escribir("Modelo compilado; iniciando simulacion...");

    const datos = { script: compilado.script, firma: compilado.firma };
    if (semilla) datos.semilla = parseInt(semilla, 10);
    const respuesta = await postJson(URL_SIMULACION, datos);
    const lector = respuesta.body.getReader();
    const decodificador = new TextDecoder();
    let resto = "";
    for (;;) {
      const { value, done } = await lector.read();
      if (value) resto += decodificador.decode(value, { stream: true });
      const lineas = resto.split("\n");
      resto = done ? "" : lineas.pop();
      for (const linea of lineas) {
        if (linea.trim()) aplicarEvento(JSON.parse(linea));
      }
      if (done) break;
    }
    terminar("Simulacion terminada.");
  } catch (e) {
    if (e.codigo) terminar(`Error del servicio (${e.codigo}): ${e.message}`);
    else if (e instanceof TypeError) terminar(`No fue posible conectar con los servicios: ${e.message}`);
    else terminar(`Error inesperado: ${e.message || e}`);
  }
}

function aplicarEvento(evento) {
  const tipo = evento.tipo;
  if (tipo === "progreso") {
    const { completadas, total } = evento;
    const base = puntosX.length;
    (evento.muestra || []).forEach((valor, i) => {
      puntosX.push(base + i);
      puntosY.push(valor);
    });
    if (puntosX.length > MAX_PUNTOS_GRAFICA) {
      puntosX = puntosX.slice(-MAX_PUNTOS_GRAFICA);
      puntosY = puntosY.slice(-MAX_PUNTOS_GRAFICA);
    }
    const promedio = (evento.estadisticos || {}).avg;
    if (promedio !== undefined && promedio !== null) {
      promediosN.push(completadas);
      promedios.push(promedio);
    }
    redibujar();
    progreso(100 * completadas / total);
    ponerEstado(`Simulando: ${miles(completadas)} de ${miles(total)} iteraciones`);
  } else if (tipo === "resultado") {
    const est = evento.estadisticos || {};
    const partes = Object.entries(est)
      .filter(([, v]) => v !== null && v !== undefined)
      .map(([k, v]) => `${ETIQUETAS[k] || k}: ${fijo(v, 4)}`);
    resultados.textContent = partes.join("   ");
    escribir(`Resultado final (${miles(evento.validas || 0)} iteraciones validas, ` +
      `${miles(evento.invalidas || 0)} invalidas, ` +
      `${pyFloat(evento.duracion_s || 0)} s, semilla ${evento.semilla}):`);
    for (const [k, v] of Object.entries(est)) {
      if (v !== null && v !== undefined) escribir(`  ${ETIQUETAS[k] || k}: ${Number(v).toFixed(6)}`);
    }
    progreso(100);
  } else if (tipo === "error") {
    escribir(`Error del simulador: ${evento.mensaje}`);
    for (const renglon of evento.detalle || []) escribir(`  ${renglon}`);
  }
}

editor.value = MODELO_EJEMPLO;
botonValidar.addEventListener("click", validar);
botonSimular.addEventListener("click", simular);
editor.addEventListener("keydown", e => {
  if (e.key === "Tab") {
    e.preventDefault();
    editor.setRangeText("\t", editor.selectionStart, editor.selectionEnd, "end");
  }
});

document.fonts.load(`14px "DejaVu Sans"`).finally(() => figura.dibujar());
reiniciarGrafica();

// despierta el contenedor (escala a cero cuando nadie lo usa)
fetch(API + "/", { cache: "no-store" }).catch(() => {});
setTimeout(() => cargarValidador().then(() => { window.pyodideListo = true; }).catch(() => {}), 300);

if ("serviceWorker" in navigator && location.protocol === "https:") {
  navigator.serviceWorker.register("sw.js").catch(() => {});
}
