"""
Genera las dos figuras que el README embebe.

Se corre a mano cuando cambian los datos o el diseño; las imágenes van
versionadas. Un README con gráficas se entiende de un vistazo y un notebook
sin ejecutar no muestra nada.

    python scripts/generar_figuras.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt          # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from src import ocupacion  # noqa: E402
from src.generar_historia import generar  # noqa: E402
from src.ocupacion import COLORES  # noqa: E402
from src.plaza import (NIVELES_NOMBRE, niveles_ordenados,  # noqa: E402
                       nombre_plaza)

DOCS = RAIZ / "docs"
DOCS.mkdir(exist_ok=True)

FONDO = "#fbfaf8"
TINTA = "#2b2b2b"


def plano(cat, libro, codigo: str = "PALT") -> None:
    est = ocupacion.estado(cat[cat["plaza"] == codigo], libro)
    niveles = niveles_ordenados(est["nivel"].unique())

    fig, ejes = plt.subplots(len(niveles), 1,
                             figsize=(13, 2.4 * len(niveles)),
                             facecolor=FONDO)
    ejes = [ejes] if len(niveles) == 1 else list(ejes)

    for ax, nivel in zip(ejes, niveles):
        sub = est[est["nivel"] == nivel]
        for r in sub.itertuples():
            # El orden importa: fondo, relleno, y el contorno hasta arriba.
            # Con el contorno relleno de blanco al final, el plano sale
            # vacío aunque la plaza esté al 89% — que fue el primer render.
            ax.add_patch(Rectangle((r.x, r.y), r.ancho, r.alto,
                                   facecolor="white", edgecolor="none",
                                   zorder=1))
            if r.ocupacion_pct > 0:
                ax.add_patch(Rectangle((r.x, r.y), r.ancho,
                                       r.alto * r.ocupacion_pct,
                                       facecolor=COLORES[r.estado],
                                       edgecolor="none", zorder=2))
            ax.add_patch(Rectangle((r.x, r.y), r.ancho, r.alto,
                                   facecolor="none", edgecolor=TINTA,
                                   linewidth=0.7, zorder=3))
        pct = sub["m2_ocupados"].sum() / sub["m2_totales"].sum()
        ax.set_title(f"{NIVELES_NOMBRE.get(nivel, nivel)} — {pct:.0%} ocupado",
                     fontsize=10, color=TINTA, loc="left")
        ax.set_xlim(sub["x"].min() - 4, (sub["x"] + sub["ancho"]).max() + 4)
        ax.set_ylim(sub["y"].min() - 3, (sub["y"] + sub["alto"]).max() + 3)
        ax.set_aspect("equal")
        ax.axis("off")
        ax.set_facecolor(FONDO)

    manijas = [Rectangle((0, 0), 1, 1, facecolor=c, edgecolor=TINTA,
                         linewidth=0.7)
               for c in (COLORES["libre"], COLORES["parcial"],
                         COLORES["ocupado"])]
    ejes[0].legend(manijas, ["Libre", "Compartido", "Ocupado"],
                   loc="upper right", fontsize=8, frameon=False, ncols=3,
                   bbox_to_anchor=(1.0, 1.32))

    fig.suptitle(f"{nombre_plaza(codigo)} — plano de ocupación",
                 fontsize=13, color=TINTA, x=0.09, ha="left")
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    fig.savefig(DOCS / "plano_ocupacion.png", dpi=150, facecolor=FONDO)
    plt.close(fig)
    print("  docs/plano_ocupacion.png")


def historia(cat, libro) -> None:
    serie = ocupacion.serie_ocupacion(cat, libro)
    rot = ocupacion.rotacion(libro)

    fig, (arriba, abajo) = plt.subplots(
        2, 1, figsize=(11, 6), sharex=True, facecolor=FONDO,
        gridspec_kw={"height_ratios": [2, 1]})

    for plaza, g in serie.groupby("plaza"):
        arriba.plot(g["fecha"], g["ocupacion"], linewidth=2,
                    label=nombre_plaza(plaza))
    arriba.set_ylim(0, 1)
    arriba.set_yticks([0, 0.25, 0.5, 0.75, 1.0])
    arriba.set_yticklabels(["0%", "25%", "50%", "75%", "100%"])
    arriba.set_title("Ocupación por metros, reconstruida del libro",
                     fontsize=12, color=TINTA, loc="left")
    arriba.legend(frameon=False, fontsize=9)
    arriba.grid(axis="y", alpha=0.25)

    abajo.bar(rot["mes"], rot["altas"], width=20, color="#2d7d46",
              label="Altas y expansiones")
    abajo.bar(rot["mes"], -rot["bajas"], width=20, color="#d7373f",
              label="Devoluciones")
    abajo.axhline(0, color=TINTA, linewidth=0.8)
    abajo.set_title("Asientos por mes", fontsize=11, color=TINTA, loc="left")
    abajo.legend(frameon=False, fontsize=9, ncols=2)
    abajo.grid(axis="y", alpha=0.25)

    for ax in (arriba, abajo):
        ax.set_facecolor(FONDO)
        for lado in ("top", "right"):
            ax.spines[lado].set_visible(False)

    fig.tight_layout()
    fig.savefig(DOCS / "ocupacion_historica.png", dpi=150, facecolor=FONDO)
    plt.close(fig)
    print("  docs/ocupacion_historica.png")


if __name__ == "__main__":
    print("Generando figuras…")
    cat, libro = generar()
    plano(cat, libro)
    historia(cat, libro)
