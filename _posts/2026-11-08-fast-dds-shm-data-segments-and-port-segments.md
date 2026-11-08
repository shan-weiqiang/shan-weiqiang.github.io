---
layout: post
title: "Fast DDS SHM: data segments and port segments"
date: 2026-11-08 10:00:00 +0800
tags: [dds, fast-dds, shared-memory, networking, middleware]
---

A data segment stores outgoing RTPS packet bytes. A port segment stores the
descriptors used to locate those bytes. Their ownership and recovery differ
because a data segment belongs to an allocating sender, while a port is a
shared communication endpoint.

Names below use `<domain>` for the implementation's SHM naming prefix.

* toc
{:toc}

## Comparison

| Aspect | Data segment | Port segment |
| --- | --- | --- |
| Main contents | Fixed `BufferNode` array, variable-size packet payloads, and Boost allocator metadata. | `PortCell` descriptor ring, ring-control state, listener status, and synchronization objects. |
| Storage and reuse model | A fixed `BufferNode` array paired with separately allocated payloads. The sender keeps node pointers in two process-local lists: `free_buffers_` holds unused nodes; `allocated_buffers_` tracks allocated nodes in allocation order. Allocation takes a free node and appends it to the allocated list. Reclamation frees its payload and moves the node back to the free list. When nodes or the logical byte budget run short, the sender scans `allocated_buffers_` oldest first and can invalidate allocations with `processing_count == 0`, even if descriptors remain queued. Nodes and payloads still being processed are not reclaimed. | A bounded `PortCell` ring with shared `write_p` and `free_cells`, and a process-local `read_p_` for each listener. Enqueue reserves the cell at `write_p`, advances `write_p`, decreases `free_cells`, and writes the descriptor. Each listener takes descriptors at its own `read_p_` and advances that pointer on pop. The cell's reference count tracks listeners that still need to take it; the last pop increases `free_cells`. Clean listener removal also releases its outstanding cell references. Pointers wrap around the ring. Packet processing can continue after a cell is freed, protected by the data node's `processing_count`. |
| If a listener crashes | Queued but unprocessed allocations can still be reclaimed under pressure. A processing count left by the crash requires a recovery path to repair it before that allocation can be reclaimed. | The dead listener can leave cell references permanently outstanding. The ring can eventually fill, causing later pushes to drop descriptors and obstructing delivery to healthy listeners too. Port recreation discards the stale queue and listener state; it depends on failure detection and a later recovery operation. |
| Scope | One local data segment per SHM transport instance; a process can have multiple instances. | A shared endpoint identified by port number P, accessed by sender and receiver transports. |
| Who creates it? | The owning SHM transport during initialization. | Usually the receiver when opening its input channel. A sender can also create it when opening a missing destination port or recreating an unusable port during recovery. |
| Can another participant create it? | Receivers open the owner's existing segment; they do not create its payload store on its behalf. | Yes. A sender opening a destination port can create it if absent or replace an unusable one through the open/create path. |
| Who manages live contents? | The owner allocates payloads and manages its local free/allocated node lists. Receivers update shared usage counters while holding buffers. | Senders enqueue descriptors; listeners consume them and update shared queue/listener state. |
| Who reclaims individual entries? | The thread making a new sender allocation reclaims eligible payloads and node slots under the owner's allocation mutex. | A cell becomes reusable after all listeners registered for that enqueue have consumed it, or through orderly listener removal. |
| Normal whole-segment cleanup | The owning segment's destruction unlinks its shared-memory name. | The last normally released `Port` wrapper attempts to unlink a healthy, unused port under its lifecycle mutex. |
| Crash cleanup | A process that mapped the remote segment can detect owner loss and unlink its name through its data-segment watchdog task. | A listener crash requires port-segment recreation. |
| Who can recreate it? | Not applicable: a data segment is not recreated. A restarted owner creates an independent segment with a new UUID; the old segment is cleaned up. | Either sender or receiver can recreate the port segment for the same port number and locator through serialized open/create/recovery. |
| Naming | `<domain>_<UUID>`; each creation generates a fresh segment ID. | `<domain>_port<P>`; recreation of the same port number uses the same name. |
| Meaning of the name | Identifies a particular payload store. Descriptors carry this segment ID. | Identifies an endpoint addressed through an SHM locator's port number. |
| Identity across restart or recovery | Each newly created data segment has its own UUID and name, independent of the previous segment. | Recreating a port preserves its locator and name, but creates a new shared-memory object with its own port-generation identity. |
| Watchdog observes | The origin-liveness lock of mapped remote segments. | Listener waiting heartbeats, processing progress, and listener bookkeeping in opened ports. |
| Watchdog action | If the owner lock is no longer held, unlink the segment name and drop local cache/watch references. | On a detected listener-health failure, set `is_port_ok=false`. The watchdog does not itself recreate the port. |
| Effect on existing mappings | Unlinking does not revoke existing mappings; active buffer objects can retain them. | Reusing the name does not redirect old mappings to the replacement; participants must reopen or regenerate their handles. |

For both kinds of segment, unlinking removes the shared-memory name.
The memory remains alive while existing mappings still hold it, and the OS
releases it after the last mapping handle closes. Crash detection and
replacement are recovery paths, not guarantees of immediate recovery.

On Linux, process termination automatically unmaps that process's memory
and closes its file descriptors, even after a crash. These actions release
its OS-level references to the segment:

| State when the process crashes | Result |
| --- | --- |
| The segment has already been unlinked | The crashed process's OS references are released. The underlying object is destroyed once no mappings or open descriptors remain. |
| The segment has not been unlinked | The crashed process's OS references are released, but the named object remains. It can persist even after all users terminate, until explicitly removed or the system shuts down. |

POSIX shared-memory objects normally appear under Linux's `/dev/shm`,
a tmpfs filesystem. This persistence is why cleanup must remove the
shared-memory name as well as release mappings.
See the [Linux shared-memory overview](https://man7.org/linux/man-pages/man7/shm_overview.7.html)
and [mapping lifetime rules](https://man7.org/linux/man-pages/man2/munmap.2.html).

OS-level references are separate from Fast DDS's counters stored inside
shared memory. A process crash releases its kernel-managed mappings and
descriptors, but does not automatically decrement
`BufferNode.processing_count` or the port's shared reference counters.
Those counters require Fast DDS's own cleanup or recovery.

## Why the names behave differently

A port number is part of the destination locator known to senders.
Recreating port P under the same name preserves that endpoint address.
Generating an unrelated name would require a way for existing peers to
learn where to open the replacement. A restarted receiver may still choose
a different port if it cannot claim the previous one, then advertise the
new locator.

A data-segment ID is carried in each packet descriptor. New packets can
therefore announce a new segment ID without changing the destination port.
A fresh UUID also separates old queued descriptors from the restarted
sender's new payload store: an old descriptor continues to name the old
segment and cannot silently resolve into the new data segment.

Within one data segment, `BufferNode.validity_id` distinguishes successive
payload allocations that reuse a node. This is separate from the UUID
that distinguishes whole data segments.

## One watchdog thread per process

Each process using SHM has one `SharedMemWatchdog` singleton and one
background `dds.shm.wdog` thread. Multiple transports in that process share
two singleton tasks on that thread:

~~~text
Process
└─ SharedMemWatchdog
   └─ dds.shm.wdog thread
      ├─ Port WatchTask
      │  Watches opened ports from sender and receiver transports
      │  Marks detected unhealthy ports as not OK
      └─ Data-segment WatchTask
         Watches mapped remote segments
         Cleans up mappings and names after owner loss
~~~

Each task maintains its own collection of watched objects. Another process
has its own watchdog thread and collections; these threads can observe
some of the same shared objects.

The data-segment task does not scan the owner's `allocated_buffers_`,
free individual packet payloads, or repair a dead receiver's usage counts.
Those are separate allocation and port-recovery operations.

## What happens after a crash?

If a data-segment owner crashes, the OS releases its liveness lock.
Processes already watching that segment can unlink its name and remove
cached mappings. A restarted transport creates a fresh segment and uses
the new ID in subsequent descriptors. Old descriptors may remain readable
while old memory is still mapped and has not been cleaned up; descriptors
whose segment can no longer be opened cannot be processed.

If a receiver crashes, its listener state can remain in the port.
The port watchdog may detect stalled activity and mark that port unhealthy.
A later send, receive, or open operation may replace the old object under
the same port number. A crashed receiver cannot perform this recovery
itself, and without a subsequent operation the watchdog's health mark alone
does not create a replacement. Existing mappings must still be refreshed.

A sender-side zombie-port recovery path can also use the old port's
recorded in-progress `BufferDescriptors` to find the corresponding
`BufferNodes` and decrement their `processing_count`, provided the segments
are accessible and the validity generations still match. These nodes
belong to the source data segments named by the descriptors, which may
include the recovering sender's own segment or other senders' segments.
The helper repairs usage counts; it does not directly remove nodes or
deallocate payloads. Each owner can reclaim eligible payloads and node
slots during a later allocation. This repair is conditional: some
port-reopening paths bypass it, so recreating a port does not guarantee
that all affected data-segment counts have been repaired.
