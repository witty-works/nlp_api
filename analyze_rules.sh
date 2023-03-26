#!/bin/bash
SEND_MAIL=true

usage() {
  echo "Usage: $0 [ -h ] [ -n ] [ -l ] " 1>&2 
}

exit_abnormal() {
  usage
  exit 1
}

while getopts "hrnl:" options; do
  case "${options}" in
    h)
      exit_abnormal
      ;;
    n)
      SEND_MAIL=false
      ;;
    l)
      lang=${OPTARG}
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

echo "Collecting data for $lang"

lt_url="https://lt.default.api.witty.works/v2/check"

diff_not_empty=false

description="Analyze $lang rules"
file="./analyze_rules/$lang.txt"
prev_file="./analyze_rules/prev_$lang.txt"
if test -f "$file"
then
  pre_cmd="mv $file $prev_file"
  eval $pre_cmd
fi

cmd="pdm run python -m bin.analyze_rules -l $lang -u $lt_url >> ./analyze_rules/$lang.txt"

echo "Executing cmd: $cmd"
eval $cmd

if test -f "$prev_file"
then
  diff="diff $prev_file $file"

  if $SEND_MAIL
  then
      diffoutput=`$diff`

      if [ -z "$diffoutput" ]
      then
        echo "$lang diff is empty"
      else
        message+="\n\n$description"
        message+="\n$diffoutput"
        diff_not_empty=true
      fi
  else
      echo "$lang diff from last run"
      eval $diff
  fi
fi

mj_payload(){
    currentDate=`date +"%Y-%m-%d"`
    messageJson=`echo "$message" | jq -Rsa .`
    messageJson=${messageJson//\\\\/\\}
    base64de=`base64 -w 0 ./analyze_rules/$lang.txt`

    cat <<EOF
{
  "Messages":[
    {
      "From": { "Email": "support@witty.works" },
      "To": [{ "Email": "$ANALYZE_RULES_EMAIL" }],
      "Subject": "Witty Rules Analysis $lang: $currentDate",
      "TextPart": $messageJson,
      "Attachments": [
          {
              "ContentType": "text/plain",
              "Filename": "de.txt",
              "Base64Content": "$base64de"
          },
          {
              "ContentType": "text/plain",
              "Filename": "en.txt",
              "Base64Content": "$base64en"
          }
      ]
    }
  ]
}
EOF
}

if $diff_not_empty
then
    echo "sending email"
    json=$(mj_payload)
    echo "$json"

    curl -s \
      -X POST \
      --user "$MJ_APIKEY_PUBLIC:$MJ_APIKEY_PRIVATE" \
      https://api.mailjet.com/v3.1/send \
      -H 'Content-Type: application/json' \
      -d "$json"
fi

