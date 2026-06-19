# Multi-chip example
import csv
import time
import logging
import logging.handlers
from datetime import datetime, date
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

# Create local data directory for CSV persistence
data_dir = config.get('data_dir', '/home/pi/oven-data')
os.makedirs(data_dir, exist_ok=True)

# Load calibration file if available
calibration = {}
calibration_path = config.get('calibration_file', '/etc/calibration.yml')
try:
    with open(calibration_path) as cal_f:
        calibration = yaml.safe_load(cal_f) or {}
    logging.info("Loaded calibration from %s" % calibration_path)
except FileNotFoundError:
    logging.info("No calibration file at %s, using uncalibrated model" % calibration_path)

# Create predictors for each thermocouple
predictors = {}
for cs_pin in cs_pins:
    location_key = pin_mapping[cs_pin]['location'].replace(' ', '_')
    cal = calibration.get(location_key, {})
    predictors[cs_pin] = TemperaturePredictor(
        tau1=cal.get('tau1'),
        tau2=cal.get('tau2'),
    )

running = True
while(running):
    try:
        influxdb_client = InfluxDBClient(url=config['influxdb_url'], 
                                       token=config['influxdb_token'], 
                                       org=config['influxdb_org'])
        write_api = influxdb_client.write_api(write_options=SYNCHRONOUS)
        points = []
        readings = []

        for thermocouple in thermocouples:
            rj = thermocouple.get_rj()
            name = pin_mapping[thermocouple.cs_pin]['name']
            location = pin_mapping[thermocouple.cs_pin]['location']
            tc = thermocouple.get()
            readings.append((name, location, tc))

            # Add measurement and get prediction
            predictor = predictors[thermocouple.cs_pin]
            predictor.add_measurement(tc)
            prediction_30min = predictor.predict_temperature(30)
            prediction_1hr = predictor.predict_temperature(60)
            prediction_2hr = predictor.predict_temperature(120)
            
            logging.info("source: %s temp: %s prediction_30min: %s prediction_1hr: %s prediction_2hr: %s" % 
                        (name, tc, prediction_30min, prediction_1hr, prediction_2hr))
            
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
                
            if prediction_1hr is not None:
                prediction_point = Point("oven-temp-prediction")\
                    .tag("location", location)\
                    .tag("name", name)\
                    .tag("prediction_minutes", "60")\
                    .field("temperature", prediction_1hr)
                points.append(prediction_point)
                
            if prediction_2hr is not None:
                prediction_point = Point("oven-temp-prediction")\
                    .tag("location", location)\
                    .tag("name", name)\
                    .tag("prediction_minutes", "120")\
                    .field("temperature", prediction_2hr)
                points.append(prediction_point)
                
            time.sleep(0.5)

        write_api.write(bucket=config['influxdb_bucket'], record=points)

        # Append readings to daily CSV file
        csv_path = os.path.join(data_dir, date.today().strftime('%Y-%m-%d') + '.csv')
        write_header = not os.path.exists(csv_path)
        with open(csv_path, 'a', newline='') as csvfile:
            writer = csv.writer(csvfile)
            if write_header:
                writer.writerow(['timestamp', 'name', 'location', 'temperature'])
            now = datetime.now().isoformat()
            for name, location, tc in readings:
                writer.writerow([now, name, location, tc])

        time.sleep(frequency)
        
    except KeyboardInterrupt:
        running = False
    except Exception as e:
        logging.error("Error: %s" % e)

for thermocouple in thermocouples:
    thermocouple.cleanup()
