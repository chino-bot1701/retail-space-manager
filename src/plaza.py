"""
El catálogo de locales: qué existe y dónde está.

Esto es la parte que *no* cambia. Un local se da de alta cuando se construye
la plaza y ya; lo que cambia todos los días es quién lo ocupa, y eso vive en
`libro.py`.

La geometría es real en el sentido que importa: cada local tiene posición y
tamaño en metros sobre el plano del nivel, y **el área del rectángulo es sus
metros rentables**. Eso permite dibujar el plano sin un archivo de dibujo
aparte, y —más útil— que el plano y la tabla no puedan contradecirse: salen
del mismo número.

Datos completamente sintéticos. Ninguna plaza, marca o contrato es real.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

SEMILLA = 20260924

# Las plazas del grupo ficticio "Almena". Cada una con su código corto, que es
# el prefijo de los ids de local — igual que en el sistema del que sale esto.
PLAZAS: dict[str, dict] = {
    "PALT": {"nombre": "Paseo Altamira", "niveles": ["PB", "N1", "N2"],
             "locales_por_nivel": 26, "anclas": 2, "anio_apertura": 2019},
    "PBER": {"nombre": "Plaza Bernal", "niveles": ["PB", "N1"],
             "locales_por_nivel": 22, "anclas": 2, "anio_apertura": 2021},
    "PSIS": {"nombre": "Paseo San Isidro", "niveles": ["PB"],
             "locales_por_nivel": 30, "anclas": 1, "anio_apertura": 2022},
}

NIVELES_NOMBRE = {"PB": "Planta baja", "N1": "Nivel 1", "N2": "Nivel 2"}

# De abajo hacia arriba. Ordenar alfabeticamente pone la planta baja hasta el
# final, que es como salio el primer plano: N1, N2, PB.
ORDEN_NIVELES = ["PB", "N1", "N2"]


def niveles_ordenados(niveles) -> list[str]:
    presentes = set(niveles)
    return [n for n in ORDEN_NIVELES if n in presentes] +         sorted(presentes - set(ORDEN_NIVELES))

# Geometría del pasillo. Dos hileras de locales enfrentadas, el pasillo en
# medio. Es la planta típica de un centro comercial lineal y es suficiente
# para que el plano se lea de un vistazo.
FONDO_M = 14.0          # profundidad de un local, del pasillo hacia afuera
PASILLO_M = 8.0         # ancho del pasillo central
FRENTE_MIN_M = 5.0      # el local más angosto que se construye
FRENTE_MAX_M = 26.0     # el local en línea más grande

# Las anclas son otra cosa: cajas al final del pasillo, mucho más profundas,
# de 800 a 1,700 m². Si no existen en el catálogo, el generador no tiene
# dónde meter un autoservicio y termina partiendo locales chicos —que fue
# exactamente el primer resultado, con 46 locales en estado parcial.
ANCLA_FRENTE_M = (28.0, 46.0)
ANCLA_FONDO_M = (30.0, 42.0)


@dataclass(frozen=True)
class Local:
    id_local: str
    plaza: str
    nivel: str
    m2_totales: float
    x: float
    y: float
    ancho: float
    alto: float


def _frentes(n: int, rng: np.random.Generator) -> np.ndarray:
    """Anchos de local a lo largo de una hilera.

    No son uniformes: una plaza real tiene muchos locales chicos, algunos
    medianos y dos o tres anclas. Una lognormal recortada da esa forma sin
    tener que enumerar casos.
    """
    crudo = rng.lognormal(mean=np.log(8.0), sigma=0.55, size=n)
    return np.clip(crudo, FRENTE_MIN_M, FRENTE_MAX_M).round(1)


def catalogo(semilla: int = SEMILLA) -> pd.DataFrame:
    """El padrón completo de locales de las tres plazas."""
    rng = np.random.default_rng(semilla)
    filas: list[Local] = []

    for codigo, cfg in PLAZAS.items():
        for nivel in cfg["niveles"]:
            n = cfg["locales_por_nivel"]
            n_norte = n // 2
            n_sur = n - n_norte

            for hilera, cuantos, y0 in (
                ("norte", n_norte, PASILLO_M / 2),
                ("sur", n_sur, -PASILLO_M / 2 - FONDO_M),
            ):
                anchos = _frentes(cuantos, rng)
                x = 0.0
                for i, ancho in enumerate(anchos):
                    # Numeración: los pares al norte, los nones al sur. Es la
                    # convención del plano comercial y la gente de operación
                    # la lee sin explicación.
                    consecutivo = (i + 1) * 2 if hilera == "norte" else (i + 1) * 2 - 1
                    filas.append(Local(
                        id_local=f"{codigo}-{nivel}-{consecutivo:03d}",
                        plaza=codigo,
                        nivel=nivel,
                        m2_totales=round(ancho * FONDO_M, 1),
                        x=round(x, 2),
                        y=y0,
                        ancho=float(ancho),
                        alto=FONDO_M,
                    ))
                    x += ancho

            # Las anclas van en planta baja, a los extremos del pasillo, que
            # es donde se ponen para jalar tráfico hacia adentro.
            if nivel == "PB":
                largo = max(f.x + f.ancho for f in filas if f.plaza == codigo
                            and f.nivel == nivel)
                for k in range(cfg["anclas"]):
                    frente = round(float(rng.uniform(*ANCLA_FRENTE_M)), 1)
                    fondo = round(float(rng.uniform(*ANCLA_FONDO_M)), 1)
                    filas.append(Local(
                        id_local=f"{codigo}-PB-A{k + 1:02d}",
                        plaza=codigo,
                        nivel=nivel,
                        m2_totales=round(frente * fondo, 1),
                        x=-frente - 6.0 if k == 0 else largo + 6.0,
                        y=-fondo / 2,
                        ancho=frente,
                        alto=fondo,
                    ))

    d = pd.DataFrame([vars(f) for f in filas])
    return d.sort_values(["plaza", "nivel", "id_local"]).reset_index(drop=True)


def nombre_plaza(codigo: str) -> str:
    return PLAZAS[codigo]["nombre"]


def m2_totales(cat: pd.DataFrame) -> dict[str, float]:
    """Mapa id_local → metros rentables. Lo consume el libro para no dejar
    que un local se ocupe por encima de su superficie."""
    return dict(zip(cat["id_local"], cat["m2_totales"]))
