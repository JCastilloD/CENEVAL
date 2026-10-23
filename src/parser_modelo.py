"""Analizador sintactico y semantico del lenguaje de modelos.

Implementa por descenso recursivo la gramatica libre de contexto G (tipo 2
en la jerarquia de Chomsky) descrita en docs/consigna_a_gramatica.md:

    programa     -> "{" modelo declaraciones iteraciones respuesta "}"
    modelo       -> "\\model" "{" IDENT "=" expresion "}"
    declaraciones-> declaracion { declaracion }
    declaracion  -> normal | distrib | uniform
    normal       -> "\\normal" IDENT "{" numero "," numero "}"
    distrib      -> "\\distrib" IDENT "{" par { par } "}"
    par          -> "{" numero "," numero "}"
    uniform      -> "\\uniform" IDENT "{" numero "," numero "}"
    iteraciones  -> "\\iter" "{" ENTERO "}"
    respuesta    -> "\\response" "{" IDENT { "," IDENT } "}"
    numero       -> [ "-" ] ( ENTERO | DECIMAL )

    expresion    -> termino { ("+" | "-" | "\\pm") termino }
    termino      -> factor { ("*" | "/") factor | factor_yuxtapuesto }
    factor       -> base [ "^" exponente ]
    exponente    -> base | "{" expresion "}"
    base         -> NUMERO | IDENT | "(" expresion ")"
                  | "\\frac" "{" expresion "}" "{" expresion "}"
                  | "\\sqrt" "{" expresion "}"
                  | "-" base

Convenciones tomadas de la notacion matematica de LaTeX:
  * Las variables aleatorias son de una sola letra; un identificador de
    varias letras dentro de una expresion (por ejemplo `ac`) se interpreta
    como producto implicito de variables (`a * c`), igual que `4ac`.
  * El operador `\\pm` selecciona aleatoriamente el signo (+ o -) en cada
    iteracion de la simulacion, con probabilidad 1/2 cada uno.
"""

from dataclasses import dataclass, field

from lexer import (
    analizar, Token,
    COMANDO, IDENT, ENTERO, DECIMAL, LLAVE_A, LLAVE_C, COMA, IGUAL, CARET,
    MAS, MENOS, POR, DIAG, PAR_A, PAR_C, FIN,
)

ITERACIONES_MAXIMAS = 100_000_000
RESPUESTAS_VALIDAS = ("avg", "min", "max", "std")


# ---------------------------------------------------------------------------
# Arbol de sintaxis abstracta (AST)
# ---------------------------------------------------------------------------

@dataclass
class Num:
    valor: float


@dataclass
class Var:
    nombre: str


@dataclass
class OpBin:
    op: str          # '+', '-', '*', '/', '^' o 'pm'
    izq: object
    der: object


@dataclass
class OpUnaria:
    op: str          # '-'
    operando: object


@dataclass
class Raiz:
    operando: object


@dataclass
class DistNormal:
    media: float
    desviacion: float


@dataclass
class DistTabla:
    pares: list      # lista de tuplas (valor, probabilidad)


@dataclass
class DistUniforme:
    minimo: float
    maximo: float


@dataclass
class Modelo:
    variable_salida: str
    expresion: object
    distribuciones: dict = field(default_factory=dict)  # nombre -> distribucion
    iteraciones: int = 0
    respuestas: list = field(default_factory=list)


@dataclass
class ErrorSintactico:
    mensaje: str
    linea: int
    columna: int

    def __str__(self):
        return f"Linea {self.linea}, col {self.columna}: {self.mensaje}"


@dataclass
class ErrorSemantico:
    mensaje: str

    def __str__(self):
        return self.mensaje


class _FalloSintaxis(Exception):
    """Interrumpe el analisis ante el primer error sintactico."""


# ---------------------------------------------------------------------------
# Analizador sintactico por descenso recursivo
# ---------------------------------------------------------------------------

class Parser:
    def __init__(self, tokens: list):
        self.tokens = tokens
        self.pos = 0
        self.errores: list[ErrorSintactico] = []

    # -- utilerias ----------------------------------------------------------

    def actual(self) -> Token:
        return self.tokens[self.pos]

    def coincide(self, tipo: str, lexema: str = None) -> bool:
        t = self.actual()
        return t.tipo == tipo and (lexema is None or t.lexema == lexema)

    def consumir(self, tipo: str, lexema: str = None, esperado: str = None) -> Token:
        t = self.actual()
        if self.coincide(tipo, lexema):
            self.pos += 1
            return t
        descripcion = esperado or lexema or tipo
        encontrado = t.lexema if t.tipo != FIN else "fin de la entrada"
        self.errores.append(ErrorSintactico(
            f"se esperaba {descripcion!r} y se encontro {encontrado!r}",
            t.linea, t.columna))
        raise _FalloSintaxis()

    # -- producciones -------------------------------------------------------

    def programa(self) -> Modelo:
        self.consumir(LLAVE_A, esperado="{")
        modelo = self.modelo()
        self.declaraciones(modelo)
        self.iteraciones(modelo)
        self.respuesta(modelo)
        self.consumir(LLAVE_C, esperado="}")
        self.consumir(FIN, esperado="fin de la entrada")
        return modelo

    def modelo(self) -> Modelo:
        self.consumir(COMANDO, "model", esperado="\\model")
        self.consumir(LLAVE_A, esperado="{")
        nombre = self.consumir(IDENT, esperado="identificador de la variable de salida").lexema
        self.consumir(IGUAL, esperado="=")
        expresion = self.expresion()
        self.consumir(LLAVE_C, esperado="}")
        return Modelo(variable_salida=nombre, expresion=expresion)

    def declaraciones(self, modelo: Modelo):
        cuantas = 0
        while self.coincide(COMANDO, "normal") or self.coincide(COMANDO, "distrib") \
                or self.coincide(COMANDO, "uniform"):
            comando = self.actual().lexema
            token_cmd = self.consumir(COMANDO)
            nombre = self.consumir(IDENT, esperado="nombre de variable").lexema
            if comando == "normal":
                self.consumir(LLAVE_A, esperado="{")
                media = self.numero()
                self.consumir(COMA, esperado=",")
                desviacion = self.numero()
                self.consumir(LLAVE_C, esperado="}")
                distribucion = DistNormal(media, desviacion)
            elif comando == "uniform":
                self.consumir(LLAVE_A, esperado="{")
                minimo = self.numero()
                self.consumir(COMA, esperado=",")
                maximo = self.numero()
                self.consumir(LLAVE_C, esperado="}")
                distribucion = DistUniforme(minimo, maximo)
            else:  # distrib
                self.consumir(LLAVE_A, esperado="{")
                pares = []
                while self.coincide(LLAVE_A):
                    self.consumir(LLAVE_A)
                    valor = self.numero()
                    self.consumir(COMA, esperado=",")
                    probabilidad = self.numero()
                    self.consumir(LLAVE_C, esperado="}")
                    pares.append((valor, probabilidad))
                if not pares:
                    self.errores.append(ErrorSintactico(
                        "\\distrib requiere al menos un par {valor, probabilidad}",
                        token_cmd.linea, token_cmd.columna))
                    raise _FalloSintaxis()
                self.consumir(LLAVE_C, esperado="}")
                distribucion = DistTabla(pares)
            if nombre in modelo.distribuciones:
                self.errores.append(ErrorSintactico(
                    f"la variable {nombre!r} ya fue declarada",
                    token_cmd.linea, token_cmd.columna))
                raise _FalloSintaxis()
            modelo.distribuciones[nombre] = distribucion
            cuantas += 1
        if cuantas == 0:
            t = self.actual()
            self.errores.append(ErrorSintactico(
                "se esperaba al menos una declaracion \\normal, \\distrib o \\uniform",
                t.linea, t.columna))
            raise _FalloSintaxis()

    def iteraciones(self, modelo: Modelo):
        self.consumir(COMANDO, "iter", esperado="\\iter")
        self.consumir(LLAVE_A, esperado="{")
        token = self.consumir(ENTERO, esperado="numero entero de iteraciones")
        modelo.iteraciones = int(token.lexema)
        self.consumir(LLAVE_C, esperado="}")

    def respuesta(self, modelo: Modelo):
        self.consumir(COMANDO, "response", esperado="\\response")
        self.consumir(LLAVE_A, esperado="{")
        modelo.respuestas.append(self.consumir(IDENT, esperado="estadistico").lexema)
        while self.coincide(COMA):
            self.consumir(COMA)
            modelo.respuestas.append(self.consumir(IDENT, esperado="estadistico").lexema)
        self.consumir(LLAVE_C, esperado="}")

    def numero(self) -> float:
        signo = 1.0
        if self.coincide(MENOS):
            self.consumir(MENOS)
            signo = -1.0
        if self.coincide(ENTERO) or self.coincide(DECIMAL):
            token = self.actual()
            self.pos += 1
            return signo * float(token.lexema)
        t = self.actual()
        self.errores.append(ErrorSintactico(
            f"se esperaba un numero y se encontro {t.lexema!r}", t.linea, t.columna))
        raise _FalloSintaxis()

    # -- expresiones --------------------------------------------------------

    def expresion(self):
        nodo = self.termino()
        while self.coincide(MAS) or self.coincide(MENOS) or self.coincide(COMANDO, "pm"):
            if self.coincide(COMANDO, "pm"):
                self.consumir(COMANDO, "pm")
                nodo = OpBin("pm", nodo, self.termino())
            elif self.coincide(MAS):
                self.consumir(MAS)
                nodo = OpBin("+", nodo, self.termino())
            else:
                self.consumir(MENOS)
                nodo = OpBin("-", nodo, self.termino())
        return nodo

    def _inicia_factor_yuxtapuesto(self) -> bool:
        # Multiplicacion implicita al estilo LaTeX: 2a, 4ac, 3\sqrt{...}
        return (self.coincide(IDENT) or self.coincide(PAR_A)
                or self.coincide(COMANDO, "frac") or self.coincide(COMANDO, "sqrt"))

    def termino(self):
        nodo = self.factor()
        while True:
            if self.coincide(POR):
                self.consumir(POR)
                nodo = OpBin("*", nodo, self.factor())
            elif self.coincide(DIAG):
                self.consumir(DIAG)
                nodo = OpBin("/", nodo, self.factor())
            elif self._inicia_factor_yuxtapuesto():
                nodo = OpBin("*", nodo, self.factor())
            else:
                return nodo

    def factor(self):
        nodo = self.base()
        if self.coincide(CARET):
            self.consumir(CARET)
            if self.coincide(LLAVE_A):
                self.consumir(LLAVE_A)
                exponente = self.expresion()
                self.consumir(LLAVE_C, esperado="}")
            else:
                exponente = self.base()
            nodo = OpBin("^", nodo, exponente)
        return nodo

    def base(self):
        if self.coincide(ENTERO) or self.coincide(DECIMAL):
            token = self.actual()
            self.pos += 1
            return Num(float(token.lexema))
        if self.coincide(IDENT):
            token = self.consumir(IDENT)
            return self._expandir_identificador(token.lexema)
        if self.coincide(PAR_A):
            self.consumir(PAR_A)
            nodo = self.expresion()
            self.consumir(PAR_C, esperado=")")
            return nodo
        if self.coincide(COMANDO, "frac"):
            self.consumir(COMANDO, "frac")
            self.consumir(LLAVE_A, esperado="{")
            numerador = self.expresion()
            self.consumir(LLAVE_C, esperado="}")
            self.consumir(LLAVE_A, esperado="{")
            denominador = self.expresion()
            self.consumir(LLAVE_C, esperado="}")
            return OpBin("/", numerador, denominador)
        if self.coincide(COMANDO, "sqrt"):
            self.consumir(COMANDO, "sqrt")
            self.consumir(LLAVE_A, esperado="{")
            operando = self.expresion()
            self.consumir(LLAVE_C, esperado="}")
            return Raiz(operando)
        if self.coincide(MENOS):
            self.consumir(MENOS)
            return OpUnaria("-", self.base())
        t = self.actual()
        encontrado = t.lexema if t.tipo != FIN else "fin de la entrada"
        self.errores.append(ErrorSintactico(
            f"expresion mal formada: no se esperaba {encontrado!r}", t.linea, t.columna))
        raise _FalloSintaxis()

    @staticmethod
    def _expandir_identificador(lexema: str):
        # `ac` equivale a `a * c` (variables de una letra, producto implicito)
        nodo = Var(lexema[0])
        for letra in lexema[1:]:
            nodo = OpBin("*", nodo, Var(letra))
        return nodo


# ---------------------------------------------------------------------------
# Analisis semantico
# ---------------------------------------------------------------------------

def _variables_de(nodo, acumulado: set):
    if isinstance(nodo, Var):
        acumulado.add(nodo.nombre)
    elif isinstance(nodo, OpBin):
        _variables_de(nodo.izq, acumulado)
        _variables_de(nodo.der, acumulado)
    elif isinstance(nodo, (OpUnaria, Raiz)):
        _variables_de(nodo.operando, acumulado)


def analizar_semantica(modelo: Modelo) -> list:
    """Verifica las reglas del lenguaje que la gramatica no puede expresar."""
    errores: list[ErrorSemantico] = []

    usadas: set[str] = set()
    _variables_de(modelo.expresion, usadas)

    if modelo.variable_salida in modelo.distribuciones:
        errores.append(ErrorSemantico(
            f"la variable de salida {modelo.variable_salida!r} no puede tener "
            "una distribucion declarada"))

    for nombre in sorted(usadas):
        if nombre != modelo.variable_salida and nombre not in modelo.distribuciones:
            errores.append(ErrorSemantico(
                f"la variable {nombre!r} se usa en el modelo pero no fue declarada"))

    for nombre in sorted(modelo.distribuciones):
        if nombre not in usadas:
            errores.append(ErrorSemantico(
                f"la variable {nombre!r} fue declarada pero no se usa en el modelo"))

    for nombre, dist in modelo.distribuciones.items():
        if isinstance(dist, DistNormal) and dist.desviacion <= 0:
            errores.append(ErrorSemantico(
                f"\\normal {nombre}: la desviacion estandar debe ser positiva"))
        elif isinstance(dist, DistUniforme) and dist.minimo >= dist.maximo:
            errores.append(ErrorSemantico(
                f"\\uniform {nombre}: el minimo debe ser menor que el maximo"))
        elif isinstance(dist, DistTabla):
            probabilidades = [p for _, p in dist.pares]
            if any(p <= 0 or p > 1 for p in probabilidades):
                errores.append(ErrorSemantico(
                    f"\\distrib {nombre}: toda probabilidad debe estar en (0, 1]"))
            elif abs(sum(probabilidades) - 1.0) > 1e-6:
                errores.append(ErrorSemantico(
                    f"\\distrib {nombre}: las probabilidades deben sumar 1 "
                    f"(suman {sum(probabilidades):g})"))

    if not (1 <= modelo.iteraciones <= ITERACIONES_MAXIMAS):
        errores.append(ErrorSemantico(
            f"\\iter: el numero de iteraciones debe estar entre 1 y "
            f"{ITERACIONES_MAXIMAS} (se pidio {modelo.iteraciones})"))

    vistas = set()
    for respuesta in modelo.respuestas:
        if respuesta not in RESPUESTAS_VALIDAS:
            errores.append(ErrorSemantico(
                f"\\response: estadistico no soportado {respuesta!r}; "
                f"validos: {', '.join(RESPUESTAS_VALIDAS)}"))
        elif respuesta in vistas:
            errores.append(ErrorSemantico(
                f"\\response: estadistico repetido {respuesta!r}"))
        vistas.add(respuesta)

    return errores


# ---------------------------------------------------------------------------
# Punto de entrada de validacion (usado por el cliente y por los servicios)
# ---------------------------------------------------------------------------

def validar(texto: str):
    """Corre las tres fases de analisis sobre el texto del modelo.

    Devuelve (modelo, errores): si errores no esta vacio, modelo es None.
    Cada error es un dict con las claves 'etapa' y 'mensaje'.
    """
    tokens, errores_lexicos = analizar(texto)
    if errores_lexicos:
        return None, [{"etapa": "lexica", "mensaje": str(e)} for e in errores_lexicos]

    parser = Parser(tokens)
    try:
        modelo = parser.programa()
    except _FalloSintaxis:
        return None, [{"etapa": "sintactica", "mensaje": str(e)} for e in parser.errores]

    errores_semanticos = analizar_semantica(modelo)
    if errores_semanticos:
        return None, [{"etapa": "semantica", "mensaje": str(e)} for e in errores_semanticos]

    return modelo, []
