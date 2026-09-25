"""
Cuatro años y medio de movimientos sintéticos.

El generador no escribe el libro a mano: **llama a la misma API que usa la
app** (`Libro.alta`, `.expansion`, `.baja_total`). Así que si una invariante
se rompe, la historia no se puede generar. Es la prueba de humo más barata
que hay: `python scripts/run_demo.py` falla antes de llegar a las aserciones.

Ninguna marca, plaza ni contrato de aquí existe. Los nombres son inventados
y elegidos para que no se parezcan a cadenas reales.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from .libro import AsientoInvalido, Libro, siguiente_id_contrato
from .plaza import PLAZAS, catalogo, m2_totales

SEMILLA = 20260924
INICIO = date(2022, 1, 1)
FIN = date(2026, 8, 31)

# Inquilinos ficticios, agrupados por giro. El giro decide cuántos metros
# pide, cuánto dura y qué tan probable es que se expanda — que es como se
# comporta un centro comercial de verdad: una ancla firma diez años y una
# cafetería rota cada dieciocho meses.
GIROS = {
    "Ancla": {
        "marcas": ["Autoservicio Miramar", "Tienda Verano", "Almacenes Rueda"
                   "Mercado Bastion",
                   "Surtidora Peniche",],
        "m2": (900, 1800), "meses": (96, 144), "p_expande": 0.05,
    },
    "Entretenimiento": {
        "marcas": ["Cines Meridiano", "Boliche Astral", "Parque Jícara"
                   "Arena Lumbre",
                   "Laberinto Kiro",],
        "m2": (600, 1400), "meses": (72, 120), "p_expande": 0.08,
    },
    "Gimnasio": {
        "marcas": ["Fuerza Nogal", "Estudio Vértice"
                   "Ritmo Cardon",
                   "Box Ferrer",],
        "m2": (400, 900), "meses": (48, 96), "p_expande": 0.12,
    },
    "Moda": {
        "marcas": ["Vistoria", "Rambla Nueve", "Tejido Norte", "Casa Lumen",
                   "Indigo Ocho", "Sastrería Bruma", "Calzado Peral"
                   "Lino Quinto",
                   "Panal Denim",
                   "Atelier Ruda",
                   "Zapateria Volcan",
                   "Bordado Sur",
                   "Marea Textil",
                   "Perchero Nueve",],
        "m2": (90, 320), "meses": (36, 72), "p_expande": 0.20,
    },
    "Restaurante": {
        "marcas": ["Brasa Bruna", "Grill Almendral", "Parrilla Tolvanera",
                   "Cocina Tepeyac", "Mariscos Tinaja"
                   "Fonda Retama",
                   "Asador Quiroz",
                   "Trattoria Belen",
                   "Cantina Ocaso",
                   "Barra Zamora",],
        "m2": (120, 380), "meses": (30, 66), "p_expande": 0.16,
    },
    "Comida rápida": {
        "marcas": ["Pollo Kaibó", "Taquería El Sauco", "Wok Sereno",
                   "Burger Ocotal", "Pizza Murmullo"
                   "Alitas Fogon",
                   "Torteria Nieto",
                   "Sushi Repique",
                   "Baguette Ciervo",
                   "Arepas Tobal",],
        "m2": (45, 120), "meses": (24, 54), "p_expande": 0.10,
    },
    "Café y postres": {
        "marcas": ["Café Muérdago", "Helados Piamonte", "Repostería Alondra",
                   "Té Bahía"
                   "Tostado Once",
                   "Churros Nimbo",
                   "Nieves Corvina",
                   "Panaderia Solaz",],
        "m2": (30, 90), "meses": (18, 48), "p_expande": 0.14,
    },
    "Servicios financieros": {
        "marcas": ["Banco del Istmo", "Banco Norte", "Crédito Sauce",
                   "Caja Ribera"
                   "Banco Altavista",
                   "Financiera Ebano",],
        "m2": (80, 200), "meses": (60, 120), "p_expande": 0.06,
    },
    "Telecomunicaciones": {
        "marcas": ["Celnor", "Fibra Nítida", "Enlace Zafiro"
                   "Movil Quetzal",
                   "Redes Tamarindo",],
        "m2": (40, 110), "meses": (36, 72), "p_expande": 0.18,
    },
    "Salud y belleza": {
        "marcas": ["Farmacia Trébol", "Óptica Candil", "Estética Rosal",
                   "Clínica Aliso"
                   "Botica Genciana",
                   "Barberia Roble",
                   "Spa Amaranto",
                   "Laboratorio Cenit",],
        "m2": (50, 160), "meses": (30, 66), "p_expande": 0.12,
    },
    "Servicios": {
        "marcas": ["Lavandería Nube", "Cerrajería Pinar", "Agencia Duna",
                   "Papelería Cantera"
                   "Tintoreria Faro",
                   "Copiadora Juno",
                   "Viajes Almendro",
                   "Reparadora Tizon",],
        "m2": (25, 80), "meses": (18, 42), "p_expande": 0.08,
    },
}

MARCA_GIRO = {m: g for g, cfg in GIROS.items() for m in cfg["marcas"]}


def _meses(inicio: date, fin: date) -> list[pd.Timestamp]:
    return list(pd.date_range(inicio, fin, freq="MS"))


M2_MINIMO_RENTABLE = 22.0   # menos que esto no se comercializa, se junta


def _colocar(disp: dict[str, float], totales: dict[str, float],
             vecinos: dict[str, str | None],
             rng: np.random.Generator) -> dict[str, float] | None:
    """Elige qué espacio se coloca, mirando primero el inventario.

    Va en este orden porque es el orden en que trabaja un área comercial: no
    se parte de "un inquilino quiere 300 m²", se parte de "tengo este local
    vacío". Al revés —que fue el primer intento— el generador buscaba huecos
    de 1,500 m² que no existían y terminaba subdividiendo locales chicos: 46
    de 152 quedaban en estado parcial, que no se parece a ninguna plaza real.
    """
    candidatos = [k for k, v in disp.items() if v >= M2_MINIMO_RENTABLE]
    if not candidatos:
        return None

    # Se prefiere colocar en un local entero antes que rellenar un remanente.
    peso = np.array([3.0 if disp[k] >= totales[k] - 0.5 else 1.0
                     for k in candidatos])
    elegido = str(rng.choice(candidatos, p=peso / peso.sum()))
    libre = disp[elegido]
    entero = libre >= totales[elegido] - 0.5

    if not entero:
        # Remanente de un local ya ocupado: se coloca completo o casi.
        return {elegido: round(libre, 1)}

    if totales[elegido] >= 180 and rng.random() < 0.34:
        # Subdivisión de un local grande. Aquí nacen los *parciales*: dos
        # marcas conviviendo en la misma cortina, que es un caso real y el
        # que rompe los sistemas que tratan el local como un sí/no.
        return {elegido: round(libre * rng.uniform(0.40, 0.70), 1)}

    tramos = {elegido: round(libre, 1)}

    # Un inquilino mediano a veces toma el local de al lado y tira el muro.
    vecino = vecinos.get(elegido)
    if (vecino and rng.random() < 0.16
            and disp.get(vecino, 0) >= totales.get(vecino, 0) - 0.5
            and totales[elegido] < 180):
        tramos[vecino] = round(disp[vecino], 1)

    return tramos


def _giro_para(m2: float, rng: np.random.Generator) -> str:
    """Qué clase de negocio ocupa un espacio de ese tamaño.

    El tamaño manda: nadie pone una cafetería en 1,400 m² ni un cine en 60.
    Entre los giros cuyo rango cubre la superficie se elige por frecuencia.
    """
    caben = [g for g, c in GIROS.items() if c["m2"][0] * 0.7 <= m2 <= c["m2"][1] * 1.4]
    if not caben:
        caben = [min(GIROS, key=lambda g: abs(np.mean(GIROS[g]["m2"]) - m2))]
    p = np.array([_FRECUENCIA[g] for g in caben], dtype=float)
    return str(rng.choice(caben, p=p / p.sum()))


# Qué tan seguido firma cada giro. Las anclas una vez por sexenio; las
# cafeterías, constantemente.
_FRECUENCIA = {
    "Ancla": 0.02, "Entretenimiento": 0.03, "Gimnasio": 0.05, "Moda": 0.20,
    "Restaurante": 0.14, "Comida rápida": 0.16, "Café y postres": 0.12,
    "Servicios financieros": 0.06, "Telecomunicaciones": 0.07,
    "Salud y belleza": 0.08, "Servicios": 0.07,
}


def _meta_ocupacion(meses_abierta: int, rng: np.random.Generator) -> float:
    """La curva de colocación de una plaza.

    Abre con la mitad comprometida y se llena a lo largo de dos años hasta un
    techo del 93%. No llega a 100 nunca: siempre hay un local en obra o entre
    inquilinos, y una plaza al 100% en el tablero es señal de que el tablero
    miente.
    """
    techo = 0.93
    curva = techo * (1 - np.exp(-(meses_abierta + 4) / 11))
    return float(np.clip(curva + rng.normal(0, 0.012), 0.30, techo))


def generar(semilla: int = SEMILLA, inicio: date = INICIO,
            fin: date = FIN) -> tuple[pd.DataFrame, Libro]:
    """Devuelve el catálogo y el libro con la historia ya asentada."""
    rng = np.random.default_rng(semilla)
    cat = catalogo(semilla)
    totales = m2_totales(cat)
    libro = Libro(totales)

    # Contratos vivos: id → (cliente, mes de vencimiento)
    vivos: dict[str, tuple[str, pd.Timestamp]] = {}
    usos: dict[str, int] = {}          # sucursales por marca

    por_plaza = {c: list(g["id_local"]) for c, g in cat.groupby("plaza")}
    vecinos = _vecinos(cat)

    for mes in _meses(inicio, fin):
        reloj = _Calendario(mes)
        for codigo, cfg in PLAZAS.items():
            if mes.year < cfg["anio_apertura"]:
                continue
            locales = por_plaza[codigo]

            # Disponibilidad al inicio del mes, calculada una sola vez y
            # actualizada conforme se asienta. Recalcularla en cada evento
            # costaba seis segundos de generación para nada.
            saldos = libro.saldos()
            disp = {k: totales[k] - float(saldos.get(k, 0.0)) for k in locales}
            tot_plaza = sum(totales[k] for k in locales)
            # Los meses se cuentan desde que la plaza abrió, no desde que
            # arranca el libro. Paseo Altamira abrió en 2019: para enero de
            # 2022 ya estaba madura, y contarla como recién inaugurada la
            # dejaba llenándose durante dos años que ya habían pasado.
            meses_abierta = (mes.year - cfg["anio_apertura"]) * 12 \
                + mes.month - 1
            meta = _meta_ocupacion(meses_abierta, rng)

            # --- Altas: se coloca hasta alcanzar la meta del mes ---------
            # El tope es alto a proposito: el primer mes del libro tiene que
            # alcanzar a colocar la plaza entera de una vez (es la migracion
            # del estado que ya traia), y el resto de los meses sale del
            # `break` en cuanto se llega a la meta.
            intentos = 0
            while intentos < 250:
                ocupado = tot_plaza - sum(disp.values())
                if ocupado / tot_plaza >= meta:
                    break
                intentos += 1
                tramos = _colocar(disp, totales, vecinos, rng)
                if tramos is None:
                    break

                m2 = sum(tramos.values())
                giro = _giro_para(m2, rng)
                marcas = [m for m in GIROS[giro]["marcas"] if usos.get(m, 0) < 3]
                if not marcas:
                    continue
                marca = str(rng.choice(marcas))

                dia = reloj.siguiente(rng)
                cid = siguiente_id_contrato(libro, codigo, dia)
                try:
                    libro.alta(dia, cid, marca, tramos)
                except AsientoInvalido:
                    continue
                for k, v in tramos.items():
                    disp[k] -= v
                usos[marca] = usos.get(marca, 0) + 1
                # Los contratos de la apertura se escalonan. Si todos
                # arrancaran con su plazo completo el mismo mes, la plaza no
                # rotaria en cuatro anios y volveria a vencer en bloque - que
                # es un riesgo real de comercializacion, pero no el caso base.
                plazo = int(rng.integers(*GIROS[giro]["meses"]))
                if meses_abierta <= 6:
                    plazo = max(12, int(plazo * rng.uniform(0.30, 1.0)))
                vivos[cid] = (marca, mes + pd.DateOffset(months=plazo))

            # --- Expansiones -------------------------------------------
            for cid, (marca, _) in list(vivos.items()):
                if not cid.startswith(codigo):
                    continue
                if rng.random() > GIROS[MARCA_GIRO[marca]]["p_expande"] / 12:
                    continue
                if (tot_plaza - sum(disp.values())) / tot_plaza >= meta:
                    break
                tramos = _colocar(disp, totales, vecinos, rng)
                if tramos is None or sum(tramos.values()) > 260:
                    continue
                try:
                    libro.expansion(reloj.siguiente(rng), cid, marca, tramos)
                except AsientoInvalido:
                    continue
                for k, v in tramos.items():
                    disp[k] -= v

            # --- Bajas: vence el contrato y el inquilino entrega --------
            for cid, (marca, vence) in list(vivos.items()):
                if not cid.startswith(codigo) or mes < vence:
                    continue
                try:
                    libro.baja_total(reloj.siguiente(rng), cid)
                except AsientoInvalido:
                    pass
                vivos.pop(cid, None)
                usos[marca] = max(0, usos.get(marca, 1) - 1)

    return cat, libro


def _vecinos(cat: pd.DataFrame) -> dict[str, str | None]:
    """El local de al lado, por nivel. Los ids consecutivos de la misma
    hilera son contiguos por construcción del catálogo."""
    v: dict[str, str | None] = {}
    for _, g in cat.groupby(["plaza", "nivel"]):
        ids = sorted(g["id_local"])
        for i, k in enumerate(ids):
            v[k] = ids[i + 1] if i + 1 < len(ids) else None
    return v


class _Calendario:
    """Reparte los días de un mes en orden no decreciente.

    Hace falta porque el libro **rechaza asientos fechados hacia atrás**, y
    eso es correcto: un registro contable no se retro-fecha. La primera
    versión del generador sorteaba un día al azar por evento y el libro le
    rechazaba nueve de cada diez altas — el generador estaba mal, no la
    invariante. Es justo la clase de choque que aparece cuando las reglas
    viven en el código y no en la buena voluntad de quien captura.
    """

    def __init__(self, mes: pd.Timestamp) -> None:
        self.mes = mes
        self.dia = 1

    def siguiente(self, rng: np.random.Generator) -> date:
        # Muchas firmas caen el día uno; el resto avanza de a poco.
        if rng.random() >= 0.45:
            self.dia = min(28, self.dia + int(rng.integers(0, 4)))
        return date(self.mes.year, self.mes.month, self.dia)
