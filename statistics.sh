#!/bin/bash
READ_REMOTE=false 

BACKUP=false

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
    b)
      BACKUP=true
      ;;
    e)
      ENV=${OPTARG}
      ;;
    d)
      DATE=${OPTARG}
      re_isanum='^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
      if ! [[ $DATE =~ $re_isanum ]] ; then
        echo "Error: DATE must be a date format YYYY-mm-dd"
        exit_abnormal
        exit 1
      fi
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

if $BACKUP && $READ_REMOTE;
then
    echo "Backup cannot be enabled with remote";
    exit_abnormal
fi

if [[ -z "$DATE" ]];
then
    unamestr="${OSTYPE//[0-9.]/}"

    if [ "${OSTYPE//[0-9.]/}" == "darwin" ]
    then
        date="-v -0d"
    else
        date="--date=today"
    fi

    cmd="date $date +\"%Y-%m-%d\""
    DATE=$(eval $cmd)
fi

echo "Collecting data for $DATE $ENV";

if $READ_REMOTE;
then
    echo "Connecting to $ENV";
fi

descriptions=(
    "Total number of installations"
    "Total number of active installations"
    "Number of total requests including click on alternatives/ignores"
    "Number of clicks on an alternative"
    "Number of clicks on ignore"
)

data_dir="user_training_data";
date_dir="$data_dir/$DATE";

cmds=(
    "ls $data_dir/installs | wc -l"
    "ls $date_dir | wc -l"
    "find $date_dir -type f | wc -l"
    "ls $date_dir/ | grep -r '\"alternative\"' | wc -l"
    "ls $date_dir/ | grep -r '\"igore\"' | wc -l"
)

if [[ ! -d $date_dir ]];
then
    echo "Directory $date_dir does not exist."
    exit 1;
fi

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

if $BACKUP;
then
    cd $data_dir;
    tar -czf "$DATE.tar.gz" $DATE;
    rm -rf $DATE;
fi
