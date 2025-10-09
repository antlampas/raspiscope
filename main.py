"""
Author: Antlampas
CC BY-SA 4.0
https://creativecommons.org/licenses/by-sa/4.0/
"""

import sys
import signal
from multiprocessing import Process
from threading       import Thread

from eventManager    import EventManager
from configLoader    import ConfigLoader
from logger          import Logger
from lightSource     import LightSource
from cuvetteSensor   import CuvetteSensor
from camera          import Camera
from analysis        import Analysis
from cli             import CLI
from gui             import GUI

def main():
    """
    Main entry point of the application.
    Loads the configuration, starts all enabled modules in separate processes,
    and runs the EventManager in the main thread to coordinate them.
    """
    config_path = "config.json"
    if len(sys.argv) > 1:
        config_path = sys.argv[1]

    config_loader = ConfigLoader(config_path)
    config = config_loader.get_config()

    modules_to_start = {
        "logger"        : Logger,
        "lightSource"   : LightSource,
        "cuvetteSensor" : CuvetteSensor,
        "camera"        : Camera,
        "analysis"      : Analysis,
    }
    running_processes = []
    
    event_manager = EventManager(configPath=config_path)
    emProcess = Process(target=event_manager.run)
    emProcess.start()

    # Start each enabled module (except GUI) in its own process
    for name, module_class in modules_to_start.items():
        if name in config['modules'] and config['modules'][name].get('enabled', False):
            print(f"Starting module: {name}")
            module_config = config['modules'][name]
            network_config = config['network']
            system_config = config['system']
            
            instance = module_class(module_config, network_config, system_config)
            
            process = Process(target=instance.run)
            process.start()
            
            running_processes.append({'name': name, 'process': process})

    # Run GUI in the main process if it's enabled
    gui_instance = None
    if 'gui' in config['modules'] and config['modules']['gui'].get('enabled', False):
        print("Starting module: gui")
        module_config = config['modules']['gui']
        network_config = config['network']
        system_config = config['system']
        gui_instance = GUI(module_config, network_config, system_config)

    def shutdown(signum=None, frame=None):
        print("Shutdown signal received. Terminating all processes...")
        
        # Stop the GUI instance if it exists
        if gui_instance:
            gui_instance.stop()

        # Stop the EventManager
        event_manager.stop()
        
        # Terminate all child processes
        for p_info in running_processes:
            print(f"Terminating {p_info['name']}...")
            if p_info['process'].is_alive():
                p_info['process'].terminate()
                p_info['process'].join(timeout=5) # Add timeout
        
        # Wait for the EventManager process to finish
        if emProcess.is_alive():
            emProcess.join(timeout=5)

        print("All processes terminated. Exiting.")
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # Start the GUI, which will block the main thread
    if gui_instance:
        try:
            gui_instance.run()
        except KeyboardInterrupt:
            shutdown()
    else:
        # If GUI is not running, wait for the EventManager to finish
        if emProcess.is_alive():
            emProcess.join()

    # After the GUI closes or if it wasn't started, perform shutdown
    shutdown()

if __name__ == "__main__":
    main()
