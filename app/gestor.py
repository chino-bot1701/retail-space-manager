"""
Gestor de espacios comerciales — demo.

Cuatro pestañas sobre un mismo libro: el plano, dar de alta, dar de baja y el
historial. Todo el estado sale del libro de asientos; no hay una tabla de
"ocupación actual" que mantener.

Corre sin base de datos y sin credenciales. Los datos son sintéticos.

    streamlit run app/gestor.py
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import ocupacion, plano  # noqa: E402
from src.generar_historia import FIN, GIROS, MARCA_GIRO, generar  # noqa: E402
from src.libro import AsientoInvalido, Libro, siguiente_id_contrato  # noqa: E402
from src.plaza import (NIVELES_NOMBRE, niveles_ordenados,  # noqa: E402
                       nombre_plaza)

st.set_page_config(page_title="Retail Space Manager",
                   page_icon="🏬", layout="wide")

MARCAS = sorted({m for cfg in GIROS.values() for m in cfg["marcas"]})


# ---------------------------------------------------------------------------
# Estado
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner="Generando cuatro años de movimientos…")
def _historia():
    cat, libro = generar()
    return cat, libro.asientos


def libro_de_sesion() -> tuple[pd.DataFrame, Libro]:
    """El catálogo es fijo; el libro vive en la sesión y crece con lo que
    haga el visitante. Cada pestaña del navegador tiene el suyo, así que dos
    personas pueden jugar con la demo al mismo tiempo sin pisarse."""
    cat, asientos = _historia()
    if "libro" not in st.session_state:
        from src.plaza import m2_totales
        st.session_state.libro = Libro(m2_totales(cat), asientos)
    return cat, st.session_state.libro


cat, libro = libro_de_sesion()


def confirmar(mensaje: str) -> None:
    """Guarda el aviso y reejecuta.

    `st.success()` seguido de `st.rerun()` no se ve nunca: el rerun vuelve a
    pintar la página desde cero y se lleva el mensaje. Se descubrió probando
    la app con `AppTest` —la baja se asentaba y la pantalla no decía nada—,
    que es justo lo que un clic manual apurado no alcanza a notar.
    """
    st.session_state["aviso"] = mensaje
    st.rerun()

# La fecha de trabajo: nunca antes del último asiento, porque el libro no se
# retro-fecha.
hoy = max(FIN, libro.asientos["fecha"].max().date())


# ---------------------------------------------------------------------------
# Encabezado
# ---------------------------------------------------------------------------

st.title("Gestor de espacios comerciales")
st.caption(
    "Ocupación, contratos e historial de tres plazas comerciales. **Todos los "
    "datos son sintéticos** — ninguna plaza, marca ni contrato es real. "
    "La app no se conecta a ninguna base de datos."
)

with st.sidebar:
    st.header("Plaza")
    codigo = st.selectbox(
        "Centro comercial", sorted(cat["plaza"].unique()),
        format_func=lambda c: f"{nombre_plaza(c)} ({c})")
    cat_p = cat[cat["plaza"] == codigo]

    st.divider()
    st.subheader("El libro")
    st.metric("Asientos", f"{len(libro):,}")
    st.metric("Contratos históricos",
              f"{libro.asientos['id_contrato'].nunique():,}")
    st.caption(
        "Dar de baja no borra: asienta los metros en negativo. Por eso el "
        "historial y el estado no pueden desincronizarse — el estado *es* la "
        "suma del historial."
    )
    if st.button("Reiniciar la demo", width="stretch"):
        st.session_state.pop("libro", None)
        st.rerun()


if aviso := st.session_state.pop("aviso", None):
    st.success(aviso)

tab_plano, tab_alta, tab_baja, tab_hist = st.tabs(
    ["Plano y disponibilidad", "Rentar espacio", "Liberar espacio",
     "Historial y rotación"])


# ---------------------------------------------------------------------------
# 1 · Plano
# ---------------------------------------------------------------------------

with tab_plano:
    primera = libro.asientos["fecha"].min().date()
    corte = st.slider(
        "Ver el plano a esta fecha", min_value=primera, max_value=hoy,
        value=hoy, format="MMM YYYY",
        help="El libro se corta a la fecha y el estado se recalcula. No hay "
             "tabla histórica: el pasado se reconstruye del mismo registro.")

    est = ocupacion.estado(cat_p, libro, corte)
    r = ocupacion.resumen(est)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Ocupación (m²)", f"{r['ocupacion_m2']:.1%}")
    c2.metric("m² disponibles", f"{r['m2_disponibles']:,.0f}")
    c3.metric("Locales libres", f"{r['locales_libres']} de {r['locales']}")
    c4.metric("Locales compartidos", r["locales_parciales"],
              help="Dos o más inquilinos en el mismo local.")

    if abs(r["ocupacion_m2"] - r["ocupacion_locales"]) > 0.03:
        st.info(
            f"Por metros la ocupación es **{r['ocupacion_m2']:.1%}**, por número "
            f"de locales **{r['ocupacion_locales']:.1%}**. La diferencia son las "
            "anclas: un local grande vacío pesa mucho más que uno chico, y "
            "contar locales lo esconde.")

    for nivel in niveles_ordenados(est["nivel"].unique()):
        sub = est[est["nivel"] == nivel]
        st.altair_chart(
            plano.dibujar(
                sub,
                f"{nombre_plaza(codigo)} — {NIVELES_NOMBRE.get(nivel, nivel)}"
                f" · {sub['m2_ocupados'].sum() / sub['m2_totales'].sum():.0%} ocupado",
                altura=260),
            width="stretch")

    st.subheader("Detalle por local")
    cols = ["id_local", "nivel", "m2_totales", "m2_ocupados", "m2_disponibles",
            "estado", "clientes", "contratos"]
    st.dataframe(
        est[cols].rename(columns={
            "id_local": "Local", "nivel": "Nivel", "m2_totales": "m² totales",
            "m2_ocupados": "m² ocupados", "m2_disponibles": "m² libres",
            "estado": "Estado", "clientes": "Inquilinos",
            "contratos": "Contratos"}),
        hide_index=True, width="stretch", height=320)

    st.subheader("Quién ocupa la plaza")
    inq = ocupacion.por_cliente(libro, corte, cat_p["id_local"])

    if inq.empty:
        st.info("Ningún inquilino en esta plaza a esta fecha.")
    else:
        izq, der = st.columns([3, 2])

        top = inq.head(12).copy()
        top["giro"] = top["cliente"].map(MARCA_GIRO).fillna("Otro")
        izq.altair_chart(
            alt.Chart(top).mark_bar().encode(
                x=alt.X("m2_ocupados:Q", title="m² ocupados"),
                y=alt.Y("cliente:N", sort="-x", title=None),
                color=alt.Color("giro:N", title="Giro",
                                legend=alt.Legend(orient="bottom", columns=3)),
                tooltip=[alt.Tooltip("cliente:N", title="Cliente"),
                         alt.Tooltip("giro:N", title="Giro"),
                         alt.Tooltip("m2_ocupados:Q", title="m²", format=",.0f"),
                         alt.Tooltip("n_locales:Q", title="Locales"),
                         alt.Tooltip("locales:N", title="Cuáles")],
            ).properties(height=320, title="Los 12 mayores, por metros"),
            width="stretch")

        # La mezcla de giros es la pregunta comercial de fondo: una plaza que
        # es 60% comida no es la misma que una que es 60% moda, aunque las dos
        # estén al 90% de ocupación.
        mezcla = (inq.assign(giro=inq["cliente"].map(MARCA_GIRO).fillna("Otro"))
                  .groupby("giro", as_index=False)["m2_ocupados"].sum())
        der.altair_chart(
            alt.Chart(mezcla).mark_arc(innerRadius=55).encode(
                theta=alt.Theta("m2_ocupados:Q"),
                color=alt.Color("giro:N", title="Giro",
                                legend=alt.Legend(orient="bottom", columns=2)),
                tooltip=[alt.Tooltip("giro:N", title="Giro"),
                         alt.Tooltip("m2_ocupados:Q", title="m²", format=",.0f")],
            ).properties(height=320, title="Mezcla comercial, por metros"),
            width="stretch")

        st.dataframe(
            inq.rename(columns={
                "cliente": "Cliente", "m2_ocupados": "m² ocupados",
                "locales": "Locales", "n_locales": "Núm. locales",
                "n_contratos": "Núm. contratos"}),
            hide_index=True, width="stretch", height=280)
        st.caption(
            f"{len(inq)} inquilinos en {nombre_plaza(codigo)}. Para la ocupación "
            "mes a mes, la rotación y el libro completo, ve a "
            "**Historial y rotación**.")


# ---------------------------------------------------------------------------
# 2 · Rentar
# ---------------------------------------------------------------------------

with tab_alta:
    st.subheader("Registrar una renta")
    st.caption(
        "El libro valida antes de escribir. Pide más metros de los que quedan "
        "y la operación se rechaza entera — no se asientan los tramos que sí "
        "cabían.")

    est_hoy = ocupacion.estado(cat_p, libro)
    con_espacio = est_hoy[est_hoy["m2_disponibles"] > 0.05].sort_values("id_local")

    if con_espacio.empty:
        st.success("La plaza está llena. No hay metros que colocar.")
    else:
        izq, der = st.columns([2, 1])

        with izq:
            tipo = st.radio(
                "Tipo de operación", ["Contrato nuevo", "Expansión"],
                horizontal=True,
                help="La expansión agrega metros a un contrato existente, "
                     "manteniendo su folio.")

            vivos = libro.contratos_activos()
            if tipo == "Expansión" and vivos.empty:
                st.warning("No hay contratos vigentes que expandir.")
                tipo = "Contrato nuevo"

            if tipo == "Contrato nuevo":
                cliente = st.selectbox(
                    "Cliente", MARCAS, index=None,
                    placeholder="Elige una marca o escribe una nueva",
                    accept_new_options=True)
                contrato = None
            else:
                opciones = (vivos.groupby("id_contrato")["cliente"].first()
                            .sort_index())
                contrato = st.selectbox(
                    "Contrato a expandir", list(opciones.index),
                    format_func=lambda c: f"{c} — {opciones[c]}")
                cliente = opciones[contrato]
                st.caption(f"Cliente: **{cliente}**")

            etiquetas = {
                r.id_local: f"{r.id_local} · {r.m2_disponibles:,.0f} m² libres"
                            f" de {r.m2_totales:,.0f}"
                for r in con_espacio.itertuples()}
            elegidos = st.multiselect(
                "Locales", list(etiquetas), format_func=etiquetas.get,
                help="Un contrato puede abarcar varios locales. Es el caso "
                     "normal cuando un inquilino toma dos cortinas contiguas.")

            tramos: dict[str, float] = {}
            for id_local in elegidos:
                libre = float(
                    con_espacio.loc[con_espacio["id_local"] == id_local,
                                    "m2_disponibles"].iloc[0])
                tramos[id_local] = st.number_input(
                    f"m² en {id_local}", min_value=1.0, max_value=libre,
                    value=libre, step=1.0, key=f"m2_{id_local}")

        with der:
            st.markdown("**Resumen**")
            if tramos:
                st.metric("m² a colocar", f"{sum(tramos.values()):,.1f}")
                st.metric("Locales", len(tramos))
                if cliente in MARCA_GIRO:
                    st.caption(f"Giro: {MARCA_GIRO[cliente]}")
            else:
                st.caption("Elige al menos un local.")

        if st.button("Registrar renta", type="primary", disabled=not tramos):
            if not cliente:
                st.error("Falta el cliente.")
            else:
                try:
                    if tipo == "Contrato nuevo":
                        cid = siguiente_id_contrato(libro, codigo, hoy)
                        libro.alta(hoy, cid, cliente, tramos)
                    else:
                        cid = contrato
                        libro.expansion(hoy, cid, cliente, tramos)
                    confirmar(f"Contrato **{cid}** — {cliente}, "
                              f"{sum(tramos.values()):,.1f} m² en "
                              f"{len(tramos)} local(es).")
                except AsientoInvalido as e:
                    st.error(f"Rechazado por el libro: {e}")


# ---------------------------------------------------------------------------
# 3 · Liberar
# ---------------------------------------------------------------------------

with tab_baja:
    st.subheader("Liberar espacio")
    st.caption(
        "No se borra el registro: se asienta la devolución con los metros en "
        "negativo. El contrato sigue en el historial con su fecha de alta y "
        "su fecha de baja.")

    vivos = libro.contratos_activos()
    vivos = vivos[vivos["id_local"].isin(cat_p["id_local"])]

    if vivos.empty:
        st.info("No hay contratos vigentes en esta plaza.")
    else:
        etiquetas = (vivos.groupby("id_contrato")
                     .agg(cliente=("cliente", "first"),
                          m2=("m2_ocupados", "sum"),
                          n=("id_local", "nunique")))
        cid = st.selectbox(
            "Contrato", list(etiquetas.index),
            format_func=lambda c: (f"{c} — {etiquetas.loc[c, 'cliente']} · "
                                   f"{etiquetas.loc[c, 'm2']:,.0f} m² en "
                                   f"{etiquetas.loc[c, 'n']} local(es)"))

        detalle = vivos[vivos["id_contrato"] == cid]
        st.dataframe(
            detalle.rename(columns={"id_local": "Local",
                                    "m2_ocupados": "m² ocupados",
                                    "cliente": "Cliente",
                                    "id_contrato": "Contrato"}),
            hide_index=True, width="stretch")

        modo = st.radio("Alcance", ["Cerrar el contrato completo",
                                    "Devolver parte de un local"],
                        horizontal=True)

        if modo == "Cerrar el contrato completo":
            if st.button("Cerrar contrato", type="primary"):
                try:
                    folios = libro.baja_total(hoy, cid)
                    confirmar(f"Contrato **{cid}** cerrado con "
                              f"{len(folios)} asiento(s) de devolución.")
                except AsientoInvalido as e:
                    st.error(f"Rechazado por el libro: {e}")
        else:
            id_local = st.selectbox("Local", list(detalle["id_local"]))
            tope = float(detalle.loc[detalle["id_local"] == id_local,
                                     "m2_ocupados"].iloc[0])
            m2 = st.number_input("m² a devolver", min_value=1.0,
                                 max_value=tope, value=tope, step=1.0)
            if st.button("Devolver metros", type="primary"):
                try:
                    libro.baja(hoy, cid, id_local, m2)
                    confirmar(f"**{m2:,.1f} m²** devueltos en {id_local}.")
                except AsientoInvalido as e:
                    st.error(f"Rechazado por el libro: {e}")

        with st.expander("Prueba a romperlo"):
            st.markdown(
                "Intenta devolver más metros de los que el contrato tiene, o "
                "colocar en un local lleno. El libro rechaza el asiento y "
                "explica por qué; **no queda nada a medias**. Esa validación "
                "es la diferencia contra el sistema del que sale esto, que "
                "insertaba el negativo sin comprobar el saldo y dejaba locales "
                "con ocupación imposible.")


# ---------------------------------------------------------------------------
# 4 · Historial
# ---------------------------------------------------------------------------

with tab_hist:
    st.subheader("Ocupación en el tiempo")
    serie = ocupacion.serie_ocupacion(cat, libro)
    st.altair_chart(
        alt.Chart(serie).mark_line(point=False, strokeWidth=2).encode(
            x=alt.X("fecha:T", title=None),
            y=alt.Y("ocupacion:Q", title="Ocupación",
                    axis=alt.Axis(format="%"),
                    scale=alt.Scale(domain=[0, 1])),
            color=alt.Color("plaza:N", title="Plaza"),
            tooltip=[alt.Tooltip("fecha:T", title="Mes", format="%b %Y"),
                     alt.Tooltip("plaza:N", title="Plaza"),
                     alt.Tooltip("ocupacion:Q", title="Ocupación",
                                 format=".1%"),
                     alt.Tooltip("m2_ocupados:Q", title="m²", format=",.0f")],
        ).properties(height=260),
        width="stretch")
    st.caption(
        "Esta serie no se guardó en ningún lado. Se reconstruye recorriendo el "
        "libro y acumulando — la consecuencia directa de no borrar.")

    st.subheader("Altas y bajas por mes")
    rot = ocupacion.rotacion(libro).melt(
        "mes", var_name="movimiento", value_name="n")
    st.altair_chart(
        alt.Chart(rot).mark_bar().encode(
            x=alt.X("mes:T", title=None),
            y=alt.Y("n:Q", title="Asientos"),
            color=alt.Color("movimiento:N", title=None,
                            scale=alt.Scale(domain=["altas", "bajas"],
                                            range=["#2d7d46", "#d7373f"])),
            tooltip=["mes:T", "movimiento:N", "n:Q"],
        ).properties(height=200),
        width="stretch")

    st.subheader("Contratos")
    vig = libro.vigencias()
    solo_vig = st.checkbox("Solo los vigentes", value=False)
    if solo_vig:
        vig = vig[vig["fecha_baja"].isna()]
    st.dataframe(
        vig.assign(
            fecha_alta=vig["fecha_alta"].dt.date,
            fecha_baja=vig["fecha_baja"].dt.date,
        ).rename(columns={
            "id_contrato": "Contrato", "cliente": "Cliente",
            "fecha_alta": "Alta", "fecha_baja": "Baja",
            "m2_vigentes": "m² vigentes", "locales": "Locales",
            "dias": "Días"}),
        hide_index=True, width="stretch", height=300)

    st.subheader("El libro, tal cual")
    asientos = libro.asientos.sort_values("id_asiento", ascending=False)
    st.dataframe(
        asientos.assign(fecha=asientos["fecha"].dt.date).rename(columns={
            "id_asiento": "Folio", "fecha": "Fecha",
            "id_contrato": "Contrato", "id_local": "Local",
            "cliente": "Cliente", "m2": "m²", "motivo": "Motivo"}),
        hide_index=True, width="stretch", height=320)
    st.caption(
        "Los m² negativos son devoluciones. Ninguna fila de esta tabla se "
        "modificó nunca después de escribirse.")
