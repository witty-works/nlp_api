#!/bin/bash

rm -rf training_data/en-GB/*
cp training_data/en-US/* training_data/en-GB/.
pipenv run python -m eng training_data/en-GB/. --ext=csv --target="uk"
