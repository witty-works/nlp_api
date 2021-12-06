<?php

$message = [];
$date = date("Y-m-d", strtotime("yesterday"));
exec("./statistics.sh -b -d $date", $message, $retval);

$message = implode("\n", $message);
echo $message;

mail("everyone@witty.works", "Witty Statistics: $date", $message, "From: support@witty.works");
