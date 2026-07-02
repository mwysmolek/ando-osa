"""Application entry point: ``python -m ando_osa`` or the ``ando-osa`` script."""

import logging
import sys

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import QApplication
from matplotlib import style


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )

    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    dpi = app.primaryScreen().logicalDotsPerInch()
    font = QFont()
    font.setPointSizeF(10.0 * dpi / 96.0)
    app.setFont(font)

    style.use("dark_background")

    from .gui import SpectrometerGUI
    gui = SpectrometerGUI()
    gui.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
