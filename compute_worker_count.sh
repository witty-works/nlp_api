#!/bin/bash
THREADS=1
CPUS=1
MULTIPLIER=1

usage() {
  echo "Usage: $0 [ -h ] [ -t ] [ -m ] [ -a ] [ -c ] [ -n ]" 1>&2 
}

exit_abnormal() {
  usage
  exit 1
}

while getopts "ht:a:c:m:" options; do
  case "${options}" in
    h)
      exit_abnormal
      ;;
    t)
      THREADS=${OPTARG}
      ;;
    m)
      MULTIPLIER=${OPTARG}
      ;;
    a)
      CPUS=$(echo ${OPTARG} | base64 --decode | jq '.resources.profile_size | tonumber')
      ;;
    c)
      CPUS=${OPTARG}
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

GUNICORN_MAIN_PID=$(pgrep gunicorn | head -n 1)
RUNNING_WORKER_COUNT=$(pgrep gunicorn | wc -l | xargs)
RUNNING_WORKER_COUNT=1

if [ $CPUS -lt 1 ]
then
  echo 1
  exit
fi

# https://docs.gunicorn.org/en/stable/design.html#how-many-workers
THREAD_COUNT=$((($CPUS*$MULTIPLIER*2)+1))

# https://medium.com/building-the-system/gunicorn-3-means-of-concurrency-efbb547674b7
FINAL_WORKER_COUNT=$(( ( $THREAD_COUNT / $THREADS ) + ( $THREAD_COUNT % $THREADS > 0 ) ))

echo $FINAL_WORKER_COUNT
