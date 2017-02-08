# Multi-chip example
import time
from max31855.max31855 import MAX31855, MAX31855Error
import librato
import yaml
import os

f = open(os.environ['TEMP_LOGGER_CONFIG'])
config = yaml.safe_load(f)
f.close()

api = librato.connect(config['librato_email'], config['librato_key'])
cs_pins = []
pin_mapping = {}
for thermocouple in config['thermocouples']:
  cs_pins.append(thermocouple['pin'])
  pin_mapping[thermocouple['pin']] = thermocouple['name']
clock_pin = config['clock_pin']
data_pin = config['data_pin']
frequency = config['frequency']
units = "f"

thermocouples = []
for cs_pin in cs_pins:
    thermocouples.append(MAX31855(cs_pin, clock_pin, data_pin, units))
running = True
while(running):
    try:
        q   = api.new_queue()
        for thermocouple in thermocouples:
            rj = thermocouple.get_rj()
            try:
                tc = thermocouple.get()
            except MAX31855Error as e:
                tc = "Error: "+ e.value
                running = False
            name = pin_mapping[thermocouple.cs_pin]
            print("source: %s temp: %s" % (name, tc))
            q.add('temperature',tc,source=name)
        time.sleep(frequency)
        q.submit()
    except KeyboardInterrupt:
        running = False
for thermocouple in thermocouples:
    thermocouple.cleanup()
