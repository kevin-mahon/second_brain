#!/bin/bash
# This script is used to initiate the python environment and
# call the python script
#
#
# Load the python environment
source $HOME/coding/secondbrain/bin/activate
# Call the python script
python $HOME/coding/secondbrain/src/main.py $@
# Deactivate the python environment
deactivate
