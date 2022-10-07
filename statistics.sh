#!/bin/bash
READ_REMOTE=false 
SEND_MAIL=true

ENV=main

usage() {
  echo "Usage: $0 [ -h ] [ -r ] [ -b ] [ -e ] [ -n ] " 1>&2 
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
    r)
      READ_REMOTE=true
      ;;
    n)
      SEND_MAIL=false
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

if $SEND_MAIL;
then
    message="Collecting data for $ENV\n";
else
    message=""
    echo "Collecting data for $ENV";
fi

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

    if $SEND_MAIL;
    then
        message+="\n\n$description";

        cmdoutput=`$cmd`
        message+="\n$cmdoutput";
    else
        echo $description

        if $READ_REMOTE;
        then
          platform ssh -e $ENV -A app "$cmd";
        else
          eval $cmd;
        fi
    fi

done

mj_payload(){
    currentDate=`date +"%Y-%m-%d"`
    messageJson=`echo "$message" | jq -Rsa .`
    messageJson=${messageJson//\\\\/\\}

    cat <<EOF
{
  "Messages":[
    {
      "From": { "Email": "support@witty.works" },
      "To": [{ "Email": "$ANALYZE_RULES_EMAIL" }],
      "Subject": "Witty Statistics: $currentDate",
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

