# Reproduction of a DQT Bug Triggered by rabbitmq/rabbitmq-server#10469

This repository demonstrates a previously addressed (see a list of pull requests below) bug in RabbitMQ 3.13.x
where queue redeclaration fails with `PRECONDITION_FAILED` when a virtual host has `default_queue_type` set to "undefined" (not the `undefined` atom or a valid queue type alias).

## The Root Cause

In the `3.13` series, when a virtual host has a `default_queue_type` [metadata](https://www.rabbitmq.com/docs/vhosts#metadata) field set to
an unsupported value, the queue property equivalence check fails in [`rabbit_misc:assert_args_equivalence/4`](https://github.com/rabbitmq/rabbitmq-server/blob/v3.13.x/deps/rabbit_common/src/rabbit_misc.erl#L329-L346), that is propagated to the client
as a `PRECONDITION_FAILED` channel exception:

```
2025-12-11 16:43:11.185170-06:00 [error] <0.52727231.0> operation queue.declare caused a channel exception precondition_failed: inequivalent arg 'x-queue-type' for queue 'cq.1' in vhost 'vhost1': received the value 'undefined' of type 'longstr' but current is none
2025-12-11 16:43:11.185429-06:00 [error] <0.52727216.0> operation queue.declare caused a channel exception precondition_failed: inequivalent arg 'x-queue-type' for queue 'cq.2' in vhost 'vhost2': received the value 'undefined' of type 'longstr' but current is none
```

### Related Issues

The following issues significantly increase the probability of hitting this bug:

 * [rabbitmq/rabbitmq-server#10469](https://github.com/rabbitmq/rabbitmq-server/discussions/10469) — export sets DQT to undefined
 * [rabbitmq/rabbitmq-server#5399](https://github.com/rabbitmq/rabbitmq-server/issues/5399) — definition import ignores DQT


## Requirements

 * RabbitMQ 3.13.x running locally with default guest:guest credentials
 * `rabbitmqctl` in `PATH`
 * [`rabbitmqadmin` v2](https://www.rabbitmq.com/docs/management-cli) in `PATH`
 * Python 3.8+ with `pip`


## Files

| File | Description |
|------|-------------|
| `requirements.txt` | Python dependencies |
| `repro.py` | Repro steps using Python and the Pika client |
| `repro.sh` | A shell script that drives `rabbitmqctl`, `rabbitmqadmin`, and Pika client-based scripts |
| `workaround.py` | Applies a workaround to all virtual hosts |

## Resolution and a Workaround Available

This issue is addressed with a series of other changes around how Default Queue Type is used:

1. [rabbitmq/rabbitmq-server#11541](https://github.com/rabbitmq/rabbitmq-server/pull/11541) (shipped in 3.13.4)
2. [rabbitmq/rabbitmq-server#12109](https://github.com/rabbitmq/rabbitmq-server/pull/12109) (shipped in 4.0.5)
3. [rabbitmq/rabbitmq-server#12821](https://github.com/rabbitmq/rabbitmq-server/pull/12821) (shipped in 4.0.5)
4. [rabbitmq/rabbitmq-server#13837](https://github.com/rabbitmq/rabbitmq-server/pull/13837) (shipped in 4.1.1)

For RabbitMQ 3.13.4 and later versions, there is a workaround: explicitly set the default queue type for every affected virtual host
and [set `default_queue_type`](https://www.rabbitmq.com/docs/vhosts#default-queue-type) to `classic` in the `rabbitmq.conf` file, to be used by all future virtual hosts.

Using `rabbitmqctl`:

```bash
rabbitmqctl update_vhost_metadata <vhost_name> --default-queue-type classic
```

Using `rabbitmqadmin` v2:

```bash
rabbitmqadmin vhosts declare --name <vhost_name> --default-queue-type classic
```

Or inspect and use `workaround.py` in this very repository:

```bash
pip install -r requirements.txt
python3 workaround.py
```

### Using `rabbitmqctl eval`

For environments that have `rabbitmqctl` access and a large number of virtual hosts,
the following `rabbitmqctl eval` snippet will set `default_queue_type` to `classic` for all vhosts that don't have it set (proactively) or have it set to
a value that is not correctly compared for equivalence:

```bash
rabbitmqctl eval '
lists:foreach(
  fun(VHostName) ->
    VHost = rabbit_vhost:lookup(VHostName),
    Meta = vhost:get_metadata(VHost),
    case maps:get(default_queue_type, Meta, undefined) of
      undefined ->
        rabbit_db_vhost:merge_metadata(VHostName, #{default_queue_type => <<"classic">>}),
        io:format("Set DQT for virtual host ~p (was not set)~n", [VHostName]);
      <<"undefined">> ->
        rabbit_db_vhost:merge_metadata(VHostName, #{default_queue_type => <<"classic">>}),
        io:format("Set DQT for virtual host ~p (was <<\"undefined\">>)~n", [VHostName]);
      DQT ->
        io:format("Virtual host ~p already has DQT = ~p~n", [VHostName, DQT])
    end
  end,
  rabbit_vhost:list_names()),
ok.
'
```

In addition, the following snippet can be used to set `x-queue-type` to `classic` for all queues that don't have it set
or have it set to a value that is not correctly compared for equivalence.

This can be useful for ensuring that management UI pages do not display queue
type as `undefined`, causing doubt.

```bash
rabbitmqctl eval '
lists:foreach(
  fun(Q) ->
    QName = amqqueue:get_name(Q),
    Args = amqqueue:get_arguments(Q),
    case rabbit_misc:table_lookup(Args, <<"x-queue-type">>) of
      undefined ->
        NewArgs = rabbit_misc:set_table_value(Args, <<"x-queue-type">>, longstr, <<"classic">>),
        rabbit_db_queue:update(QName, fun(Q0) -> amqqueue:set_arguments(Q0, NewArgs) end),
        io:format("Set x-queue-type for ~p to <<\"classic\">> (was not set)~n", [QName]);
      {longstr, <<"undefined">>} ->
        NewArgs = rabbit_misc:set_table_value(Args, <<"x-queue-type">>, longstr, <<"classic">>),
        rabbit_db_queue:update(QName, fun(Q0) -> amqqueue:set_arguments(Q0, NewArgs) end),
        io:format("Set x-queue-type for ~p to <<\"classic\">> (was <<\"undefined\">>)~n", [QName]);
      {_Type, Val} ->
        io:format("Queue ~p already has x-queue-type = ~p~n", [QName, Val])
    end
  end,
  rabbit_amqqueue:list()),
ok.
'
```
