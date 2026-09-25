"""
Pruebas del libro y del estado que se deriva de él.

No prueban que la app se vea bien. Prueban las invariantes que, si se rompen,
hacen que todo lo demás mienta sin avisar:

- que **nada se borra ni se modifica**,
- que un local no se pueda ocupar por encima de su superficie,
- que nadie devuelva metros que no tiene,
- que un alta de varios locales sea **todo o nada**,
- que el estado sea exactamente la suma del libro, hoy y en cualquier fecha
  pasada.

La penúltima es la que más fácil se rompe al refactorizar: basta con quitar
el ensayo de `_en_bloque` y todo sigue pasando salvo esa.

    pytest -q
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import ocupacion  # noqa: E402
from src.generar_historia import generar  # noqa: E402
from src.libro import (EPS, AsientoInvalido, Libro,  # noqa: E402
                       siguiente_id_contrato)
from src.plaza import catalogo, m2_totales  # noqa: E402

HOY = date(2026, 1, 15)


@pytest.fixture(scope="module")
def mundo():
    return generar()


@pytest.fixture
def vacio():
    cat = catalogo()
    return cat, Libro(m2_totales(cat))


def _tres(cat):
    return list(cat["id_local"].iloc[:3]), list(cat["m2_totales"].iloc[:3])


# --------------------------------------------------------------------------
# El libro solo crece
# --------------------------------------------------------------------------

def test_asentar_devuelve_folios_consecutivos(vacio):
    cat, libro = vacio
    ids, m2 = _tres(cat)
    f1 = libro.asentar(HOY, "C1", ids[0], "Marca", m2[0], "alta")
    f2 = libro.asentar(HOY, "C2", ids[1], "Otra", m2[1], "alta")
    assert (f1, f2) == (1, 2)


def test_una_baja_no_borra_la_fila_del_alta(vacio):
    cat, libro = vacio
    ids, m2 = _tres(cat)
    libro.alta(HOY, "C1", "Marca", {ids[0]: m2[0]})
    libro.baja_total(date(2026, 3, 1), "C1")

    d = libro.asientos
    assert len(d) == 2, "la baja debe agregar una fila, no quitar la del alta"
    assert d["m2"].iloc[0] == pytest.approx(m2[0])
    assert d["m2"].iloc[1] == pytest.approx(-m2[0])
    assert libro.ocupado(ids[0]) == pytest.approx(0.0)


def test_nadie_edita_el_libro_por_fuera(vacio):
    """`asientos` devuelve copia: tocar lo que sale no debe alterar el libro."""
    cat, libro = vacio
    ids, m2 = _tres(cat)
    libro.alta(HOY, "C1", "Marca", {ids[0]: m2[0]})
    fuera = libro.asientos
    fuera.loc[0, "m2"] = 99_999
    assert libro.ocupado(ids[0]) == pytest.approx(m2[0])


def test_no_se_puede_fechar_hacia_atras(vacio):
    cat, libro = vacio
    ids, m2 = _tres(cat)
    libro.alta(date(2026, 5, 1), "C1", "Marca", {ids[0]: m2[0]})
    with pytest.raises(AsientoInvalido, match="fechar"):
        libro.alta(date(2026, 4, 30), "C2", "Otra", {ids[1]: m2[1]})


# --------------------------------------------------------------------------
# Capacidad
# --------------------------------------------------------------------------

def test_no_cabe_mas_de_lo_que_mide_el_local(vacio):
    cat, libro = vacio
    ids, m2 = _tres(cat)
    with pytest.raises(AsientoInvalido, match="libres"):
        libro.alta(HOY, "C1", "Marca", {ids[0]: m2[0] + 1})


def test_dos_inquilinos_caben_en_un_local_si_suman(vacio):
    """El caso *parcial*: la mitad para cada uno, y el local queda lleno."""
    cat, libro = vacio
    ids, m2 = _tres(cat)
    mitad = round(m2[0] / 2, 1)
    libro.alta(HOY, "C1", "Marca", {ids[0]: mitad})
    libro.alta(HOY, "C2", "Otra", {ids[0]: m2[0] - mitad})
    assert libro.disponible(ids[0]) == pytest.approx(0.0, abs=EPS)
    with pytest.raises(AsientoInvalido):
        libro.alta(HOY, "C3", "Tercera", {ids[0]: 5.0})


def test_liberar_devuelve_capacidad(vacio):
    cat, libro = vacio
    ids, m2 = _tres(cat)
    libro.alta(HOY, "C1", "Marca", {ids[0]: m2[0]})
    libro.baja(date(2026, 2, 1), "C1", ids[0], m2[0] / 2)
    assert libro.disponible(ids[0]) == pytest.approx(m2[0] / 2, abs=EPS)


# --------------------------------------------------------------------------
# Nadie devuelve lo que no tiene
# --------------------------------------------------------------------------

def test_no_se_devuelve_de_mas(vacio):
    cat, libro = vacio
    ids, m2 = _tres(cat)
    libro.alta(HOY, "C1", "Marca", {ids[0]: m2[0]})
    with pytest.raises(AsientoInvalido, match="devolver"):
        libro.baja(date(2026, 2, 1), "C1", ids[0], m2[0] + 1)


def test_un_contrato_no_devuelve_los_metros_de_otro(vacio):
    """El bug del sistema original, convertido en prueba.

    Dos inquilinos comparten local. Si la baja no mira el saldo **de ese
    contrato** sino el del local, el primero puede devolver los metros del
    segundo y el local queda con ocupación imposible.
    """
    cat, libro = vacio
    ids, m2 = _tres(cat)
    mitad = round(m2[0] / 2, 1)
    libro.alta(HOY, "C1", "Marca", {ids[0]: mitad})
    libro.alta(HOY, "C2", "Otra", {ids[0]: mitad})
    with pytest.raises(AsientoInvalido):
        libro.baja(date(2026, 2, 1), "C1", ids[0], m2[0])
    assert libro.ocupado(ids[0]) == pytest.approx(2 * mitad, abs=EPS)


# --------------------------------------------------------------------------
# Todo o nada
# --------------------------------------------------------------------------

def test_un_alta_de_varios_locales_que_falla_no_deja_rastro(vacio):
    cat, libro = vacio
    ids, m2 = _tres(cat)
    with pytest.raises(AsientoInvalido):
        libro.alta(HOY, "C1", "Marca",
                   {ids[0]: m2[0], ids[1]: m2[1] + 500})
    assert len(libro) == 0
    assert libro.ocupado(ids[0]) == 0.0


def test_no_se_expande_un_contrato_que_no_existe(vacio):
    cat, libro = vacio
    ids, m2 = _tres(cat)
    with pytest.raises(AsientoInvalido, match="expandir"):
        libro.expansion(HOY, "NO-EXISTE", "Marca", {ids[0]: 10.0})


def test_el_local_tiene_que_estar_en_el_catalogo(vacio):
    _, libro = vacio
    with pytest.raises(AsientoInvalido, match="catálogo"):
        libro.alta(HOY, "C1", "Marca", {"XXXX-PB-999": 10.0})


def test_el_cliente_no_puede_ir_vacio(vacio):
    cat, libro = vacio
    ids, _ = _tres(cat)
    with pytest.raises(AsientoInvalido, match="cliente"):
        libro.alta(HOY, "C1", "   ", {ids[0]: 10.0})


# --------------------------------------------------------------------------
# Texto que rompe sistemas hechos con concatenación
# --------------------------------------------------------------------------

@pytest.mark.parametrize("nombre", [
    "Café O'Brien",
    'Tienda "La Esquina"',
    "Ropa & Más, S.A. de C.V.",
    "Óptica Ñandú — sucursal 2",
    "DROP TABLE locales;--",
])
def test_el_nombre_del_cliente_sobrevive_intacto(vacio, nombre):
    cat, libro = vacio
    ids, _ = _tres(cat)
    libro.alta(HOY, "C1", nombre, {ids[0]: 10.0})
    assert libro.asientos["cliente"].iloc[0] == nombre
    assert libro.contratos_activos()["cliente"].iloc[0] == nombre


# --------------------------------------------------------------------------
# Folios de contrato
# --------------------------------------------------------------------------

def test_el_folio_de_contrato_es_legible_y_no_se_repite(vacio):
    cat, libro = vacio
    ids, m2 = _tres(cat)
    plaza = cat["plaza"].iloc[0]
    primero = siguiente_id_contrato(libro, plaza, HOY)
    assert primero == f"{plaza}-2026-0001"
    libro.alta(HOY, primero, "Marca", {ids[0]: m2[0]})
    assert siguiente_id_contrato(libro, plaza, HOY) == f"{plaza}-2026-0002"


def test_el_folio_no_cambia_cuando_el_contrato_se_expande(vacio):
    """El id del sistema original se armaba concatenando los locales, así que
    expandirse a otro local implicaba otro id para el mismo contrato."""
    cat, libro = vacio
    ids, m2 = _tres(cat)
    libro.alta(HOY, "C1", "Marca", {ids[0]: m2[0]})
    libro.expansion(HOY, "C1", "Marca", {ids[1]: m2[1]})
    vivos = libro.contratos_activos()
    assert set(vivos["id_contrato"]) == {"C1"}
    assert vivos["m2_ocupados"].sum() == pytest.approx(m2[0] + m2[1])


# --------------------------------------------------------------------------
# El estado es la suma del libro
# --------------------------------------------------------------------------

def test_el_estado_cuadra_con_la_suma_del_libro(mundo):
    cat, libro = mundo
    est = ocupacion.estado(cat, libro)
    suma = libro.asientos.groupby("id_local")["m2"].sum()
    calculado = est.set_index("id_local")["m2_ocupados"]
    esperado = suma.reindex(calculado.index).fillna(0.0)
    pd.testing.assert_series_equal(calculado.round(1), esperado.round(1),
                                   check_names=False)


def test_ningun_local_se_pasa_de_su_superficie(mundo):
    cat, libro = mundo
    est = ocupacion.estado(cat, libro)
    assert (est["m2_ocupados"] <= est["m2_totales"] + EPS).all()
    assert (est["m2_ocupados"] >= -EPS).all()


def test_los_tres_estados_son_coherentes(mundo):
    cat, libro = mundo
    est = ocupacion.estado(cat, libro)
    libres = est[est["estado"] == "libre"]
    llenos = est[est["estado"] == "ocupado"]
    parciales = est[est["estado"] == "parcial"]
    assert (libres["m2_ocupados"] <= EPS).all()
    assert (llenos["m2_disponibles"] <= EPS).all()
    assert ((parciales["m2_ocupados"] > EPS)
            & (parciales["m2_disponibles"] > EPS)).all()
    assert (libres["clientes"] == "").all()


def test_el_pasado_se_reconstruye_cortando_el_libro(mundo):
    cat, libro = mundo
    corte = date(2023, 6, 30)
    est = ocupacion.estado(cat, libro, corte)
    d = libro.asientos
    suma = d[d["fecha"] <= pd.Timestamp(corte)].groupby("id_local")["m2"].sum()
    calculado = est.set_index("id_local")["m2_ocupados"]
    esperado = suma.reindex(calculado.index).fillna(0.0)
    pd.testing.assert_series_equal(calculado.round(1), esperado.round(1),
                                   check_names=False)


def test_el_pasado_no_se_mueve_al_asentar_hoy(mundo):
    """La prueba de que el histórico es inmutable: agregar un contrato hoy no
    puede cambiar cómo se veía la plaza hace dos años."""
    cat, libro_base = mundo
    corte = date(2024, 1, 31)
    antes = ocupacion.estado(cat, libro_base, corte)["m2_ocupados"].to_numpy()

    libro = Libro(m2_totales(cat), libro_base.asientos)
    hueco = ocupacion.estado(cat, libro)
    libre = hueco[hueco["m2_disponibles"] > 20].iloc[0]
    libro.alta(date(2026, 9, 1), "NUEVO", "Marca de prueba",
               {libre["id_local"]: 20.0})

    despues = ocupacion.estado(cat, libro, corte)["m2_ocupados"].to_numpy()
    assert (antes == despues).all()


def test_la_ocupacion_por_metros_no_es_la_de_por_locales(mundo):
    """Si fueran iguales, el tablero estaría escondiendo las anclas vacías."""
    cat, libro = mundo
    r = ocupacion.resumen(ocupacion.estado(cat, libro))
    assert r["ocupacion_m2"] != r["ocupacion_locales"]
    assert 0.0 < r["ocupacion_m2"] < 1.0


# --------------------------------------------------------------------------
# Historial
# --------------------------------------------------------------------------

def test_las_vigencias_distinguen_al_que_se_quedo_del_que_se_fue(mundo):
    _, libro = mundo
    vig = libro.vigencias()
    vivos = vig[vig["fecha_baja"].isna()]
    idos = vig[vig["fecha_baja"].notna()]
    assert len(vivos) and len(idos)
    assert (vivos["m2_vigentes"] > 0).all()
    assert (idos["m2_vigentes"] == 0).all()
    assert (vig["fecha_alta"] <= vig["fecha_baja"].fillna(vig["fecha_alta"])).all()


def test_la_serie_de_ocupacion_nunca_sale_del_rango(mundo):
    cat, libro = mundo
    s = ocupacion.serie_ocupacion(cat, libro)
    assert (s["ocupacion"] >= -1e-9).all()
    assert (s["ocupacion"] <= 1 + 1e-9).all()
    assert s["plaza"].nunique() == cat["plaza"].nunique()


def test_la_rotacion_cuenta_los_mismos_asientos_que_el_libro(mundo):
    _, libro = mundo
    rot = ocupacion.rotacion(libro)
    assert rot[["altas", "bajas"]].to_numpy().sum() == len(libro)


# --------------------------------------------------------------------------
# Catálogo
# --------------------------------------------------------------------------

def test_el_catalogo_es_determinista():
    pd.testing.assert_frame_equal(catalogo(), catalogo())


def test_el_area_del_rectangulo_son_los_metros_rentables():
    """El plano y la tabla salen del mismo número. Si esto se rompe, el mapa
    dibuja una cosa y el reporte dice otra."""
    cat = catalogo()
    esperado = (cat["ancho"] * cat["alto"]).round(1)
    assert (cat["m2_totales"] - esperado).abs().max() < 0.06


def test_los_locales_no_se_encinan(mundo):
    """Dos locales del mismo nivel no pueden ocupar el mismo espacio."""
    cat, _ = mundo
    for (_, _), g in cat[~cat["id_local"].str.contains("-A")].groupby(
            ["plaza", "nivel"]):
        for hilera in (g[g["y"] > 0], g[g["y"] < 0]):
            h = hilera.sort_values("x")
            solapes = h["x"].shift(-1).dropna() - (h["x"] + h["ancho"])[:-1]
            assert (solapes >= -0.01).all()
