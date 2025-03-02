#!/bin/bash

cd "$(dirname "$0")"
export TEMP_LOGGER_CONFIG="/etc/temp-logger.yml"
if [ -d temp-logger ]; then sudo rm -rf temp-logger;fi
git clone https://github.com/dlleigh/temp-logger.git
cd temp-logger
make deploy
python temp_logger.py
