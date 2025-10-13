"""
Author: Antlampas
CC BY-SA 4.0
https://creativecommons.org/licenses/by-sa/4.0/
"""

import base64
from io import BytesIO
from threading import Thread
from typing import Optional

from kivy.app import App
from kivy.clock import Clock
from kivy.core.image import Image as CoreImage
from kivy.logger import Logger
from kivy.properties import ObjectProperty
from kivy.uix.boxlayout import BoxLayout

from matplotlib.figure import Figure
from matplotlib.backend_bases import TimerBase
from kivy_garden.matplotlib.backend_kivyagg import FigureCanvasKivyAgg

from module import Module
from configLoader import ConfigLoader


class _PassiveTimer(TimerBase):
    """Matplotlib timer that never schedules work on the Kivy Clock."""

    def _timer_start(self):
        return None

    def _timer_stop(self):
        return None

    def _timer_set_interval(self):
        return None


class _PassiveFigureCanvas(FigureCanvasKivyAgg):
    """Figure canvas that disables Matplotlib's periodic timers."""

    def new_timer(self, *args, **kwargs):
        return _PassiveTimer(*args, **kwargs)


class SpectrogramGraph(BoxLayout):
    """Widget that renders spectrogram data using Matplotlib."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._figure = Figure(figsize=(5, 3), dpi=100)
        self._axes = self._figure.add_subplot(111)
        self._configure_axes()
        self._canvas = _PassiveFigureCanvas(self._figure)
        self.add_widget(self._canvas)
        self._draw_placeholder()

    def _configure_axes(self) -> None:
        self._axes.set_xlabel("Frequenza (Hz)")
        self._axes.set_ylabel("Intensità")
        self._axes.set_title("Spettrogramma")
        self._axes.grid(True, alpha=0.2)

    def _draw_placeholder(self) -> None:
        self._axes.clear()
        self._configure_axes()
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
        self._canvas.draw()

    def update_data(self, values) -> None:
        self._axes.clear()
        if values is None:
            self._draw_placeholder()
            return
        try:
            data = list(values)
        except TypeError:
            Logger.warning("GUI: spectrogram data is not iterable")
            self._draw_placeholder()
            return
        if not data:
            self._draw_placeholder()
            return
        try:
            x_values = list(range(len(data)))
            self._axes.plot(x_values, data, color="#1f77b4", linewidth=1.5)
            self._configure_axes()
        except Exception as exc:
            Logger.warning(f"GUI: failed to draw spectrogram: {exc}")
            self._draw_placeholder()
            return
        self._figure.tight_layout()
        self._canvas.draw()


class MainLayout(BoxLayout):
    """Root layout for the GUI.

    Holds the captured image, spectrogram data, identified substances labels, and CLI panel.
    """

    camera_pane = ObjectProperty(None)
    camera_image = ObjectProperty(None)
    spectrogram_graph = ObjectProperty(None)
    substances_label = ObjectProperty(None)
    cli_pane = ObjectProperty(None)
    cli_history_label = ObjectProperty(None)
    cli_input = ObjectProperty(None)
    cli_scroll = ObjectProperty(None)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._core_image_ref: Optional[CoreImage] = None

    def on_kv_post(self, base_widget):
        super().on_kv_post(base_widget)
        self._ensure_references()
        Clock.schedule_once(lambda _dt: self._focus_cli_input(), 0)

    def _ensure_references(self) -> None:
        if self.camera_pane is None:
            self.camera_pane = self.ids.get("camera_pane")
        if self.camera_image is None and self.camera_pane is not None:
            self.camera_image = getattr(self.camera_pane, "ids", {}).get("camera_image")
        spectrogram_pane = self.ids.get("spectrogram_pane")
        if self.spectrogram_graph is None and spectrogram_pane is not None:
            self.spectrogram_graph = getattr(spectrogram_pane, "ids", {}).get("spectrogram_graph")
        if self.substances_label is None and spectrogram_pane is not None:
            self.substances_label = getattr(spectrogram_pane, "ids", {}).get("substances_label")
        if self.cli_pane is None:
            self.cli_pane = self.ids.get("cli_pane")
        if self.cli_pane is not None:
            pane_ids = getattr(self.cli_pane, "ids", {})
            if self.cli_history_label is None:
                self.cli_history_label = pane_ids.get("cli_history")
            if self.cli_input is None:
                self.cli_input = pane_ids.get("cli_input")
            if self.cli_scroll is None:
                self.cli_scroll = pane_ids.get("cli_scroll")

    def set_image_from_bytes(self, image_bytes: bytes) -> None:
        """Decode JPEG bytes and update the image texture."""
        self._ensure_references()
        if self.camera_image is None:
            return
        if not image_bytes:
            self.camera_image.texture = None
            self._core_image_ref = None
            return
        try:
            data_stream = BytesIO(image_bytes)
            core_image = CoreImage(data_stream, ext="jpg")
        except Exception as exc:  # pragma: no cover
            Logger.warning(f"GUI: unable to load image bytes: {exc}")
            return
        self._core_image_ref = core_image
        self.camera_image.texture = core_image.texture

    def update_spectrogram(self, spectrogram_data) -> None:
        self._ensure_references()
        if self.spectrogram_graph is None:
            return
        self.spectrogram_graph.update_data(spectrogram_data)

    def update_substances(self, substances) -> None:
        self._ensure_references()
        if self.substances_label is None:
            return
        if substances:
            text = ", ".join(str(item) for item in substances if item)
            if text:
                self.substances_label.text = f"Sostanze riconosciute: {text}"
                return
        self.substances_label.text = "Sostanze riconosciute: nessuna"

    def show_analysis_error(self, message: str) -> None:
        self._ensure_references()
        if self.substances_label is None:
            return
        self.substances_label.text = f"Errore analisi: {message}"

    def append_cli_output(self, text: str) -> None:
        self._ensure_references()
        if self.cli_history_label is None or text is None:
            return
        rendered = str(text)
        existing = self.cli_history_label.text
        self.cli_history_label.text = f"{existing}\n{rendered}" if existing else rendered
        Clock.schedule_once(lambda _dt: self._scroll_cli_to_bottom(), 0)

    def clear_cli_history(self) -> None:
        self._ensure_references()
        if self.cli_history_label is None:
            return
        self.cli_history_label.text = ""
        self._focus_cli_input()

    def _focus_cli_input(self) -> None:
        self._ensure_references()
        if self.cli_input is not None:
            self.cli_input.focus = True

    def _scroll_cli_to_bottom(self) -> None:
        self._ensure_references()
        if self.cli_history_label is not None:
            self.cli_history_label.texture_update()
        if self.cli_scroll is not None:
            self.cli_scroll.scroll_y = 0

    def submit_cli_command(self, raw_command: str) -> None:
        self._ensure_references()
        command = (raw_command or "").strip()
        if self.cli_input is not None:
            self.cli_input.text = ""
        if not command:
            self._focus_cli_input()
            return
        self.append_cli_output(f"> {command}")
        app = App.get_running_app()
        response = None
        if hasattr(app, "process_cli_command"):
            try:
                response = app.process_cli_command(command)
            except Exception as exc:  # pragma: no cover
                Logger.warning(f"GUI: errore nell'esecuzione del comando '{command}': {exc}")
                response = f"Errore durante l'esecuzione del comando: {exc}"
        else:
            response = "Applicazione non pronta per eseguire comandi."
        if response:
            self.append_cli_output(response)
        Clock.schedule_once(lambda _dt: self._focus_cli_input(), 0)


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
        self.sendMessage("EventManager", "Register")
        if self._stop_observer is None:
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

    def _check_stop_event(self, _dt):
        if self.stopEvent.is_set():
            if self._stop_observer is not None:
                self._stop_observer.cancel()
                self._stop_observer = None
            App.stop(self)
            return False
        return True

    def _append_cli_text(self, text: str) -> None:
        if self.main_layout is None:
            return
        self.main_layout.append_cli_output(text)

    def process_cli_command(self, command: str) -> str:
        normalized = (command or "").strip()
        if not normalized:
            return "Nessun comando inserito."
        key = normalized.replace(" ", "").lower()
        if key in {"help", "?"}:
            return "Comandi disponibili: takePicture, analyze, CalibrateCamera, CalibrateCuvette, lightOn, lightOff"
        commands = {
            "analyze": ("Camera", "Analyze", "Richiesta di analisi inviata al modulo camera."),
            "analysis": ("Camera", "Analyze", "Richiesta di analisi inviata al modulo camera."),
            "calibratecamera": ("Camera", "Calibrate", "Calibrazione della camera avviata."),
            "takepicture": ("Camera", "Take", "Richiesta di acquisizione immagine"),
            "lighton": ("LightSource", "TurnOn", "Sorgente luminosa accesa."),
            "lightoff": ("LightSource", "TurnOff", "Sorgente luminosa spenta."),
        }
        action = commands.get(key)
        if action is None:
            return f"Comando sconosciuto: {command}"
        destination, message_type, feedback = action
        self.sendMessage(destination, message_type)
        return feedback

    def handleMessage(self, message):
        msg = message.get("Message", {})
        msg_type = msg.get("type")
        payload = msg.get("payload", {})
        if msg_type == "PictureTaken":
            self.log("INFO", "Picture taken")
            image_b64 = payload.get("image")
            if image_b64:
                try:
                    image_bytes = base64.b64decode(image_b64)
                except (ValueError, TypeError) as exc:
                    self.log("ERROR", f"Failed to decode image: {exc}")
                    Clock.schedule_once(
                        lambda _dt, text=f"Errore nel decodificare l'immagine: {exc}": self._append_cli_text(text),
                        0,
                    )
                else:
                    self.log("INFO", "Updating image")
                    Clock.schedule_once(lambda _dt, data=image_bytes: self._update_image(data))
                    Clock.schedule_once(
                        lambda _dt: self._append_cli_text("Immagine acquisita dal modulo camera."),
                        0,
                    )
            else:
                Clock.schedule_once(
                    lambda _dt: self._append_cli_text("Nessuna immagine fornita dal modulo camera."),
                    0,
                )
        elif msg_type == "AnalysisComplete":
            self.log("INFO", "Analysis complete")
            spectrogram = payload.get("spectrogram_data") or []
            substances_payload = payload.get("identified_substances")
            if isinstance(substances_payload, (list, tuple, set)):
                substances = list(substances_payload)
            elif substances_payload:
                substances = [substances_payload]
            else:
                substances = []
            Clock.schedule_once(
                lambda _dt, data=spectrogram, labels=substances: self._apply_analysis_results(data, labels)
            )
            summary_items = [str(item) for item in substances if item]
            summary = ", ".join(summary_items) if summary_items else "nessuna sostanza rilevata"
            Clock.schedule_once(
                lambda _dt, text=f"Analisi completata: {summary}": self._append_cli_text(text),
                0,
            )
        elif msg_type == "AnalysisError":
            error_message = payload.get("message") or payload.get("error") or "Errore sconosciuto"
            self.log("ERROR", error_message)
            Clock.schedule_once(lambda _dt, text=error_message: self._handle_analysis_error(text))
            Clock.schedule_once(
                lambda _dt, text=f"Errore analisi: {error_message}": self._append_cli_text(text),
                0,
            )
        elif msg_type == "CameraError":
            error_message = payload.get("message") or payload.get("error") or "Errore sconosciuto dalla camera"
            self.log("ERROR", f"Camera error: {error_message}")
            Clock.schedule_once(lambda _dt, text=error_message: self._append_cli_text(text), 0)

    def _update_image(self, image_bytes: bytes) -> None:
        if self.main_layout is None:
            return
        self.main_layout.set_image_from_bytes(image_bytes)

    def _apply_analysis_results(self, spectrogram_data, substances) -> None:
        if self.main_layout is None:
            return
        data_list = list(spectrogram_data) if spectrogram_data is not None else []
        substances_list = list(substances) if substances is not None else []
        self.main_layout.update_spectrogram(data_list)
        self.main_layout.update_substances(substances_list)

    def _handle_analysis_error(self, message: str) -> None:
        if self.main_layout is None:
            return
        self.main_layout.show_analysis_error(message)
