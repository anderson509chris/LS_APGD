# gas.py
# Handles all serial communication with the Alicat BASIS 2 mass flow controller.
# Connected via /dev/ttyAMA0 at 38400 baud, RS-232.
#
# BASIS 2 ASCII Protocol (Protocol 2):
#   Poll device:           "A\r"          -> "A +23.8 +0.000 +00000.000 +0.000 +000.00 He\r"
#   Set setpoint source:   "ALSS u\r"    -> unsaved digital (required before setting flow)
#   Set flow setpoint:     "AS 100.0\r"  -> sets flow to 100.0 mL/min
#   Stop flow:             "AS 0\r"
#   Set active gas:        "AGS 7\r"     -> 7 = Helium
#
# Data frame format:
#   unit_id  temperature  flow  total  setpoint  valve_drive  gas
#   A        +23.8        +0.000  +00000.000  +0.000  +000.00  He
#
# Gas numbers: 0=Air, 1=Ar, 2=CO2, 3=N2, 4=O2, 5=N2O, 6=H2, 7=He, 8=CH4

import serial
import time


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------
def open_gas_valve(port="/dev/ttyAMA0", baudrate=38400):
    s = serial.Serial()
    s.port          = port
    s.baudrate      = baudrate
    s.parity        = serial.PARITY_NONE
    s.stopbits      = serial.STOPBITS_ONE
    s.xonxoff       = False
    s.rtscts        = False
    s.dsrdtr        = False
    s.timeout       = 1.0
    s.write_timeout = 2.0
    s.open()
    return s


def close_gas_valve(ser):
    try:
        if ser and ser.is_open:
            ser.close()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------
def _send(ser, command_str):
    try:
        ser.write(command_str.encode('ascii') + b'\r')
        time.sleep(0.1)
    except serial.SerialException as e:
        print(f"[gas] serial error sending '{command_str}': {e}")


def _send_read(ser, command_str):
    try:
        ser.reset_input_buffer()
        ser.write(command_str.encode('ascii') + b'\r')
        line = ser.readline()
        return line.decode('ascii', errors='replace').strip()
    except serial.SerialException as e:
        print(f"[gas] serial error on '{command_str}': {e}")
        return ""


# ---------------------------------------------------------------------------
# Public commands
# ---------------------------------------------------------------------------
def stop_flow(ser):
    _send(ser, "AS 0")


def set_flow(ser, ml_per_min):
    try:
        flow = float(ml_per_min)
    except (ValueError, TypeError):
        flow = 0.0
    _send(ser, f"AS {flow:.3f}")


def set_cal_gas(ser, gas_index):
    index = int(gas_index)
    if index < 0 or index > 8:
        index = 7
    _send(ser, f"AGS {index}")


def read_flow_data(ser):
    raw = _send_read(ser, "A")
    if not raw:
        return "", ""
    parts = raw.split()
    if len(parts) >= 7 and parts[0] == 'A':
        try:
            flow_val = parts[2].lstrip('+')
            return raw, flow_val
        except Exception:
            pass
    return raw, ""


def read_temperature(ser):
    raw = _send_read(ser, "A")
    if not raw:
        return None
    parts = raw.split()
    if len(parts) >= 7 and parts[0] == 'A':
        try:
            return float(parts[1])
        except (ValueError, IndexError):
            pass
    return None


def initialise_gas_valve(ser):
    # Set setpoint source to unsaved digital
    resp = _send_read(ser, "ALSS u")
    print(f"[gas] init ALSS u -> {resp}")
    time.sleep(0.1)
    # Explicitly zero the setpoint — ALSS u can leave a residual value
    resp = _send_read(ser, "AS 0")
    print(f"[gas] init AS 0 -> {resp}")
    time.sleep(0.1)
    # Confirm comms with a poll
    resp = _send_read(ser, "A")
    print(f"[gas] init poll -> {resp}")
