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

if $SEND_MAIL;
then
    message="Collecting data\n";
else
    echo "Collecting data";
fi

langs=(
  "de"
  "en"
)

diff_run="Diff from last run"

for i in ${!langs[@]};
do
    lang=${langs[$i]}

    description="Analyze $lang rules"
    file="./analyze_rules/$lang.txt"
    prev_file="./analyze_rules/prev_$lang.txt"
    if test -f "$file"; then
      pre_cmd="mv $file $prev_file"
      eval $pre_cmd
    fi

    lt_url="https://lt.default.api.witty.works/v2/check"
    cmd="pipenv run python -m bin.analyze_rules -l $lang -u $lt_url >> ./analyze_rules/$lang.txt"
    diff="diff $prev_file $file"

    if $SEND_MAIL;
    then
        message+="\n\n$description";

        eval $cmd;

        if test -f "$prev_file"; then
          message+="\n\n$diff_run";

          diffoutput=`$diff`
          message+="\n$diffoutput";
        fi
    else
        echo $description
        eval $cmd;

        if test -f "$prev_file"; then
          echo $diff_run;
          eval $diff;
        fi
    fi

done

if $SEND_MAIL;
then
  for i in ${!langs[@]};
  do
      lang=${langs[$i]}
      description="Analyze $lang rules"
      file="./analyze_rules/$lang.txt"

      message+="\n\n$description";

      cmdoutput=`cat $file`
      message+="\n$cmdoutput";
  done
fi

mj_payload(){
    currentDate=`date +"%Y-%m-%d"`
    messageJson=`echo "$message" | jq -Rsa .`
    messageJson=${messageJson//\\\\/\\}

    cat <<EOF
{
  "Messages":[
    {
      "From": { "Email": "support@witty.works" },
      "To": [{ "Email": "$STATISTICS_TO_EMAIL" }],
      "Subject": "Witty Rules Analysis: $currentDate",
      "TextPart": $messageJson
    }
  ]
}
EOF
}

if $SEND_MAIL;
then
    curl -s \
      -X POST \
      --user "$MJ_APIKEY_PUBLIC:$MJ_APIKEY_PRIVATE" \
      https://api.mailjet.com/v3.1/send \
      -H 'Content-Type: application/json' \
      -d "$(mj_payload)"
fi

