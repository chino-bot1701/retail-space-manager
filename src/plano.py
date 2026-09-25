"""
El plano de ocupación.

Un rectángulo por local, blanco de fondo y relleno de color en proporción a
los metros tomados. Un local a medias se ve a medias — no hay un cuarto color
para "parcial", se ve porque el relleno no llega arriba.

El relleno sale de `m2_ocupados / m2_totales`, los mismos números de la tabla.
Que el plano y la tabla no puedan discrepar no es casualidad: leen la misma
columna.
"""

from __future__ import annotations

import altair as alt
import pandas as pd

from .ocupacion import COLORES, LIBRE, OCUPADO, PARCIAL

ORDEN = [LIBRE, PARCIAL, OCUPADO]
ETIQUETA = {LIBRE: "Libre", PARCIAL: "Parcial", OCUPADO: "Ocupado"}


def preparar(est: pd.DataFrame) -> pd.DataFrame:
    """Agrega al estado las coordenadas que necesita el dibujo."""
    d = est.copy()
    d["x2"] = d["x"] + d["ancho"]
    d["y2"] = d["y"] + d["alto"]
    # El relleno crece desde el borde inferior del local.
    d["y_ocupado"] = d["y"] + d["alto"] * d["ocupacion_pct"]
    d["cx"] = d["x"] + d["ancho"] / 2
    d["cy"] = d["y"] + d["alto"] / 2
    d["etiqueta"] = d["id_local"].str.rsplit("-", n=1).str[-1]
    d["estado_txt"] = d["estado"].map(ETIQUETA)
    d["ocupacion_txt"] = (d["ocupacion_pct"] * 100).round(0).astype(int).astype(str) + "%"
    d["inquilinos"] = d["clientes"].replace("", "—")
    return d


def dibujar(est: pd.DataFrame, titulo: str, altura: int = 420,
            leyenda: bool = True) -> alt.LayerChart:
    """Devuelve el plano como una gráfica de tres capas."""
    d = preparar(est)

    tooltip = [
        alt.Tooltip("id_local:N", title="Local"),
        alt.Tooltip("estado_txt:N", title="Estado"),
        alt.Tooltip("m2_totales:Q", title="m² totales", format=",.0f"),
        alt.Tooltip("m2_ocupados:Q", title="m² ocupados", format=",.0f"),
        alt.Tooltip("m2_disponibles:Q", title="m² libres", format=",.0f"),
        alt.Tooltip("ocupacion_txt:N", title="Ocupación"),
        alt.Tooltip("inquilinos:N", title="Inquilinos"),
        alt.Tooltip("contratos:N", title="Contratos"),
    ]

    base = alt.Chart(d).encode(
        x=alt.X("x:Q", axis=None, scale=alt.Scale(nice=False, zero=False)),
        x2="x2:Q",
        tooltip=tooltip,
    )

    # El local completo, en blanco: el continente.
    contorno = base.mark_rect(
        fill="#ffffff", stroke="#3d3d3d", strokeWidth=1.2
    ).encode(
        y=alt.Y("y:Q", axis=None, scale=alt.Scale(nice=False, zero=False)),
        y2="y2:Q",
    )

    # Lo tomado, en color: el contenido.
    relleno = base.transform_filter(
        alt.datum.ocupacion_pct > 0
    ).mark_rect(stroke=None).encode(
        # `axis=None` en TODAS las capas, no solo en una.
        # Si una capa anula el eje y otra lo deja por defecto, Vega-Lite
        # revienta al fusionarlas —`Cannot read properties of undefined` en
        # `parseAxesAndHeaders`— y el plano no se dibuja. `AppTest` no lo ve:
        # el error ocurre en el navegador, no en Python.
        y=alt.Y("y:Q", axis=None),
        y2="y_ocupado:Q",
        color=alt.Color(
            "estado_txt:N",
            title="Estado",
            scale=alt.Scale(domain=[ETIQUETA[e] for e in ORDEN],
                            range=[COLORES[e] for e in ORDEN]),
            legend=(alt.Legend(orient="top", direction="horizontal",
                               symbolType="square", symbolSize=140)
                    if leyenda else None),
        ),
    )

    numero = alt.Chart(d).mark_text(
        fontSize=8, color="#1f1f1f", angle=270, baseline="middle"
    ).encode(
        x=alt.X("cx:Q", axis=None),
        y=alt.Y("cy:Q", axis=None),
        text="etiqueta:N",
        tooltip=tooltip,
    )

    # Sin `width="container"`: en un chart de capas, Vega-Lite lo combina mal
    # con el ancho que impone Streamlit y el plano sale sin ancho — invisible.
    # Se deja que Streamlit mande, con `use_container_width=True`.
    return (contorno + relleno + numero).properties(
        title=titulo, height=altura
    ).configure_view(strokeWidth=0).configure_axis(grid=False)
