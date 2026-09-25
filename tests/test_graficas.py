"""
Cada gráfica tiene que poder dibujarse de verdad.

Esta es la prueba que faltaba y que costó un despliegue roto.

`AppTest` corre el script de Python y reporta que no hubo excepción, pero
**una especificación de Vega-Lite inválida no falla en Python**: falla en el
navegador, al renderizar. El plano de ocupación se subió a producción sin
dibujarse: una capa anulaba el eje y otra lo dejaba por defecto, y al
fusionarlas Vega-Lite reventaba con `Cannot read properties of undefined` —
del lado del cliente, donde ninguna prueba de Python miraba.

`vl_convert` compila la especificación con el mismo Vega-Lite que usa el
navegador. Si la gráfica no se puede dibujar, esto falla aquí y no allá.

    pip install -r requirements-dev.txt && pytest -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import altair as alt
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import ocupacion, plano  # noqa: E402
from src.generar_historia import MARCA_GIRO, generar  # noqa: E402

vlc = pytest.importorskip(
    "vl_convert", reason="falta vl-convert-python; `pip install -r requirements-dev.txt`")


@pytest.fixture(scope="module")
def mundo():
    return generar()


def _dibuja(grafica: alt.TopLevelMixin) -> int:
    """Compila con el mismo Vega-Lite del navegador. Devuelve bytes del PNG."""
    png = vlc.vegalite_to_png(grafica.to_json(), scale=1)
    return len(png)


@pytest.mark.parametrize("plaza", ["PALT", "PBER", "PSIS"])
def test_el_plano_se_dibuja_en_todos_los_niveles(mundo, plaza):
    cat, libro = mundo
    est = ocupacion.estado(cat[cat["plaza"] == plaza], libro)
    for nivel in est["nivel"].unique():
        sub = est[est["nivel"] == nivel]
        assert _dibuja(plano.dibujar(sub, f"{plaza} {nivel}", 260)) > 1_000


def test_el_plano_se_dibuja_aunque_la_plaza_este_vacia(mundo):
    """El día uno del libro no hay un solo asiento. El plano tiene que salir
    igual, todo en blanco, en vez de tronar."""
    cat, libro = mundo
    primera = libro.asientos["fecha"].min().date()
    est = ocupacion.estado(cat[cat["plaza"] == "PSIS"], libro, primera)
    assert _dibuja(plano.dibujar(est, "vacía", 260)) > 1_000


def test_la_serie_de_ocupacion_se_dibuja(mundo):
    cat, libro = mundo
    serie = ocupacion.serie_ocupacion(cat, libro)
    grafica = alt.Chart(serie).mark_line(strokeWidth=2).encode(
        x=alt.X("fecha:T", title=None),
        y=alt.Y("ocupacion:Q", title="Ocupación", axis=alt.Axis(format="%"),
                scale=alt.Scale(domain=[0, 1])),
        color=alt.Color("plaza:N", title="Plaza"),
    ).properties(height=260)
    assert _dibuja(grafica) > 1_000


def test_la_rotacion_se_dibuja(mundo):
    _, libro = mundo
    rot = ocupacion.rotacion(libro).melt("mes", var_name="movimiento",
                                         value_name="n")
    grafica = alt.Chart(rot).mark_bar().encode(
        x=alt.X("mes:T", title=None),
        y=alt.Y("n:Q", title="Asientos"),
        color=alt.Color("movimiento:N", title=None),
    ).properties(height=200)
    assert _dibuja(grafica) > 1_000


def test_las_graficas_de_inquilinos_se_dibujan(mundo):
    cat, libro = mundo
    inq = ocupacion.por_cliente(libro, None, cat[cat["plaza"] == "PALT"]["id_local"])
    inq = inq.assign(giro=inq["cliente"].map(MARCA_GIRO).fillna("Otro"))

    barras = alt.Chart(inq.head(12)).mark_bar().encode(
        x=alt.X("m2_ocupados:Q", title="m² ocupados"),
        y=alt.Y("cliente:N", sort="-x", title=None),
        color=alt.Color("giro:N", title="Giro"),
    ).properties(height=320)
    assert _dibuja(barras) > 1_000

    mezcla = inq.groupby("giro", as_index=False)["m2_ocupados"].sum()
    dona = alt.Chart(mezcla).mark_arc(innerRadius=55).encode(
        theta=alt.Theta("m2_ocupados:Q"),
        color=alt.Color("giro:N", title="Giro"),
    ).properties(height=320)
    assert _dibuja(dona) > 1_000
