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
    grafica = alt.Chart(serie).mark_line(
        strokeWidth=2.5, interpolate="monotone"
    ).encode(
        x=alt.X("fecha:T", title=None),
        y=alt.Y("ocupacion:Q", title="Ocupación", axis=alt.Axis(format="%"),
                scale=alt.Scale(domain=[0, 1])),
        color=alt.Color("plaza:N", title=None, scale=alt.Scale(
            domain=list(ocupacion.COLOR_PLAZA),
            range=list(ocupacion.COLOR_PLAZA.values()))),
    ).properties(height=280)
    assert _dibuja(grafica) > 1_000


def test_cada_plaza_tiene_su_propio_color(mundo):
    """Con la paleta por defecto dos de las tres salían en azules casi
    iguales y la serie no se podía leer."""
    cat, _ = mundo
    assert set(cat["plaza"]) <= set(ocupacion.COLOR_PLAZA)
    assert len(set(ocupacion.COLOR_PLAZA.values())) == len(ocupacion.COLOR_PLAZA)


def test_todo_giro_pertenece_a_una_familia():
    """Si se agrega un giro al generador y se olvida su familia, cae en
    'Otro' en silencio y la mezcla comercial miente."""
    from src.generar_historia import GIROS
    sin_familia = [g for g in GIROS if g not in ocupacion.FAMILIA]
    assert not sin_familia, f"giros sin familia: {sin_familia}"
    assert set(ocupacion.FAMILIA.values()) == set(ocupacion.ORDEN_FAMILIAS)


def test_todo_giro_tiene_color_y_ninguno_se_repite():
    from src.generar_historia import GIROS
    sin_color = [g for g in GIROS if g not in ocupacion.COLOR_GIRO]
    assert not sin_color, f"giros sin color: {sin_color}"
    colores = list(ocupacion.COLOR_GIRO.values())
    assert len(set(colores)) == len(colores)


def test_los_giros_van_agrupados_por_familia_en_la_leyenda():
    """El orden de la leyenda y de la dona. Si un giro se cuela fuera de su
    bloque, los tonos de una familia dejan de quedar contiguos y la dona se
    lee como once rebanadas sueltas en vez de cinco bloques."""
    familias = [ocupacion.familia(g) for g in ocupacion.ORDEN_GIROS]
    bloques = [f for i, f in enumerate(familias) if i == 0 or f != familias[i - 1]]
    assert len(bloques) == len(set(bloques)),         f"una familia aparece en dos bloques separados: {familias}"


def test_la_leyenda_no_muestra_giros_ausentes(mundo):
    cat, libro = mundo
    inq = ocupacion.por_cliente(libro, None, cat[cat["plaza"] == "PSIS"]["id_local"])
    giros = inq["cliente"].map(MARCA_GIRO).map(ocupacion.giro_visible)
    dominio, rango = ocupacion.escala_giros(giros)
    assert set(dominio) == set(giros)
    assert len(dominio) == len(rango)


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
    inq = inq.assign(
        giro=inq["cliente"].map(MARCA_GIRO).map(ocupacion.giro_visible),
        familia=inq["cliente"].map(MARCA_GIRO).map(ocupacion.familia))
    top = inq.head(12)

    dominio, rango = ocupacion.escala_giros(inq["giro"])
    color = alt.Color("giro:N", title="Giro",
                      scale=alt.Scale(domain=dominio, range=rango))
    altura = 30 * len(top) + 30

    barras = alt.Chart(top).mark_bar(size=22, cornerRadiusEnd=3).encode(
        x=alt.X("m2_ocupados:Q", title="m² ocupados"),
        y=alt.Y("cliente:N", sort="-x", title=None,
                scale=alt.Scale(paddingInner=0.25)),
        color=color,
    ).properties(width=520, height=altura)

    mezcla = inq.groupby("giro", as_index=False)["m2_ocupados"].sum()
    mezcla["orden"] = mezcla["giro"].map(
        {g: i for i, g in enumerate(ocupacion.ORDEN_GIROS)}).fillna(99)
    dona = alt.Chart(mezcla).mark_arc(
        innerRadius=64, outerRadius=122, stroke="#00000040", strokeWidth=1.5
    ).encode(
        theta=alt.Theta("m2_ocupados:Q", stack=True),
        color=color,
        order=alt.Order("orden:Q"),
    ).properties(width=300, height=altura)

    # Concatenadas es como las dibuja la app: una sola leyenda compartida.
    juntas = alt.hconcat(barras, dona, spacing=40).resolve_scale(color="shared")
    assert _dibuja(juntas) > 1_000
