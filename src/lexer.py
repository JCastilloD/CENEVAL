"""Analizador lexico del lenguaje de modelos de simulacion Monte Carlo.

Implementa un automata finito determinista (AFD) definido formalmente como
la quintupla:

    M = (Q, Sigma, delta, q0, F)

donde:
    Q     = {Q0, Q_BARRA, Q_CMD, Q_IDENT, Q_ENT, Q_PUNTO, Q_DEC}
            mas un estado aceptor implicito por cada simbolo simple.
    Sigma = clases de caracteres: BARRA, LETRA, DIGITO, PUNTO, simbolos
            simples ({ } , = ^ + - * / ( )) y ESPACIO. Todo caracter fuera
            de estas clases pertenece a la clase OTRO y provoca rechazo.
    delta = tabla TRANSICIONES (abajo). Toda transicion no listada es
            indefinida y provoca rechazo de la cadena.
    q0    = Q0
    F     = {Q_CMD, Q_IDENT, Q_ENT, Q_DEC} mas los simbolos simples.

El AFD opera con la politica de coincidencia maxima (maximal munch): desde
la posicion actual consume caracteres mientras exista transicion definida;
al detenerse, si el estado alcanzado es final emite el token, si no,
registra un error lexico.

Seguridad (deteccion de entradas maliciosas):
    1. El alfabeto es una lista blanca: comillas, punto y coma, corchetes,
       signos de porcentaje, etc., no tienen transicion definida, por lo que
       cualquier intento de inyectar codigo (por ejemplo `import os` entre
       comillas, `; os.system(...)`, cadenas con formato) se rechaza antes
       de llegar al generador de codigo.
    2. Los comandos (`\\model`, `\\normal`, ...) tambien son lista blanca:
       un comando no reconocido se reporta como posible entrada maliciosa.
    3. Se impone un limite de longitud a la entrada para evitar abusos de
       recursos (denegacion de servicio).
"""

from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Configuracion
# ---------------------------------------------------------------------------

MAX_LONGITUD_ENTRADA = 10_000  # caracteres; proteccion contra abuso de recursos

COMANDOS_VALIDOS = {
    "model", "normal", "distrib", "uniform", "iter", "response",
    "frac", "sqrt", "pm",
}

# ---------------------------------------------------------------------------
# Tipos de token
# ---------------------------------------------------------------------------

COMANDO = "COMANDO"
IDENT = "IDENT"
ENTERO = "ENTERO"
DECIMAL = "DECIMAL"
LLAVE_A = "LLAVE_A"
LLAVE_C = "LLAVE_C"
COMA = "COMA"
IGUAL = "IGUAL"
CARET = "CARET"
MAS = "MAS"
MENOS = "MENOS"
POR = "POR"
DIAG = "DIAG"
PAR_A = "PAR_A"
PAR_C = "PAR_C"
FIN = "FIN"


@dataclass
class Token:
    tipo: str
    lexema: str
    linea: int
    columna: int

    def __repr__(self):
        return f"{self.tipo}({self.lexema!r})"


@dataclass
class ErrorLexico:
    mensaje: str
    linea: int
    columna: int
    malicioso: bool = False

    def __str__(self):
        marca = " [posible entrada maliciosa]" if self.malicioso else ""
        return f"Linea {self.linea}, col {self.columna}: {self.mensaje}{marca}"


# ---------------------------------------------------------------------------
# Definicion formal del AFD
# ---------------------------------------------------------------------------

# Estados
Q0 = "Q0"            # estado inicial
Q_BARRA = "Q_BARRA"  # se leyo '\'; se espera la primera letra del comando
Q_CMD = "Q_CMD"      # leyendo letras de un comando (final)
Q_IDENT = "Q_IDENT"  # leyendo letras de un identificador (final)
Q_ENT = "Q_ENT"      # leyendo digitos de un entero (final)
Q_PUNTO = "Q_PUNTO"  # se leyo el punto decimal; se espera un digito
Q_DEC = "Q_DEC"      # leyendo la parte decimal (final)

# Clases de caracteres (particion del alfabeto Sigma)
C_BARRA = "BARRA"
C_LETRA = "LETRA"
C_DIGITO = "DIGITO"
C_PUNTO = "PUNTO"
C_ESPACIO = "ESPACIO"
C_SIMPLE = "SIMPLE"
C_OTRO = "OTRO"

SIMBOLOS_SIMPLES = {
    "{": LLAVE_A, "}": LLAVE_C, ",": COMA, "=": IGUAL, "^": CARET,
    "+": MAS, "-": MENOS, "*": POR, "/": DIAG, "(": PAR_A, ")": PAR_C,
}


def clase_de(caracter: str) -> str:
    """Funcion de clasificacion: asigna cada caracter a su clase en Sigma."""
    if caracter == "\\":
        return C_BARRA
    if caracter.isascii() and caracter.isalpha():
        return C_LETRA
    if caracter.isascii() and caracter.isdigit():
        return C_DIGITO
    if caracter == ".":
        return C_PUNTO
    if caracter in " \t\r\n":
        return C_ESPACIO
    if caracter in SIMBOLOS_SIMPLES:
        return C_SIMPLE
    return C_OTRO


# Funcion de transicion delta. Toda combinacion (estado, clase) ausente de
# esta tabla es una transicion indefinida: el automata se detiene.
TRANSICIONES = {
    Q0:      {C_BARRA: Q_BARRA, C_LETRA: Q_IDENT, C_DIGITO: Q_ENT},
    Q_BARRA: {C_LETRA: Q_CMD},
    Q_CMD:   {C_LETRA: Q_CMD},
    Q_IDENT: {C_LETRA: Q_IDENT},
    Q_ENT:   {C_DIGITO: Q_ENT, C_PUNTO: Q_PUNTO},
    Q_PUNTO: {C_DIGITO: Q_DEC},
    Q_DEC:   {C_DIGITO: Q_DEC},
}

# Estados finales F y el tipo de token que emiten
ESTADOS_FINALES = {
    Q_CMD: COMANDO,
    Q_IDENT: IDENT,
    Q_ENT: ENTERO,
    Q_DEC: DECIMAL,
}


# ---------------------------------------------------------------------------
# Ejecucion del automata
# ---------------------------------------------------------------------------

def analizar(texto: str):
    """Recorre la entrada con el AFD y devuelve (tokens, errores).

    La entrada es valida a nivel lexico si y solo si la lista de errores
    resulta vacia. Ante un error se descarta el caracter conflictivo y se
    continua, de modo que se reportan todos los errores en una sola pasada;
    la entrada completa, sin embargo, queda rechazada.
    """
    tokens: list[Token] = []
    errores: list[ErrorLexico] = []

    if len(texto) > MAX_LONGITUD_ENTRADA:
        errores.append(ErrorLexico(
            f"la entrada excede el limite de {MAX_LONGITUD_ENTRADA} caracteres",
            1, 1, malicioso=True))
        return tokens, errores

    pos = 0
    linea = 1
    columna = 1
    n = len(texto)

    def avanzar(caracter):
        nonlocal linea, columna
        if caracter == "\n":
            linea += 1
            columna = 1
        else:
            columna += 1

    while pos < n:
        caracter = texto[pos]
        clase = clase_de(caracter)

        # Espacios y saltos de linea se descartan (no forman tokens)
        if clase == C_ESPACIO:
            avanzar(caracter)
            pos += 1
            continue

        # Simbolos de un solo caracter: estado aceptor inmediato
        if clase == C_SIMPLE:
            tokens.append(Token(SIMBOLOS_SIMPLES[caracter], caracter, linea, columna))
            avanzar(caracter)
            pos += 1
            continue

        # Caracter fuera del alfabeto: rechazo (lista blanca)
        if clase == C_OTRO:
            errores.append(ErrorLexico(
                f"caracter no permitido {caracter!r}", linea, columna, malicioso=True))
            avanzar(caracter)
            pos += 1
            continue

        # Recorrido del AFD con coincidencia maxima
        estado = Q0
        inicio = pos
        linea_ini, col_ini = linea, columna
        ultimo_final = None       # (estado_final, posicion_siguiente)
        p = pos
        while p < n:
            c = texto[p]
            siguiente = TRANSICIONES.get(estado, {}).get(clase_de(c))
            if siguiente is None:
                break
            estado = siguiente
            p += 1
            if estado in ESTADOS_FINALES:
                ultimo_final = (estado, p)

        if ultimo_final is None:
            # El automata no alcanzo ningun estado final: error lexico
            fragmento = texto[inicio:min(inicio + 10, n)]
            errores.append(ErrorLexico(
                f"secuencia mal formada a partir de {fragmento!r}",
                linea_ini, col_ini, malicioso=True))
            avanzar(caracter)
            pos += 1
            continue

        estado_final, fin_lexema = ultimo_final
        lexema = texto[inicio:fin_lexema]
        tipo = ESTADOS_FINALES[estado_final]

        # Lista blanca de comandos
        if tipo == COMANDO:
            nombre = lexema[1:]
            if nombre not in COMANDOS_VALIDOS:
                errores.append(ErrorLexico(
                    f"comando no reconocido {lexema!r}",
                    linea_ini, col_ini, malicioso=True))
            else:
                tokens.append(Token(COMANDO, nombre, linea_ini, col_ini))
        else:
            tokens.append(Token(tipo, lexema, linea_ini, col_ini))

        for c in texto[inicio:fin_lexema]:
            avanzar(c)
        pos = fin_lexema

    tokens.append(Token(FIN, "", linea, columna))
    return tokens, errores
