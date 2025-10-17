# Raspiscope Python Application
## Downlod the 3D files for FreeCAD Software.
[click here](https://github.com/antlampas/raspiscope-spectroscope)

## Project Architecture
- **Modular Design:** Each hardware/software function (e.g., camera, light source, cuvette sensor, analysis, logger, GUI) is implemented as a separate module class (see `camera.py`, `lightSource.py`, etc.), inheriting from the abstract `Module` base class (`module.py`).
- **EventManager:** Central orchestrator (`eventManager.py`) runs as a process, routes messages between modules, and manages lifecycle (registration, shutdown, etc.).
- **Inter-Process Communication:** Modules communicate via message queues managed by the `Communicator` class. Messages are dictionaries with `Sender`, `Destination`, and `Message` (with `type` and `payload`).
- **Configuration:** All runtime configuration is loaded from `config.json` via `ConfigLoader`. Module enablement, hardware parameters, and network settings are defined here.
- **Startup:** `main.py` loads config, starts enabled modules as separate processes, and launches the EventManager. Shutdown is coordinated via signals.

## Developer Workflows
- **Unit Tests:** Located in `tests/unit/`. Each module has a corresponding test file. Run all tests with:
  ```python -m unittest discover tests/unit```
  Or run individual tests as in CI (`.github/workflows/unitTests.yml`).
- **Dependencies:** `apt install libcap-dev python3-dev qtbase5-dev python3-libcamera python3-kms++` `pip install -r requirements.txt`
- **Debugging:** Each module logs via the Logger module. Use log messages for tracing inter-module communication and errors.
- **Configuration Changes:** Edit `config.json` to enable/disable modules or change hardware/network settings. Restart the app to apply changes.

## Patterns & Conventions
- **Message Routing:** All inter-module communication uses the message queue pattern. Always use `sendMessage(destination, msgType, payload)` from `Module`.
- **Lifecycle Hooks:** Modules override `onStart`, `mainLoop`, `handleMessage`, and `onStop` for custom logic.
- **Registration:** Modules register with EventManager on startup by sending a `Register` message.
- **Logging:** Use the `log(level, message)` method to send logs to the Logger module. Do not print directly except for startup/shutdown.
- **Threading:** Each module runs its own thread for communication. Main logic runs in a separate process.

## Integration Points
- **Kivy GUI:** The GUI module (`gui.py`, `gui.kv`) uses Kivy for the user interface. It is started as a module and communicates via the same message system.
- **Hardware:** GPIO, camera, and sensor modules use hardware-specific libraries (see `requirements.txt`).
- **Diagrams:** Architecture and activity diagrams are in `diagrams/` for reference.

## Examples
- To add a new module, inherit from `Module`, implement lifecycle methods, and update `main.py` and `config.json`.
- To send a message from a module:
  ```python
  self.sendMessage("EventManager", "Register")
  self.sendMessage("Logger", "LogMessage", {"level": "INFO", "message": "Started"})
  ```

## Key Files
- `main.py`: Startup and process orchestration
- `module.py`: Base class for all modules
- `eventManager.py`: Central message router
- `config.json`: Configuration for modules and system
- `requirements.txt`: Python dependencies
- `tests/unit/`: Unit tests for each module
- `diagrams/`: Architecture diagrams

---
_If any section is unclear or missing, please provide feedback for further refinement._

ITALIAN (Translated to English)

This section retains the structure of the original Italian walkthrough, now rendered in English for consistency.

## Project Architecture
- **Modular design:** Every hardware or software capability (camera, light source, cuvette sensor, analysis, logger, GUI) lives in its own module class (see `camera.py`, `lightSource.py`, etc.) that subclasses the abstract `Module` base (`module.py`).
- **EventManager:** The central orchestrator (`eventManager.py`) runs as a standalone process, routes messages among modules, and manages lifecycle events such as registration and shutdown.
- **Inter-process communication:** Modules talk through message queues handled by the `Communicator` class. Each message is a dictionary with `Sender`, `Destination`, and a `Message` payload containing `type` and `payload`.
- **Configuration:** Runtime settings come from `config.json` via `ConfigLoader`, covering module enablement, hardware parameters, and networking details.
- **Startup:** `main.py` loads the configuration, launches enabled modules as separate processes, and starts the EventManager; shutdown is coordinated via signals.

## Developer Workflows
- **Unit tests:** Located in `tests/unit/`. Each module has a dedicated test file. Run the full suite with:
  ```python -m unittest discover tests/unit```
  or execute individual tests as configured in CI (`.github/workflows/unitTests.yml`).
- **Dependencies:** `apt install libcap-dev python3-dev qtbase5-dev python3-libcamera` `pip install -r requirements.txt`
- **Debugging:** Every module emits logs through the Logger module. Use those messages to trace inter-module communication and diagnose issues.
- **Configuration changes:** Edit `config.json` to toggle modules or tweak hardware/network settings. Restart the app to apply updates.

## Patterns & Conventions
- **Message routing:** All inter-module communication leverages the message queue pattern; always call `sendMessage(destination, msgType, payload)` from `Module`.
- **Lifecycle hooks:** Modules override `onStart`, `mainLoop`, `handleMessage`, and `onStop` to provide their behaviour.
- **Registration:** Modules register with the EventManager at startup by sending a `Register` message.
- **Logging:** Prefer `log(level, message)` to forward logs to the Logger module; avoid `print` except during startup/shutdown.
- **Threading:** Each module owns a communication thread, while its main logic runs in a separate process.

## Integration Points
- **Kivy GUI:** The GUI module (`gui.py`, `gui.kv`) builds the user interface with Kivy and communicates through the same messaging system.
- **Hardware:** GPIO, camera, and sensor modules rely on hardware-specific libraries (see `requirements.txt`).
- **Diagrams:** Architecture and activity diagrams are stored in `diagrams/`.

## Examples
- **Adding a new module:** Subclass `Module`, implement the lifecycle methods, and update both `main.py` and `config.json`.
- **Sending a message from a module:**
  ```python
  self.sendMessage("EventManager", "Register")
  self.sendMessage("Logger", "LogMessage", {"level": "INFO", "message": "Started"})
  ```

## Key Files
- `main.py`: Startup and process orchestration
- `module.py`: Base class for every module
- `eventManager.py`: Central message router
- `config.json`: Module and system configuration
- `requirements.txt`: Python dependencies
- `tests/unit/`: Unit tests for each module
- `diagrams/`: Architecture diagrams

---
_If any section still feels unclear or incomplete, please leave a comment so we can improve it further._
