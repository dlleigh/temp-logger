# Multi-chip example
import time
from max31855.max31855 import MAX31855, MAX31855Error
import librato
import yaml

f = open('/etc/temp-logger.yaml')
config = yaml.safe_load(f)
f.close()

api = librato.connect(config['librato_email'], config['librato_key'])
cs_pins = config['cs_pins']
clock_pin = config['clock_pin']
data_pin = config['data_pin']
units = "f"

thermocouples = []
for cs_pin in cs_pins:
    thermocouples.append(MAX31855(cs_pin, clock_pin, data_pin, units))
running = True
while(running):
    try:
        for thermocouple in thermocouples:
            rj = thermocouple.get_rj()
            try:
                tc = thermocouple.get()
            except MAX31855Error as e:
                tc = "Error: "+ e.value
                running = False
            print("tc: {} and rj: {}".format(tc, rj))
        time.sleep(1)
    except KeyboardInterrupt:
        running = False
for thermocouple in thermocouples:
    thermocouple.cleanup()
