"""
La app tiene que levantar sin credenciales y aguantar que la usen.

`AppTest` corre el script de Streamlit de verdad, sin navegador. Aquí importa
más que en una app de solo lectura, porque esta **escribe**: rentar y liberar
modifican el libro. Lo que se prueba es que el botón mueva el libro y que un
intento inválido no lo mueva.

Fue este archivo el que encontró que la confirmación de la baja no se veía
nunca: `st.success()` seguido de `st.rerun()` repinta la página y se lleva el
mensaje. A ojo no se nota; el asiento se hacía y la pantalla no decía nada.

    pytest -q
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[1] / "app" / "gestor.py"
TIEMPO = 420


def abrir() -> AppTest:
    at = AppTest.from_file(str(APP), default_timeout=TIEMPO)
    at.run()
    return at


@pytest.fixture(scope="module")
def app() -> AppTest:
    return abrir()


def _metrica(at: AppTest, etiqueta: str) -> str:
    return next(m.value for m in at.metric if m.label == etiqueta)


def _asientos(at: AppTest) -> int:
    return int(_metrica(at, "Asientos").replace(",", ""))


def test_levanta_sin_excepciones(app):
    assert not app.exception


def test_declara_que_los_datos_son_sinteticos(app):
    texto = " ".join(c.value for c in app.caption)
    assert "sintéticos" in texto
    assert "no se conecta a ninguna base de datos" in texto


def test_muestra_las_cuatro_pestanas(app):
    assert len(app.tabs) == 4


def test_entrega_el_estado_de_la_plaza(app):
    etiquetas = [m.label for m in app.metric]
    for esperada in ("Ocupación (m²)", "m² disponibles", "Locales libres",
                     "Locales compartidos"):
        assert esperada in etiquetas
    assert _metrica(app, "Ocupación (m²)").endswith("%")


def test_el_historial_trae_contratos_y_asientos(app):
    assert len(app.dataframe) >= 4


# --------------------------------------------------------------------------
# Escritura
# --------------------------------------------------------------------------

def test_rentar_agrega_asientos_al_libro():
    at = abrir()
    antes = _asientos(at)

    # `options` trae las etiquetas ya formateadas; el valor crudo es el id.
    id_local = at.multiselect[0].options[0].split(" ")[0]
    at.multiselect[0].set_value([id_local]).run()
    next(s for s in at.selectbox if s.label == "Cliente").set_value("Vistoria").run()
    next(b for b in at.button if "Registrar renta" in b.label).click().run()

    assert not at.exception
    assert _asientos(at) > antes
    assert any("Vistoria" in s.value for s in at.success)


def test_cerrar_un_contrato_agrega_devoluciones_y_avisa():
    at = abrir()
    antes = _asientos(at)
    next(b for b in at.button if b.label == "Cerrar contrato").click().run()

    assert not at.exception
    assert _asientos(at) > antes, "la baja debe asentar, no borrar"
    assert any("cerrado" in s.value for s in at.success), \
        "la confirmación se perdía al reejecutar tras st.rerun()"


def test_reiniciar_devuelve_el_libro_a_su_estado_original():
    at = abrir()
    original = _asientos(at)
    next(b for b in at.button if b.label == "Cerrar contrato").click().run()
    assert _asientos(at) != original
    next(b for b in at.button if b.label == "Reiniciar la demo").click().run()
    assert _asientos(at) == original


# --------------------------------------------------------------------------
# Lectura del pasado
# --------------------------------------------------------------------------

def test_retroceder_la_fecha_baja_la_ocupacion():
    """Se mide sobre Paseo San Isidro a propósito.

    Paseo Altamira abrió en 2019 y en 2022 ya estaba al 92%: retroceder no le
    mueve la aguja, y la primera versión de esta prueba fallaba por eso — no
    porque el viaje en el tiempo estuviera roto, sino porque preguntaba en la
    plaza equivocada. San Isidro abrió en 2022 y sí tiene rampa.
    """
    at = abrir()
    next(s for s in at.selectbox if s.label == "Centro comercial") \
        .set_value("PSIS").run()
    hoy = _metrica(at, "Ocupación (m²)")
    at.slider[0].set_value(date(2022, 6, 1)).run()

    assert not at.exception
    antes = _metrica(at, "Ocupación (m²)")
    assert float(antes.rstrip("%")) < float(hoy.rstrip("%"))


def test_el_plano_de_una_plaza_madura_casi_no_cambia_con_la_fecha():
    """El complemento: Paseo Altamira llevaba tres años abierta cuando
    arranca el libro, así que su ocupación de 2022 se parece a la de hoy."""
    at = abrir()
    hoy = float(_metrica(at, "Ocupación (m²)").rstrip("%"))
    at.slider[0].set_value(date(2022, 6, 1)).run()
    antes = float(_metrica(at, "Ocupación (m²)").rstrip("%"))
    assert abs(hoy - antes) < 15


def test_cambiar_de_plaza_cambia_el_plano():
    at = abrir()
    selector = next(s for s in at.selectbox if s.label == "Centro comercial")
    primero = _metrica(at, "Locales libres")
    selector.set_value("PSIS").run()

    assert not at.exception
    assert _metrica(at, "Locales libres") != primero
