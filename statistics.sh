


echo "Number if installations"

platform ssh -e main -A app "ls user_training_data/ | wc -l"

echo "Number of total requests and click on alternatives/ignores"

platform ssh -e main -A app "find user_training_data -type f | wc -l"

echo "Number of clicks on an alternative"


platform ssh -e main -A app "ls user_training_data/ | grep -r '\"alternative\"' | wc -l"

echo "Number of clicks on ignore"

platform ssh -e main -A app "ls user_training_data/ | grep -r '\"igore\"' | wc -l"