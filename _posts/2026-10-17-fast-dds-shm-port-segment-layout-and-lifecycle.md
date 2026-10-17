---
layout: post
title: "Fast DDS: SHM port segment layout and lifecycle"
date: 2026-10-17 07:01:00 +0800
tags: [dds, fast-dds, shared-memory, networking]
---

This note covers SHM **port segments**, not payload data segments. It assumes one unicast, ReadExclusive receiver per port and any number of writers. "Reader" means the SHM receive-channel owner and its port listener, not necessarily a DDS DataReader. The sequences below describe source-code paths, not guaranteed recovery outcomes.

* toc
{:toc}

## Port segment memory layout

`fastrtps_port<P>` is one named Boost managed shared-memory object: a continuous mapped byte range. `init_port()` requests a named PortNode, then an anonymous PortCell array, then an anonymous ring-control Node; the managed-segment allocator also stores metadata. The downward stream below expands the fields that matter to send, receive, and watchdog checks. It is a **logical linearization**, not a measured byte map or a guarantee of physical offsets, padding, or allocation order.

~~~text
fastrtps_port<P>  (conceptual low-to-high stream; not a literal offset dump)
mapping start
    |
    v
+---------------------------------------------------------------------------------------------+
| Boost managed-segment metadata / allocator bookkeeping                                      |
| The allocator manages named and anonymous allocations inside this same mapping.             |
+---------------------------------------------------------------------------------------------+
    |
    v
+---------------------------------------------------------------------------------------------+
| PortNode named "port_node_abi5" (one object, fields in source declaration order)            |
| last_listeners_status_check_time_ms : atomic timestamp for watchdog scan interval           |
| ref_counter                         : atomic count of Port wrappers mapping this generation |
| buffer                              : segment-relative offset of PortCell[capacity]         |
| buffer_node                         : segment-relative offset of ring Node                  |
| port_id                             : numeric P                                             |
| num_listeners                       : registered listener-status slots                      |
| healthy_check_timeout_ms           : timeout used by port health checks                     |
| port_wait_timeout_ms               : receive timed-wait interval                            |
| max_buffer_descriptors             : ring capacity                                          |
| waiting_count                      : number of listeners currently waiting                  |
| is_port_ok                         : shared health bit                                      |
| is_opened_read_exclusive           : shared exclusive-reading bit                           |
| is_opened_for_reading              : shared reading-opened bit                              |
| uuid                               : identity of this port generation                       |
| empty_cv                           : interprocess condition variable                        |
| empty_cv_mutex                     : interprocess mutex guarding wait/status operations     |
| listeners_status[1024]             : fixed array of ListenerStatus entries                  |
|   each entry: is_in_use, is_waiting, is_processing                                          |
|               counter, last_verified_counter                                                |
|               descriptor {source_segment_id, buffer_node_offset, validity_id}               |
| domain_name                        : SHM domain stored in the node                          |
+---------------------------------------------------------------------------------------------+
    |
    v
+---------------------------------------------------------------------------------------------+
| PortCell[capacity] (anonymous allocation; default capacity = 512)                           |
| each cell.ref_counter_             : remaining listeners for this descriptor                |
| each cell.data_                    : BufferDescriptor                                       |
|   {source_segment_id, buffer_node_offset, validity_id}                                      |
|   Descriptor points to payload in a separate fastrtps_<source-segment-id> object.           |
+---------------------------------------------------------------------------------------------+
    |
    v
+---------------------------------------------------------------------------------------------+
| Ring Node (anonymous allocation)                                                            |
| pointer_                           : atomic {write_p, free_cells}                           |
| total_cells_                       : ring capacity                                          |
| registered_listeners_             : number of ring consumers                                |
+---------------------------------------------------------------------------------------------+
    |
    v
+---------------------------------------------------------------------------------------------+
| Remaining managed-segment capacity                                                          |
| Available for allocator bookkeeping/alignment; not a message-payload heap.                  |
+---------------------------------------------------------------------------------------------+
    |
    v
mapping end

Outside this port segment:
  fastrtps_port<P>_mutex                              # Named lifecycle mutex; not PortNode.empty_cv_mutex.
  fastrtps_port<P>_el / _sl                           # Separate reader-ownership lock files.
  process-local Port wrapper / Listener / WatchTask  # Mapping, read cursor, watchdog PortContext.
  fastrtps_<source-segment-id>                       # Separate payload data segment.
~~~

The watchdog reads `PortNode.listeners_status[]`, `num_listeners`, and `last_listeners_status_check_time_ms`; it sets PortNode.`is_port_ok=false` on failure. Its `PortContext.last_checked_buffer[]` history lives in the watching **process**, not in `fastrtps_port<P>`. A listener's ring read cursor is likewise process-local, while its status slot and the ring's write/free-cell state are shared.

The pseudocode below follows the v2.6.10 call paths. A descriptor lives in this port segment; its payload lives in a separate data segment.

~~~text
function RING_PUSH(port, descriptor):
    lock port.PortNode.empty_cv_mutex
    if !port.PortNode.is_port_ok:
        unlock; throw "port not ok"
    if port.RingNode.registered_listeners_ == 0:
        unlock; return NO_LISTENERS                # Nothing is enqueued.
    if port.RingNode.free_cells == 0:
        unlock; return FULL                        # Drop this descriptor; do not regenerate.
    index = port.RingNode.write_p
    atomically advance write_p and decrement free_cells
    port.PortCell[index].data_ = descriptor
    port.PortCell[index].ref_counter_ = registered_listeners_
    was_waiting = (port.PortNode.waiting_count > 0)
    unlock port.PortNode.empty_cv_mutex
    if was_waiting:
        notify listener(s)
    return ENQUEUED

function WRITER_SEND(payload, remote_locator_P):
    if Linux:
        for each cached output port Q:
            if !(Q.is_port_ok && Q.is_opened_for_reading && Q.num_listeners > 0):
                evict Q from opened_ports_          # cleanup_output_ports()
    shared_buffer = copy payload into separate fastrtps_<source-segment-id>
    descriptor = {source_segment_id, buffer_node_offset, validity_id}
    for attempt in 1..2:                            # push_discard()
        port = opened_ports_[P] or open_port(P, Write)
        try:
            result = RING_PUSH(port, descriptor)    # SharedMemManager::Port::try_push()
            if result == ENQUEUED or result == NO_LISTENERS:
                return                              # NO_LISTENERS undoes enqueued count.
            if result == FULL:
                continue                            # is_port_ok remains true.
        catch error:
            if port.is_port_ok:
                propagate error
            port.regenerate_port()                   # Same P; may throw or fail.
            evict P from opened_ports_
            continue                                # Retry via find_port(P).
    return                                          # push_discard() may report success after drops.

function READER_POP(listener):
    try:
        while listener.head() == null:              # read_p is process-local.
            listener.port.wait_pop()                # Check is_port_ok before/after timed waits.
        if !listener.port.is_port_ok:
            throw "port not ok"
        descriptor = listener.head().data_
        last_consumer = listener.ring.pop()          # Decrement cell.ref_counter_; advance read_p.
        if last_consumer:
            atomically increment RingNode.free_cells
        buffer = resolve descriptor in separate data segment
        mark listener_status.is_processing = true
        return buffer                               # Caller later clears is_processing.
    catch error:
        if listener.port.is_port_ok:
            propagate error
        listener.regenerate_port()                   # Same P; create a new listener; may fail.
        return null

function PORT_WATCH_TASK(port):
    if listener-status check is due:
        lock port.PortNode.empty_cv_mutex
        defer unlock port.PortNode.empty_cv_mutex
        if any listener is stuck processing the same descriptor,
           or a waiting listener's counter has not advanced,
           or in-use listener count != num_listeners,
           or the check throws:
            port.PortNode.is_port_ok = false        # Does not unlink or recreate P.

# Both recovery paths call open_port_internal(P, mode); see Section 1 for its logic.
# They keep numeric P; neither mutates or re-advertises the locator.
# A surviving reader reaches it from READER_POP's bad-port catch.
# On Linux a writer normally evicts bad P at its next WRITER_SEND and reopens it;
# it may instead regenerate if P becomes bad after cleanup but before RING_PUSH.
# A crashed reader cannot regenerate; without another send/pop/open, no replacement occurs.
~~~

## Objects and names

- The transport's SHM domain is "fastrtps". Port ID P names segment "`fastrtps_port<P>`" and is carried in the SHM locator. The segment contains a PortNode, descriptor ring, listener-status slots, and shared `ref_counter`.
- "`fastrtps_port<P>_mutex`" serializes named-port open/create/regenerate operations. On Linux the named mutex may appear as a "sem." entry under `/dev/shm`.
- "`fastrtps_port<P>_el`" is the ReadExclusive receiver's robust file lock. Write-mode users do not hold it.
- Every `SharedMemGlobal::Port` wrapper, reader-side or writer-side, increments the shared `ref_counter` and registers a PortContext with its process-local `Port::WatchTask`. Its destructor decrements `ref_counter`.
- The process that physically calls `create_only` is not necessarily the logical receiver. Unlink removes a name; it does not invalidate other processes' existing mappings of the old object.

## 1. Shared core: `SharedMemGlobal::open_port_internal()`

Both sides enter this function through `SharedMemManager::open_port()`: the receiver uses ReadExclusive, and the writer uses Write on a cache miss. The function also supports ReadShared, which is outside this note's single-exclusive-receiver scenario. Its named mutex serializes the open/create decision for one port number; `_el` represents exclusive receive ownership, not writer ownership or listener health. The code below follows the v2.6.10 implementation, including its exception-driven create fallback.

Parameters (source names in parentheses):

- P (`port_id`): numeric destination port ID. It forms the shared-memory name `fastrtps_port<P>`; the receiver passes its candidate locator port, while the writer passes the remote locator port.
- capacity (`max_buffer_descriptors`): descriptor-ring capacity **if this call creates a new segment**; it does not resize an existing port. The transport passes `port_queue_capacity()` (default 512).
- `health_timeout` (`healthy_check_timeout_ms`): timeout in milliseconds for `healthy_check()` on an existing port. A new port stores this value in its PortNode and derives its receive-wait timeout as one third of it. The transport default is 1000 ms.
- mode (`open_mode`): ReadExclusive for the unicast receiver or Write for a sender; ReadShared is also supported for multicast ports. It controls reader-lock acquisition and the new port's reading flags.
- `regenerating_port`: nullptr for ordinary `open_port()`; `regenerate_port()` passes the existing Port wrapper, from which it also obtains P, capacity, and `health_timeout`. Its read locks are released (best effort) before the open/create attempt.

~~~text
open_port_internal(P, capacity, health_timeout, mode, regenerating_port):
  port = nullptr
  lock "fastrtps_port<P>_mutex"                                                   # Held until return or exception.
  if regenerating_port:
    try regenerating_port.unlock_read_locks()                                    # Best effort; release its old reader lock first.

  try OPEN_EXISTING:
    if is_zombie(P):
      unlink named segment P; throw to CREATE                                    # Zombie probe examines lock files, not segment existence.
    segment = open_only(P)                                                       # Missing named port (or any other open error) falls through to CREATE.
    try:
      require segment.check_sanity()                                             # Validate the managed-segment allocator.
      require PortNode with current ABI name                                     # Reject incompatible/missing ABI; no cross-version reuse.
      port = Port(segment, node)                                                 # Increment shared ref_counter; register watch context.
    catch:
      unlink named segment P; throw to CREATE                                    # Any creator; old mapped inodes survive the name removal.

    try:
      if mode == ReadExclusive:
        if port.lock_read_exclusive(_el) fails:
          port.reset(); skip health check; go to RESULT                           # P is occupied by another reader (or _el failed); throw, then caller may mutate P.
      if mode == Write: do not acquire _el                                       # A writer may open P while the receiver holds _el.
      if port != nullptr:                                                        # Existing P may be reader- or writer-created; reuse still needs health check.
        port.healthy_check()                                                     # Both modes check status; it may throw and enter the catch below.
        node.is_opened_read_exclusive |= (mode == ReadExclusive)
        node.is_opened_for_reading |= (mode != Write)
        go to RESULT
    catch:
      port.unlock_read_locks()                                                   # Only a reader may have a lock to release.
      node.is_port_ok = false
      unlink named segment P; throw to CREATE                                    # Unhealthy existing object is replaced by name.

  catch CREATE:
    try new_segment = create_only(P)                                             # Same name, caller's ABI; later opens can map new inode, old FDs stay old.
    catch: new_segment = nullptr                                                # Creation failure does not replace an existing port wrapper.
    if new_segment != nullptr:
      try:
        pre-fault/initialize segment storage
        port = init_port(P, new_segment, mode, health_timeout)                   # ReadExclusive acquires _el; Write does not; then init node/ring and Port.
      catch:
        unlink newly named segment P; throw                                     # init_port failure escapes to caller.

  RESULT:
    if port == nullptr: throw "Couldn't open port"                               # Receiver caller may mutate P; writer caller cannot.
    return port                                                                  # Named *_mutex is released on exit.
~~~

`is_zombie`(P) returns true if an existing `_el` file can be exclusively locked, or if an existing `_sl` file has no remaining shared-lock holder. It does not inspect the port segment. A held `_el` therefore does not stop the writer from trying the existing segment; a competing ReadExclusive receiver only fails later when it attempts to acquire `_el`. An absent `_el` can mean a writer-created port, which a receiver may reuse after claiming `_el` and passing the checks.

The synchronous `healthy_check()` is an **open-time check**, distinct from the periodic watchdog below. It tests `is_port_ok` and listener status for up to `healthy_check_timeout_ms` (default 1000 ms). The create fallback can be reached from either mode after zombie, open, sanity/ABI, or health failure. Conversely, the receiver's failed `_el` acquisition clears port and exits with an error rather than recreating a healthy port owned by another receiver.

One source-level corner case remains: after a health failure, the old port wrapper is not reset before `create_only`(P). If creation also fails, the final null check can return that old, unlinked mapping. Returning a wrapper is therefore not by itself proof that it maps the object currently named P.

## 2. Reader creates or opens its receive port

The participant computes an initial candidate, then attempts to bind a receive channel before enabling discovery. The default rules and retries are:

~~~text
RTPSDomainImpl::prepare_participant_id(input_id)
  input_id >= 0 -> use configured participant ID (check uniqueness in this process)
  input_id < 0  -> getNewId(): smallest ID neither used nor reserved in this process

Default PortParameters:
  portBase=7400; domainIDGain=250; participantIDGain=2
  metatraffic unicast offsetd1=10
  user/default unicast offsetd3=11

For domain D and participant ID I:
  metatraffic unicast candidate = 7400 + 250*D + 10 + 2*I
  user/default unicast candidate = 7400 + 250*D + 11 + 2*I

Example for D=0, I=0:
  metatraffic = 7410; user/default = 7411
~~~

The participant ID allocator is process-local, not host-global. On the same host and domain, processes that allocate the same participant IDs with the default port parameters deterministically compute the same initial port candidates; with multiple participants per process, their candidate sequences can overlap repeatedly. This makes initial port collisions expected, not exceptional. The named-port and ReadExclusive locks prevent two live receivers from claiming the same port, but successful mutation retries are essential: each receiver must find another port and retain that successful port in its locator before it can receive there.

Mutation happens on a failed receiver-resource build, not only when another receiver owns the `_el` lock; permission errors or other opening failures can also trigger it. The first candidate plus 100 retries means up to 101 attempted ports per locator with default settings. For example, 7413 could be the initial user port for I=1 or the first mutation from I=0; a port number alone does not identify the participant ID. If all retries fail, `createReceiverResources()` omits that locator from its output list and logs a warning; only successful locators are retained for advertisement.

The following is one call chain. The initial attempt and each retry call the **same** `NetworkFactory::BuildReceiverResources()` function; the retry is not a separate creation path.

~~~text
RTPSDomain::createParticipant
  -> prepare_participant_id()                                                   # Select a process-local ID; no host-wide port reservation.
  -> RTPSParticipantImpl constructor
     -> populate SHM Locator_t list with candidate ports                        # Use default formulas or configured values; no named port mutex is held.
     -> createReceiverResources(locator_list&, ApplyMutation=true)              # Constructor passes RegisterReceiver=false.
        for each Locator_t& loc in the mutable list:                            # loc.port already contains candidate P0.
          attempt 0:
            ret = NetworkFactory::BuildReceiverResources(loc)
              -> if this transport's input channel is not already open:
                 construct ReceiverResource(transport, loc)
                   -> SharedMemTransport::OpenInputChannel(loc)
                      -> CreateInputChannelResource(loc)                        # Select ReadExclusive for unicast SHM.
                         -> SharedMemManager::open_port(loc.port, ReadExclusive)
                            -> SharedMemGlobal::open_port_internal(loc.port)    # ReadExclusive branch of shared core in section 1.
                         -> on success: Port::create_listener()                 # After *_mutex is released, use empty_cv_mutex to reserve a slot and increment num_listeners.
                      -> channel owns listener and starts its receive thread
              -> if channel was already open: return success without opening it again
          if !ret && ApplyMutation:
            for retry = 1..mutation_tries (default 100):
              applyLocatorAdaptRule(loc): loc.port += participantIDGain         # Mutate the same locator outside *_mutex; default gain is +2.
              ret = NetworkFactory::BuildReceiverResources(loc)                 # Re-enter the attempt-0 path at the new port.
              if ret: break
          for each newly returned ReceiverResource:
            retain it and create a MessageReceiver                              # Registration happens later.
          success -> append loc with working P to the output locator list
          exhausted retries -> omit loc from that list and log a warning         # No receive resource or advertised locator for it.
     -> initialize builtin protocols with the possibly mutated locator lists
  -> after construction, RTPSDomain::createParticipant calls enable()
     -> enable builtin protocols and register MessageReceivers to start reception
~~~

A reader can also open a segment created earlier by a writer in Write mode: it acquires `_el`, passes the existing-port checks, marks the port opened for reading, and registers the first listener. Conversely, `create_only` succeeding does not guarantee that `init_port()` succeeds: acquiring `_el` can still fail, in which case this creation attempt removes the new segment name.

## 3. Writer opens or creates the destination port

A writer uses the destination's SHM locator P. Its transport caches writer-side Port wrappers in `opened_ports_[P]`. The cache key is the numeric port ID, not the segment inode or generation.

~~~text
SharedMemTransport::send(destination P)
  -> cleanup_output_ports()
     -> evict cached ports for which has_listeners() is false
  -> find_port(P)
     -> opened_ports_[P] exists? reuse its Port wrapper and mapping
     -> otherwise open_port(P, Write)
        -> open_port_internal(P, Write)                                          # Write branch of shared core in section 1.
        -> cache wrapper in opened_ports_[P]
  -> try_push(descriptor into P)
~~~

Normally the reader opens P before advertising it, so a writer opens the existing segment. But `open_port_internal()` also permits **Write mode to create** a segment: the named object may be absent, or an old zombie, incompatible, or unhealthy one may have been unlinked. A writer can reach this path with a previously learned locator or a configured/derived peer locator; it is not the normal new-reader announcement sequence.

~~~text
Writer creates P in Write mode:
  create_only("fastrtps_port<P>")
  -> no ReadExclusive _el lock
  -> num_listeners=0; is_opened_for_reading=false; is_port_ok=true
  -> writer Port wrapper: ref_counter++
  -> no consumer until a reader opens P and registers a listener
~~~

The send path's `has_listeners()` condition is `is_port_ok` && `is_opened_for_reading` && `num_listeners` > 0. If a cached writer wrapper still maps an old unlinked object, `find_port`(P) does **not** compare its inode or PortNode UUID with the current object named P. Same-name recreation alone therefore does not rebind that writer. Eviction, regeneration on a failed push, or transport teardown must release the old wrapper.

## 4. Periodic Port WatchTask examines port health

The process-local SharedMemWatchdog worker wakes about every 1000 ms and runs registered tasks sequentially. Each Port wrapper, whether opened by a receiver or a writer, registers a PortContext with its process's `Port::WatchTask`. The context holds this process's previous-descriptor history; the listener status, check timestamp, and `is_port_ok` bit live in the mapped PortNode and can be examined by watchdogs in different processes.

~~~text
SharedMemWatchdog::run():
  while not exiting:
    wait up to 1000 ms
    lock process-local task set
    for each registered task:
      task.run()                                                     # Sequential; no per-port worker.

Port::WatchTask::run():
  now = current high-resolution-clock time
  lock this process's watched_ports_ list
  for each watched PortContext ctx:
    node = ctx.node
    if now - node.last_listeners_status_check_time_ms
         <= node.healthy_check_timeout_ms:
      continue                                                       # Shared timestamp gates this check.
    try:
      lock node.empty_cv_mutex
      if now - node.last_listeners_status_check_time_ms
           > node.healthy_check_timeout_ms:                         # Recheck after acquiring the lock.
        if !CHECK_LISTENERS(ctx):
          node.is_port_ok = false                                    # Mark bad; do not unlink/recreate.
      unlock node.empty_cv_mutex
    catch std::exception:
      node.is_port_ok = false
      log warning
      remove ctx from this process's watched_ports_ list            # Exception path stops watching it.

CHECK_LISTENERS(ctx) -> bool:
  node = ctx.node
  listeners_found = 0
  for i = 0 .. 1023:
    status = node.listeners_status[i]
    if !status.is_in_use:
      continue
    listeners_found += 1

    if status.is_processing:
      if status.descriptor == ctx.last_checked_buffer[i]:
        return false                                                # Same descriptor across checks: stuck.
      ctx.last_checked_buffer[i] = status.descriptor                # Remember in this watchdog process.
    else:
      ctx.last_checked_buffer[i] = empty descriptor
      if status.is_waiting:                                        # Timed waits provide a heartbeat without messages.
        if status.counter == status.last_verified_counter:
          return false                                              # No new wait heartbeat since the last verification.
        status.last_verified_counter = status.counter               # Save heartbeat baseline; NOT a messages-read count.
      # is_waiting=0 and is_processing=0: no counter/progress test.

    if listeners_found == node.num_listeners:
      break                                                         # Remaining slots are not inspected.

  node.last_listeners_status_check_time_ms = current time           # Only reached after the scan.
  return listeners_found == node.num_listeners                       # Mismatch means bad registration/count.
~~~

A listener's `wait_pop()` sets `is_waiting=1` and writes counter=`last_verified_counter`+1, including after each timed wait; normal exit from the wait clears `is_waiting`. This small counter is a timed-wait heartbeat, not a count of descriptors read. Starting and finishing buffer processing set and clear `is_processing`. Listener registration/unregistration updates `is_in_use` and `num_listeners`. The default `healthy_check_timeout_ms` is 1000 ms, and the receive wait timeout is one third of it; scheduling or lock contention can delay detection beyond one second.

### Potential blind spot: a crashed listener in the idle state

This failure path requires a receiver to crash while its registered listener has `is_waiting=0` and `is_processing=0`. Both flags start at zero, and a live listener also briefly enters this state between waiting and processing, or between processing and its next wait. An abrupt exit leaves `is_in_use=1` and `num_listeners` unchanged in the old port generation.

~~~text
1. Crash is missed in old generation G1
   listener slot: is_in_use=1, is_waiting=0, is_processing=0
   WatchTask: no progress test for this slot; if counts and other slots pass, G1 stays OK
   G1: is_port_ok=true, is_opened_for_reading=true, num_listeners>0
   Writers that already cached G1: has_listeners() remains true -> keep G1 mapped

2. Same port name P is reused by replacement receiver
   old _el lock is released by the crash
   opening P: is_zombie() -> unlink name P -> create new generation G2 named P
   G1 still exists through old writers' mappings; G2 is what the new receiver reads
   Old writers -> G1 queue -> no receiver; new receiver <- G2 queue only

3. Existing and newly opened connections diverge
   Existing writers with cached G1 -> G1: messages are not delivered to G2;
                                       with no consumer, G1 ring fills and later
                                       pushes fail/drop descriptors
   New writers opening name P      -> G2: can communicate with the new receiver
~~~

Here G1 and G2 are different SHM objects with the same port number and, at different times, the same filesystem name. The failed connection is **old writer to new receiver**; the old receiver has crashed. "Existing writers" means only writers that retain a wrapper for G1. A writer that opens P after replacement maps G2. An old writer can also recover if it later drops its cached wrapper and reopens P; the idle-slot path alone does not force that to happen.

## Port-segment design philosophy

1. **The receiver determines and advertises its port number.** It tries an initial candidate, then mutates P on a failed receive-resource build; the ReadExclusive `_el` check rejects a port held by another receiver. A successful build keeps that locator in the list to advertise. If the initial attempt and every retry fail, Fast DDS removes that locator from the advertised list; other successful locators remain.

2. **The port segment is collaboratively managed by sender and receiver transports.** Either side can open or create it, with `fastrtps_port<P>_mutex` serializing those lifecycle decisions. For example, a receiver can advertise P and then crash before a writer first opens that destination. The writer still knows P; its Write-mode open sees the stale unlocked `_el`, unlinks the old named segment, and can create a new segment at P. Until a receiver registers a listener on that new segment, writes to it are not enqueued.

3. **For a unicast port, only one receiver transport holds the `_el` lock.** A competing ReadExclusive receiver cannot claim P and may try another locator. An existing but unlocked `_el` file signals a former owner and can cause replacement of the named segment; writers do not hold this lock.

4. **An abruptly lost receiver can eventually fill the port segment.** Each pushed cell remains occupied until every listener registered for it consumes it or unregisters cleanly. If a listener crashes without clearing its registration and writers keep sending to that generation, its outstanding cell references persist, the ring eventually fills, and later descriptors are dropped. The port must be regenerated to discard that stale listener state and resume using a healthy queue.

5. **The watchdog monitors listener status and marks detected failures `is_port_ok=false`.** It checks timed-wait heartbeats, repeated processing descriptors, and listener counts; it does not itself recreate the port.

6. **Recovery keeps the same port number.** Regeneration reopens P and may unlink and create a new SHM generation under that name. A receiver releases its old read lock before the attempt and reacquires `_el` on a successful ReadExclusive open; existing mappings do not automatically switch generations.

7. **A writer going offline does not directly mark the port not OK.** Writers own no `_el` reader lock or listener slot, so their death does not fail the listener-health check or trigger regeneration. An abrupt exit may still leave stale shared bookkeeping.

## Open-order outcomes after a unicast receiver crash

R1 advertised port P and then crashed. R2 is its restarted receiver, T is an unrelated receiver, and W is a writer that still has R1's old locator P. The matrix assumes W has dropped its old port mapping and reopens P; the stale-mapping blind spot discussed above is separate. P2 denotes a successfully mutated port chosen by R2.

| Open/claim order at P | Who owns P afterward? | R2 advertises | W using old locator P before rediscovery | After W discovers and matches R2 |
|---|---|---|---|---|
| R2 → W | R2 creates P and holds `_el` | P | W maps R2's queue | W sends to R2 at P |
| W → R2 | W creates P; R2 later claims it and holds `_el` | P | Writes before R2 registers a listener are not enqueued; later writes reach R2's queue | W sends to R2 at P |
| T → W → R2 (or T → R2 → W) | T holds `_el` at P; R2 cannot claim it | Mutated P2 | **Transition:** if W sends while still using stale P, it writes into T's queue | W sends to R2 at P2 |
| W → T → R2 | W creates P; T claims it first; R2 must move | Mutated P2 | **Transition:** early writes have no listener; after T claims P, stale-P writes enter T's queue | W sends to R2 at P2 |
| W; no receiver claims P yet | Writer-created P has no listener | Not yet known | Descriptors are not enqueued | Depends on which receiver claims P first |

The transition in the T rows exists only while W still targets R1's stale P; discovery may catch up before W sends. Reaching T's SHM queue does not establish an RTPS reader match or guarantee that T accepts the message.
