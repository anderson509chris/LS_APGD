# hardware.py
# Handles all low-level hardware communication:
#   - RPi GPIO (power supply relay, shutdown pin)
#   - pigpio PWM (igniter)
#   - smbus2 / AD5593R I2C DAC+ADC (power supply control and monitoring)
#   - Adafruit ADS1115 ADC (supply ground reference voltage)

import time
import threading
import smbus2
import pigpio
import RPi.GPIO as GPIO

import board
import busio
import adafruit_ads1x15.ads1115 as ADS
from adafruit_ads1x15.analog_in import AnalogIn
from adafruit_ads1x15.ads1x15 import Mode, Pin


# ---------------------------------------------------------------------------
# GPIO pin assignments
# ---------------------------------------------------------------------------
PIN_POWER_SUPPLY = 4    # Output: enables/disables power supply relay
PIN_SHUTDOWN     = 24   # Output: triggers remote system shutdown

# ---------------------------------------------------------------------------
# AD5593R I2C address
# ---------------------------------------------------------------------------
AD5593_ADDR = 17  # 0x11


# ---------------------------------------------------------------------------
# GPIO setup
# ---------------------------------------------------------------------------
def gpio_setup():
    """Initialise RPi GPIO pins. Call once at startup."""
    GPIO.setwarnings(False)
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(PIN_POWER_SUPPLY, GPIO.OUT)
    GPIO.setup(PIN_SHUTDOWN,     GPIO.OUT)


def gpio_cleanup():
    """Release GPIO resources. Call on exit."""
    GPIO.cleanup()


def power_supply_on():
    GPIO.output(PIN_POWER_SUPPLY, 1)


def power_supply_off():
    GPIO.output(PIN_POWER_SUPPLY, 0)


def trigger_shutdown_pin():
    """Assert the hardware shutdown pin (held high briefly)."""
    GPIO.output(PIN_SHUTDOWN, 1)
    time.sleep(0.5)


# ---------------------------------------------------------------------------
# pigpio PWM – igniter
# ---------------------------------------------------------------------------
_pwm = None  # pigpio instance, initialised by pwm_setup()

def pwm_setup():
    """Start pigpio and configure the igniter PWM output (GPIO 18)."""
    global _pwm
    _pwm = pigpio.pi()
    if not _pwm.connected:
        raise RuntimeError(
            "Cannot connect to pigpio daemon. "
            "Run 'sudo pigpiod' before starting the application."
        )
    _pwm.hardware_PWM(18, 1000, 0)  # 1 kHz, 0% duty cycle


def pwm_set(duty_cycle_millionths):
    """Set igniter PWM duty cycle (0 – 1 000 000)."""
    if _pwm is None:
        raise RuntimeError("PWM not initialised. Call pwm_setup() first.")
    _pwm.hardware_PWM(18, 1000, int(duty_cycle_millionths))


def pwm_off():
    """Turn igniter PWM off (0% duty cycle)."""
    pwm_set(0)


def pwm_cleanup():
    """Stop pigpio."""
    if _pwm is not None:
        try:
            pwm_off()
            _pwm.stop()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# smbus2 helpers
# ---------------------------------------------------------------------------
_bus = None

def bus_setup():
    """Open I2C bus 1. Call once at startup."""
    global _bus
    _bus = smbus2.SMBus(1)


def bus_cleanup():
    if _bus is not None:
        _bus.close()


# ---------------------------------------------------------------------------
# AD5593R register-level helpers
# ---------------------------------------------------------------------------
# Channel assignments on the AD5593R at address AD5593_ADDR:
#   0 – CH1 voltage monitor  (ADC input)
#   1 – CH1 current setpoint (DAC output)
#   2 – CH1 current monitor  (ADC input)
#   3 – CH2 voltage monitor  (ADC input)
#   4 – CH2 current setpoint (DAC output)
#   5 – CH2 current monitor  (ADC input)

def _ad5593_write(address, cmd, val):
    d = (((val & 0xFF) << 8) | ((val >> 8) & 0xFF))
    _bus.write_word_data(address, cmd, d)


def _ad5593_write_dac(address, chan, val):
    d = [((val >> 8) & 0x0F) | ((chan << 4) | 0x80), (val & 0xFF)]
    c = 0x10 | chan
    _bus.write_i2c_block_data(address, c, d)


def _ad5593_read_word(address, pb):
    j = _bus.read_word_data(address, pb)
    j = ((j & 0xFF) << 8) | ((j >> 8) & 0xFF)
    return j


def _ad5593_read_adc(address, chan):
    _ad5593_write(address, 0x02, (1 << chan))
    i = _ad5593_read_word(address, 0x40)
    if ((i >> 12) & 0x7) != chan:
        return -1
    return i & 0xFFF


def ad5593_setup(address=AD5593_ADDR):
    """Configure the AD5593R chip. Call once after bus_setup()."""
    _ad5593_write(address, 3,  0x0100)  # ADC range 0-5 V
    _ad5593_write(address, 11, 0x0200)  # External reference
    _ad5593_write(address, 7,  0x0000)  # LDAC mode
    _ad5593_write(address, 5,  0x0012)  # DAC output channels (1 and 4)
    _ad5593_write(address, 4,  0x002D)  # ADC input channels (0,2,3,5)
    _ad5593_write(address, 6,  0x0000)  # Disable all pull-downs


def set_dac(chan, val, address=AD5593_ADDR):
    """Write a 12-bit value to a DAC output channel."""
    _ad5593_write_dac(address, chan, val)


def read_adc_channel(chan, address=AD5593_ADDR):
    """Read a 12-bit value from an ADC input channel. Returns -1 on error."""
    return _ad5593_read_adc(address, chan)


# Convenience wrappers used by the GUI logic
def set_ch1_current(raw_value):
    set_dac(1, raw_value)

def set_ch2_current(raw_value):
    set_dac(4, raw_value)

def set_both_current(raw_ch1, raw_ch2):
    set_dac(1, raw_ch1)
    set_dac(4, raw_ch2)

def zero_outputs():
    """Set both DAC outputs to zero. Call on startup and shutdown."""
    set_dac(1, 0)
    set_dac(4, 0)

def read_ch1_voltage():
    return read_adc_channel(0)

def read_ch2_voltage():
    return read_adc_channel(3)

def read_ch1_current():
    return read_adc_channel(2)

def read_ch2_current():
    return read_adc_channel(5)


# ---------------------------------------------------------------------------
# ADS1115 ADC – supply ground reference
# ---------------------------------------------------------------------------
_adc_device  = None
_adc_channel = None

def adc_setup():
    """Initialise the ADS1115 on the default I2C bus. Call once at startup."""
    global _adc_device, _adc_channel
    i2c = busio.I2C(board.SCL, board.SDA)
    _adc_device = ADS.ADS1115(i2c)
    _adc_device.gain = 1
    _adc_device.mode = Mode.CONTINUOUS
    _adc_channel = AnalogIn(_adc_device, Pin.A1)


def adc_read_reference():
    """Return the raw 16-bit ADC value from channel 1 (ground reference)."""
    if _adc_channel is None:
        raise RuntimeError("ADC not initialised. Call adc_setup() first.")
    return _adc_channel.value


# ---------------------------------------------------------------------------
# Convenience: initialise / tear down everything at once
# ---------------------------------------------------------------------------
def hardware_setup():
    """Call once at application startup to bring up all hardware."""
    gpio_setup()
    pwm_setup()
    bus_setup()
    ad5593_setup()
    adc_setup()
    zero_outputs()


def hardware_cleanup():
    """Call on application exit to safely release all hardware."""
    try:
        zero_outputs()
    except Exception:
        pass
    try:
        power_supply_off()
    except Exception:
        pass
    pwm_cleanup()
    bus_cleanup()
    gpio_cleanup()


# ---------------------------------------------------------------------------
# Background sensor polling thread
# ---------------------------------------------------------------------------
class SensorPoller:
    """
    Reads all ADC channels on a background thread so the Tkinter UI thread
    is never blocked by I2C waits.

    Usage:
        poller = SensorPoller()
        poller.start()
        ...
        data = poller.get()   # returns latest dict, never blocks
        ...
        poller.stop()
    """

    # How long to sleep between full read cycles (seconds).
    # 80 ms gives ~12 Hz refresh — faster than the 200 ms UI tick.
    POLL_INTERVAL = 0.08

    def __init__(self):
        self._data = {
            "ch1_voltage": -1,
            "ch2_voltage": -1,
            "ch1_current": -1,
            "ch2_current": -1,
            "adc_ref":      0,
        }
        self._lock   = threading.Lock()
        self._stop   = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="SensorPoller")

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()

    def get(self):
        """Return a shallow copy of the latest sensor readings."""
        with self._lock:
            return dict(self._data)

    def _run(self):
        while not self._stop.is_set():
            readings = {}
            try:
                readings["ch1_voltage"] = read_ch1_voltage()
                readings["ch2_voltage"] = read_ch2_voltage()
                readings["ch1_current"] = read_ch1_current()
                readings["ch2_current"] = read_ch2_current()
                # adc_ref intentionally omitted — ADS1115 is not thread-safe
            except Exception as e:
                print(f"[SensorPoller] read error: {e}")
                self._stop.wait(self.POLL_INTERVAL)
                continue

            with self._lock:
                self._data.update(readings)

            self._stop.wait(self.POLL_INTERVAL)
