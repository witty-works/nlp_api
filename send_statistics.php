<?php

$message = [];
$date = date("Y-m-d", strtotime("yesterday"));
exec("./statistics.sh", $message, $retval);

$message = implode("\n", $message);
echo "message:\n";
echo $message . "\n";

$emails = getenv('STATISTICS_TO_EMAILS_CSV');
echo "emails:\n";
echo $emails . "\n";

foreach (explode(',', $emails) as $email) {
    mail(trim($email), "Witty Statistics: $date", $message, "From: support@witty.works");
}
