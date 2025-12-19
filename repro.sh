#!/bin/bash
#
# Reproduction script for PRECONDITION_FAILED with x-queue-type
#
# Bug: When vhost has default_queue_type set to literal string "undefined",
# queue redeclaration fails with:
#   "inequivalent arg 'x-queue-type': received 'undefined' but current is none"
#
# Requirements:
#   - RabbitMQ 3.13.x running locally
#   - rabbitmqctl and rabbitmqadmin v2 in PATH
#   - Python 3 with pika installed (pip install pika)
#
# Usage:
#   ./repro.sh

set -e

VHOST="dqt_bug_repro"
QUEUE="test_queue"

# Colors
CYAN='\033[0;36m'
YELLOW='\033[0;33m'
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

section() {
    echo ""
    echo -e "${CYAN}============================================================${NC}"
    echo -e "${CYAN}  $1${NC}"
    echo -e "${CYAN}============================================================${NC}"
    echo ""
}

run() {
    echo -e "  ${YELLOW}\$ $@${NC}"
    "$@"
}

run_eval() {
    echo -e "  ${YELLOW}\$ rabbitmqctl eval '$1'${NC}"
    rabbitmqctl eval "$1"
}

declare_queue_pika() {
    local vhost="$1"
    local queue="$2"
    local expect_fail="${3:-false}"

    echo -e "  ${YELLOW}\$ python3: pika queue_declare('$queue', durable=True)${NC}"

    python3 - "$vhost" "$queue" "$expect_fail" << 'PYTHON_EOF'
import sys
import pika

vhost = sys.argv[1]
queue = sys.argv[2]
expect_fail = sys.argv[3] == "true"

credentials = pika.PlainCredentials("guest", "guest")
parameters = pika.ConnectionParameters(
    host="localhost",
    virtual_host=vhost,
    credentials=credentials
)

try:
    connection = pika.BlockingConnection(parameters)
    channel = connection.channel()
    channel.queue_declare(queue=queue, durable=True)
    connection.close()
    if expect_fail:
        print("  \033[0;31merror: Queue declaration succeeded (bug not reproduced)\033[0m")
        sys.exit(1)
    else:
        print("  \033[0;32mQueue declared successfully.\033[0m")
except pika.exceptions.ChannelClosedByBroker as e:
    if expect_fail and "PRECONDITION_FAILED" in str(e):
        print("  \033[0;32mSuccess: got expected precondition_failed:\033[0m")
        print(f"    {e}")
    else:
        print(f"  \033[0;31merror: {e}\033[0m")
        sys.exit(1)
except Exception as e:
    print(f"  \033[0;31merror: {type(e).__name__}: {e}\033[0m")
    sys.exit(1)
PYTHON_EOF
}

# Cleanup from previous runs
section "CLEANUP"
run rabbitmqctl delete_vhost "$VHOST" 2>/dev/null || true

section "STEP 1: Create test virtual host"
run rabbitmqadmin vhosts declare --name "$VHOST"
run rabbitmqadmin permissions declare --vhost "$VHOST" --user guest --configure '.*' --write '.*' --read '.*'

section "STEP 2: Create queue with Pika (no x-queue-type argument)"
echo "Pika does NOT set x-queue-type by default for classic queues."
echo "This simulates legacy client behavior."
echo ""
declare_queue_pika "$VHOST" "$QUEUE"

section "STEP 3: Verify that the queue has no x-queue-type argument stored"
run_eval "
QName = rabbit_misc:r(<<\"$VHOST\">>, queue, <<\"$QUEUE\">>),
{ok, Q} = rabbit_amqqueue:lookup(QName),
Args = amqqueue:get_arguments(Q),
XQT = rabbit_misc:table_lookup(Args, <<\"x-queue-type\">>),
io:format(\"Stored x-queue-type: ~p~n\", [XQT])."

section "STEP 4: Check current virtual host default_queue_type metadata"
run_eval "
VHost = rabbit_vhost:lookup(<<\"$VHOST\">>),
Meta = vhost:get_metadata(VHost),
DQT = maps:get(default_queue_type, Meta, not_set),
io:format(\"Current default_queue_type: ~p~n\", [DQT])."

section "STEP 5: Set virtual host default_queue_type to literal string 'undefined'"
echo 'This simulates metadata that contains the literal string <<"undefined">>.'
echo "This can happen via definition import/export or API calls."
echo ""
run_eval "rabbit_db_vhost:merge_metadata(<<\"$VHOST\">>, #{default_queue_type => <<\"undefined\">>})."

section "STEP 6: Verify that default_queue_type is now the literal string"
run_eval "
VHost = rabbit_vhost:lookup(<<\"$VHOST\">>),
Meta = vhost:get_metadata(VHost),
DQT = maps:get(default_queue_type, Meta, not_set),
io:format(\"default_queue_type: ~p~n\", [DQT])."

section "STEP 7: Redeclare queue with Pika (should fail)"
echo "The server will inject x-queue-type from the virtual host's default_queue_type."
echo "Since it's set to 'undefined', the redeclaration will fail."
echo ""
declare_queue_pika "$VHOST" "$QUEUE" "true" || true

section "STEP 8: Work around the problem by setting the virtual host's default_queue_type to 'classic'"
run rabbitmqctl update_vhost_metadata "$VHOST" --default-queue-type classic

section "STEP 9: Verify that the metadata was changed as expected"
run_eval "
VHost = rabbit_vhost:lookup(<<\"$VHOST\">>),
Meta = vhost:get_metadata(VHost),
DQT = maps:get(default_queue_type, Meta, not_set),
io:format(\"Fixed default_queue_type: ~p~n\", [DQT])."

section "STEP 10: Redeclare queue with Pika (should succeed)"
echo "With DQT set to 'classic', the redeclaration now succeeds."
echo ""
declare_queue_pika "$VHOST" "$QUEUE"

section "CLEANUP"
echo -e "To clean up: ${YELLOW}rabbitmqctl delete_vhost $VHOST${NC}"
