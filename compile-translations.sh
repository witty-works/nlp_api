#!/bin/bash

mkdir -p locales/en_GB/LC_MESSAGES
rm -rf locales/en_GB/LC_MESSAGES/*
cp -r locales/en_US/LC_MESSAGES/messages.po locales/en_GB/LC_MESSAGES/.

rm -rf training_data/en-GB/*
cp training_data/en-US/* training_data/en-GB/.
pipenv run python -m eng training_data/en-GB/. --ext=csv --target="uk"

mkdir -p locales/de_AT/LC_MESSAGES
rm -rf locales/de_AT/LC_MESSAGES/*
cp -r locales/de_DE/LC_MESSAGES/messages.po locales/de_AT/LC_MESSAGES/.

mkdir -p locales/de_CH/LC_MESSAGES
rm -rf locales/de_CH/LC_MESSAGES/*

sed 's/ß/ss/g' locales/de_DE/LC_MESSAGES/messages.po > locales/de_CH/LC_MESSAGES/messages.po

pipenv run pybabel compile -d locales -l de_DE -f
pipenv run pybabel compile -d locales -l de_AT -f
pipenv run pybabel compile -d locales -l de_CH -f
pipenv run pybabel compile -d locales -l en_US -f
pipenv run pybabel compile -d locales -l en_GB -f