# Multi-chip example
import time
import logging
import logging.handlers
from max31855 import MAX31855, MAX31855Error
import yaml
import os
from influxdb_client import InfluxDBClient, Point
from influxdb_client .client.write_api import SYNCHRONOUS
from temp_predictor import TemperaturePredictor

class MAX31855a(MAX31855):
    def get(self):
        self.read()
        try:
            MAX31855.checkErrors(self)
        except MAX31855Error as error:
            logging.error("cs_pin: %s error: %s" % (self.cs_pin, error.value))
        return getattr(self, "to_" + self.units)(self.data_to_tc_temperature())

f = open(os.environ['TEMP_LOGGER_CONFIG'])
config = yaml.safe_load(f)
f.close()

log_handler = logging.handlers.WatchedFileHandler(config['logfile'])
formatter = logging.Formatter('%(asctime)s %(message)s')
log_handler.setFormatter(formatter)
logger = logging.getLogger()
logger.addHandler(log_handler)
logger.setLevel(logging.INFO)

cs_pins = []
pin_mapping = {}
for thermocouple in config['thermocouples']:
  cs_pins.append(thermocouple['pin'])
  pin_mapping[thermocouple['pin']] = {'name': thermocouple['name'], 'location': thermocouple['location']}
clock_pin = config['clock_pin']
data_pin = config['data_pin']
frequency = config['frequency']
units = "f"

thermocouples = []
for cs_pin in cs_pins:
    thermocouples.append(MAX31855a(cs_pin, clock_pin, data_pin, units))

# Create predictors for each thermocouple
predictors = {}
for cs_pin in cs_pins:
    predictors[cs_pin] = TemperaturePredictor()

running = True
while(running):
    try:
        influxdb_client = InfluxDBClient(url=config['influxdb_url'], 
                                       token=config['influxdb_token'], 
                                       org=config['influxdb_org'])
        write_api = influxdb_client.write_api(write_options=SYNCHRONOUS)
        points = []
        
        for thermocouple in thermocouples:
            rj = thermocouple.get_rj()
            name = pin_mapping[thermocouple.cs_pin]['name']
            location = pin_mapping[thermocouple.cs_pin]['location']
            tc = thermocouple.get()
            
            # Add measurement and get prediction
            predictor = predictors[thermocouple.cs_pin]
            predictor.add_measurement(tc)
            prediction_30min = predictor.predict_temperature(30)
            
            logging.info("source: %s temp: %s prediction_30min: %s" % 
                        (name, tc, prediction_30min))
            
            # Create points for current temperature and prediction
            current_point = Point("oven-temp")\
                .tag("location", location)\
                .tag("name", name)\
                .field("temperature", tc)
            points.append(current_point)
            
            if prediction_30min is not None:
                prediction_point = Point("oven-temp-prediction")\
                    .tag("location", location)\
                    .tag("name", name)\
                    .tag("prediction_minutes", "30")\
                    .field("temperature", prediction_30min)
                points.append(prediction_point)
                
            time.sleep(0.5)
            
        write_api.write(bucket=config['influxdb_bucket'], record=points)
        time.sleep(frequency)
        
    except KeyboardInterrupt:
        running = False
    except Exception as e:
        logging.error("Error: %s" % e)

for thermocouple in thermocouples:
    thermocouple.cleanup()
