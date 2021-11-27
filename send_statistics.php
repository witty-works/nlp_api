<?php

$message = [];
exec('./statistics.sh', $message, $retval);

$message = implode("\n", $message);
echo $message;

mail("everyone@witty.works", "Statistics: " . date("Y-m-d"), $message, "From: support@witty.works");
