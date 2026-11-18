# Multi-chip example
import csv
import time
import logging
import logging.handlers
from datetime import datetime, date, timedelta
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

# Daily CSV files accumulate forever otherwise, slowly filling the SD card.
csv_retention_days = config.get('csv_retention_days', 30)


def cleanup_old_csvs():
    """Delete daily CSV files older than the retention window."""
    cutoff = date.today() - timedelta(days=csv_retention_days)
    for fname in os.listdir(data_dir):
        if not fname.endswith('.csv'):
            continue
        try:
            fdate = datetime.strptime(fname[:-4], '%Y-%m-%d').date()
        except ValueError:
            continue
        if fdate < cutoff:
            try:
                os.remove(os.path.join(data_dir, fname))
                logging.info("Removed old CSV %s" % fname)
            except OSError as e:
                logging.error("Could not remove %s: %s" % (fname, e))

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

def connect_influx():
    """Open an InfluxDB client + write API. Created once and reused across the
    loop; previously this was rebuilt every cycle, leaking a socket each time."""
    client = InfluxDBClient(url=config['influxdb_url'],
                            token=config['influxdb_token'],
                            org=config['influxdb_org'])
    return client, client.write_api(write_options=SYNCHRONOUS)


influxdb_client = None
write_api = None
last_cleanup = None

running = True
while(running):
    try:
        if write_api is None:
            influxdb_client, write_api = connect_influx()

        # Trim old CSVs once a day (and on first iteration).
        today = date.today()
        if last_cleanup != today:
            cleanup_old_csvs()
            last_cleanup = today

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
            
            # Per-cycle, per-sensor -- logged at DEBUG so a healthy run stays
            # quiet (every 30s x 3 sensors would otherwise grow the log forever).
            logging.debug("source: %s temp: %s prediction_30min: %s prediction_1hr: %s prediction_2hr: %s" %
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

        # Append readings to the daily CSV first, so local data survives even
        # if the InfluxDB write below fails (e.g. network/cloud outage).
        csv_path = os.path.join(data_dir, today.strftime('%Y-%m-%d') + '.csv')
        write_header = not os.path.exists(csv_path)
        with open(csv_path, 'a', newline='') as csvfile:
            writer = csv.writer(csvfile)
            if write_header:
                writer.writerow(['timestamp', 'name', 'location', 'temperature'])
            now = datetime.now().isoformat()
            for name, location, tc in readings:
                writer.writerow([now, name, location, tc])

        write_api.write(bucket=config['influxdb_bucket'], record=points)

        time.sleep(frequency)
        
    except KeyboardInterrupt:
        running = False
    except Exception as e:
        logging.error("Error: %s" % e)
        # Drop the client so the next iteration reconnects cleanly, and back off
        # so a persistent failure (e.g. network down) doesn't spin hot.
        if influxdb_client is not None:
            try:
                influxdb_client.close()
            except Exception:
                pass
        influxdb_client = None
        write_api = None
        time.sleep(frequency)

if influxdb_client is not None:
    influxdb_client.close()
for thermocouple in thermocouples:
    thermocouple.cleanup()
