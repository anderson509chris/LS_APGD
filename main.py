# main.py
# LS-APGD Control Application
# initialises hardware and serial connections,
# then hands control to the GUI.
#
# Folder layout expected on the Pi:
#   ~/LSAPGD/
#       main.py
#       hardware.py
#       pump.py
#       gas.py
#       settings_manager.py
#       gui_pages.py
#       dialogs.py
#
# Run with:
#   cd ~/LSAPGD
#   python3 main.py

import sys
import tkinter as tk
import tkinter.messagebox as msgbox

import hardware
import pump as pump_module
import gas as gas_module
from gui_pages import App

from hardware import SensorPoller

def show_startup_error(title, message):
    """Display a simple error dialog before the main window opens."""
    root = tk.Tk()
    root.withdraw()
    msgbox.showerror(title, message)
    root.destroy()


def main():
    # ------------------------------------------------------------------
    # 1. Initialise all hardware (GPIO, PWM, I2C, ADC)
    # ------------------------------------------------------------------
    try:
        hardware.hardware_setup()
        sensor_poller = SensorPoller()
        sensor_poller.start()
    except RuntimeError as e:
        # pigpio daemon not running is the most common cause
        show_startup_error("Hardware Error", str(e))
        sys.exit(1)
    except Exception as e:
        show_startup_error("Hardware Error",
                           f"Failed to initialise hardware:\n{e}\n\n"
                           "Check connections and try again.")
        sys.exit(1)

    # ------------------------------------------------------------------
    # 2. Open serial connections
    # ------------------------------------------------------------------
    pump_serial = None
    gas_serial  = None

    try:
        pump_serial = pump_module.open_pump(port="/dev/ttyUSB0", baudrate=38400)
    except Exception as e:
        show_startup_error("ERROR 2 – Syringe Pump",
                           f"Cannot open pump serial port:\n{e}\n\n"
                           "Check USB connection and port name.")
        hardware.hardware_cleanup()
        sys.exit(1)

    try:
        gas_serial = gas_module.open_gas_valve(port="/dev/ttyAMA0", baudrate=38400)
    except Exception as e:
        show_startup_error("ERROR 1 – Gas Valve",
                           f"Cannot open gas valve serial port:\n{e}\n\n"
                           "Check connection and port name.")
        pump_module.close_pump(pump_serial)
        sys.exit(1)

    # ------------------------------------------------------------------
    # 3. Send initialisation commands to peripherals
    # ------------------------------------------------------------------
    try:
        pump_module.initialise_pump(pump_serial)
        gas_module.initialise_gas_valve(gas_serial)
    except Exception as e:
        show_startup_error("Initialisation Error",
                           f"Failed to initialise peripherals:\n{e}")
        pump_module.close_pump(pump_serial)
        gas_module.close_gas_valve(gas_serial)
        hardware.hardware_cleanup()
        sys.exit(1)

    # ------------------------------------------------------------------
    # 4. Build and run the GUI
    # ------------------------------------------------------------------
    try:
        app = App(pump_serial=pump_serial, gas_serial=gas_serial, sensor_poller=sensor_poller)
        app.run()
    except Exception as e:
        print(f"Unhandled application error: {e}")
    finally:
        # Ensure everything is cleaned up even if the GUI crashes
        pump_module.close_pump(pump_serial)
        gas_module.close_gas_valve(gas_serial)
        hardware.hardware_cleanup()


if __name__ == "__main__":
    main()
