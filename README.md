# LS-APGD Control System

Raspberry Pi 3B+ control application for the LS-APGD plasma glow discharge instrument.

## Hardware
- Raspberry Pi 3B+ with custom CAMS HAT R3.0
- Pi Display 2 (DSI, 853x480 scaled)
- Alicat BASIS 2 mass flow controller (/dev/ttyAMA0)
- Syringe pump (/dev/ttyUSB0)
- AD5593R DAC/ADC + ADS1115 (I2C)

## Deploy
    cd /home/cams/LS_APGD && git pull origin main

## Setup
See LSAPGD_Setup_Recipe.docx for full fresh install instructions.
