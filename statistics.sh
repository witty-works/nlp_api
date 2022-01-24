#!/bin/bash
READ_REMOTE=false 

ENV=main

usage() {
  echo "Usage: $0 [ -h ] [ -r ] [ -b ] [ -e ] [ -d YYYY-mm-dd ] " 1>&2 
}

exit_abnormal() {
  usage
  exit 1
}

while getopts "hrbe:d:" options; do
  case "${options}" in
    h)
      exit_abnormal
      ;;
    r)
      READ_REMOTE=true
      ;;
    e)
      ENV=${OPTARG}
      ;;
    :)
      echo "Error: -${OPTARG} requires an argument."
      exit_abnormal
      ;;
    *)
      exit_abnormal
      ;;
  esac
done

if [ $ENV != "main" ];
then
    READ_REMOTE=true
fi

echo "Collecting data for $ENV";

if $READ_REMOTE;
then
    echo "Connecting to $ENV";
fi

descriptions=(
    "Number of German rules"
    "Number of English rules"
)

training_data_dir="training_data";

cmds=(
    "wc -l $training_data_dir/de-DE/*"
    "wc -l $training_data_dir/en-US/*"
)

for i in ${!descriptions[@]};
do
    description=${descriptions[$i]}
    cmd=${cmds[$i]};

    echo $description;

    if $READ_REMOTE;
    then
        platform ssh -e $ENV -A app "$cmd";
    else
        eval $cmd;
    fi

done
