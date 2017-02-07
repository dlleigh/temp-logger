#!/bin/bash

pip install virtualenv
virtualenv venv
source venv/bin/activate
pip install -r requirements.txt
git clone https://github.com/Tuckie/max31855.git
