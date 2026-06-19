The purpose of this repo is to provide real-time temperature metrics for my retained heat wood-fired brick oven. The oven has 3 thermocouples embedded in different parts of the masonry. This code runs on a raspberry pi which collects temperature readings and sends them to influxdb. I use a grafana dashboard to visualize temperature readings (instantaneous and recent historical).

Upon boot, the pi runs `deploy.sh` which pulls down latest code from GitHub and runs `temp-logger.sh` which starts the monitoring script `temp-logger.py`. Configuration is in `/etc/temp-logger.yml` on the pi.

Current status:
- instantaenous temp measurements and graph of temp over past hour are useful
- There is a fair bit of noise in the temp readings, but this is not a big problem.
- The question that I most want to answer is "what will the temp be 1 hour from now. This is still difficult to answer
- I have tried to enhance the logging code to predict what the temp will be 1 hour from now, but this prediction not working at all.