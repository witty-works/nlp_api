#!/bin/bash

set -e;

descriptions=(
    "Number of installations"
    "Number of total requests and click on alternatives/ignores"
    "Number of clicks on an alternative"
    "Number of clicks on ignore"
)

cmds=(
    "ls user_training_data/ | wc -l"
    "find user_training_data -type f | wc -l"
    "ls user_training_data/ | grep -r '\"alternative\"' | wc -l"
    "ls user_training_data/ | grep -r '\"igore\"' | wc -l"
)

for i in ${!descriptions[@]};
do
    description=${descriptions[$i]}
    cmd=${cmds[$i]};

    echo $description;

    if [[ -z "${PLATFORM_PROJECT}" ]];
    then
        platform ssh -e main -A app "$cmd";
    else
        eval $cmd;
    fi

done
