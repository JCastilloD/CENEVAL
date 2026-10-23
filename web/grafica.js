// Dibuja la figura imitando a matplotlib (Figure 6.4x4.6, dpi 100, dos subplots)

const PT = 100 / 72;
const AZUL = "#1f77b4";
const FUENTE = '"DejaVu Sans", Verdana, sans-serif';
const PASOS = [0.1, 0.2, 0.25, 0.5, 1, 2, 2.5, 5, 10, 20];

function noSingular(a, b) {
  if (!isFinite(a) || !isFinite(b)) return [-0.001, 0.001];
  const maxAbs = Math.max(Math.abs(a), Math.abs(b));
  if (b - a <= maxAbs * 1e-15) {
    if (a === 0 && b === 0) return [-0.05, 0.05];
    return [a - 0.05 * Math.abs(a), b + 0.05 * Math.abs(b)];
  }
  return [a, b];
}

function escala(vmin, vmax, n) {
  const dv = Math.abs(vmax - vmin);
  const media = (vmin + vmax) / 2;
  let offset = 0;
  if (Math.abs(media) / dv >= 100) {
    offset = Math.sign(media) * Math.pow(10, Math.floor(Math.log10(Math.abs(media))));
  }
  return [Math.pow(10, Math.floor(Math.log10(dv / n))), offset];
}

function marcas(vmin, vmax, nbins) {
  const [sc, offset] = escala(vmin, vmax, nbins);
  const a = vmin - offset, b = vmax - offset;
  const pasos = PASOS.map(p => p * sc);
  const crudo = (b - a) / nbins;
  let i = pasos.findIndex(p => p >= crudo);
  if (i < 0) i = pasos.length - 1;
  let ticks = [];
  for (let j = i; j >= 0; j--) {
    const paso = pasos[j];
    const base = Math.floor(a / paso) * paso;
    const bajo = Math.floor((a - base) / paso + 1e-10);
    const alto = Math.ceil((b - base) / paso - 1e-10);
    ticks = [];
    for (let k = bajo; k <= alto; k++) ticks.push(k * paso + base);
    const visibles = ticks.filter(t => t >= a - 1e-12 && t <= b + 1e-12).length;
    if (visibles >= 2) break;
  }
  return ticks.map(t => t + offset);
}

function formato(locs, vmin, vmax) {
  const vis = locs.filter(t => t >= vmin - 1e-12 && t <= vmax + 1e-12);
  const maxAbs = Math.max(...vis.map(Math.abs), 0);
  let orden = 0;
  if (maxAbs > 0) {
    const oom = Math.floor(Math.log10(maxAbs));
    if (oom <= -5 || oom >= 6) orden = oom;
  }
  let vals = locs.map(t => t / Math.pow(10, orden));
  let rango = Math.max(...vals) - Math.min(...vals);
  if (rango === 0) rango = Math.max(...vals.map(Math.abs)) || 1;
  const rOom = Math.floor(Math.log10(rango));
  let dec = Math.max(0, 3 - rOom);
  const umbral = 1e-3 * Math.pow(10, rOom);
  while (dec >= 0) {
    const f = Math.pow(10, dec);
    if (Math.max(...vals.map(v => Math.abs(v - Math.round(v * f) / f))) < umbral) dec--;
    else break;
  }
  dec++;
  const etiqueta = v => {
    let s = v.toFixed(dec);
    if (/^-0(\.0+)?$/.test(s)) s = s.slice(1);
    return s.replace("-", "−");
  };
  return { textos: vals.map(etiqueta), sufijo: orden ? "1e" + orden : "" };
}

function limites(valores) {
  if (!valores.length) return [0, 1];
  let a = Infinity, b = -Infinity;
  for (const v of valores) { if (v < a) a = v; if (v > b) b = v; }
  [a, b] = noSingular(a, b);
  const m = (b - a) * 0.05;
  return [a - m, b + m];
}

export class Figura {
  constructor(canvas) {
    this.canvas = canvas;
    this.ejes = [
      { titulo: "Muestra de valores simulados de x", xlabel: "iteracion", tipo: "puntos", x: [], y: [], caja: [0.11, 0.5953, 0.97, 0.93] },
      { titulo: "Promedio acumulado de x", xlabel: "iteraciones completadas", tipo: "linea", x: [], y: [], caja: [0.11, 0.11, 0.97, 0.4447] },
    ];
    this.pendiente = false;
    new ResizeObserver(() => this.dibujar()).observe(canvas);
  }

  datos(indice, x, y) {
    this.ejes[indice].x = x;
    this.ejes[indice].y = y;
    if (!this.pendiente) {
      this.pendiente = true;
      requestAnimationFrame(() => { this.pendiente = false; this.dibujar(); });
    }
  }

  dibujar() {
    const c = this.canvas;
    const r = window.devicePixelRatio || 1;
    const ancho = c.clientWidth, alto = c.clientHeight;
    if (!ancho || !alto) return;
    if (c.width !== Math.round(ancho * r) || c.height !== Math.round(alto * r)) {
      c.width = Math.round(ancho * r);
      c.height = Math.round(alto * r);
    }
    const ctx = c.getContext("2d");
    ctx.setTransform(r, 0, 0, r, 0, 0);
    ctx.fillStyle = "#fff";
    ctx.fillRect(0, 0, ancho, alto);
    for (const eje of this.ejes) this.dibujarEje(ctx, eje, ancho, alto);
  }

  dibujarEje(ctx, eje, ancho, alto) {
    const [fx0, fy0, fx1, fy1] = eje.caja;
    const x0 = Math.max(fx0 * ancho, 60), x1 = fx1 * ancho;
    const y0 = (1 - fy1) * alto, y1 = (1 - fy0) * alto;
    const w = x1 - x0, h = y1 - y0;

    const [xa, xb] = limites(eje.x);
    const [ya, yb] = limites(eje.y);
    const px = v => x0 + (v - xa) / (xb - xa) * w;
    const py = v => y1 - (v - ya) / (yb - ya) * h;

    ctx.save();
    ctx.beginPath();
    ctx.rect(x0, y0, w, h);
    ctx.clip();
    ctx.fillStyle = AZUL;
    ctx.strokeStyle = AZUL;
    if (eje.tipo === "puntos") {
      const rad = 1.4;
      ctx.beginPath();
      for (let i = 0; i < eje.x.length; i++) {
        const cx = px(eje.x[i]), cy = py(eje.y[i]);
        ctx.moveTo(cx + rad, cy);
        ctx.arc(cx, cy, rad, 0, 2 * Math.PI);
      }
      ctx.fill();
    } else if (eje.x.length) {
      ctx.lineWidth = 1.5 * PT;
      ctx.lineJoin = "round";
      ctx.lineCap = "butt";
      ctx.beginPath();
      eje.x.forEach((v, i) => i ? ctx.lineTo(px(v), py(eje.y[i])) : ctx.moveTo(px(v), py(eje.y[i])));
      ctx.stroke();
    }
    ctx.restore();

    const lw = 0.8 * PT, largo = 3.5 * PT, pad = 3.5 * PT;
    const tam = 10 * PT;
    ctx.strokeStyle = "#000";
    ctx.fillStyle = "#000";
    ctx.lineWidth = lw;
    ctx.strokeRect(x0, y0, w, h);
    ctx.font = `${tam}px ${FUENTE}`;

    const nx = Math.max(1, Math.min(9, Math.floor((w / PT) / (10 * 3))));
    const tx = marcas(xa, xb, nx);
    const fxs = formato(tx, xa, xb);
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    tx.forEach((t, i) => {
      if (t < xa - 1e-9 || t > xb + 1e-9) return;
      const x = Math.round(px(t)) + 0.5;
      ctx.beginPath(); ctx.moveTo(x, y1); ctx.lineTo(x, y1 + largo); ctx.stroke();
      ctx.fillText(fxs.textos[i], x, y1 + largo + pad);
    });
    const bajoTicks = y1 + largo + pad + tam * 1.17;
    if (fxs.sufijo) {
      ctx.textAlign = "right";
      ctx.fillText(fxs.sufijo, x1, bajoTicks + 1);
    }
    ctx.textAlign = "center";
    ctx.fillText(eje.xlabel, x0 + w / 2, bajoTicks + 4 * PT * 0.3);

    const ny = Math.max(1, Math.min(9, Math.floor((h / PT) / (10 * 2))));
    const ty = marcas(ya, yb, ny);
    const fys = formato(ty, ya, yb);
    ctx.textAlign = "right";
    ctx.textBaseline = "middle";
    ty.forEach((t, i) => {
      if (t < ya - 1e-9 || t > yb + 1e-9) return;
      const y = Math.round(py(t)) + 0.5;
      ctx.beginPath(); ctx.moveTo(x0, y); ctx.lineTo(x0 - largo, y); ctx.stroke();
      ctx.fillText(fys.textos[i], x0 - largo - pad, y);
    });
    if (fys.sufijo) {
      ctx.textAlign = "left";
      ctx.textBaseline = "bottom";
      ctx.fillText(fys.sufijo, x0, y0 - 2);
    }

    ctx.font = `${12 * PT}px ${FUENTE}`;
    ctx.textAlign = "center";
    ctx.textBaseline = "alphabetic";
    ctx.fillText(eje.titulo, x0 + w / 2, y0 - 6 * PT - 3);
  }
}
