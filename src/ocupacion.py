"""
El estado, derivado del libro.

Nada de lo que hay aquí se guarda. Cada función recibe el catálogo y el libro
y calcula. Esa es la razón de que no exista el bug clásico de estos sistemas
—que la tabla de "estado actual" y la de movimientos digan cosas distintas—:
no hay dos tablas.

El precio es recalcular. Con decenas de miles de asientos eso es milisegundos
en pandas; en la base sería una vista materializada. En ninguno de los dos
casos justifica mantener el estado a mano.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from .libro import EPS, Libro

LIBRE, PARCIAL, OCUPADO = "libre", "parcial", "ocupado"

# El plano usa estos tres colores y nada más. Rojo es ocupado, ámbar es
# parcial, blanco es libre — que es como lo pedía operación.
COLORES = {LIBRE: "#ffffff", PARCIAL: "#f0a202", OCUPADO: "#d7373f"}


def estado(cat: pd.DataFrame, libro: Libro,
           fecha: date | None = None) -> pd.DataFrame:
    """Una fila por local, con lo que tiene encima en esa fecha.

    Con `fecha=None` es el presente. Con una fecha pasada, es el plano de ese
    día — sin ninguna tabla histórica, solo cortando el libro.
    """
    d = cat.copy()
    saldos = libro.saldos(fecha)
    d["m2_ocupados"] = d["id_local"].map(saldos).fillna(0.0).round(1)
    d["m2_disponibles"] = (d["m2_totales"] - d["m2_ocupados"]).round(1)

    d["estado"] = np.select(
        [d["m2_ocupados"] <= EPS, d["m2_disponibles"] <= EPS],
        [LIBRE, OCUPADO],
        default=PARCIAL,
    )
    d["color"] = d["estado"].map(COLORES)
    d["ocupacion_pct"] = (d["m2_ocupados"] / d["m2_totales"]).clip(0, 1)

    vivos = libro.contratos_activos(fecha)
    if vivos.empty:
        d["clientes"] = ""
        d["contratos"] = ""
        d["n_clientes"] = 0
    else:
        por_local = vivos.groupby("id_local").agg(
            clientes=("cliente", lambda s: " · ".join(sorted(set(s)))),
            contratos=("id_contrato", lambda s: " · ".join(sorted(set(s)))),
            n_clientes=("cliente", "nunique"),
        )
        d = d.join(por_local, on="id_local")
        d[["clientes", "contratos"]] = d[["clientes", "contratos"]].fillna("")
        d["n_clientes"] = d["n_clientes"].fillna(0).astype(int)

    return d


def resumen(est: pd.DataFrame) -> dict[str, float]:
    """Los cuatro números que pide la dirección.

    La tasa de ocupación se calcula **por metros, no por locales**. Un local
    ancla vacío pesa lo que pesa; contarlo como "uno de sesenta" esconde el
    hueco. Las dos cifras se devuelven para que la diferencia se vea.
    """
    total = float(est["m2_totales"].sum())
    ocupado = float(est["m2_ocupados"].sum())
    return {
        "m2_totales": round(total, 1),
        "m2_ocupados": round(ocupado, 1),
        "m2_disponibles": round(total - ocupado, 1),
        "ocupacion_m2": ocupado / total if total else 0.0,
        "ocupacion_locales": float((est["estado"] != LIBRE).mean()),
        "locales": int(len(est)),
        "locales_libres": int((est["estado"] == LIBRE).sum()),
        "locales_parciales": int((est["estado"] == PARCIAL).sum()),
    }


def por_cliente(libro: Libro, fecha: date | None = None) -> pd.DataFrame:
    """Quién ocupa qué, ordenado por metros. El tablero de inquilinos."""
    vivos = libro.contratos_activos(fecha)
    if vivos.empty:
        return pd.DataFrame(columns=["cliente", "m2_ocupados", "locales",
                                     "n_locales", "n_contratos"])
    g = vivos.groupby("cliente").agg(
        m2_ocupados=("m2_ocupados", "sum"),
        locales=("id_local", lambda s: ", ".join(sorted(s))),
        n_locales=("id_local", "nunique"),
        n_contratos=("id_contrato", "nunique"),
    ).reset_index()
    g["m2_ocupados"] = g["m2_ocupados"].round(1)
    return g.sort_values("m2_ocupados", ascending=False).reset_index(drop=True)


def serie_ocupacion(cat: pd.DataFrame, libro: Libro,
                    frecuencia: str = "MS") -> pd.DataFrame:
    """Ocupación mes a mes desde el primer asiento.

    Se reconstruye recorriendo el libro una sola vez y acumulando, en vez de
    llamar a `estado()` una vez por mes. Con 24 meses da igual; con diez años
    de historia y varias plazas, no.
    """
    d = libro.asientos
    if d.empty:
        return pd.DataFrame(columns=["fecha", "plaza", "m2_ocupados",
                                     "m2_totales", "ocupacion"])

    plaza_de = dict(zip(cat["id_local"], cat["plaza"]))
    totales = cat.groupby("plaza")["m2_totales"].sum()

    d = d.assign(plaza=d["id_local"].map(plaza_de))
    periodos = pd.date_range(d["fecha"].min().to_period("M").to_timestamp(),
                             d["fecha"].max(), freq=frecuencia)

    neto = (d.set_index("fecha").groupby("plaza")["m2"]
            .resample(frecuencia).sum().unstack("plaza")
            .reindex(periodos).fillna(0.0).cumsum())

    largo = neto.stack().rename("m2_ocupados").reset_index()
    largo.columns = ["fecha", "plaza", "m2_ocupados"]
    largo["m2_totales"] = largo["plaza"].map(totales)
    largo["ocupacion"] = largo["m2_ocupados"] / largo["m2_totales"]
    return largo


def rotacion(libro: Libro) -> pd.DataFrame:
    """Altas y bajas por mes: el pulso comercial de la plaza.

    Sale del mismo libro. Un sistema que borra al dar de baja no puede
    contestar esto sin una tabla de auditoría aparte.
    """
    d = libro.asientos
    if d.empty:
        return pd.DataFrame(columns=["mes", "altas", "bajas"])
    d = d.assign(mes=d["fecha"].dt.to_period("M").dt.to_timestamp())
    g = d.groupby("mes").agg(
        altas=("motivo", lambda s: int(s.isin(["alta", "expansion"]).sum())),
        bajas=("motivo", lambda s: int(s.isin(["baja", "baja_total"]).sum())),
    ).reset_index()
    return g
