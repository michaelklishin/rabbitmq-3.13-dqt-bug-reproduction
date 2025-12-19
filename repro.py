#!/usr/bin/env python3
"""
Reproduction script for PRECONDITION_FAILED with x-queue-type

Bug: When vhost has default_queue_type set to literal string "undefined",
queue redeclaration fails with:
  "inequivalent arg 'x-queue-type': received 'undefined' but current is none"

Requirements:
  - RabbitMQ 3.13.x running locally
  - rabbitmqctl and rabbitmqadmin v2 in PATH
  - pip install pika

Usage:
  python3 repro.py
"""

import subprocess
import sys

try:
    import pika
except ImportError:
    print("error: pika not installed. Run: pip install pika")
    sys.exit(1)

VHOST = "dqt_bug_repro"
QUEUE = "test_queue"

# ANSI colors
CYAN = "\033[0;36m"
YELLOW = "\033[0;33m"
GREEN = "\033[0;32m"
RED = "\033[0;31m"
NC = "\033[0m"


def section(title):
    print()
    print(f"{CYAN}============================================================{NC}")
    print(f"{CYAN}  {title}{NC}")
    print(f"{CYAN}============================================================{NC}")
    print()


def run(cmd, check=True, shell=False):
    """Run a command and print it."""
    if isinstance(cmd, list):
        cmd_str = " ".join(cmd)
    else:
        cmd_str = cmd
        shell = True
    print(f"  {YELLOW}$ {cmd_str}{NC}")
    result = subprocess.run(cmd, shell=shell, capture_output=True, text=True)
    if result.stdout.strip():
        print(result.stdout)
    if result.stderr.strip():
        print(result.stderr)
    if check and result.returncode != 0:
        raise subprocess.CalledProcessError(result.returncode, cmd)
    return result


def run_eval(erlang_code):
    """Run rabbitmqctl eval and print it."""
    display_code = " ".join(erlang_code.split())
    print(f"  {YELLOW}$ rabbitmqctl eval '{display_code}'{NC}")
    result = subprocess.run(
        ["rabbitmqctl", "eval", erlang_code],
        capture_output=True,
        text=True
    )
    if result.stdout.strip():
        print(result.stdout)
    if result.stderr.strip():
        print(result.stderr)
    return result


def declare_queue_pika(vhost, queue, expect_fail=False):
    """Declare a queue using Pika (does NOT set x-queue-type by default)."""
    print(f"  {YELLOW}$ python: pika queue_declare('{queue}', durable=True){NC}")

    credentials = pika.PlainCredentials("guest", "guest")
    parameters = pika.ConnectionParameters(
        host="localhost",
        virtual_host=vhost,
        credentials=credentials
    )

    try:
        connection = pika.BlockingConnection(parameters)
        channel = connection.channel()
        # Pika does NOT set x-queue-type by default - this is key!
        channel.queue_declare(queue=queue, durable=True)
        connection.close()
        if expect_fail:
            print(f"  {RED}error: Queue declaration succeeded (bug not reproduced){NC}")
            return False
        else:
            print(f"  {GREEN}Queue declared successfully.{NC}")
            return True
    except pika.exceptions.ChannelClosedByBroker as e:
        if expect_fail and "PRECONDITION_FAILED" in str(e):
            print(f"  {GREEN}Success: got expected precondition_failed:{NC}")
            print(f"    {e}")
            return True
        else:
            print(f"  {RED}error: {e}{NC}")
            return False
    except Exception as e:
        print(f"  {RED}error: {type(e).__name__}: {e}{NC}")
        return False


def main():
    # Cleanup from previous runs
    section("CLEANUP")
    run(["rabbitmqctl", "delete_vhost", VHOST], check=False)

    section("STEP 1: Create test virtual host")
    run(["rabbitmqadmin", "vhosts", "declare", "--name", VHOST])
    run(["rabbitmqadmin", "permissions", "declare",
         "--vhost", VHOST, "--user", "guest",
         "--configure", ".*", "--write", ".*", "--read", ".*"])

    section("STEP 2: Create queue with Pika (no x-queue-type argument)")
    print("Pika does NOT set x-queue-type by default for classic queues.")
    print("This simulates legacy client behavior.")
    print()
    if not declare_queue_pika(VHOST, QUEUE):
        sys.exit(1)

    section("STEP 3: Verify that the queue has no x-queue-type argument stored")
    run_eval(f'''
        QName = rabbit_misc:r(<<"{VHOST}">>, queue, <<"{QUEUE}">>),
        {{ok, Q}} = rabbit_amqqueue:lookup(QName),
        Args = amqqueue:get_arguments(Q),
        XQT = rabbit_misc:table_lookup(Args, <<"x-queue-type">>),
        io:format("Stored x-queue-type: ~p~n", [XQT]).
    ''')

    section("STEP 4: Check current virtual host default_queue_type metadata")
    run_eval(f'''
        VHost = rabbit_vhost:lookup(<<"{VHOST}">>),
        Meta = vhost:get_metadata(VHost),
        DQT = maps:get(default_queue_type, Meta, not_set),
        io:format("Current default_queue_type: ~p~n", [DQT]).
    ''')

    section("STEP 5: Set virtual host default_queue_type to literal string 'undefined'")
    print('This simulates metadata that contains the literal string <<"undefined">>.')
    print("This can happen via definition import/export or API calls.")
    print()
    run_eval(f'rabbit_db_vhost:merge_metadata(<<"{VHOST}">>, #{{default_queue_type => <<"undefined">>}}).')

    section("STEP 6: Verify that default_queue_type is now the literal string")
    run_eval(f'''
        VHost = rabbit_vhost:lookup(<<"{VHOST}">>),
        Meta = vhost:get_metadata(VHost),
        DQT = maps:get(default_queue_type, Meta, not_set),
        io:format("default_queue_type: ~p~n", [DQT]).
    ''')

    section("STEP 7: Redeclare queue with Pika (should fail)")
    print("The server will inject x-queue-type from the virtual host's default_queue_type.")
    print("Since it's set to 'undefined', the redeclaration will fail.")
    print()
    declare_queue_pika(VHOST, QUEUE, expect_fail=True)

    section("STEP 8: Work around the problem by setting the virtual host's DQT to 'classic'")
    run(["rabbitmqctl", "update_vhost_metadata", VHOST, "--default-queue-type", "classic"])

    section("STEP 9: Verify that the metadata was changed as expected")
    run_eval(f'''
        VHost = rabbit_vhost:lookup(<<"{VHOST}">>),
        Meta = vhost:get_metadata(VHost),
        DQT = maps:get(default_queue_type, Meta, not_set),
        io:format("Fixed default_queue_type: ~p~n", [DQT]).
    ''')

    section("STEP 10: Redeclare queue with Pika (should succeed)")
    print("With DQT set to 'classic', the redeclaration now succeeds.")
    print()
    declare_queue_pika(VHOST, QUEUE)

    section("CLEANUP")
    print(f"To clean up: {YELLOW}rabbitmqctl delete_vhost {VHOST}{NC}")


if __name__ == "__main__":
    main()
