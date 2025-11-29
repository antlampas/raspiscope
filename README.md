# Raspiscope

### License
The project is released as free software under the Creative Commons Attribution-ShareAlike 4.0 International (CC BY-SA 4.0) license.

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

## Hardware

This dark chamber is the hardware companion to Raspiscope, the Raspberry Pi 4-based spectrophotometer that runs the software linked above. Every part is tuned for resin 3D printing to keep the optical path opaque and dimensionally accurate.

### Additional components
- **Bidirectional level shifter** to translate the Raspberry Pi 4 GPIO 3.3 V logic to the 5 V required by the LED and the Hall effect sensor ([Amazon link](https://www.amazon.it/Gebildet-Converter-Bi-Directional-Shifter-CYT1076/dp/B07RY15XMJ/ref=sr_1_2_sspa?__mk_it_IT=%C3%85M%C3%85%C5%BD%C3%95%C3%91&sr=8-2-spons&sp_csd=d2lkZ2V0TmFtZT1zcF9hdGY)).
- **12 V -> 5 V DC-DC converter** when powering the LED and sensor with eight AA batteries; otherwise rely on a dedicated 5 V power supply. You can tap the Raspberry Pi’s 5 V rail, but it often proves unstable for this load ([Amazon link](https://www.amazon.it/JZK-Convertitore-ultraridotto-regolabile-alimentazione/dp/B08HK6Z91G/ref=pd_ybh_a_d_sccl_8/261-7476846-8643263?psc=1)).
- **SS49E Hall effect sensor** to monitor the presence of the cuvette ([Amazon link](https://www.amazon.it/EPLZON-Rilevatore-magnetico-riparazione-confezione/dp/B0C7TF2QN7/ref=sr_1_1_sspa?__mk_it_IT=%C3%85M%C3%85%C5%BD%C3%95%C3%91&sr=8-1-spons&sp_csd=d2lkZ2V0TmFtZT1zcF9hdGY&psc=1)).
- **Diffraction grating** to decompose the light spectrum ([Amazon link](https://www.amazon.it/educative-diffrazione-trasmissione-strumento-disponibili/dp/B0FS6TSNWJ/ref=sr_1_3?__mk_it_IT=%C3%85M%C3%85%C5%BD%C3%95%C3%91&sr=8-3))
- **RGB LED** as light source ([Amazon link](https://www.amazon.it/BTF-LIGHTING-indirizzabili-individuali-dissipatore-incorporato/dp/B088K8DVMQ/ref=sr_1_6?__mk_it_IT=%C3%85M%C3%85%C5%BD%C3%95%C3%91&sr=8-6))
- **Raspberry Pi Camera V2 or V3** ([Amazon link](https://www.amazon.it/Raspberry-Pi-Modulo-NoIR-fotocamera/dp/B01ER2SMHY/ref=sr_1_1?__mk_it_IT=%C3%85M%C3%85%C5%BD%C3%95%C3%91&sr=8-1)) ([Amazon link](https://www.amazon.it/Raspberry-Pi-Camera-Module-NoIR/dp/B0BRY3L9H7/ref=sr_1_7?__mk_it_IT=%C3%85M%C3%85%C5%BD%C3%95%C3%91&sr=8-7))
- **Raspberry Pi** ([Amazon link](https://www.amazon.it/Raspberry-Starter-Alimentatore-Alloggiamento-dissipatore/dp/B0DZQQSK8C/ref=sr_1_1_sspa?__mk_it_IT=%C3%85M%C3%85%C5%BD%C3%95%C3%91&sr=8-1-spons&aref=Y3mbFXHpZ3&sp_csd=d2lkZ2V0TmFtZT1zcF9hdGY))

### Construction Schemes

![Schema Elettrico](./spectroscope/images/Schema%20Generale.png)
![Schema Visuale](./spectroscope/images/Schema%20Visuale.png)

### Images:

![Project Scheme 1](./spectroscope/images/spettro001.jpg)
![Project Scheme 2](./spectroscope/images/spettro002.jpg)
![Project Scheme 3](./spectroscope/images/spettro003.jpg)
![Project Scheme 4](./spectroscope/images/spettro004.jpg)
![Project Scheme 5](./spectroscope/images/spettro005.jpg)
![Project Scheme 6](./spectroscope/images/spettro006.jpg)
![Project Scheme 7](./spectroscope/images/spettro007.jpg)
![Project Scheme 8](./spectroscope/images/spettro008.jpg)

---
_If any section is unclear or missing, please provide feedback for further refinement._