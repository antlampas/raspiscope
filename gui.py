"""
Author: Antlampas
CC BY-SA 4.0
https://creativecommons.org/licenses/by-sa/4.0/
"""

from pathlib   import Path
from kivy.lang import Builder

import base64
from io import BytesIO
from threading import Thread
from typing import Optional

from kivy.app import App
from kivy.clock import Clock
from kivy.core.image import Image as CoreImage
from kivy.logger import Logger
from kivy.properties import ListProperty, ObjectProperty, StringProperty
from kivy.uix.boxlayout import BoxLayout

from matplotlib.figure import Figure
from kivy_garden.matplotlib.backend_kivyagg import FigureCanvasKivyAgg

from module import Module
from configLoader import ConfigLoader


class SpectrogramGraph(BoxLayout):
    """Widget that renders spectrogram data using Matplotlib."""

    spectrogram_data = ListProperty([])

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self._figure = Figure(figsize=(5, 3), dpi=100)
        self._axes = self._figure.add_subplot(111)
        self._axes.set_xlabel("Pixel")
        self._axes.set_ylabel("Intensità")
        self._axes.set_title("Spettrogramma")
        self._axes.grid(True, alpha=0.2)

        self._canvas = FigureCanvasKivyAgg(self._figure)
        self.add_widget(self._canvas)

        self._draw_placeholder()

    def _draw_placeholder(self) -> None:
        self._axes.clear()
        self._axes.text(
            0.5,
            0.5,
            "Nessun dato",
            ha="center",
            va="center",
            transform=self._axes.transAxes,
            fontsize=12,
        )
        self._axes.set_xticks([])
        self._axes.set_yticks([])
        self._axes.set_title("Spettrogramma")
        self._canvas.draw()

    def on_spectrogram_data(self, instance, value):  # pylint: disable=unused-argument
        self._axes.clear()
        if value:
            try:
                x_values = list(range(len(value)))
                self._axes.plot(x_values, value, color="#1f77b4", linewidth=1.5)
                self._axes.set_xlabel("Pixel")
                self._axes.set_ylabel("Intensità")
                self._axes.set_title("Spettrogramma")
                self._axes.grid(True, alpha=0.2)
            except Exception as exc:  # pragma: no cover
                Logger.warning(f"GUI: failed to draw spectrogram: {exc}")
                self._draw_placeholder()
                return
        else:
            self._draw_placeholder()
            return

        self._figure.tight_layout()
        self._canvas.draw()


class MainLayout(BoxLayout):
    """Root layout for the GUI.

    Holds the captured image, spectrogram data, and identified substances labels.
    """

    image_texture = ObjectProperty(None, allownone=True)
    spectrogram_data = ListProperty([])
    identified_substances = ListProperty([])
    substances_text = StringProperty("Sostanze riconosciute: nessuna")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._core_image_ref: Optional[CoreImage] = None

    def set_image_from_bytes(self, image_bytes: bytes) -> None:
        """Decode JPEG bytes and update the image texture."""
        if not image_bytes:
            self.image_texture = None
            self._core_image_ref = None
            return

        try:
            data_stream = BytesIO(image_bytes)
            core_image = CoreImage(data_stream, ext="jpg")
        except Exception as exc:  # pragma: no cover
            Logger.warning(f"GUI: unable to load image bytes: {exc}")
            return

        self._core_image_ref = core_image
        self.image_texture = core_image.texture

    def on_identified_substances(self, instance, value):  # pylint: disable=unused-argument
        if value:
            self.substances_text = "Sostanze riconosciute: " + ", ".join(value)
        else:
            self.substances_text = "Sostanze riconosciute: nessuna"


class GUI(Module, App):
    """Graphical user interface module combining Kivy and the IPC Module base."""

    def __init__(self, moduleConfig, networkConfig, systemConfig, configPath="config.json"):
        if moduleConfig is None or networkConfig is None or systemConfig is None:
            loader = ConfigLoader(configPath)
            full_config = loader.get_config()
            moduleConfig = moduleConfig or full_config.get("modules", {}).get("gui", {})
            networkConfig = networkConfig or full_config.get("network", {})
            systemConfig = systemConfig or full_config.get("system", {})

        Module.__init__(self, "GUI", networkConfig, systemConfig)
        App.__init__(self)

        self.config = moduleConfig or {}
        self._message_thread: Optional[Thread] = None
        self._stop_observer = None
        self.main_layout: Optional[MainLayout] = None

    def build(self):
        self.main_layout = MainLayout()
        return self.main_layout

    def on_start(self):
        self._stop_observer = Clock.schedule_interval(self._check_stop_event, 0.2)

    def on_stop(self):
        self.stopEvent.set()
        if self._stop_observer is not None:
            self._stop_observer.cancel()
            self._stop_observer = None

    def run(self):
        self.log("INFO", "GUI module starting.")

        communicator_thread = Thread(target=self.communicator.run, args=(self.stopEvent,), daemon=True)
        communicator_thread.start()

        self.onStart()

        self._message_thread = Thread(target=self.mainLoop, daemon=True)
        self._message_thread.start()

        try:
            App.run(self)
        finally:
            self.stopEvent.set()

            if self._message_thread and self._message_thread.is_alive():
                self._message_thread.join(timeout=1)

            if communicator_thread.is_alive():
                communicator_thread.join(timeout=1)

            self.onStop()
            self.log("INFO", "GUI module terminated.")

    def onStart(self):
        self.sendMessage("EventManager", "Register")

    def onStop(self):
        """Called when the module is asked to terminate."""
        pass

    def _check_stop_event(self, _dt):
        if self.stopEvent.is_set():
            if self._stop_observer is not None:
                self._stop_observer.cancel()
                self._stop_observer = None
            if self._running:
                App.stop(self)
            return False
        return True

    def handleMessage(self, message):
        msg = message.get("Message", {})
        msg_type = msg.get("type")
        payload = msg.get("payload", {})

        if msg_type == "PictureTaken":
            image_b64 = payload.get("image")
            if image_b64:
                try:
                    image_bytes = base64.b64decode(image_b64)
                except (ValueError, TypeError) as exc:
                    self.log("ERROR", f"Failed to decode image: {exc}")
                else:
                    Clock.schedule_once(lambda _dt, data=image_bytes: self._update_image(data))
        elif msg_type == "AnalysisComplete":
            spectrogram = payload.get("spectrogram_data") or []
            substances = payload.get("identified_substances") or []
            Clock.schedule_once(
                lambda _dt, data=spectrogram, labels=substances: self._apply_analysis_results(data, labels)
            )
        elif msg_type == "AnalysisError":
            error_message = payload.get("message") or payload.get("error") or "Errore sconosciuto"
            Clock.schedule_once(lambda _dt, text=error_message: self._handle_analysis_error(text))

    def _update_image(self, image_bytes: bytes) -> None:
        if self.main_layout is not None:
            self.main_layout.set_image_from_bytes(image_bytes)

    def _apply_analysis_results(self, spectrogram_data, substances) -> None:
        if self.main_layout is None:
            return
        try:
            self.main_layout.spectrogram_data = list(spectrogram_data)
        except TypeError:
            self.main_layout.spectrogram_data = []
        self.main_layout.identified_substances = list(substances)

    def _handle_analysis_error(self, message: str) -> None:
        if self.main_layout is None:
            return
        self.main_layout.substances_text = f"Errore analisi: {message}"

