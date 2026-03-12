# pump.py
# Handles all serial communication with the syringe pump.
# The pump is connected via USB serial (/dev/ttyUSB0) at 38400 baud.
#
# All public functions accept a serial.Serial instance as their first
# argument so the connection is managed externally (in main.py) 

import serial
import time


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------
def open_pump(port="/dev/ttyUSB0", baudrate=38400):
    """
    Open and return a serial connection to the syringe pump.
    Raises serial.SerialException if the port cannot be opened.
    """
    s = serial.Serial()
    s.port     = port
    s.baudrate = baudrate
    s.timeout  = 0.2
    s.open()
    return s


def close_pump(ser):
    """Safely close the pump serial connection."""
    try:
        if ser and ser.is_open:
            ser.close()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Low-level send / receive
# ---------------------------------------------------------------------------
def _send_command(ser, command):
    """
    Send a command string to the pump and return the cleaned response.
    Retries once if the pump returns 'Invalid'.
    Returns an empty string if communication fails.
    """
    for attempt in range(2):
        try:
            arg = bytes(str(command), 'utf8') + b'\r'
            ser.flushInput()
            ser.write(arg)

            # Longer delay for diameter commands (pump needs extra time)
            if command.startswith('set diameter'):
                time.sleep(0.5)
            else:
                time.sleep(0.1)

            response = _get_response(ser)
            # Strip the echoed command and prompt characters
            clean = response.strip(command).strip('>= ')

            if not clean.startswith("Invalid"):
                return clean

            time.sleep(0.1)
            print(f"Pump: invalid command on attempt {attempt + 1}: '{command}'")

        except serial.SerialException as e:
            print(f"Pump serial error sending '{command}': {e}")
            return ""

    return ""


def _get_response(ser):
    """Read all waiting bytes from the pump and return them as a string."""
    seq = []
    joined_seq = ""
    try:
        while ser.inWaiting() > 0:
            for byte in ser.read():
                ch = chr(byte)
                if ch not in ('\r', '\n'):
                    seq.append(ch)
                    joined_seq = ''.join(seq)
    except serial.SerialException as e:
        print(f"Pump serial error reading response: {e}")
    return joined_seq


# ---------------------------------------------------------------------------
# Public pump commands
# ---------------------------------------------------------------------------
def start_pump(ser):
    """Start the pump. Returns pump response string."""
    return _send_command(ser, 'start')


def stop_pump(ser):
    """Stop the pump. Returns pump response string."""
    return _send_command(ser, 'stop')


def pause_pump(ser):
    """Pause the pump. Returns pump response string."""
    return _send_command(ser, 'pause')


def restart_pump(ser):
    """Restart the pump after a pause. Returns pump response string."""
    return _send_command(ser, 'restart')


def set_units(ser, units):
    """
    Set flow-rate units.
    units=2 selects μL/min (the unit used by this application).
    """
    return _send_command(ser, f'set units {units}')


def set_diameter(ser, diameter):
    """
    Set the syringe inner diameter in mm.
    Returns the value confirmed by the pump.
    """
    return _send_command(ser, f'set diameter {diameter}')


def set_rate(ser, rate):
    """Set the flow rate in the currently configured units."""
    return _send_command(ser, f'set rate {rate}')


def set_volume(ser, volume):
    """
    Set the target dispense volume in μL.
    Returns the value confirmed by the pump (as a string).
    """
    return _send_command(ser, f'set volume {volume}')


def get_dispensed_volume(ser):
    """
    Query the volume dispensed since the last reset.
    Returns the value as a string (e.g. '12.34').
    """
    return _send_command(ser, 'dispensed volume')


def initialise_pump(ser):
    """
    Send startup configuration to the pump.
    Sets units to μL/min and an initial rate of 1 μL/min.
    """
    set_units(ser, 2)
    set_rate(ser, 1)
