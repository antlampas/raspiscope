# Raspiscope

## - ENGLISH

## Project Architecture
- **Modular Design:** Each hardware/software function (e.g., camera, light source, cuvette sensor, analysis, logger, GUI) is implemented as a separate module class (see `camera.py`, `lightSource.py`, etc.), inheriting from the abstract `Module` base class (`module.py`).
- **EventManager:** Central orchestrator (`eventManager.py`) runs as a process, routes messages between modules, and manages lifecycle (registration, shutdown, etc.).
- **Inter-Process Communication:** Modules communicate via message queues managed by the `Communicator` class. Messages are dictionaries with `Sender`, `Destination`, and `Message` (with `type` and `payload`).
- **Configuration:** All runtime configuration is loaded from `config.json` via `ConfigLoader`. Module enablement, hardware parameters, and network settings are defined here.
- **Startup:** `main.py` loads config, starts enabled modules as separate processes, and launches the EventManager. Shutdown is coordinated via signals.

## Developer Workflows
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

### License
The project is released as free software under the Creative Commons Attribution-ShareAlike 4.0 International (CC BY-SA 4.0) license.

---
## - ITALIANO

## Architettura del progetto
- **Progettazione modulare:** Ogni funzione hardware/software (ad es. camera, sorgente luminosa, sensore della cuvetta, analisi, logger, GUI) è implementata come classe modulo separata (vedi `camera.py`, `lightSource.py`, ecc.), che eredita dalla classe base astratta `Module` (`module.py`).
- **EventManager:** L'orchestratore centrale (`eventManager.py`) gira come processo, instrada i messaggi tra i moduli e gestisce il ciclo di vita (registrazione, spegnimento, ecc.).
- **Comunicazione inter-processo:** I moduli comunicano tramite code di messaggi gestite dalla classe `Communicator`. I messaggi sono dizionari con `Sender`, `Destination` e `Message` (con `type` e `payload`).
- **Configurazione:** Tutta la configurazione runtime è caricata da `config.json` tramite `ConfigLoader`. Qui sono definiti l'abilitazione dei moduli, i parametri hardware e le impostazioni di rete.
- **Avvio:** `main.py` carica la configurazione, avvia i moduli abilitati come processi separati e lancia l'EventManager. L'arresto è coordinato tramite segnali.

## Flussi di lavoro per sviluppatori
- **Dipendenze:** `apt install libcap-dev python3-dev qtbase5-dev python3-libcamera python3-kms++` `pip install -r requirements.txt`
- **Debug:** Ogni modulo registra tramite il modulo Logger. Usa i log per tracciare la comunicazione inter-modulo e gli errori.
- **Modifiche di configurazione:** Modifica `config.json` per abilitare/disabilitare i moduli o cambiare impostazioni hardware/rete. Riavvia l'app per applicare le modifiche.

## Pattern e convenzioni
- **Instradamento dei messaggi:** Tutta la comunicazione inter-modulo usa il pattern delle code di messaggi. Usa sempre `sendMessage(destination, msgType, payload)` da `Module`.
- **Hook del ciclo di vita:** I moduli sovrascrivono `onStart`, `mainLoop`, `handleMessage` e `onStop` per la logica personalizzata.
- **Registrazione:** I moduli si registrano con EventManager all'avvio inviando un messaggio `Register`.
- **Logging:** Usa `log(level, message)` per inviare i log al modulo Logger. Non stampare direttamente se non in avvio/spegnimento.
- **Threading:** Ogni modulo esegue il proprio thread per la comunicazione. La logica principale gira in un processo separato.

## Punti di integrazione
- **GUI Kivy:** Il modulo GUI (`gui.py`, `gui.kv`) usa Kivy per l'interfaccia utente. È avviato come modulo e comunica tramite lo stesso sistema di messaggi.
- **Hardware:** I moduli GPIO, camera e sensore usano librerie specifiche per l'hardware (vedi `requirements.txt`).
- **Diagrammi:** I diagrammi di architettura e attività sono in `diagrams/` come riferimento.

## Esempi
- Per aggiungere un nuovo modulo, eredita da `Module`, implementa i metodi di ciclo di vita e aggiorna `main.py` e `config.json`.
- Per inviare un messaggio da un modulo:
  ```python
  self.sendMessage("EventManager", "Register")
  self.sendMessage("Logger", "LogMessage", {"level": "INFO", "message": "Started"})
  ```

## File chiave
- `main.py`: Avvio e orchestrazione dei processi
- `module.py`: Classe base per tutti i moduli
- `eventManager.py`: Router centrale dei messaggi
- `config.json`: Configurazione per moduli e sistema
- `requirements.txt`: Dipendenze Python
- `tests/unit/`: Test unitari per ciascun modulo
- `diagrams/`: Diagrammi di architettura

## Hardware

Questa camera oscura è il compagno hardware di Raspiscope, lo spettrofotometro UV-Vis basato su Raspberry Pi 4 che esegue il software linkato sopra. Ogni parte è ottimizzata per la stampa 3D a resina per mantenere il cammino ottico opaco e dimensionalmente accurato.

### Componenti aggiuntivi
- **Traslatore di livello bidirezionale** per convertire la logica a 3,3 V dei GPIO del Raspberry Pi 4 ai 5 V richiesti dal LED e dal sensore di effetto Hall ([link Amazon](https://www.amazon.it/Gebildet-Converter-Bi-Directional-Shifter-CYT1076/dp/B07RY15XMJ/ref=sr_1_2_sspa?__mk_it_IT=%C3%85M%C3%85%C5%BD%C3%95%C3%91&sr=8-2-spons&sp_csd=d2lkZ2V0TmFtZT1zcF9hdGY)).
- **Convertitore DC-DC 12 V -> 5 V** quando si alimentano LED e sensore con otto batterie AA; altrimenti affidarsi a un'alimentazione dedicata da 5 V. È possibile prelevare la linea da 5 V del Raspberry Pi, ma spesso risulta instabile per questo carico ([link Amazon](https://www.amazon.it/JZK-Convertitore-ultraridotto-regolabile-alimentazione/dp/B08HK6Z91G/ref=pd_ybh_a_d_sccl_8/261-7476846-8643263?psc=1)).
- **Sensore di effetto Hall SS49E** per monitorare la presenza della cuvetta ([link Amazon](https://www.amazon.it/EPLZON-Rilevatore-magnetico-riparazione-confezione/dp/B0C7TF2QN7/ref=sr_1_1_sspa?__mk_it_IT=%C3%85M%C3%85%C5%BD%C3%95%C3%91&sr=8-1-spons&sp_csd=d2lkZ2V0TmFtZT1zcF9hdGY&psc=1)).
- **Reticolo di diffrazione** per scomporre lo spettro luminoso ([link Amazon](https://www.amazon.it/educative-diffrazione-trasmissione-strumento-disponibili/dp/B0FS6TSNWJ/ref=sr_1_3?__mk_it_IT=%C3%85M%C3%85%C5%BD%C3%95%C3%91&sr=8-3))
- **LED RGB** come sorgente luminosa ([link Amazon](https://www.amazon.it/BTF-LIGHTING-indirizzabili-individuali-dissipatore-incorporato/dp/B088K8DVMQ/ref=sr_1_6?__mk_it_IT=%C3%85M%C3%85%C5%BD%C3%95%C3%91&sr=8-6))
- **Raspberry Pi Camera V2 o V3** ([link Amazon](https://www.amazon.it/Raspberry-Pi-Modulo-NoIR-fotocamera/dp/B01ER2SMHY/ref=sr_1_1?__mk_it_IT=%C3%85M%C3%85%C5%BD%C3%95%C3%91&sr=8-1)) ([link Amazon](https://www.amazon.it/Raspberry-Pi-Camera-Module-NoIR/dp/B0BRY3L9H7/ref=sr_1_7?__mk_it_IT=%C3%85M%C3%85%C5%BD%C3%95%C3%91&sr=8-7))
- **Raspberry Pi** ([link Amazon](https://www.amazon.it/Raspberry-Starter-Alimentatore-Alloggiamento-dissipatore/dp/B0DZQQSK8C/ref=sr_1_1_sspa?__mk_it_IT=%C3%85M%C3%85%C5%BD%C3%95%C3%91&sr=8-1-spons&aref=Y3mbFXHpZ3&sp_csd=d2lkZ2V0TmFtZT1zcF9hdGY))

### Licenza
Il progetto è rilasciato come software libero sotto la licenza Creative Commons Attribution-ShareAlike 4.0 International (CC BY-SA 4.0).

---

![Electrical Scheme](./spectroscope/images/Schema%20Generale.png)
![Visual Scheme](./spectroscope/images/Schema%20Visuale.png)

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