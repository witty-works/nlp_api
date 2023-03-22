#!/bin/bash

mkdir -p locales/en_GB/LC_MESSAGES
rm -rf locales/en_GB/LC_MESSAGES/*
cp -r locales/en_US/LC_MESSAGES/messages.po locales/en_GB/LC_MESSAGES/.
pdm run python -m eng locales/en_GB/LC_MESSAGES/. --ext=po --target="uk"

if [ "$(uname)" == "Darwin" ]; then
    find 'locales/en_GB/LC_MESSAGES' -name '*.po' -print0 | xargs -0 sed -i '' 's/rules\.behaviour/rules.behavior/g'
else
    find 'locales/en_GB/LC_MESSAGES' -name '*.po' -print0 | xargs -0 sed -i 's/rules\.behaviour/rules.behavior/g'
fi

rm -rf training_data/en-GB/*
cp training_data/en-US/* training_data/en-GB/.
pdm run python -m eng training_data/en-GB/. --ext=csv --target="uk"

if [ "$(uname)" == "Darwin" ]; then
    find 'training_data/en-GB' -name '*.csv' -print0 | xargs -0 sed -i '' 's/,behaviour,/,behavior,/g'
else
    find 'training_data/en-GB' -name '*.csv' -print0 | xargs -0 sed -i 's/,behaviour,/,behavior,/g'
fi

mkdir -p locales/de_AT/LC_MESSAGES
rm -rf locales/de_AT/LC_MESSAGES/*
cp -r locales/de_DE/LC_MESSAGES/messages.po locales/de_AT/LC_MESSAGES/.

mkdir -p locales/de_CH/LC_MESSAGES
rm -rf locales/de_CH/LC_MESSAGES/*

sed 's/ß/ss/g' locales/de_DE/LC_MESSAGES/messages.po > locales/de_CH/LC_MESSAGES/messages.po

pdm run pybabel compile -d locales -l de_DE -f
pdm run pybabel compile -d locales -l de_AT -f
pdm run pybabel compile -d locales -l de_CH -f
pdm run pybabel compile -d locales -l en_US -f
pdm run pybabel compile -d locales -l en_GB -f