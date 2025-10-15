"""
Author: Antlampas
CC BY-SA 4.0
https://creativecommons.org/licenses/by-sa/4.0/
"""

import base64
from io import BytesIO
from threading import Thread
from typing import Optional

import numpy
from kivy.app import App
from kivy.clock import Clock
from kivy.core.image import Image as CoreImage
from kivy.logger import Logger
from kivy.properties import ObjectProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.textinput import TextInput

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

    # Keep conversion consistent with Analysis.compareWithReferences assumptions.
    _PIXEL_TO_NM_FACTOR = 0.5
    _PIXEL_TO_NM_OFFSET = 400.0
    _SPEED_OF_LIGHT = 299_792_458.0  # m/s
    _NM_TO_M = 1e-9
    _THZ_SCALE = 1e12
    _DEFAULT_VISIBLE_RANGE_NM = (380.0, 780.0)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._figure = Figure(figsize=(5, 3), dpi=100)
        self._axes = self._figure.add_subplot(111)
        self._configure_axes()
        self._canvas = _PassiveFigureCanvas(self._figure)
        self.add_widget(self._canvas)
        self._draw_placeholder()

    @classmethod
    def _wavelength_nm_to_thz(cls, wavelength_nm: float) -> float:
        wavelength_m = wavelength_nm * cls._NM_TO_M
        return (cls._SPEED_OF_LIGHT / wavelength_m) / cls._THZ_SCALE

    def _configure_axes(self) -> None:
        self._axes.set_xlabel("Frequenza (THz)")
        self._axes.set_ylabel("Intensity")
        self._axes.set_title("Spettrogramma")
        self._axes.grid(True, alpha=0.2)

    def _default_xticks(self):
        high_thz = self._wavelength_nm_to_thz(self._DEFAULT_VISIBLE_RANGE_NM[0])
        low_thz = self._wavelength_nm_to_thz(self._DEFAULT_VISIBLE_RANGE_NM[1])
        tick_candidates = numpy.arange(400.0, 801.0, 50.0)
        mask = (tick_candidates <= high_thz) & (tick_candidates >= low_thz)
        ticks = tick_candidates[mask]
        return ticks.tolist() if ticks.size else []

    def _draw_placeholder(self) -> None:
        self._axes.clear()
        self._configure_axes()
        self._axes.text(
            0.5,
            0.5,
            "No data",
            ha="center",
            va="center",
            transform=self._axes.transAxes,
            fontsize=12,
        )
        default_ticks = self._default_xticks()
        if default_ticks:
            self._axes.set_xticks(default_ticks)
        low_thz = self._wavelength_nm_to_thz(self._DEFAULT_VISIBLE_RANGE_NM[1])
        high_thz = self._wavelength_nm_to_thz(self._DEFAULT_VISIBLE_RANGE_NM[0])
        self._axes.set_xlim(low_thz, high_thz)
        self._axes.set_yticks([])
        self._canvas.draw()

    def _compute_frequency_axis(self, length: int) -> numpy.ndarray:
        if length <= 0:
            return numpy.empty(0, dtype=float)
        indices = numpy.arange(length, dtype=float)
        wavelengths_nm = self._PIXEL_TO_NM_FACTOR * indices + self._PIXEL_TO_NM_OFFSET
        wavelengths_m = wavelengths_nm * self._NM_TO_M
        frequencies_thz = (self._SPEED_OF_LIGHT / wavelengths_m) / self._THZ_SCALE
        return frequencies_thz

    def _apply_frequency_ticks(self, freq_axis: numpy.ndarray) -> None:
        if freq_axis.size == 0:
            return
        min_thz = freq_axis.min()
        max_thz = freq_axis.max()
        tick_candidates = numpy.arange(400.0, 801.0, 50.0)
        mask = (tick_candidates >= min_thz) & (tick_candidates <= max_thz)
        ticks = tick_candidates[mask]
        if ticks.size:
            self._axes.set_xticks(ticks)
        else:
            self._axes.set_xticks(numpy.linspace(max_thz, min_thz, num=5))

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
            freq_axis = self._compute_frequency_axis(len(data))
            self._axes.plot(freq_axis, data, color="#1f77b4", linewidth=1.5)
            self._configure_axes()
            self._apply_frequency_ticks(freq_axis)
            if freq_axis.size:
                self._axes.set_xlim(freq_axis.min(), freq_axis.max())
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
                self.substances_label.text = f"Identified substances: {text}"
                return
        self.substances_label.text = "Identified substances: none"

    def show_analysis_error(self, message: str) -> None:
        self._ensure_references()
        if self.substances_label is None:
            return
        self.substances_label.text = f"Analysis error: {message}"

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
                Logger.warning(f"GUI: error while executing command '{command}': {exc}")
                response = f"Error while executing the command: {exc}"
        else:
            response = "Application not ready to execute commands."
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
        self._name_popup: Optional[Popup] = None
        self._name_input: Optional[TextInput] = None

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
            return "No command entered."
        key = normalized.replace(" ", "").lower()
        if key in {"help", "?"}:
            return "Available commands: takePicture, analyze, calibrateCamera, calibrateAnalysis, lightOn, lightOff, cuvetteAnalysis, cuvetteAddSubstance, cuvetteAdd"
        commands = {
            "analyze": ("Camera", "Analyze", "Analysis request sent to the camera module."),
            "analysis": ("Camera", "Analyze", "Analysis request sent to the camera module."),
            "calibratecamera": ("Camera", "Calibrate", "Camera calibration started."),
            "calibrateanalysis": ("Analysis", "Calibrate", "Analysis module calibration started."),
            "takepicture": ("Camera", "Take", "Image capture requested."),
            "lighton": ("LightSource", "TurnOn", "Light source turned on."),
            "lightoff": ("LightSource", "TurnOff", "Light source turned off."),
            "cuvetteanalysis": ("CuvetteSensor", "Analysis", "CuvetteSensor set to Analysis mode."),
            "cuvetteaddsubstance": ("CuvetteSensor", "AddSubstance", "CuvetteSensor set to AddSubstance mode."),
            "cuvetteadd": ("CuvetteSensor", "AddSubstance", "CuvetteSensor set to AddSubstance mode."),
        }
        action = commands.get(key)
        if action is None:
            return f"Unknown command: {command}"
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
                        lambda _dt, text=f"Error decoding the image: {exc}": self._append_cli_text(text),
                        0,
                    )
                else:
                    self.log("INFO", "Updating image")
                    Clock.schedule_once(lambda _dt, data=image_bytes: self._update_image(data))
                    Clock.schedule_once(
                        lambda _dt: self._append_cli_text("Image captured by the camera module."),
                        0,
                    )
            else:
                Clock.schedule_once(
                    lambda _dt: self._append_cli_text("No image provided by the camera module."),
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
            summary = ", ".join(summary_items) if summary_items else "no substances detected"
            Clock.schedule_once(
                lambda _dt, text=f"Analysis complete: {summary}": self._append_cli_text(text),
                0,
            )
        elif msg_type == "AnalysisError":
            error_message = payload.get("message") or payload.get("error") or "Unknown error"
            self.log("ERROR", error_message)
            Clock.schedule_once(lambda _dt, text=error_message: self._handle_analysis_error(text))
            Clock.schedule_once(
                lambda _dt, text=f"Analysis error: {error_message}": self._append_cli_text(text),
                0,
            )
        elif msg_type == "AnalysisCalibration":
            status = (payload or {}).get("status", "").lower()
            if status == "started":
                feedback = "Analysis calibration started."
                self.log("INFO", feedback)
            elif status == "completed":
                feedback = "Analysis calibration completed."
                self.log("INFO", feedback)
            elif status == "error":
                message = payload.get("message") or "Error during Analysis calibration."
                feedback = f"Analysis calibration failed: {message}"
                self.log("ERROR", feedback)
            else:
                feedback = f"Analysis calibration update: {payload}"
                self.log("INFO", feedback)
            Clock.schedule_once(lambda _dt, text=feedback: self._append_cli_text(text), 0)
        elif msg_type == "CameraError":
            error_message = payload.get("message") or payload.get("error") or "Unknown camera error"
            self.log("ERROR", f"Camera error: {error_message}")
            Clock.schedule_once(lambda _dt, text=error_message: self._append_cli_text(text), 0)
        elif msg_type == "RequestName":
            Clock.schedule_once(lambda _dt: self._show_substance_name_popup(), 0)

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

    def _show_substance_name_popup(self) -> None:
        if self._name_popup is not None:
            if self._name_popup.parent is None:
                self._name_popup.open()
            if self._name_input is not None:
                Clock.schedule_once(lambda _dt: setattr(self._name_input, "focus", True), 0)
            return

        layout = BoxLayout(orientation="vertical", spacing=10, padding=15)
        prompt = Label(text="Enter the substance name:", halign="center")
        prompt.bind(size=lambda _instance, _value: setattr(prompt, "text_size", prompt.size))
        name_input = TextInput(multiline=False)

        layout.add_widget(prompt)
        layout.add_widget(name_input)

        popup = Popup(
            title="New Substance",
            content=layout,
            size_hint=(0.5, 0.3),
            auto_dismiss=True,
        )

        def submit_name(_instance):
            name = (name_input.text or "").strip()
            if name:
                self.sendMessage("Analysis", "newSubstanceName", {"name": name})
                popup.dismiss()

        name_input.bind(on_text_validate=submit_name)
        popup.bind(on_dismiss=lambda *_args: self._cleanup_name_popup())

        self._name_popup = popup
        self._name_input = name_input

        popup.open()
        Clock.schedule_once(lambda _dt: setattr(name_input, "focus", True), 0)

    def _cleanup_name_popup(self) -> None:
        self._name_popup = None
        self._name_input = None
