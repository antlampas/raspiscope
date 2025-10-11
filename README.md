# Raspiscope Python Application
Thisi is a fork of antlampas/rapiscope-python original code.

# Instructions for Raspiscope Python Application

## Project Architecture
- **Modular Design:** Each hardware/software function (e.g., camera, light source, cuvette sensor, analysis, logger, GUI) is implemented as a separate module class (see `camera.py`, `lightSource.py`, etc.), inheriting from the abstract `Module` base class (`module.py`).
- **EventManager:** Central orchestrator (`eventManager.py`) runs as a process, routes messages between modules, and manages lifecycle (registration, shutdown, etc.).
- **Inter-Process Communication:** Modules communicate via message queues managed by the `Communicator` class. Messages are dictionaries with `Sender`, `Destination`, and `Message` (with `type` and `payload`).
- **Configuration:** All runtime configuration is loaded from `config.json` via `ConfigLoader`. Module enablement, hardware parameters, and network settings are defined here.
- **Startup:** `main.py` loads config, starts enabled modules as separate processes, and launches the EventManager. Shutdown is coordinated via signals.

## Developer Workflows
- **Unit Tests:** Located in `tests/unit/`. Each module has a corresponding test file. Run all tests with:
  ```powershell
  python -m unittest discover tests/unit
  ```
  Or run individual tests as in CI (`.github/workflows/unitTests.yml`).
- **Dependencies:** Install with `pip install -r requirements.txt`. Some modules require hardware-specific libraries (see `requirements.txt`).
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

ITALIANO

# Istruzioni per Copilot – Applicazione Python **Raspiscope**

## Architettura del Progetto
- **Design modulare:** Ogni funzione hardware/software (es. fotocamera, sorgente luminosa, sensore della cuvetta, analisi, logger, GUI) è implementata come classe modulo separata (vedi `camera.py`, `lightSource.py`, ecc.), che eredita dalla classe base astratta `Module` (`module.py`).
- **EventManager:** L’orchestratore centrale (`eventManager.py`) viene eseguito come processo, instrada i messaggi tra i moduli e gestisce il ciclo di vita (registrazione, arresto, ecc.).
- **Comunicazione inter‑processo:** I moduli comunicano tramite code di messaggi gestite dalla classe `Communicator`. I messaggi sono dizionari con `Sender`, `Destination` e `Message` (che contiene `type` e `payload`).
- **Configurazione:** Tutta la configurazione a runtime è caricata da `config.json` tramite `ConfigLoader`. L’abilitazione dei moduli, i parametri hardware e le impostazioni di rete sono definiti qui.
- **Avvio:** `main.py` carica la configurazione, avvia i moduli abilitati come processi separati e lancia l’EventManager. L’arresto è coordinato tramite segnali.

## Flussi di Lavoro per gli Sviluppatori
- **Test unitari:** In `tests/unit/`. Ogni modulo ha un file di test corrispondente. Per eseguire tutti i test:
  ```powershell
  python -m unittest discover tests/unit
  ```
  Oppure esegui test singoli come in CI (`.github/workflows/unitTests.yml`).

- **Dipendenze:** Installa con:
  ```bash
  pip install -r requirements.txt
  ```
  Alcuni moduli richiedono librerie specifiche per l’hardware (vedi `requirements.txt`).

- **Debug:** Ogni modulo effettua logging tramite il modulo Logger. Usa i messaggi di log per tracciare la comunicazione inter‑modulo e gli errori.

- **Modifiche di configurazione:** Modifica `config.json` per abilitare/disabilitare moduli o cambiare impostazioni hardware/rete. Riavvia l’app per applicare le modifiche.

## Pattern e Convenzioni
- **Instradamento dei messaggi:** Tutta la comunicazione tra moduli utilizza il pattern delle code di messaggi. Usa sempre `sendMessage(destination, msgType, payload)` dalla classe `Module`.
- **Hook di ciclo di vita:** I moduli sovrascrivono `onStart`, `mainLoop`, `handleMessage` e `onStop` per la logica personalizzata.
- **Registrazione:** I moduli si registrano con l’EventManager all’avvio inviando un messaggio `Register`.
- **Logging:** Usa il metodo `log(level, message)` per inviare log al modulo Logger. Evita `print`, tranne che per avvio/arresto.
- **Threading:** Ogni modulo esegue un proprio thread per la comunicazione. La logica principale gira in un processo separato.

## Punti di Integrazione
- **GUI Kivy:** Il modulo GUI (`gui.py`, `gui.kv`) usa Kivy per l’interfaccia utente. È avviato come modulo e comunica tramite lo stesso sistema di messaggistica.
- **Hardware:** I moduli GPIO, fotocamera e sensori usano librerie specifiche all’hardware (vedi `requirements.txt`).
- **Diagrammi:** I diagrammi di architettura e delle attività si trovano in `diagrams/`.

## Esempi
- **Aggiungere un nuovo modulo:** eredita da `Module`, implementa i metodi del ciclo di vita e aggiorna `main.py` e `config.json`.
- **Inviare un messaggio da un modulo:**
  ```python
  self.sendMessage("EventManager", "Register")
  self.sendMessage("Logger", "LogMessage", {"level": "INFO", "message": "Avviato"})
  ```

## File Chiave
- `main.py`: Avvio e orchestrazione dei processi
- `module.py`: Classe base per tutti i moduli
- `eventManager.py`: Router centrale dei messaggi
- `config.json`: Configurazione di moduli e sistema
- `requirements.txt`: Dipendenze Python
- `tests/unit/`: Test unitari per ogni modulo
- `diagrams/`: Diagrammi architetturali

---
_Se qualche sezione risulta poco chiara o mancante, lascia un commento per ulteriori miglioramenti._
