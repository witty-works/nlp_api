#!/bin/bash
set -e

# start sshd
/usr/sbin/sshd

# calculate 80% of available memory for java heap size
avail_mem=$(free -m | awk '/Mem:/ {print $2}')
heap=$(echo -n "${avail_mem}/100*${HEAP_PERCENTAGE}" | bc)

echo "==== initializing language tool ===="
echo "Found available memory: ${avail_mem}"
echo "Calculated heap size (by percentage ${HEAP_PERCENTAGE}): ${heap}" 
echo ""

su-exec languagetool java -noverify \
    -Xms${heap}M \
    -Xmx${heap}M \
    -XX:+UseG1GC \
    -XX:+UseStringDeduplication \
    -cp languagetool-server.jar org.languagetool.server.HTTPServer \
    --public \
    --config server.properties \
    --port $PORT \
    --allow-origin "*"
