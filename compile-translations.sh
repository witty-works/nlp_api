#!/bin/bash

rm -rf training_data/en-GB/*
cp training_data/en-US/* training_data/en-GB/.
pdm run python -m eng training_data/en-GB/. --ext=csv --target="uk"

if [ "$(uname)" == "Darwin" ]; then
    find 'training_data/en-GB' -name '*.csv' -print0 | xargs -0 sed -i '' 's/,behaviour,/,behavior,/g'
    find 'training_data/en-GB' -name '*.csv' -print0 | xargs -0 sed -i '' 's/,colour,colour,/,color,color,/g'
    find 'training_data/en-GB' -name '*.csv' -print0 | xargs -0 sed -i '' 's/,colour,/,color,/g'
else
    find 'training_data/en-GB' -name '*.csv' -print0 | xargs -0 sed -i 's/,behaviour,/,behavior,/g'
    find 'training_data/en-GB' -name '*.csv' -print0 | xargs -0 sed -i 's/,colour,colour,/,color,color,/g'
    find 'training_data/en-GB' -name '*.csv' -print0 | xargs -0 sed -i 's/,colour,/,color,/g'
fi