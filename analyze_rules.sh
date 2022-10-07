#!/bin/bash
SEND_MAIL=true

usage() {
  echo "Usage: $0 [ -h ] [ -n ] " 1>&2 
}

exit_abnormal() {
  usage
  exit 1
}

while getopts "hrne:" options; do
  case "${options}" in
    h)
      exit_abnormal
      ;;
    n)
      SEND_MAIL=false
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

echo "Collecting data"

lt_url="https://lt.default.api.witty.works/v2/check"

diff_not_empty=false

python=`which python`
if ! [[ "$python" =~ ^/ ]]
then
    python="python"
fi

langs=(
  "de"
  "en"
)
for i in ${!langs[@]}
do
    lang=${langs[$i]}

    description="Analyze $lang rules"
    file="./analyze_rules/$lang.txt"
    prev_file="./analyze_rules/prev_$lang.txt"
    if test -f "$file"
    then
      pre_cmd="mv $file $prev_file"
      eval $pre_cmd
    fi

    cmd="pipenv run $python -m bin.analyze_rules -l $lang -u $lt_url >> ./analyze_rules/$lang.txt"

    if ! [ $SEND_MAIL ]
    then
        echo $description
    fi

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

done

mj_payload(){
    currentDate=`date +"%Y-%m-%d"`
    messageJson=`echo "$message" | jq -Rsa .`
    messageJson=${messageJson//\\\\/\\}
    base64de=`base64 -w 0 ./analyze_rules/de.txt`
    base64en=`base64 -w 0 ./analyze_rules/en.txt`

    cat <<EOF
{
  "Messages":[
    {
      "From": { "Email": "support@witty.works" },
      "To": [{ "Email": "$ANALYZE_RULES_EMAIL" }],
      "Subject": "Witty Rules Analysis: $currentDate",
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

