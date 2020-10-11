# pumpy3
Pumpy3 allows you to control your Harvard syringe pump  from your computer over an RS-232 interface using python 3. 
Adapted from the original pumpy project by tomwphillips and ported to python 3.

# Supported pumps

Harvard PHD 2000
Harvard PHD Ultra

# Features
- set pump volume
- set pump diameter
- set infuse and withdraw rate
- set target volumes
- wait until target volume

# Requirements
- Python 3 (tested: 3.6.10)
- pyserial
- Computer with RS232 port or adapter to USB

# Install
- Just download the pump class

# Usage

```
# import class
from pump import Chain, Pump

# Initialise chain
chain1 = Chain("COM1")
chain2 = Chain("COM2", baudrate=9600)

# Initialise pumps
# Initialise Ultra pump with address = 0
pump1 = Pump(chain1)
# Initialise PHD 2000 with address = 2
pump2 = Pump2000(chain2, address=2)

pump1.cvolume()
pump1.setdiameter(3.26)
pump1.setsyringevolume(500, "u")
pump1.setinfusionrate(100, "u/m")
pump1.setwithdrawrate(100, "u/m")
pump1.settargetvolume(droplet_volume, "u")
pump1.infuse()
pump1.waituntilfinished()

```

# Known issues
- PHD2000 will only take notice of target volumes when it has been put into volume mode using the keypad.
- PHD2000 sometimes won't wait until infusion/withdrawal is finished.
