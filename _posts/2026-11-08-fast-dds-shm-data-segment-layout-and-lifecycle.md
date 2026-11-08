---
layout: post
title: "Fast DDS SHM data segment layout and lifecycle"
date: 2026-11-08 09:30:00 +0800
tags: [dds, fast-dds, shared-memory, networking, middleware]
---

This note describes the layout and lifecycle of a Fast DDS shared-memory data
segment: how packet buffers are allocated, referenced, reclaimed, and cleaned
up.

* toc
{:toc}

## Model and layout

Each shared-memory transport creates one local data segment at initialization.
An outgoing RTPS packet is copied into an allocated payload block there. The
segment also holds `BufferNode` records that locate those blocks and track their
lifetime. Other processes can map the segment and resolve a node's relative
offset to access its packet bytes.

The data segment is one named Boost managed shared-memory object:
`<domain>_<UUID>`. The diagram expands the fields that govern allocation and
buffer lifetime. It is a **logical linearization**, not a measured byte map:
Boost chooses physical offsets, alignment, and reuse of freed regions.

~~~text
<domain>_<UUID>  (conceptual low-to-high stream; NOT literal offsets)
mapping start
    |
    v
+----------------------------------------------------------------------------------+
| Boost managed-segment header and rbtree_best_fit allocator bookkeeping           |
| The allocator manages the BufferNode array and all packet-byte allocations.      |
+----------------------------------------------------------------------------------+
    |
    v
+----------------------------------------------------------------------------------+
| BufferNode[max_allocations] (ONE anonymous array of metadata records)            |
| The array stores packet locations and lifetime state, not packet bytes.          |
|                                                                                  |
| Each BufferNode holds:                                                           |
|   atomic status: validity_id, enqueued_count, processing_count                    |
|   data_size: RTPS packet allocation length                                        |
|   data_offset: segment-relative handle to its payload bytes                      |
|                                                                                  |
| A free node has no live packet allocation. Its data_size/data_offset fields      |
| are initialized to zero; after reclamation, old values need not be cleared.      |
+----------------------------------------------------------------------------------+
    |
    v
+----------------------------------------------------------------------------------+
| Separately allocated payload blocks (zero or more, variable sizes)               |
|   block for node A: RTPS packet bytes [data_size]                                 |
|   block for node B: RTPS packet bytes [data_size]                                 |
|   ...                                                                            |
| Boost's rbtree_best_fit allocates, frees, and reuses these byte blocks.          |
| These blocks are NOT a contiguous fixed-size packet array.                       |
+----------------------------------------------------------------------------------+
    |
    v
+----------------------------------------------------------------------------------+
| Available managed-segment space, possibly fragmented among allocations           |
| The mapping includes estimated overhead beyond the configured payload budget.    |
+----------------------------------------------------------------------------------+
    |
    v
mapping end

Outside this data segment:
  <domain>_<UUID>_el               separate origin-liveness lock file
  sender Segment wrapper          free_buffers_, allocated_buffers_, alloc_mutex_,
                                  free_bytes_, segment_id_, overflows_count_
  receiver SegmentWrapper/cache   mapped handle, ID, name, last alive-check time
~~~

To identify a node across processes, the sender puts a `BufferDescriptor`
in a destination port segment's `PortCell`. The descriptor contains the
sender's data-segment ID, the node's segment-relative
`buffer_node_offset`, and its `validity_id`. The receiver reads the cell,
maps the named data segment, and resolves `buffer_node_offset` to the
`BufferNode`. The node's separate `data_offset` then locates the packet
bytes.

The array is a **fixed pool of metadata slots**, not an array of messages.
At creation, the sender puts pointers to all its nodes on the process-local
`free_buffers_` list. For one outgoing RTPS packet it takes a node, separately
asks Boost to allocate the packet bytes, and fills the node's `data_offset`
and `data_size`. Another process can use the node to find the bytes. On
later reclamation the sender deallocates the bytes, advances the node's
validity generation, and returns the same node to its free list.

`max_allocations` is the number of elements in the fixed-size `BufferNode`
array. Each packet allocation uses one node, which can be reused after
reclamation. Allocating a packet requires both a free node and enough space
for its bytes in the data segment.

`free_bytes_` tracks the remaining payload capacity in the data segment.
The actual free space may be split across several regions; Boost determines
whether a large enough contiguous block is available for each allocation.

Boost.Interprocess manages the data segment's byte allocations. Its
`rbtree_best_fit` allocator chooses space for the metadata array and the
separately allocated, variable-size RTPS packet buffers; reclaimed blocks
can be reused. This is distinct from the sender's process-local
`free_buffers_` list, which chooses a `BufferNode` record rather than a byte
block.

## BufferNode reference counts

Each `BufferNode` has a validity generation and two shared counters. The
sender and receivers update them atomically to track the current payload's
lifetime.

A **queued reference** here means a `BufferDescriptor` stored in a
destination port segment's `PortCell`. It contains `source_segment_id`,
`buffer_node_offset`, and `validity_id`, which identify the data segment,
the `BufferNode`, and the allocation's generation. Enqueuing a reference means
writing this descriptor into a `PortCell`.

A port can have one or more listeners. This queued reference remains until
every listener registered when it was enqueued has taken the descriptor.
Only the **last listener** to take it subtracts 1 from `enqueued_count`;
earlier listeners leave that count unchanged. Taking the descriptor does
not mean packet processing has finished: each listener's
`processing_count` contribution protects the payload while it is in use.

A **buffer wrapper** means a process-local C++ `SharedMemBuffer` object.
It points to one `BufferNode` in shared memory and holds the segment mapping,
the allocation's validity ID, and the packet's address. Sender and receivers
can each have their own object referring to the same `BufferNode` and payload.

These objects use C++ RAII: the allocation or receive path increments
`processing_count` before using the buffer, and the object's destructor
decrements it. A `std::shared_ptr` manages the object's lifetime, so the
destructor runs when its last owner releases it. Copying that `shared_ptr`
does not add another processing count. Destroying the object releases its
usage reference; the sender reclaims the shared payload separately.

| Counter | What it counts | When it increases | When it decreases |
| --- | --- | --- | --- |
| `enqueued_count` | Queued BufferDescriptors referring to this buffer, one per port enqueue. | Sender adds 1 before each enqueue. | The final listener to take that PortCell's descriptor subtracts 1; sender undoes the increment if the enqueue is abandoned. |
| `processing_count` | Active SharedMemBuffer objects holding the payload in the sender or receivers. | Sender adds 1 when allocating its buffer; each receiver adds 1 before processing a valid buffer. | Each SharedMemBuffer destructor subtracts 1 when its last owner releases it. |

For the receiver, `processing_count` increases **before RTPS message
processing** and decreases when its `SharedMemBuffer` is destroyed, normally
after processing returns. This protects the payload from being reclaimed
while it is in use. If another owner retains the same object, destruction
and the decrement happen later. The sender also contributes to this count
from allocation until its own `SharedMemBuffer` is destroyed.

For one successful enqueue to a port with one listener, assuming no other
holder retains the buffer:

| Event | enqueued_count | processing_count |
| --- | ---: | ---: |
| Sender allocates the payload and holds a SharedMemBuffer | 0 | 1 |
| Sender writes a BufferDescriptor into a PortCell | 1 | 1 |
| Sender releases the last owner of its SharedMemBuffer; its destructor runs | 1 | 0 |
| Receiver takes the descriptor and acquires the buffer before processing | 0 | 1 |
| Receiver finishes processing and releases its SharedMemBuffer; its destructor runs | 0 | 0 |

When the **final** listener takes a PortCell's descriptor, it performs
`enqueued_count - 1` and `processing_count + 1` as one atomic status update,
provided the descriptor's validity generation still matches the node.
Earlier listeners increase only `processing_count`. For example, with two
listeners on one port, `enqueued_count` remains 1 after the first listener
takes the descriptor and becomes 0 after the second takes it; both listeners
contribute to `processing_count` while holding the buffer. Finishing packet
processing and releasing the buffer reduces only `processing_count`.

The normal reclaim condition is `enqueued_count == 0` and
`processing_count == 0`. Reaching zero does not immediately deallocate the
payload: the sender reclaims it during a later allocation pass. Under memory
pressure, a queued but currently unprocessed allocation can instead be
invalidated and reclaimed. Advancing `validity_id` makes old descriptors
recognizable as stale if another process encounters them later.

## 1. Create the segment

When the shared-memory transport starts, it creates a local data segment
with a generated ID. The configured segment size determines its payload
budget; the maximum number of BufferNodes is a separate limit on
simultaneous packet allocations.

The managed mapping includes space for allocator metadata and the BufferNode
array as well as the configured payload budget. The sender's `free_bytes_`
is a logical payload counter, not the mapping's total physical free space.

`Segment` generates a UUID, obtains an exclusive `<domain>_<UUID>_el` lock file,
removes an old object with that name, creates the shared-memory object with
`create_only`, constructs the anonymous BufferNode array, initializes every
node, and stores their pointers on its local free list. The `_el` lock is outside
the data mapping and indicates that the origin remains alive.

## 2. Allocate and reference packet buffers

Allocation runs in the thread calling the SHM transport's send operation.
This may be the application thread or a DDS sending thread, depending on
the sending path. The sender serializes allocation and reclamation with
its local allocation mutex.

BufferNodes are created once with the data segment; allocating a packet
takes an existing node from the fixed array. The order is:

1. Acquire the allocation mutex and recover eligible older buffers, as
   described in section 4.
2. Take a node from `free_buffers_`.
3. Ask Boost's `rbtree_best_fit` allocator for the payload block and subtract
   its size from `free_bytes_`.
4. Write the payload's offset and length into the node's `data_offset` and
   `data_size`.
5. Read the node's current `validity_id`, create a process-local
   `SharedMemBuffer` referring to it, and increase `processing_count` by 1
   for the sender.
6. Append the node to `allocated_buffers_` and release the allocation mutex.
7. Copy the assembled RTPS packet into the payload block.

The first use starts with the node's initial generation. Reusing a node
uses the generation left by its previous reclamation; allocation does
**not** increment the generation again.

The sender holds its `SharedMemBuffer` while sending. When the object's last
owner releases it, its destructor decreases `processing_count` in that
owner's thread. Usually this happens as the send finishes; packet logging
or other retained ownership can delay it. Destruction does not free the
payload or return the node to `free_buffers_`.

## 3. Map and read a remote data segment

The SHM receive-channel thread obtains a descriptor and accesses the
sender's data segment in this order:

1. Look up the segment by ID. On the first access, open and map the named
   segment, cache it, and register it for the data-segment watchdog.
2. Resolve the BufferNode's relative offset and prepare a local
   `SharedMemBuffer` for its payload.
3. Atomically check the descriptor's generation and increase
   `processing_count`. The final listener taking that queued descriptor
   also decreases `enqueued_count` in the same atomic update. A generation
   mismatch makes the descriptor stale, so its payload is not processed.
4. Pass the mapped packet bytes to RTPS message processing.
5. Release the receive thread's buffer reference, then clear its recorded
   receive-channel processing status.

The `SharedMemBuffer` destructor decreases `processing_count` when its last
owner releases it. Normally this runs in the receive thread after message
processing; retained ownership can move the destruction to a later time
and another thread. Releasing a packet does not normally unmap the segment,
because the receiver caches the mapping.

## 4. Reclaim a payload and reuse its node

Reclamation runs in the thread requesting a new packet allocation in the
sender, under its allocation mutex. It is not a background task triggered
when a reference count reaches zero.

A new packet of `size` bytes needs **both**:

- An unused BufferNode: `free_buffers_` must not be empty.
- A payload block of `size` bytes, allocated by Boost inside the data segment.

Before asking Boost for the block, Fast DDS runs the following recovery
passes. `allocated_buffers_` stores `BufferNode*` in allocation order,
with the oldest allocation at the front.

### First pass: recover bytes and unreferenced allocations

Fast DDS scans `allocated_buffers_` **from oldest to newest**, checking the current
`free_bytes_` against the requested size at each node:

| Byte-budget condition | Action on the current node |
| --- | --- |
| `free_bytes_ >= size` | Reclaim only if both `enqueued_count == 0` and `processing_count == 0`; otherwise skip it. |
| `free_bytes_ < size` | Try to invalidate and reclaim if `processing_count == 0`, even if descriptors are still queued; otherwise skip it. |

“Not enough bytes” here means exactly `free_bytes_ < size`. For example,
a 10 KiB request with only 4 KiB of remaining budget needs at least 6 KiB
to be recovered.

Each reclaimed payload increases `free_bytes_`. Once it reaches `size`,
the rest of this scan reclaims only completely unreferenced allocations.
The scan continues to the end of the list.

Victim selection is **oldest eligible allocation first**, skipping nodes
whose `processing_count` is nonzero. It is not random and does not choose
victims by their payload size or position in Boost's tree.

`free_bytes_ >= size` means only that the logical byte budget is sufficient;
the actual free space may be split across separate regions. This first pass
does not check for a contiguous block. Once the budget is sufficient, it
stops invalidating queued buffers to recover bytes, even if fragmentation
might prevent allocation. Boost's `rbtree_best_fit` checks for a suitable
contiguous block afterward. If that allocation fails, this call does not
perform another recovery pass or retry.

### Second pass: recover a node slot if none is free

After the first pass, the byte budget may be sufficient while
`free_buffers_` is still empty: all fixed-array node slots are occupied.

Fast DDS scans the remaining nodes in `allocated_buffers_` again, oldest first.
It skips nodes with `processing_count > 0` and tries to invalidate the first
node with `processing_count == 0`, even if its descriptors are still queued.
After successfully reclaiming that node's payload and returning the node
to `free_buffers_`, this pass stops. It does not reclaim a node while
leaving its old payload allocated.

### Reclamation order for each selected node

1. Atomically increase `validity_id` and reset both counters to zero.
   Forced invalidation succeeds only if `processing_count` is still zero.
2. Ask Boost's `rbtree_best_fit` allocator to deallocate the node's payload.
3. Add the released payload size back to `free_bytes_`.
4. Put the node into `free_buffers_` and remove it from `allocated_buffers_`.

The node and payload remain associated until the payload is deallocated.
The node stays in the fixed array and can then be used for a new payload.
These are ordered steps under the sender's mutex, not one combined atomic
operation. Old queued descriptors retain their previous generation, so
receivers reject them after invalidation.

In particular, `enqueued_count == 0` alone does not permit reclamation:
a nonzero `processing_count` protects both the node and its payload.

### What if Boost still cannot allocate the payload?

`free_bytes_` is Fast DDS's remaining payload-byte budget. It does not
describe the actual free blocks in Boost's allocator. Even after recovery
makes `free_bytes_ >= size` and supplies a node, Boost must still find a
suitable contiguous block inside the managed segment.

If the budget is still below `size`, allocation fails before calling Boost.
If no node can be recovered, taking a free node fails. If Boost itself
cannot allocate the requested block, Fast DDS returns the reserved node to
`free_buffers_` and this allocation fails. It does **not** run an additional
victim-selection pass or retry Boost allocation within that same call.

Thus Fast DDS selects which existing packet allocations to invalidate;
Boost's `rbtree_best_fit` selects where the new payload bytes fit in the
segment.

## 5. Segment shutdown and watchdog cleanup

On normal shutdown, the thread tearing down the transport releases its
local data segment and unlinks its shared-memory name. Existing buffer
references and remote mappings may keep the memory alive. The OS releases
the memory after the name has been removed and the last mapping handle
closes. The origin-liveness lock is released when the owning segment is
destroyed.

Each process using SHM has one `SharedMemWatchdog` singleton and one
background thread named `dds.shm.wdog`. Multiple SHM transports in that
process share the thread. It runs two process-level singleton tasks:

~~~text
Process
└─ SharedMemWatchdog singleton
   └─ dds.shm.wdog thread
      ├─ Port WatchTask singleton
      │  Checks opened ports for stalled or dead listeners
      └─ Data-segment WatchTask singleton
         Checks mapped remote data segments for dead owners
~~~

Each task keeps its own collection of watched objects. Ports and remote
data-segment mappings from different transports register with these shared
tasks. Other processes have their own watchdogs and watched collections;
the watchdog thread is not shared across processes.

The **data-segment task** periodically:

1. Checks the origin-liveness lock of each watched remote segment.
2. Keeps the cached mapping if the origin still holds the lock.
3. If the lock is no longer held, unlinks the shared-memory name, removes
   the segment from the local mapping cache, and drops its watchdog entry.

An active `SharedMemBuffer` retains its own mapping reference, so cache
removal does not immediately invalidate a buffer already in use. Detection
and cleanup happen periodically rather than at the instant the origin
exits.

The data-segment watchdog cleans up abandoned **segments and mappings**.
It does not scan `allocated_buffers_`, deallocate individual payload blocks,
or repair a crashed receiver's `processing_count`.

## 6. Receiver crash: a stuck processing count

If a receiver crashes while holding a buffer, its `SharedMemBuffer`
destructor does not run. The affected `BufferNode.processing_count`
**in the sender's data segment** can therefore remain above zero.
The sender's normal recovery scan will not reclaim that node or its payload,
even under memory pressure.

The data-segment watchdog does not repair this count. It monitors the
data-segment owner, which may still be alive; the failed process here is
a receiver using that owner's payload.

### The implemented port-recovery repair path

The sender has a counter-repair helper, `recover_blocked_processing()`.
Its port-regeneration method calls this helper **before** replacing the
port. The send-side path is:

1. A push encounters a port marked unhealthy and throws.
2. The sender's port wrapper catches the failure and enters regeneration.
3. The repair helper checks whether the port is a zombie using its
   receiver-ownership locks. Being marked unhealthy alone is insufficient.
4. For a zombie port, it reads each listener-status entry still marked
   in use and processing, obtains its recorded `BufferDescriptor`, and
   clears that entry's processing flag.
5. It uses the descriptor's segment ID and node offset to locate the
   `BufferNode`, then atomically decrements that node's `processing_count`
   if the validity generation still matches.
6. Port regeneration proceeds. A later sender allocation can reclaim the
   payload and node if the resulting counts permit it.

The descriptor record is in the port segment, but the repaired counter
is in the **data segment**. The helper does not directly deallocate payloads.

### Why this does not guarantee reclamation

The repair is tied to that specific regeneration path. Recreating or
reopening a port does not necessarily run it:

- On the non-Windows send path, cached ports are checked before sending.
  An already-unhealthy port can be removed from the cache and subsequently
  reopened through the ordinary open/create path, bypassing the
  counter-repair helper.
- Allocating the new outgoing packet happens before pushing its descriptor.
  If allocation fails because buffers remain pinned, that send never
  reaches the push-failure regeneration path.
- A port must pass the zombie check. For example, a shared port with another
  receiver still holding its ownership lock may not qualify.
- Repair also depends on accessible in-progress records, an available
  source segment, and a matching validity generation.

There is no general timeout that resets a BufferNode's processing count.
If the repair path is bypassed or cannot repair the count, the node and
payload can remain occupied for the lifetime of the owning segment.
