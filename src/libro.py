"""
El libro de ocupación: un registro que solo crece.

Esta es la pieza central del repositorio y la decisión que vale la pena
defender.

Dar de baja a un inquilino **no borra ni modifica nada**. Asienta una línea
nueva con los metros en negativo. Lo ocupado de un local es la suma de sus
asientos, y lo disponible es su superficie menos esa suma.

Tres cosas caen solas de ahí:

1. **El historial no es una bitácora que alguien tenga que acordarse de
   escribir.** Es el libro mismo. No puede desincronizarse del estado porque
   el estado se deriva de él.
2. **El estado a cualquier fecha pasada se reconstruye** filtrando los
   asientos hasta esa fecha. "¿Qué había en el local 014 en marzo de 2023?"
   es una consulta, no una investigación.
3. **Un error no se corrige editando el pasado**, se corrige con un asiento
   que lo compensa — y los dos quedan a la vista.

El costo es que hay que validar **en el momento de asentar**, porque después
ya no hay dónde. Eso es lo que hace `asentar`, y es la diferencia más
importante contra el sistema original, que insertaba el negativo sin
comprobar que hubiera algo que liberar.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

# Tolerancia en m². Los frentes vienen con un decimal y las capturas de
# operación redondean; sin holgura, cerrar un local exacto falla por 0.001.
EPS = 0.05

COLUMNAS = ["id_asiento", "fecha", "id_contrato", "id_local",
            "cliente", "m2", "motivo"]

MOTIVOS = {"alta", "expansion", "baja", "baja_total", "ajuste"}


class AsientoInvalido(ValueError):
    """Se rechazó un asiento. El libro quedó intacto."""


class Libro:
    """Los asientos de ocupación de un conjunto de plazas.

    `m2_por_local` es el catálogo: el libro necesita saber la superficie de
    cada local para no dejar que se ocupe de más. Sin eso podría asentar
    cualquier cosa y el error aparecería semanas después, en un reporte.
    """

    def __init__(self, m2_por_local: dict[str, float],
                 asientos: pd.DataFrame | None = None) -> None:
        self._m2 = dict(m2_por_local)
        if asientos is None:
            self._d = pd.DataFrame(columns=COLUMNAS).astype(
                {"id_asiento": "int64", "m2": "float64"})
            self._d["fecha"] = pd.to_datetime(self._d["fecha"])
        else:
            self._d = asientos[COLUMNAS].copy().reset_index(drop=True)
            self._d["fecha"] = pd.to_datetime(self._d["fecha"])

    # ------------------------------------------------------------------
    # Lectura
    # ------------------------------------------------------------------

    @property
    def asientos(self) -> pd.DataFrame:
        """Copia del libro. Se devuelve copia a propósito: nadie edita el
        libro por fuera de `asentar`."""
        return self._d.copy()

    def __len__(self) -> int:
        return len(self._d)

    def hasta(self, fecha: date | None) -> pd.DataFrame:
        """Los asientos hasta esa fecha inclusive. Sin fecha, todos."""
        if fecha is None:
            return self._d
        return self._d[self._d["fecha"] <= pd.Timestamp(fecha)]

    def ocupado(self, id_local: str, fecha: date | None = None) -> float:
        d = self.hasta(fecha)
        return float(d.loc[d["id_local"] == id_local, "m2"].sum())

    def disponible(self, id_local: str, fecha: date | None = None) -> float:
        return self._m2[id_local] - self.ocupado(id_local, fecha)

    def saldos(self, fecha: date | None = None) -> pd.Series:
        """m² ocupados por local. Los locales sin ningún asiento no aparecen;
        `ocupacion.estado()` los repone desde el catálogo."""
        d = self.hasta(fecha)
        if d.empty:
            return pd.Series(dtype="float64", name="m2_ocupados")
        s = d.groupby("id_local")["m2"].sum()
        s.name = "m2_ocupados"
        return s

    def saldo_contrato(self, id_contrato: str, id_local: str,
                       fecha: date | None = None) -> float:
        """Lo que *ese contrato* tiene tomado en *ese local*.

        Es lo que hay que mirar antes de una baja: un local puede tener tres
        inquilinos y cada uno solo puede devolver lo suyo.
        """
        d = self.hasta(fecha)
        m = (d["id_contrato"] == id_contrato) & (d["id_local"] == id_local)
        return float(d.loc[m, "m2"].sum())

    def contratos_activos(self, fecha: date | None = None) -> pd.DataFrame:
        """Contratos con saldo vivo, con su cliente, sus locales y sus metros."""
        d = self.hasta(fecha)
        if d.empty:
            return pd.DataFrame(columns=["id_contrato", "cliente", "id_local",
                                         "m2_ocupados"])
        g = (d.groupby(["id_contrato", "cliente", "id_local"], as_index=False)["m2"]
             .sum().rename(columns={"m2": "m2_ocupados"}))
        return g[g["m2_ocupados"] > EPS].reset_index(drop=True)

    def vigencias(self) -> pd.DataFrame:
        """Alta y baja de cada contrato: el historial que pedía operación.

        `fecha_baja` es nula mientras el contrato conserve metros. Se calcula
        del libro, no de una columna de estado que alguien tenga que mantener.
        """
        if self._d.empty:
            return pd.DataFrame(columns=["id_contrato", "cliente", "fecha_alta",
                                         "fecha_baja", "m2_vigentes",
                                         "locales", "dias"])
        filas = []
        for (cid, cliente), g in self._d.groupby(["id_contrato", "cliente"]):
            vivo = g.groupby("id_local")["m2"].sum()
            vivo = vivo[vivo > EPS]
            alta = g["fecha"].min()
            baja = pd.NaT if len(vivo) else g["fecha"].max()
            fin = baja if pd.notna(baja) else self._d["fecha"].max()
            filas.append({
                "id_contrato": cid,
                "cliente": cliente,
                "fecha_alta": alta,
                "fecha_baja": baja,
                "m2_vigentes": round(float(vivo.sum()), 1),
                "locales": ", ".join(sorted(vivo.index)) if len(vivo) else "",
                "dias": int((fin - alta).days),
            })
        return (pd.DataFrame(filas)
                .sort_values("fecha_alta", ascending=False)
                .reset_index(drop=True))

    # ------------------------------------------------------------------
    # Escritura — el único camino
    # ------------------------------------------------------------------

    def asentar(self, fecha: date, id_contrato: str, id_local: str,
                cliente: str, m2: float, motivo: str) -> int:
        """Agrega un asiento y devuelve su folio.

        Valida antes de escribir. Si algo no cuadra levanta `AsientoInvalido`
        y el libro queda exactamente como estaba — no hay asientos a medias.
        """
        cliente = (cliente or "").strip()
        id_contrato = (id_contrato or "").strip()

        if not cliente:
            raise AsientoInvalido("El asiento necesita un cliente.")
        if not id_contrato:
            raise AsientoInvalido("El asiento necesita un id de contrato.")
        if motivo not in MOTIVOS:
            raise AsientoInvalido(
                f"Motivo '{motivo}' desconocido. Válidos: {sorted(MOTIVOS)}.")
        if id_local not in self._m2:
            raise AsientoInvalido(
                f"El local '{id_local}' no está en el catálogo de la plaza.")
        if abs(m2) < EPS:
            raise AsientoInvalido("Un asiento de cero metros no dice nada.")

        # El libro no se fecha hacia atrás. Corregir el pasado se hace con un
        # asiento nuevo, que es justamente lo que lo vuelve auditable.
        if len(self._d):
            ultimo = self._d["fecha"].max()
            if pd.Timestamp(fecha) < ultimo:
                raise AsientoInvalido(
                    f"No se puede fechar un asiento el {fecha} cuando el último "
                    f"es del {ultimo.date()}. Para corregir, asienta un ajuste.")

        if m2 > 0:
            libre = self.disponible(id_local)
            if m2 > libre + EPS:
                raise AsientoInvalido(
                    f"El local {id_local} tiene {libre:.1f} m² libres y se "
                    f"piden {m2:.1f} m².")
        else:
            tomado = self.saldo_contrato(id_contrato, id_local)
            if abs(m2) > tomado + EPS:
                raise AsientoInvalido(
                    f"El contrato {id_contrato} tiene {tomado:.1f} m² en "
                    f"{id_local} y pretende devolver {abs(m2):.1f} m².")

        folio = int(self._d["id_asiento"].max()) + 1 if len(self._d) else 1
        self._d.loc[len(self._d)] = {
            "id_asiento": folio,
            "fecha": pd.Timestamp(fecha),
            "id_contrato": id_contrato,
            "id_local": id_local,
            "cliente": cliente,
            "m2": round(float(m2), 2),
            "motivo": motivo,
        }
        return folio

    # -- azúcar sobre `asentar`, para que la app lea como el negocio habla --

    def alta(self, fecha: date, id_contrato: str, cliente: str,
             tramos: dict[str, float]) -> list[int]:
        """Un contrato nuevo sobre uno o varios locales.

        Es todo o nada: si un solo tramo no cabe, no se asienta ninguno. Un
        contrato a medias es peor que un contrato rechazado, porque nadie se
        entera hasta que no cuadra el cobro.
        """
        return self._en_bloque(fecha, id_contrato, cliente, tramos, "alta")

    def expansion(self, fecha: date, id_contrato: str, cliente: str,
                  tramos: dict[str, float]) -> list[int]:
        """Metros adicionales para un contrato que ya existe."""
        if not self._existe(id_contrato):
            raise AsientoInvalido(
                f"No hay contrato {id_contrato} que expandir.")
        return self._en_bloque(fecha, id_contrato, cliente, tramos, "expansion")

    def baja(self, fecha: date, id_contrato: str, id_local: str,
             m2: float) -> int:
        """Devolución parcial o total de un local."""
        cliente = self._cliente_de(id_contrato)
        return self.asentar(fecha, id_contrato, id_local, cliente,
                            -abs(m2), "baja")

    def baja_total(self, fecha: date, id_contrato: str) -> list[int]:
        """Cierre del contrato: devuelve todo lo que tenga, donde lo tenga."""
        vivos = self.contratos_activos()
        mio = vivos[vivos["id_contrato"] == id_contrato]
        if mio.empty:
            raise AsientoInvalido(
                f"El contrato {id_contrato} no tiene metros vigentes.")
        cliente = str(mio["cliente"].iloc[0])
        return [self.asentar(fecha, id_contrato, r.id_local, cliente,
                             -r.m2_ocupados, "baja_total")
                for r in mio.itertuples()]

    # ------------------------------------------------------------------

    def _en_bloque(self, fecha, id_contrato, cliente, tramos, motivo):
        """Ensaya el bloque completo sobre una copia; solo si pasa, lo aplica.

        Sin este ensayo, `alta` podría dejar dos tramos asentados y reventar en
        el tercero, y limpiar eso requiere asientos compensatorios que nadie
        pidió.
        """
        if len(tramos) > 1:
            ensayo = Libro(self._m2, self._d)
            for id_local, m2 in tramos.items():
                ensayo.asentar(fecha, id_contrato, id_local, cliente, m2, motivo)
        return [self.asentar(fecha, id_contrato, id_local, cliente, m2, motivo)
                for id_local, m2 in tramos.items()]

    def _existe(self, id_contrato: str) -> bool:
        return bool((self._d["id_contrato"] == id_contrato).any())

    def _cliente_de(self, id_contrato: str) -> str:
        d = self._d[self._d["id_contrato"] == id_contrato]
        if d.empty:
            raise AsientoInvalido(f"No existe el contrato {id_contrato}.")
        return str(d["cliente"].iloc[0])


def siguiente_id_contrato(libro: Libro, plaza: str, fecha: date) -> str:
    """Folio de contrato legible y determinista: `PALT-2026-0007`.

    El sistema original lo armaba concatenando los locales y pegándole un
    número al azar, y comprobaba contra la base si ya existía. Eso daba ids
    ilegibles (`PB-014_PB-016_8231`), cambiaba si el contrato se expandía a
    otro local, y la comprobación era una carrera entre dos capturistas. Un
    consecutivo por plaza y año no tiene ninguno de los tres problemas.
    """
    d = libro.asientos
    prefijo = f"{plaza}-{fecha.year}-"
    usados = d.loc[d["id_contrato"].str.startswith(prefijo), "id_contrato"]
    n = max((int(c.rsplit("-", 1)[1]) for c in usados), default=0) + 1
    return f"{prefijo}{n:04d}"
