Python bringup and test scripts for the bitaxeProto running bitaxe-raw

## Pin mapping
VDDIO 5V Enable | ESP32 GPIO21
FAN PWM | ESP32 GPIO8
FAN TACH | ESP32 GPIO9
ASIC Reset | ESP32 GPIO1
TPS546 Enable | ESP32 GPIO10
ASIC TX | ESP32 GPIO17
ASIC RX | ESP32 GPIO18
Board SDA | ESP32 GPIO47
Board SCL | ESP32 GPIO48
Display GPIO1 | ESP32 GPIO4
Display GPIO2 | ESP32 GPIO5
Display SCL | ESP32 GPIO6
Display SDA | ESP32 GPIO7

- vr-bringup.py -> configure and enable the TPS546D24S voltage regulator.
- asic_comm.py -> set ASIC_ID on each of the 4 BZM2 chips.
- fan_tester.py -> set and monitor fan speed.
