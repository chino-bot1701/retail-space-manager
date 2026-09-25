"""
Corre el pipeline completo y comprueba que lo que dice el README es cierto.

No imprime "todo bien": mide y afirma. Si una cifra del README deja de
cumplirse, esto falla.

    python scripts/run_demo.py
"""

from __future__ import annotations

import sys
import time
from datetime import date
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

# La consola de Windows sale en cp1252 y revienta con una flecha o un "m²".
# Sin esto el script parece roto cuando lo único que falla es el terminal.
for flujo in (sys.stdout, sys.stderr):
    if hasattr(flujo, "reconfigure"):
        flujo.reconfigure(encoding="utf-8", errors="replace")

from src import ocupacion  # noqa: E402
from src.generar_historia import generar  # noqa: E402
from src.libro import EPS, AsientoInvalido, Libro  # noqa: E402
from src.plaza import PLAZAS, m2_totales, nombre_plaza  # noqa: E402

fallos: list[str] = []


def afirmar(condicion: bool, texto: str) -> None:
    marca = "OK  " if condicion else "FALLA"
    print(f"  [{marca}] {texto}")
    if not condicion:
        fallos.append(texto)


def titulo(t: str) -> None:
    print(f"\n{t}\n{'-' * len(t)}")


# ---------------------------------------------------------------------------
titulo("1 · Generación")

t0 = time.time()
cat, libro = generar()
segundos = time.time() - t0
asientos = libro.asientos

print(f"  {len(cat)} locales en {cat['plaza'].nunique()} plazas · "
      f"{cat['m2_totales'].sum():,.0f} m² rentables")
print(f"  {len(asientos)} asientos · "
      f"{asientos['id_contrato'].nunique()} contratos · "
      f"{asientos['fecha'].min():%b %Y} a {asientos['fecha'].max():%b %Y}")
print(f"  generado en {segundos:.1f} s")

afirmar(segundos < 6, f"la historia se genera en menos de 6 s ({segundos:.1f} s)")

cat2, libro2 = generar()
afirmar(libro2.asientos.equals(asientos), "el generador es determinista")

# ---------------------------------------------------------------------------
titulo("2 · El libro solo crece")

afirmar((asientos["id_asiento"].diff().dropna() == 1).all(),
        "los folios son consecutivos y sin huecos")
afirmar(asientos["fecha"].is_monotonic_increasing,
        "ningún asiento está fechado antes del anterior")
afirmar((asientos["m2"].abs() > EPS).all(),
        "no hay asientos de cero metros")
afirmar(asientos["m2"].lt(0).any() and asientos["m2"].gt(0).any(),
        "hay asientos positivos (altas) y negativos (devoluciones)")

n_bajas = int(asientos["motivo"].isin(["baja", "baja_total"]).sum())
print(f"  altas {int(asientos['motivo'].eq('alta').sum())} · "
      f"expansiones {int(asientos['motivo'].eq('expansion').sum())} · "
      f"devoluciones {n_bajas}")

# ---------------------------------------------------------------------------
titulo("3 · Ningún local se ocupa de más ni de menos")

est = ocupacion.estado(cat, libro)
afirmar((est["m2_ocupados"] >= -EPS).all(),
        "ningún local tiene ocupación negativa")
afirmar((est["m2_ocupados"] <= est["m2_totales"] + EPS).all(),
        "ningún local excede su superficie")

peor = (est["m2_ocupados"] - est["m2_totales"]).max()
print(f"  mayor exceso sobre la superficie: {peor:+.2f} m²")

# ---------------------------------------------------------------------------
titulo("4 · El estado es la suma del historial")

# La comprobación que justifica el diseño entero: reconstruir la ocupación
# sumando el libro a mano tiene que dar exactamente lo mismo que el estado.
a_mano = asientos.groupby("id_local")["m2"].sum()
del_estado = est.set_index("id_local")["m2_ocupados"]
brecha = (del_estado - a_mano.reindex(del_estado.index).fillna(0)).abs().max()
afirmar(brecha < 0.051,
        f"el estado coincide con la suma del libro (brecha máx {brecha:.3f} m²)")

# ---------------------------------------------------------------------------
titulo("5 · El pasado se reconstruye del mismo libro")

corte = date(2023, 6, 30)
antes = ocupacion.estado(cat, libro, corte)
solo_hasta = asientos[asientos["fecha"] <= pd.Timestamp(corte)]
suma = solo_hasta.groupby("id_local")["m2"].sum()
b2 = (antes.set_index("id_local")["m2_ocupados"]
      - suma.reindex(antes["id_local"]).fillna(0).to_numpy()).abs().max()
afirmar(b2 < 0.051, f"el plano de {corte:%b %Y} cuadra con el libro cortado")

r_antes = ocupacion.resumen(antes)
r_hoy = ocupacion.resumen(est)
print(f"  ocupación jun-2023 {r_antes['ocupacion_m2']:.1%} → "
      f"hoy {r_hoy['ocupacion_m2']:.1%}")
afirmar(r_antes["ocupacion_m2"] < r_hoy["ocupacion_m2"],
        "la plaza se llenó con el tiempo")

# ---------------------------------------------------------------------------
titulo("6 · La ocupación se parece a la de una plaza real")

for codigo in PLAZAS:
    e = ocupacion.estado(cat[cat["plaza"] == codigo], libro)
    r = ocupacion.resumen(e)
    print(f"  {nombre_plaza(codigo):18s} {r['ocupacion_m2']:6.1%} · "
          f"{r['locales_libres']:2d} libres · "
          f"{r['locales_parciales']:2d} compartidos · "
          f"{r['locales']} locales")

afirmar(0.70 <= r_hoy["ocupacion_m2"] <= 0.95,
        f"la ocupación global cae entre 70% y 95% ({r_hoy['ocupacion_m2']:.1%})")
afirmar(r_hoy["locales_parciales"] >= 2,
        f"hay locales compartidos entre inquilinos ({r_hoy['locales_parciales']})")
afirmar(abs(r_hoy["ocupacion_m2"] - r_hoy["ocupacion_locales"]) > 0.005,
        "contar metros y contar locales no da lo mismo")

# ---------------------------------------------------------------------------
titulo("7 · El historial contesta lo que pedía operación")

vig = libro.vigencias()
cerrados = vig[vig["fecha_baja"].notna()]
print(f"  {len(vig)} contratos · {len(vig) - len(cerrados)} vigentes · "
      f"{len(cerrados)} cerrados")
print(f"  duración mediana de un contrato cerrado: "
      f"{cerrados['dias'].median():.0f} días")

afirmar(len(cerrados) >= 20,
        f"hay historia de inquilinos que se fueron ({len(cerrados)})")
afirmar((vig[vig["fecha_baja"].isna()]["m2_vigentes"] > 0).all(),
        "todo contrato sin fecha de baja conserva metros")
afirmar((cerrados["m2_vigentes"] == 0).all(),
        "todo contrato cerrado quedó en cero metros")

clientes = ocupacion.por_cliente(libro)
print(f"  {len(clientes)} inquilinos activos · "
      f"el mayor ocupa {clientes['m2_ocupados'].iloc[0]:,.0f} m²")
afirmar(clientes["n_locales"].max() >= 2,
        "hay inquilinos con más de un local")

# ---------------------------------------------------------------------------
titulo("8 · Las reglas están en el código, no en la buena voluntad")

prueba = Libro(m2_totales(cat))
local = cat["id_local"].iloc[0]
techo = float(cat["m2_totales"].iloc[0])


def rechaza(fn, motivo: str) -> bool:
    try:
        fn()
    except AsientoInvalido:
        return True
    return False


afirmar(rechaza(lambda: prueba.asentar(date(2026, 1, 1), "C1", local,
                                       "Marca", techo + 50, "alta"), ""),
        "se rechaza ocupar más metros de los que tiene el local")

prueba.alta(date(2026, 1, 1), "C1", "Marca", {local: techo})
afirmar(rechaza(lambda: prueba.baja(date(2026, 2, 1), "C1", local, techo + 10), ""),
        "se rechaza devolver más metros de los que se tienen")
afirmar(rechaza(lambda: prueba.asentar(date(2025, 1, 1), "C2", local,
                                       "Otra", 10, "alta"), ""),
        "se rechaza un asiento fechado hacia atrás")
afirmar(rechaza(lambda: prueba.asentar(date(2026, 3, 1), "C3", "NO-EXISTE",
                                       "Otra", 10, "alta"), ""),
        "se rechaza un local que no está en el catálogo")

# Y la que importa de verdad: un rechazo no deja nada a medias.
segundo = cat["id_local"].iloc[1]
n_antes = len(prueba)
rechaza(lambda: prueba.alta(date(2026, 3, 1), "C4", "Marca",
                            {segundo: 10.0, local: 999_999.0}), "")
afirmar(len(prueba) == n_antes,
        "un alta de varios locales que falla no asienta ninguno")

# ---------------------------------------------------------------------------
titulo("9 · Un nombre con comilla no rompe nada")

# El sistema original armaba el INSERT con sprintf. Un cliente llamado
# "O'Brien" cerraba la cadena SQL y tumbaba la operación —o algo peor—.
raro = "Café O'Brien & Hijos, S.A. de C.V. — 100% \"nuevo\""
tercero = cat["id_local"].iloc[2]
prueba.alta(date(2026, 4, 1), "C5", raro, {tercero: 15.0})
guardado = prueba.asientos[prueba.asientos["id_contrato"] == "C5"]["cliente"].iloc[0]
afirmar(guardado == raro, "el nombre del cliente sobrevive intacto")

# ---------------------------------------------------------------------------
print("\n" + "=" * 68)
if fallos:
    print(f"{len(fallos)} ASERCIÓN(ES) FALLIDA(S):")
    for f in fallos:
        print(f"  - {f}")
    sys.exit(1)
print("Todas las aserciones pasaron.")
