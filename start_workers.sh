#!/bin/bash
THREADS=1
CPUS=1

usage() {
  echo "Usage: $0 [ -h ] [ -t ] [ -a ] [ -c ]" 1>&2 
}

exit_abnormal() {
  usage
  exit 1
}

while getopts "ht:a:c:" options; do
  case "${options}" in
    h)
      exit_abnormal
      ;;
    t)
      THREADS=${OPTARG}
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

echo "CPUs $CPUS and threads $THREADS\n"

GUNICORN_MAIN_PID=$(pgrep gunicorn | head -n 1)
RUNNING_WORKER_COUNT=$(pgrep gunicorn | wc -l | xargs)

echo "Currently running $RUNNING_WORKER_COUNT workers\n"

if [ $CPUS -lt 1 ]
then
  FINAL_WORKER_COUNT=1
  echo "CPUs below 1, so running only a single worker\n"
  exit
fi

# https://docs.gunicorn.org/en/stable/design.html#how-many-workers
THREAD_COUNT=$((($CPUS*2)+1))

# https://medium.com/building-the-system/gunicorn-3-means-of-concurrency-efbb547674b7
FINAL_WORKER_COUNT=$(( ( $THREAD_COUNT / $THREADS ) + ( $THREAD_COUNT % $THREADS > 0 ) ))

echo "Aiming to run $THREAD_COUNT threads on $FINAL_WORKER_COUNT workers\n"

MISSING_WORKERS="$(($FINAL_WORKER_COUNT-$RUNNING_WORKER_COUNT))";

if [ $MISSING_WORKERS -ge 0 ]
then
  echo "Starting $MISSING_WORKERS additional workers to reach $FINAL_WORKER_COUNT workers\n"
  for (( c=$RUNNING_WORKER_COUNT+1; c<=$FINAL_WORKER_COUNT; c++ ))
  do
    echo "Starting worker $c"
    # https://docs.gunicorn.org/en/stable/faq.html#how-can-i-change-the-number-of-workers-dynamically
    kill -TTIN $GUNICORN_MAIN_PID
  done
fi
