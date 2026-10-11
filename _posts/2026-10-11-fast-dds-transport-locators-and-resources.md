---
layout: post
title: "Fast DDS Transport Architecture"
date: 2026-10-11 09:00:00 +0800
tags: [dds, rtps, fast-dds, networking, shared-memory]
---

The authoritative DDSI-RTPS standard is published by the Object Management Group and is available as the [OMG DDSI-RTPS 2.2 specification](https://www.omg.org/spec/DDSI-RTPS/2.2/PDF). It defines the RTPS protocol, its wire-level messages, endpoint behavior, and abstractions such as locators.

The concrete transport layer is implementation-specific. The RTPS standard does not define how Fast DDS organizes UDP sockets, TCP connections, shared-memory segments, resource ownership, or receive threads. Those details must be understood from the Fast DDS code base.

This note sketches the implementation architecture of the Fast DDS transport layer. It focuses on how Fast DDS maps the RTPS locator abstraction onto UDP, TCP, and shared memory, and how the corresponding runtime resources and threads are organized.

Its scope is the `NetworkFactory` transport path that moves serialized RTPS messages. Fast DDS Data Sharing QoS and intraprocess delivery are separate delivery mechanisms and are not the SHM transport described here. Chaining transports, TLS internals, WAN translation, security processing, and every recovery path are also outside this architectural sketch.

* toc
{:toc}


## Runtime ownership model

A Fast DDS process can contain multiple RTPS participants. Each participant owns one `NetworkFactory`, and the factory owns that participant's runtime transport instances.

Each transport descriptor in the participant configuration is instantiated by `NetworkFactory` into one transport instance. A participant may configure multiple descriptors of the same type, producing multiple independent instances of that transport type.

Tree notation: an unmarked child is exactly one member; `name?` means zero or one; `name[]` means zero or more; and `map[key]` means zero or more keyed entries. Numeric forms such as `address[0]` and `port[31:0]` denote field indexing, not cardinality.

```text
Fast DDS process
└── RTPS participant[]
    └── NetworkFactory
        └── registered transport instance[]
            └── concrete type: UDP | TCP | SHM
```

Transports carry RTPS messages between writers and readers. The RTPS standard does not prescribe Fast DDS's concrete transport implementations; those implementations use concepts defined by RTPS, particularly the locator, to identify transport-specific communication endpoints.

## Locator model

The RTPS standard represents a transport destination with a locator composed of a transport kind, an address, and a port. Writers and readers use locators to describe the receiving addresses at which they accept incoming RTPS messages. Fast DDS implements this concept as `Locator_t`:

```cpp
class Locator_t
{
public:
    int32_t kind;
    uint32_t port;
    octet address[16];
};
```

The three transport families use the same shape, but interpret `address` and `port` differently:

| Transport | `kind` | `address` | `port` | Receiving resource selected by the locator |
| --- | --- | --- | --- | --- |
| UDP | `UDPv4` or `UDPv6` | IP address | Physical UDP port | Bound UDP socket |
| SHM | `SHM` | Mode plus host identifier | Queue-port ID | Named shared-memory queue segment |
| TCP | `TCPv4` or `TCPv6` | IP address | Two packed 16-bit ports: physical and logical | Physical TCP endpoint plus logical RTPS receiver |

The receiver advertises a local receiving locator during discovery. A remote sender stores that locator and uses it as a destination:

```text
Receiver                                      Sender
--------                                      ------
local receiving locator  -- discovery -->     remote destination locator
                                                 |
                                                 +-- transport send(locator)
```

A locator identifies a transport-level destination: an addressable receive endpoint to which an RTPS message can be sent. DDS/RTPS endpoint identifiers inside the received traffic identify the reader, writer, and topic-level communication. Both an RTPS writer and an RTPS reader can act as a sender or receiver of RTPS messages.

One RTPS receiver can have multiple locators across multiple transport instances. These locators may use different transport kinds, such as UDP, TCP, and SHM, or may come from multiple instances of the same transport kind. Each locator provides an alternative transport-level destination for reaching the same RTPS receiver.

## UDP: IP address and physical port

UDP uses the locator fields directly:

```text
Locator
├── kind                                  [one: UDPv4 or UDPv6]
├── address                               [one 16-byte field: destination IP]
└── port                                  [one: destination UDP port]
```

On receive, the locator supplies the physical UDP port, while `get_binding_interfaces_list()` supplies the local address or addresses to bind. With no interface whitelist this is normally one wildcard address; with a whitelist it can be one address per selected interface. Multicast setup may additionally bind or join the multicast group. On send, Fast DDS constructs the remote UDP endpoint from the remote locator's destination address and physical port.

### Inside one UDP transport instance

```text
UDPv4Transport or UDPv6Transport instance
├── configuration_                              [one descriptor copy]
├── interface_whitelist_[]                      [zero or more IP addresses]
└── UDPTransportInterface state
    ├── io_context_                             [one]
    ├── mInputSockets[physical_port]             [zero or more map entries]
    │   └── vector<UDPChannelResource*>
    │       └── UDPChannelResource              [one per bound interface/socket]
    │           ├── socket_                     [one bound UDP socket]
    │           ├── interface_                  [one interface identifier]
    │           ├── message_receiver_           [one non-owning pointer]
    │           └── ChannelResource base
    │               ├── message_buffer_         [one]
    │               ├── alive_                  [one]
    │               └── thread_                 [one dds.udp.<port> thread]
    ├── mSendBufferSize / mReceiveBufferSize    [one each]
    ├── allowed_interfaces_[]                   [zero or more]
    ├── netmask_filter_                         [one]
    └── statistics_info_                        [one]

Objects created by this instance but stored in participant send-resource lists
└── UDPSenderResource[]                         [zero or more]
    ├── socket_                                 [one output UDP socket]
    ├── transport_                              [one reference to this instance]
    └── send_lambda_                            [one]
```

The transport instance directly owns its input-channel map. Its output sockets live in `UDPSenderResource` objects created by the transport instance, then retained and managed directly by `RTPSParticipantImpl` through the participant’s `send_resource_list_`.

### UDP receive threads

Each `UDPChannelResource` owns one blocking receive thread:

```text
UDPChannelResource                         [one bound socket resource]
└── dds.udp.<port> thread                 [one]
    └── receive_from(socket)              [repeated operation]
        └── OnDataReceived(...)           [one call per received datagram]
```

The relationship is more precisely **one thread per bound socket resource**, rather than one thread per numeric UDP port. `OpenAndBindInputSockets()` may create one resource for each selected interface, and `mInputSockets[physical_port]` stores a vector:

```text
physical UDP port P
└── bound socket resource[]
    ├── UDP socket                              [one]
    └── receive thread                          [one]
```

Sending uses an output socket on the calling path. Fast DDS does not create one dedicated sending thread per UDP destination.

### UDP with no interface whitelist

An empty interface whitelist means that every usable interface is allowed. Fast DDS treats locator advertisement, receiving, unicast sending, and multicast sending differently:

```text
multi-interface host
├── advertised UDP locators
│   └── one concrete locator per discovered local IP address
├── unicast receive for physical port P
│   └── one socket bound to wildcard address 0.0.0.0:P or [::]:P
├── unicast send
│   └── one wildcard-bound output socket
│       └── kernel routing selects the source interface and source address
└── multicast send
    └── one multicast-purpose output socket per discovered interface
        └── each socket selects that interface as its multicast outbound interface
```

The default unicast locator initially has an unspecified address. `NormalizeLocator()` expands it into the discovered local addresses, excluding loopback when ordinary interfaces exist and falling back to loopback when none exists. These concrete locators are what peers can use to reach the participant.

For input, `get_binding_interfaces_list()` returns only the wildcard address when the whitelist is empty. `OpenAndBindInputSockets()` therefore creates one `UDPChannelResource` for the physical port, and its wildcard-bound socket accepts unicast datagrams arriving through any local interface. This gives one receive thread for that port resource, rather than one thread per interface.

For unicast output, `OpenOutputChannel()` creates a generic wildcard-bound socket. `send_to()` supplies the remote locator's destination IP and port, and the operating-system routing table chooses the outgoing interface and source IP. Locator selection can include all of a peer's advertised unicast addresses, so Fast DDS may send the message to several remote IP addresses. Each send is routed independently; Fast DDS does not duplicate each destination send across every local interface.

Multicast requires explicit interface selection. Fast DDS creates a multicast-purpose output socket for every discovered interface and sends the multicast datagram through each applicable socket. On receive, the wildcard-bound input socket joins the multicast group separately on every discovered interface. The local output socket also keeps multicast loopback enabled so local participants continue to communicate when no external interface is usable.

1. SPDP uses multicast for participant discovery by default. Fast DDS always prepares a localhost multicast path; when no external interface is available, this leaves the loopback interface as the path through which local SPDP announcements can still be exchanged.
2. Participants on the same machine can therefore discover each other through multicast. The multicast-loopback socket option enables locally sent multicast packets to be delivered to local sockets that joined the group, while Fast DDS also joins the group on the loopback interface.
3. The multicast group IP address and UDP port identify the destination group. A local interface IP is not the multicast destination, but it selects the interface used to join the group or transmit the packet, supplies the usual source address, and determines the network through which the packet can reach other hosts.

## SHM: host identifier and queue port

`SHMLocator::create_locator()` constructs an SHM locator as follows:

```text
Locator
├── kind                                  [one: SHM]
├── address                               [one 16-byte field]
│   ├── address[0] = 'U'                  [unicast-style: exclusive reader]
│   │              or 'M'                [multicast-style: shared readers]
│   └── address[1..2]                     [one host identifier]
└── port                                  [one queue-port ID]
```

The SHM locator identifies the receiver's notification queue, not the shared-memory location of the message bytes. Its `port` selects the receiver's named queue segment. When sending, the publisher places a descriptor in that queue; the descriptor contains the source data-segment ID, buffer offset, and validity ID needed to locate and validate the message bytes.

Fast DDS derives the queue segment name in `SharedMemGlobal::open_port_internal()`:

```cpp
auto port_segment_name = domain_name_ + "_port" + std::to_string(port_id);
```

For the usual domain name, an SHM locator with port `52661` selects a file such as:

```text
/dev/shm/fastrtps_port52661
```

### SHM region relationships

Fast DDS separates the payload storage from the destination queue.

Every `SharedMemTransport` instance creates exactly one data segment in `SharedMemTransport::init()`:

```cpp
shared_mem_manager_ = SharedMemManager::create(SHM_MANAGER_DOMAIN);
shared_mem_segment_ = shared_mem_manager_->create_segment(
    configuration_.segment_size(), max_allocations);
```

The member is singular:

```cpp
std::shared_ptr<SharedMemManager::Segment> shared_mem_segment_;
```

### Inside one SHM transport instance

```text
SharedMemTransport instance
├── configuration_                              [one descriptor copy]
├── shared_mem_manager_                         [one manager: creates, opens, and maps SHM resources]
│   ├── global_segment_                         [SharedMemGlobal helper: named-port lifecycle]
│   ├── ids_segments_[segment_id]               [remote data segments opened from received descriptors]
│   │   └── SegmentWrapper                      [one per mapped segment ID]
│   └── watch_task_                             [watches cached remote data segments]
├── shared_mem_segment_                         [this transport's fixed-size managed SHM heap]
│   └── fastrtps_<this-transport-segment-id>
│       ├── managed-allocator metadata          [one rbtree_best_fit allocator]
│       ├── BufferNode[]                        [fixed number of reusable metadata slots]
│       │   ├── status                          [validity and reference counters]
│       │   ├── data_size                       [this message's variable byte length]
│       │   └── data_offset ────────────────────┐
│       └── variable-length payload block[] <───┘ [one contiguous allocation per live message]
├── input_channels_[]                           [this transport's receiving channels]
│   └── SharedMemChannelResource                [one per opened input locator]
│       ├── locator_                            [one]
│       ├── message_receiver_                   [one non-owning pointer]
│       ├── listener_                           [one queue listener; owns no thread]
│       │   ├── global_port_                    [shared wrapper for the local input-port segment]
│       │   ├── global_listener_                [one private descriptor-ring cursor]
│       │   └── listener_index_                 [one listener-status slot index]
│       ├── packet_logger_?                     [optional]
│       └── ChannelResource base
│           ├── message_buffer_                 [one]
│           ├── alive_                          [one]
│           └── thread_                         [one dds.shm.<port> thread calling listener_->pop()]
├── opened_ports_[port_id]                      [remote input ports opened or created in Write mode]
│   └── SharedMemManager::Port                  [one cached writer-side wrapper per port ID]
│       └── global_port_                        [one port wrapper]
└── packet_logger_?                             [optional]

Objects created by this instance but stored in participant send-resource lists
└── SharedMemSenderResource[]                   [zero or more across lists]
    └── send_lambda_                            [one]

Independent named SHM objects accessed through the members above
├── fastrtps_port<local-input-port-id>[]        [opened or created in Read mode by input channels]
├── fastrtps_port<remote-input-port-id>[]       [opened or created in Write mode by send resources]
└── fastrtps_<remote-segment-id>[]              [opened and mapped from received descriptors]
```

`shared_mem_manager_` is the transport instance's shared-memory resource manager. It creates the transport's local payload data segment; opens or creates globally named receiver port queues for both this transport instance's input channels in read mode and other transport instances' destination ports in write mode; resolves received descriptors by opening their source data segments; caches those remote mappings in `ids_segments_`; and registers them with the shared watchdog task. The named port segments remain independent, domain-wide SHM objects rather than resources contained by this manager or its data segment. The manager is a control and lifetime-management object; it is not itself an additional shared-memory data segment.

| SHM object | Relationship to this transport instance | Access mode | Open/create behavior | Wrapper or mapping retained by |
|---|---|---|---|---|
| `fastrtps_<local-segment-id>` payload data segment | Local; stores messages allocated by this transport instance | Read/write payload allocation | Creates a new uniquely named segment with `create_only` | `SharedMemTransport::shared_mem_segment_` |
| `fastrtps_<source-segment-id>` payload data segment | External; contains message bytes referenced by a received descriptor | Read remote payload | Opens an existing segment with `open_only`; never creates it | `SharedMemManager::ids_segments_`, with lifetime monitoring by `watch_task_` |
| `fastrtps_port<local-input-port-id>` receiver queue segment | Local input destination consumed by this transport instance | `ReadShared` or `ReadExclusive` | Opens an existing segment or creates it when absent; may regenerate an unhealthy segment | The input-channel `SharedMemManager::Port` and listener |
| `fastrtps_port<remote-input-port-id>` receiver queue segment | External destination into which this transport instance sends descriptors | `Write` | Opens an existing segment or creates it when absent; may regenerate an unhealthy segment | `SharedMemTransport::opened_ports_[port_id]` |

Despite its member name, `global_segment_` is a `SharedMemGlobal` helper rather than a shared-memory payload segment. It stores the SHM domain name and manages globally named port segments. Given a `port_id`, it derives the name `<domain>_port<P>`, locks that port's named mutex, opens or creates the segment, validates or regenerates an existing port, initializes a new `PortNode` and descriptor ring when needed, and can unlink the port. It returns a `Port` wrapper; the wrapper is retained by an input channel or by `opened_ports_`.

`listener_` is a descriptor-queue consumer registration, not a thread and not an RTPS Reader. Its blocking `pop()` waits for a descriptor, reads and removes that descriptor using `global_listener_`'s private ring cursor, opens or finds the descriptor's source data segment, resolves the buffer offset, validates the buffer's `validity_id`, and returns a `SharedMemBuffer` to `SharedMemChannelResource`. `global_port_` keeps access to the shared port segment, while `listener_index_` identifies this listener's status slot for wait, processing, and health tracking. Closing the listener wakes a blocked `pop()`; destroying it unregisters its cursor and status slot.

The thread belongs to `SharedMemChannelResource`. In the normal transport path, one input-channel resource contains one listener and starts one `dds.shm.<port>` thread that repeatedly calls that listener's `pop()`. A `ReadShared` port can register multiple listeners, typically from different channel resources or transport instances; each such channel resource has its own thread. A `ReadExclusive` port permits only one reading owner. Therefore the precise relationship is one receive thread per input-channel resource, not one thread intrinsic to the port or to the `Listener` class.

`watch_task_` keeps the process-wide `SegmentWrapper::WatchTask` alive while a manager is using it. The `dds.shm.wdog` thread invokes this task periodically. For each cached remote data segment, the task checks whether the originating process still holds the segment's exclusive-lock file. If that lock is no longer held, the origin has exited or crashed, so the task unlinks the stale segment name and removes its mapping from `ids_segments_`. This task monitors remote data-segment lifetime; it does not receive RTPS messages.

### Variable-length payload allocation

The data segment is created at a fixed configured size, but it is formatted as a Boost managed shared-memory heap using an `rbtree_best_fit` allocator. At initialization, Fast DDS also creates a fixed array of reusable `BufferNode` metadata slots. A message does not own a fixed-size slot of payload storage.

Boost documents the allocator's layout and behavior in [`rbtree_best_fit`: best-fit logarithmic-time allocation](https://www.boost.org/latest/doc/html/interprocess/allocators_containers.html#interprocess.allocators_containers.memory_algorithms.rbtree_best_fit).

For each outgoing RTPS message:

1. `copy_to_shared_buffer()` requests `alloc_buffer(total_bytes)`.
2. The segment takes one free `BufferNode` and dynamically allocates one contiguous `total_bytes` block from the managed heap.
3. The message's network buffers are copied consecutively into that block.
4. The node stores `data_offset` and `data_size`; its status stores `validity_id`, `enqueued_count`, and `processing_count`.
5. The port descriptor carries the data-segment ID, the **BufferNode offset**, and the validity ID. The receiver first finds the node, then uses the node's `data_offset` and `data_size` to access the variable-length payload.

```text
fixed-size data segment
├── BufferNode A ── data_offset ──> payload A [120 bytes]
├── BufferNode B ── data_offset ──> payload B [4 KiB]
├── BufferNode C ── data_offset ──> payload C [1.2 MiB]
└── currently free heap ranges[]
```

When a buffer has neither queued descriptors nor active processing references, the segment increments its validity generation, deallocates the payload block, and returns the `BufferNode` to the free-node list. Before a new allocation, `recover_buffers()` reclaims such buffers. Under memory pressure it may also invalidate the oldest buffer that is not currently being processed; descriptors carrying the old validity ID then fail validation and are discarded. Allocation can fail when there is insufficient usable space or no free metadata node.

The subscriber's receiving locator selects a separate, globally named port segment. This port segment is **not inside a `SharedMemTransport` and is not part of that transport's data segment**. A `SharedMemTransport` uses its `SharedMemManager` to open the named port and owns the `SharedMemChannelResource`/listener that accesses it, but the port segment remains an independent SHM object addressed by `port_id`. It contains a queue of descriptors rather than copies of the message bytes:

```text
Subscriber receiving locator
    kind    = SHM
    address = <mode, host_id>
    port    = P
                |
                v
Receiver port segment: /dev/shm/fastrtps_port<P>
└── descriptor ring                             [one]
    └── BufferDescriptor[]                      [zero or more queued entries]
        ├── source_segment_id
        ├── buffer_node_offset
        └── validity_id
```

The complete relationship is:

```text
Publisher                                      Receiver

Data segment S                                 Port segment P
┌──────────────────────────┐                  ┌──────────────────────────┐
│ BufferNode at offset N   │                  │ descriptor queue         │
│ └── data_offset = D      │                  └────────────┬─────────────┘
│     └── message bytes    │                               │
│         at offset D      │                               │
└──────────────────────────┘                               │
             │                                             │
             └── enqueue descriptor { S, N, validity } ───>│
                                                           │ pop
                                                           v
                                              map data segment S, locate
                                              BufferNode N, validate it,
                                              then read payload at D
```

The mental model is:

```text
Data segment = where the message bytes live
Port segment = where references to those bytes are delivered
SHM locator  = identifies the destination port segment
Descriptor   = identifies the source data segment and buffer offset
```

The send path therefore does this:

```text
1. Allocate/write an RTPS message in the publisher's data segment.
2. Build BufferDescriptor(segment_id, offset, validity_id).
3. Use remote_locator.port to open/find the receiver's port segment.
4. Push the descriptor into that port's ring.
5. The receiver pops the descriptor and resolves the payload in the data segment.
```

This distinction explains why the SHM locator names the **notification/delivery queue**, while each queued descriptor identifies the **payload storage**.

### How an SHM input channel opens its port

The input-channel path is:

```text
RTPSParticipantImpl::createReceiverResources(locator)
  -> NetworkFactory::BuildReceiverResources(locator)
       for every registered transport that supports locator.kind:
         -> transport->IsInputChannelOpen(locator)
         -> new ReceiverResource(transport, locator, ...)
              -> SharedMemTransport::OpenInputChannel(locator, receiver, ...)
                   -> CreateInputChannelResource(...)
                        -> SharedMemManager::open_port(port_id, ..., open_mode)
                        -> Port::create_listener()
                        -> SharedMemChannelResource(listener, ...)
```

`CreateInputChannelResource()` chooses the port mode from `locator.address[0]`:

```cpp
auto open_mode = locator.address[0] == 'M'
        ? SharedMemGlobal::Port::OpenMode::ReadShared
        : SharedMemGlobal::Port::OpenMode::ReadExclusive;
```

`SharedMemGlobal::open_port_internal()` derives one global name from the domain and port ID:

```cpp
auto port_segment_name = domain_name_ + "_port" + std::to_string(port_id);
```

It then serializes open/create operations with another named object:

```text
<domain>_port<P>_mutex
```

While holding that mutex, it follows this sequence:

```text
1. Try open_only("<domain>_port<P>").
2. If it exists:
   - validate the segment and ABI PortNode;
   - create another Port wrapper for the same segment;
   - acquire the requested read-mode lock;
   - run the health check;
   - increment the shared PortNode ref_counter.
3. If it does not exist, or an invalid/zombie port was removed:
   - create_only("<domain>_port<P>");
   - allocate and initialize PortNode;
   - allocate the descriptor-ring cells and ring node;
   - acquire the requested read-mode lock;
   - create the first Port wrapper and listener.
```

The port object is managed cooperatively across processes and transport instances:

```text
named port segment
├── PortNode                                    [one]
│   ├── UUID and ABI version                    [one]
│   ├── health state                            [one]
│   ├── shared ref_counter                      [one]
│   ├── empty_cv                                [one port-wide interprocess condition variable]
│   ├── empty_cv_mutex                          [one port-wide interprocess mutex]
│   ├── waiting_count                           [one count of waiting listener threads]
│   ├── listener_status[]                       [status slots only; no per-listener futex]
│   └── descriptor-ring offsets                 [one set]
├── descriptor-ring cell[]                      [configured capacity]
└── descriptor-ring control node                [one]
```

Creating a listener reserves one listener-status slot and registers an independent ring read position. The status slot stores `is_in_use`, `is_waiting`, `is_processing`, health counters, and the descriptor currently being processed; it contains no futex or condition variable. Destroying the listener unregisters its ring position and status slot.

All threads reading the same port wait on the single `PortNode::empty_cv` under `empty_cv_mutex`. After a writer pushes a descriptor, a unicast-style `ReadExclusive` port uses `notify_one()` when the ring was previously empty. A multicast-style `ReadShared` port uses `notify_all()`, waking every waiting listener thread. Each awakened thread evaluates `listener.head() != nullptr` against its own registered ring cursor, so each shared listener can consume the descriptor independently. Timed waits also let listeners update their health counters and notice a failed port.

Multiple transport instances can read the same named port only in `ReadShared` mode. Each instance has its own `SharedMemChannelResource`, listener cursor, listener-status slot, and receive thread, but all those threads wait on the same port-wide `empty_cv` stored in the shared port segment.

Every `SharedMemGlobal::Port` wrapper increments `PortNode::ref_counter`; its destructor decrements the counter. The last wrapper removes the port segment and its named mutex when the port remains healthy and nobody reopened it while cleanup acquired the mutex.

### Two SHM transports opening the same port

Two `SharedMemTransport` instances use the same SHM manager domain and derive the same name for the same `port_id`. They therefore do **not** normally create two port segments:

```text
SharedMemTransport instance[]                    (two shown)
├── instance A -- open port P --┐
└── instance B -- open port P --┴--> one /dev/shm/fastrtps_port<P>
```

The named mutex makes the open-or-create operation atomic. The first transport creates the segment; the second executes `open_only()` and maps the existing segment.

What happens next depends on the mode:

| Open combination | Result |
| --- | --- |
| `Write` + `Write` | Both can open wrappers for the same port segment and push descriptors. |
| `Write` + reader | The writer and reader refer to the same port segment. |
| `ReadShared` + `ReadShared` | Both can open it and register separate listeners, subject to listener capacity. |
| `ReadExclusive` + second reader | The second reader open fails because the exclusive read lock is already held. |
| `ReadShared` + `ReadExclusive`, either order | The conflicting open fails. |

This matters when one participant registers two SHM transports. `NetworkFactory::BuildReceiverResources()` visits both because both report support for `LOCATOR_KIND_SHM`:

```text
unicast-style SHM locator ('U')
├── first transport: creates/opens port P as ReadExclusive -> succeeds
└── second transport: opens the same port P as ReadExclusive -> lock fails

multicast-style SHM locator ('M')
├── first transport: creates/opens port P as ReadShared -> listener 1
└── second transport: opens the same port P as ReadShared -> listener 2
```

On the output side, `NetworkFactory::build_send_resources()` iterates over every registered transport instance and calls `OpenOutputChannel()` or `OpenOutputChannels()` on each one. This is an opportunity for each applicable transport to provide sender resources, not an unconditional creation of one resource per transport instance. For SHM, the first applicable `SharedMemTransport` creates a `SharedMemSenderResource`. A later SHM transport instance finds that existing SHM-kind resource through `SharedMemSenderResource::cast()`, returns success, and does not append another one. Because the resource's send lambda remains bound to the transport instance that created it, a send-resource list uses that selected SHM transport's data segment rather than one data segment from every registered SHM transport.

### SHM receive threads

`SharedMemTransport::CreateInputChannelResource()` opens the locator's port, creates a listener, and constructs `SharedMemChannelResource` with its receive thread enabled:

```text
SHM input locator with port P                 [one]
└── SharedMemChannelResource                 [one]
    └── dds.shm.<P> thread                   [one]
        └── listener_->pop()                 [repeated blocking operation]
            └── resolve one descriptor
                └── OnDataReceived(...)      [one call per resolved message]
```

Thus one opened SHM input-channel resource has one listener thread. A sender pushes descriptors directly and does not create one send thread per destination port.

## TCP: physical endpoint plus logical port

TCP is connection-oriented, while the Fast DDS transport interface still needs a port-like receiver key. Fast DDS packs two 16-bit values into the locator's 32-bit `port` field:

```text
TCP Locator
├── kind                                  [one: TCPv4 or TCPv6]
├── address                               [one 16-byte field: IP address]
└── port[31:0]                            [one 32-bit field]
    ├── physical port                     [one 16-bit OS endpoint port]
    └── logical port                      [one 16-bit receiver key]
```

`IPLocator::setPhysicalPort()` and `setLogicalPort()` access the two halves. Fast DDS prints a TCP locator as:

```text
[address]:physical-port-logical-port
```

The physical port is used for socket establishment:

```text
remote IP + physical port
          |
          +-- connect(), or bind()/listen()/accept()
          |
          v
established bidirectional TCP connection
```

The logical port is used inside that connection. Every Fast DDS TCP frame has a `TCPHeader` containing `logical_port`:

```cpp
struct TCPHeader
{
    char rtcp[4];
    uint32_t length;
    uint32_t crc;
    uint16_t logical_port;
};
```

`TCPTransportInterface::OpenInputChannel()` registers a receiver under `receiver_resources_[logical_port]`; it does not create a socket or thread. The connection receive loop extracts `TCPHeader.logical_port` and uses it to select the registered receiver:

```text
one TCP connection
└── frame[]
    └── TCPHeader.logical_port -> receiver_resources_[logical_port]
```

The logical port therefore has the same upper-level role as a UDP or SHM receiving port: it selects the receiving transport channel. It is not an OS port and several logical ports can share one TCP connection.


This illustrates a general RTPS transport model: messages are addressed through a locator composed of transport kind, address, and port. The `port` here is the locator port field, not inherently an operating-system UDP or TCP port or an SHM object. The concrete transport defines its meaning. UDP maps it directly to an OS UDP port; SHM maps it to a named receiver-queue ID; Fast DDS TCP divides it into a physical OS port and a logical receiver port.

On receive, Fast DDS registers and groups `TransportReceiverInterface` callbacks according to this transport-specific port interpretation:

```text
locator kind + address + port
│
├── UDP
│   └── locator port -> OS UDP port
│       └── UDPChannelResource                         [one bound socket/interface resource]
│           └── TransportReceiverInterface             [one ReceiverResource]
│               └── MessageReceiver                    [one]
│                   └── associated local endpoint[]    [zero or more readers/writers]
│
├── SHM
│   └── locator port -> named receiver queue
│       └── SharedMemChannelResource                   [one queue listener resource]
│           └── TransportReceiverInterface             [one ReceiverResource]
│               └── MessageReceiver                    [one]
│                   └── associated local endpoint[]    [zero or more readers/writers]
│
└── TCP
    └── locator port -> physical port + logical port
        ├── TCPChannelResource                         [one established connection]
        │   └── received frame[]                       [zero or more logical ports]
        └── receiver_resources_[logical_port]
            └── TransportReceiverInterface             [one ReceiverResource per registered logical port]
                └── MessageReceiver                    [one]
                    └── associated local endpoint[]    [zero or more readers/writers]
```

`TransportReceiverInterface` itself is only the transport-facing callback abstraction and does not contain endpoint collections. In the normal path, `ReceiverResource` implements that interface and references one `MessageReceiver`. `RTPSParticipantImpl::assignEndpoint2LocatorList()` associates every local RTPS reader or writer whose locator is supported by that receiver resource. `MessageReceiver` stores those associations in `associated_readers_` and `associated_writers_`, parses each incoming RTPS message, and dispatches its submessages to the matching local endpoints.

A UDP or SHM channel resource therefore forwards received messages to one `ReceiverResource` and its `MessageReceiver`. Multiple UDP resources may share the same numeric UDP port when they bind different interfaces. A TCP channel resource instead represents a connection and can carry frames for multiple logical ports; `TCPHeader.logical_port` selects the corresponding `ReceiverResource` from `receiver_resources_`, after which its `MessageReceiver` performs RTPS endpoint dispatch.

### Message framing on the TCP byte stream

TCP preserves byte order but exposes no message boundaries. Fast DDS therefore wraps each RTPS message in its own 14-byte `TCPHeader`:

```text
one Fast DDS TCP frame
├── rtcp[4] = "RTCP"                         [synchronization marker]
├── length                                  [header plus body length]
├── crc                                     [optional body integrity check]
├── logical_port                            [receiver selection]
└── body[length - 14]                       [one complete RTPS message]
```

The receive loop does not assume that one socket read returns one frame. `receive_header()` repeatedly reads until it has found the four-byte `RTCP` marker and collected the complete 14-byte header. It then validates `length`, calculates the body size, and uses an exact-length read to accumulate that many body bytes, potentially across several TCP packets and socket reads. Only the complete body is delivered to `OnDataReceived()`.

```text
TCP packets / socket reads
    [part of header] [rest of header + part of body] [rest of body]
              └──────── exact-length accumulation ────────┘
                                  │
                                  v
                         one complete RTPS message
```

A TCP reconnection starts a new byte stream; Fast DDS never concatenates the tail of the old stream with bytes from the new one. If EOF, reset, or another read error occurs while receiving a header or body, the current frame is abandoned and the old socket is closed. A newly established connection starts a new receive loop, exchanges the RTCP bind handshake, and renegotiates pending logical ports before carrying normal frames.

```text
old connection:  [header][partial body] -- connection lost --> discard partial frame
new connection:  RTCP bind handshake -> reopen logical ports -> [new header][new body]
```

TCP provides ordered, reliable bytes only for the lifetime of one connection. Recovery of a lost RTPS message is a higher-level concern: a reliable RTPS writer may retransmit data according to the RTPS reliability protocol, while best-effort traffic may simply be lost. The transport does not splice or resume a partially received frame across connections.

### Inside one TCP transport instance

```text
TCPv4Transport or TCPv6Transport instance
├── configuration_                              [one descriptor copy]
├── interface_whitelist_[]                      [zero or more IP addresses]
└── TCPTransportInterface state
    ├── alive_                                  [one]
    ├── io_context_                             [one; accept/connect operations]
    ├── io_context_timers_                      [one]
    ├── io_context_thread_                      [one dds.tcp_accept thread]
    ├── initial_peer_local_locator_socket_?     [optional]
    ├── rtcp_message_manager_                   [one]
    ├── acceptors_[physical_locator]            [zero or more]
    │   └── TCPAcceptor                         [one per map entry]
    │       └── async_accept operation          [one outstanding operation]
    ├── unbound_channel_resources_[]            [zero or more accepted channels]
    │   └── shared_ptr<TCPChannelResource>
    ├── channel_resources_[physical_locator]    [zero or more]
    │   └── shared_ptr<TCPChannelResource>      [one per map entry]
    │       ├── locator_ / connection_status_   [one each]
    │       ├── logical_output_ports_[]         [zero or more]
    │       ├── pending_logical_output_ports_[] [zero or more]
    │       ├── negotiating_logical_ports_[transaction_id]
    │       │                                       [zero or more map entries]
    │       ├── last_checked_logical_port_[transaction_id]
    │       │                                       [zero or more map entries]
    │       ├── ChannelResource base
    │       │   ├── message_buffer_             [one]
    │       │   ├── alive_                      [one]
    │       │   └── thread_                     [one dds.tcp.<local-port> thread]
    │       └── concrete Basic or Secure channel
    │           └── bidirectional TCP socket    [one]
    ├── receiver_resources_[logical_port]       [zero or more]
    │   └── receiver + ReceiverInUseCV          [one pair per logical port]
    ├── channel_pending_logical_ports_[physical_locator]
    │   │                                         [zero or more map entries]
    │   └── logical_port[]                        [zero or more set members]
    ├── sockets_timestamp_[]                    [zero or more]
    ├── allowed_interfaces_[]                   [zero or more]
    └── netmask_filter_                         [one]

Objects created by this instance but stored in participant send-resource lists
└── TCPSenderResource[]                         [zero or more]
    ├── locator_                                [one physical/logical locator]
    ├── channel_                                [one weak_ptr]
    └── send_lambda_                            [one]
```

The physical locator selects or establishes a connection resource. The logical port selects an entry in `receiver_resources_` after a frame has arrived on that connection.

### TCP receive threads

TCP has two thread layers:

```text
TCPTransportInterface
├── dds.tcp_accept thread                       [exactly one]
│   └── shared Asio io_context                  [one]
│       └── async_accept operation[]            [one per acceptor]
│
└── established TCPChannelResource[]            [zero or more]
    ├── receive thread                          [one per connection]
    └── logical port[]                          [zero or more per connection]
```

`TCPTransportInterface::init()` starts the shared `dds.tcp_accept` event-loop thread. `TCPAcceptorBasic::async_accept()` registers accept operations on that loop.

After either `SocketAccepted()` or `SocketConnected()` creates an established `TCPChannelResource`, `create_listening_thread()` starts a blocking receive thread for that connection. Consequently:

- there is no receive thread per logical port;
- acceptors share the transport's Asio accept thread;
- there is one blocking receive thread per established TCP channel/connection.

The established TCP socket is bidirectional and can carry both sends and receives. The physical port establishes or identifies the connection; the logical port demultiplexes RTPS traffic carried within it.

### TCP with no interface whitelist

TCP uses all usable interfaces without creating one listening socket per interface:

```text
multi-interface host
├── advertised TCP locators
│   └── one concrete locator per discovered local IP address
│       └── same configured physical listening port and logical port
├── connection acceptance
│   └── one acceptor bound to wildcard address 0.0.0.0:P or [::]:P
│       └── accepts connections arriving through any local interface
└── outgoing connection
    └── one unbound client socket connects to remote IP:P
        └── kernel routing selects the local interface and source address
```

As with UDP, an unspecified default locator is expanded by `NormalizeLocator()` into concrete locators for the discovered local addresses, with loopback used as a fallback. The runtime acceptor itself is constructed with the protocol's wildcard endpoint, so one acceptor covers all local addresses on the physical listening port. All accept operations share the transport's single Asio event-loop thread; each accepted connection later receives its own blocking receive thread.

For an outgoing connection, `TCPChannelResourceBasic::connect()` creates a fresh socket and calls `async_connect()` for a selected remote locator without first binding a local interface. The operating system chooses the route, local interface, source IP, and ephemeral source port. TCP locator selection includes the supported unicast locators advertised by a peer, so Fast DDS can create output channels for several remote IP addresses. Each connection attempt still uses one kernel-selected local route; Fast DDS does not reproduce that attempt through every local interface.

The established socket is bidirectional, so these rules are independent of whether an RTPS writer or reader caused a particular message to be sent. Also, TCP is not part of Fast DDS's ordinary built-in default transport set; this describes a configured TCP transport whose interface whitelist is empty.

## Comparison

```text
UDP
  destination:      IP + physical UDP port
  receive unit:     bound socket resource
  message boundary: one UDP datagram carries one RTPS message;
                    the datagram boundary is preserved on receive
  threads:          one blocking receive thread per bound socket resource

SHM
  destination:      host ID + queue-port ID
  receive unit:     shared-memory port/listener resource
  message boundary: one descriptor references one complete RTPS message buffer
  threads:          one blocking receive thread per input-channel resource

TCP
  destination:      IP + physical TCP port + logical RTPS port
  receive unit:     established connection, then logical-port dispatch
  message boundary: byte stream framed by a 14-byte TCPHeader;
                    length determines the complete RTPS-message body
  reconnect:        discard a partial old-connection frame;
                    start fresh framing and negotiation on the new connection
  threads:          one shared accept event loop per transport
                    plus one blocking receive thread per connection
```

Large DDS samples may be represented as RTPS `DATA_FRAG` submessages before reaching any of these transport-specific message-boundary mechanisms.

At the payload level, the DDS/RTPS layer constructs a serialized RTPS message and passes that complete message to the selected transport. The transport does not parse RTPS submessages such as `DATA`, `DATA_FRAG`, `HEARTBEAT`, or `ACKNACK`; it handles the serialized RTPS message as bytes. UDP preserves the message as one datagram, SHM preserves it as one descriptor-referenced buffer, and TCP adds `TCPHeader` framing because its underlying connection provides only a byte stream.

The TCP implementation is not entirely RTPS-agnostic infrastructure because it also implements Fast DDS's RTCP connection-control and logical-port protocol. It nevertheless treats the RTPS message body as opaque bytes; interpretation of RTPS submessages remains above the transport layer.

## Caveat: multiple locators can produce duplicate transport traffic

One RTPS endpoint can advertise multiple unicast locators, typically one for each local interface. UDP and TCP locator selection can select all supported unicast locators. If a peer can reach more than one advertised address, Fast DDS may send the same RTPS message through several destination locators.

```text
one remote RTPS endpoint
├── locator 10.0.0.20:7412
└── locator 192.168.1.20:7412

one RTPS message
├── transport copy -> 10.0.0.20:7412
└── transport copy -> 192.168.1.20:7412
```

A wildcard-bound receiver may consequently receive multiple transport-level copies of the message. This behavior is confirmed by the implementation path:

1. `UDPv4Transport::NormalizeLocator()` and `TCPv4Transport::NormalizeLocator()` expand an unspecified locator into one locator for every allowed discovered interface.
2. `UDPTransportInterface::select_locators()` and `TCPTransportInterface::select_locators()` append every supported, not-already-selected unicast locator to `entry->state.unicast`.
3. UDP `send()` iterates the selected destination locators and calls `socket->send_to()` for each one. TCP `OpenOutputChannels()` creates or reuses an output channel for every selected locator, while each `TCPSenderResource` sends through the channel whose physical locator matches that destination.
4. `RTPSParticipantImpl::sendSync()` invokes all applicable sender resources with the same serialized RTPS message.

The duplicate is suppressed above the transport layer. A stateful reader checks `WriterProxy::change_was_received(sequenceNumber)` before adding a received change. A stateless reader checks `thereIsUpperRecordOf(writerGUID, sequenceNumber)`, which compares the sequence number with the last notified value. Because these checks run under the reader mutex, two copies of the same writer GUID and sequence number do not normally produce two DDS data notifications.

The qualified conclusion is therefore: multiple advertised and reachable unicast locators **can** cause duplicate UDP datagrams or RTPS messages over multiple TCP channels, while the RTPS reader normally delivers the corresponding DDS sample once. Locator filtering, multicast selection, unreachable addresses, or connection reuse can prevent duplicate transport delivery in a particular run. Any extra copies that do arrive still consume network and transport-processing resources.

## Send-Receive lifecycle

### Transports, channels, and resource objects

Four related concepts appear repeatedly in the transport code, but they are not interchangeable:

| Concept | Meaning in Fast DDS |
| ------- | ------------------- |
| **Transport instance** | The participant-local UDP, TCP, or SHM implementation. It owns transport-wide state and the concrete I/O objects that the implementation keeps. |
| **Locator** | A value that names where communication should occur. It is used to select a transport and to find, create, or reuse a channel; it does not own anything. |
| **Channel** | A transport-defined communication path prepared or registered through `OpenInputChannel()` or `OpenOutputChannel()`. The identity and physical realization of a channel depend on the transport. |
| **Resource object** | A participant-facing handle or callback adapter that gives the RTPS layer access to a transport channel. `SenderResource` and `ReceiverResource` are the two main resource abstractions. |

“Channel” is therefore an interface concept, not a promise that there is exactly one socket or one shared-memory region behind it. Fast DDS also has an internal `ChannelResource` base class, but that class is only a receive-loop/connection implementation helper. It should not be confused with every channel described by the `TransportInterface` API.

Input and output are named from the local participant's point of view:

- An **output channel** carries locally produced RTPS messages toward remote locators.
- An **input channel** accepts messages addressed to a local locator and delivers them through a `TransportReceiverInterface` callback.

### UML relationship overview

The model is shown in one layered view. A filled diamond means exclusive structural ownership, a hollow diamond means retained shared ownership, a solid arrow means an association, a dashed arrow means a dependency or delegation, and a hollow triangle means inheritance or interface realization. Multiplicities describe one object on the source side unless the label says otherwise.

[![Fast DDS participant, transport, sender-resource, and receiver-resource ownership UML](/assets/images/fast_dds_transport_resource_ownership_uml.svg)](/assets/images/fast_dds_transport_resource_ownership_uml.svg)

The diagram follows the send and receive paths through participant-owned resources and transport-owned channels. Discovery supplies remote locators; `NetworkFactory` asks each compatible transport to reuse or add a `SenderResource` to the participant's list. During `sendSync()`, each resource filters the destination locators it can serve and sends the already-formed RTPS message through its transport.

For reception, endpoint setup opens or reuses a `ReceiverResource` for each local locator, then associates the endpoint with every matching `MessageReceiver`. UDP channels receive on bound sockets, SHM channels pop descriptors from port queues, and TCP connections use the frame's logical port to select a receiver callback. All three paths reach `ReceiverResource::OnDataReceived()`, which passes the bytes to `MessageReceiver` for RTPS parsing and dispatch to associated readers or writers.

### Ownership and lifetime

Each `RTPSParticipantImpl` contains one `NetworkFactory`. The factory owns the participant's initialized transport instances. The participant separately owns its sender-resource list and its receiver control blocks. Built-in and application endpoints share these participant-level objects.

```text
RTPSParticipantImpl
|
+-- m_network_Factory : NetworkFactory
|   +-- mRegisteredTransports
|       : vector<unique_ptr<TransportInterface>>
|       +-- UDP transport
|       |   +-- receive-side UDPChannelResource objects --> one socket each
|       +-- TCP transport
|       |   +-- acceptors                              --> listening sockets
|       |   +-- TCPChannelResource objects             --> connection sockets
|       |   +-- receiver_resources_                    --> logical-port callbacks
|       +-- SHM transport
|           +-- input SharedMemChannelResource objects --> port listeners
|           +-- opened output ports
|           +-- one local segment used to allocate outgoing buffers
|
+-- send_resource_list_ : vector<unique_ptr<SenderResource>>
|   +-- UDPSenderResource      --> owns one output socket
|   +-- TCPSenderResource      --> identifies a physical destination; observes a connection
|   +-- SharedMemSenderResource --> delegates to transport-wide SHM state
|
+-- m_receiverResourcelist : list<ReceiverControlBlock>
    +-- shared_ptr<ReceiverResource> --> one transport's input-channel registration
    +-- MessageReceiver*             --> parses RTPS and dispatches to local endpoints
```

The arrows in this diagram do not all mean ownership. A sender or receiver resource is associated with exactly one transport instance, but it normally calls that transport through a reference captured in a function object. The network factory's transport must therefore outlive the participant's resource objects. The participant's shutdown order enforces that relationship.

Concrete channel objects belong to the transport that creates them. For example, the UDP transport stores raw `UDPChannelResource*` values in `mInputSockets` and deletes them when it closes the input channel. TCP stores connection resources in `shared_ptr`s, while the SHM transport stores its input channel resources and cached output ports.

The source comments describe `SenderResource` and `ReceiverResource` as RAII objects, but their current cleanup behavior is asymmetric:

- Concrete sender-resource destructors run their cleanup callbacks. A UDP sender closes its socket; a TCP sender invalidates its locator but leaves connection shutdown to the transport; an SHM sender has no per-resource cleanup.
- `ReceiverResource` opens the input registration in its constructor, but its destructor is empty. `RTPSParticipantImpl::disable()` explicitly calls `ReceiverResource::disable()`, which closes or unregisters the transport channel and waits for active callbacks. The current implementation therefore relies on ordered participant shutdown rather than destructor-only RAII for reception.

Resources are not paired one-to-one with RTPS endpoints. Several endpoints can share a receiver resource, and one endpoint can use several resources. They are also not paired with each other: a sender resource has no corresponding receiver-resource object.

### What `SenderResource` does

`SenderResource` is the type-erased sending interface retained by the participant. Its public `send()` function receives already-formed message buffers, a range of destination locators, a blocking deadline, and a transport priority. A concrete sender resource installs a callback that delegates this operation to its transport.

The resource stores the transport kind so a transport can recognize and reuse its own resources. It does not keep an endpoint registry because the caller has already selected the destinations and formed the RTPS message. The participant iterates its sender-resource list; each resource consumes or skips locators according to its transport and interface restrictions.

The concrete meaning of one sender resource varies:

- `UDPSenderResource` owns one moved-in UDP socket plus interface-related flags. The same socket can send datagrams to many remote locators.
- `TCPSenderResource` stores a remote physical locator and a weak identity reference to the connection that existed when the resource was created. The TCP transport owns the actual `TCPChannelResource` and socket. A sender resource can exist while the transport is waiting for the peer to establish that connection.
- `SharedMemSenderResource` owns no port or memory segment. One such resource is reused for the transport; each send asks the transport to allocate a buffer in its local segment and push a descriptor to each selected destination port.

### What `ReceiverResource` does

`ReceiverResource` is an internal network-layer adapter between one transport input registration and one `MessageReceiver`. Only `NetworkFactory` can invoke its private constructor. Construction calls:

```cpp
transport.OpenInputChannel(locator, this, max_message_size);
```

Here, `this` points to the `ReceiverResource` under construction. Because `ReceiverResource` implements `TransportReceiverInterface`, the call implicitly converts that pointer to `TransportReceiverInterface*`. The transport retains this non-owning base pointer in its input registration or channel resources and later calls `OnDataReceived()` on it with the bytes plus local and remote locators. Dynamic dispatch enters `ReceiverResource::OnDataReceived()`, which wraps the bytes in a `CDRMessage_t` and forwards them to its registered `MessageReceiver`. The `MessageReceiver` then parses the RTPS message and dispatches it through its associated-reader and associated-writer indexes.

`ReceiverResource` does not own a socket, TCP connection, SHM port, or receive thread. It stores callbacks that capture the transport and the locator used at construction:

- `Cleanup` calls `CloseInputChannel(locator)`.
- `LocatorMapsToManagedChannel` calls `DoInputLocatorsMatch()` so the participant can reuse the registration for an equivalent local locator.

Its mutex, callback counter, and condition variable prevent shutdown from completing while `OnDataReceived()` is active. The enclosing `ReceiverControlBlock` keeps the `ReceiverResource` and its `MessageReceiver` together.

This constructor call also establishes the main ownership and dispatch relationship. Each `ReceiverResource` is created for one specific transport instance and one seed locator. After the input registration opens successfully, `RTPSParticipantImpl` creates exactly one `MessageReceiver` for that `ReceiverResource` and registers it through `RegisterReceiver()`. In the normal participant receive path, the relationship is therefore **one transport instance + one `ReceiverResource` + one `MessageReceiver`**.

The seed locator does not always imply a one-to-one relationship with a concrete socket or connection. `ReceiverResource` retains the transport instance and seed locator in its cleanup and locator-matching callbacks, while `SupportsLocator()` delegates equivalence to that transport's `DoInputLocatorsMatch()`. A transport may therefore treat several full locator values as the same input registration, and one registration may be reached through one or several concrete channel resources.

Input-registration identity and endpoint-association equivalence are separate checks:

- UDP uses the physical UDP port for both `IsInputChannelOpen()` and `DoInputLocatorsMatch()`; locator addresses on that port share the registration.
- TCP uses the logical port for `IsInputChannelOpen()`, but `DoInputLocatorsMatch()` compares physical ports. Distinct logical-port registrations can therefore be associated with endpoints whose locators share the same physical listening port; the received `TCPHeader.logical_port` still selects the actual callback.
- SHM uses exact locator equality in `IsInputChannelOpen()`, while `DoInputLocatorsMatch()` compares SHM kind and queue-port ID. The normal same-locator case remains one input channel per SHM transport instance.

| Transport configuration | Input registration represented by one `ReceiverResource` | Concrete channel resources that can deliver to it | Effective relationship |
|---|---|---|---|
| UDP, no whitelist | One physical UDP port in one UDP transport instance | One wildcard-bound `UDPChannelResource` normally covers every local interface | One resource and one `MessageReceiver`; multiple interface-address locators converge on it because UDP input matching uses the physical port |
| UDP, interface whitelist | One physical UDP port in one UDP transport instance | One `UDPChannelResource` per selected binding interface/socket; multicast may add a multicast-address-bound resource | One `ReceiverResource` and `MessageReceiver` can serve several UDP channel resources |
| TCP, no whitelist | One `receiver_resources_[logical_port]` entry in one TCP transport instance | A wildcard acceptor can create zero or more connection-specific `TCPChannelResource` objects; frames whose `TCPHeader.logical_port` matches the entry dispatch to this receiver | One `ReceiverResource` and `MessageReceiver` can serve many TCP connection resources over time |
| TCP, interface whitelist | The same one logical-port entry | One acceptor per whitelisted local address can create zero or more connection-specific `TCPChannelResource` objects | The whitelist restricts listening addresses; all matching connections still dispatch through the transport instance's logical-port table |
| SHM, one transport instance | One SHM queue-port locator in one SHM transport instance | Exactly one `SharedMemChannelResource` and listener for that opened input locator | One `ReceiverResource` maps to one `MessageReceiver` and one SHM channel resource within that transport instance |
| SHM, multiple transports with a `ReadShared` locator | Each supporting SHM transport instance creates its own input registration for the same locator | Each instance creates its own `SharedMemChannelResource` and listener | The same locator can produce multiple independent one-to-one receiver/channel pairs, one pair per transport instance |
| SHM, `ReadExclusive` locator | Only the transport instance that successfully acquires exclusive read ownership can open the registration | One active SHM channel resource and listener | One active `ReceiverResource`–`MessageReceiver`–channel chain |

The resulting cardinalities are:

- A `ReceiverResource` belongs to exactly one transport instance and normally has exactly one `MessageReceiver`.
- A `ReceiverResource` originates from one seed locator, but it can report support for other locators that the same transport considers equivalent.
- UDP can map one `ReceiverResource` to one wildcard channel resource or several interface-specific channel resources.
- TCP maps one `ReceiverResource` to a logical-port registration; any number of established connection resources can dispatch matching frames to it.
- SHM has a one-to-one relationship between a `ReceiverResource` and a `SharedMemChannelResource` within one transport instance. Multiple SHM transport instances may independently open the same `ReadShared` locator, producing separate one-to-one chains.

### What `MessageReceiver` does

`MessageReceiver` is the RTPS protocol dispatcher behind a `ReceiverResource`. The transport and `ReceiverResource` only deliver a complete byte buffer together with its local and remote locators. `MessageReceiver::processCDRMsg()` interprets those bytes as an RTPS message and routes its submessages to the local RTPS readers and writers associated with this receive resource.

```text
transport channel resource
└── ReceiverResource::OnDataReceived()
    └── MessageReceiver::processCDRMsg()
        ├── validate the RTPS header
        ├── establish source and destination participant context
        ├── iterate through the RTPS submessages
        └── dispatch each endpoint-directed submessage
            ├── DATA / DATA_FRAG / HEARTBEAT / GAP / HEARTBEAT_FRAG
            │   └── associated local reader endpoint[]
            └── ACKNACK / NACK_FRAG
                └── associated local writer endpoint[]
```

The participant associates endpoints with a `MessageReceiver` when their local locators are supported by the corresponding `ReceiverResource`. The receiver maintains two endpoint collections:

- `associated_readers_` maps a reader entity ID to one or more local `BaseReader` objects.
- `associated_writers_` stores the local `BaseWriter` objects that can receive writer-directed feedback.

For reader-directed submessages, `findAllReaders()` selects the vector matching the destination reader entity ID. An unknown reader ID means that every associated reader is considered. The selected reader handles the DATA, DATA_FRAG, HEARTBEAT, GAP, or HEARTBEAT_FRAG operation.

For writer-directed ACKNACK and NACK_FRAG submessages, `MessageReceiver` scans `associated_writers_`. Each writer checks the destination writer GUID, and dispatch stops when the matching writer accepts the submessage.

Other RTPS submessages, such as INFO_SRC, INFO_DST, and INFO_TS, update the parsing context used for later submessages rather than selecting an endpoint directly. The `MessageReceiver` therefore performs RTPS parsing and endpoint dispatch; it does not receive bytes from the OS or implement UDP, TCP, or SHM transport behavior.

## Transport configuration best practices

Fast DDS uses one UDPv4 transport and one SHM transport by default. UDP provides cross-host communication, while SHM provides same-host communication. This configuration is normally sufficient.

When interface restrictions or custom SHM sizing are required, disable the built-in transports and define one UDP transport with the desired interface whitelist plus one SHM transport with the desired segment size.

Registering multiple transport instances of the same kind is normally redundant. This is especially true for SHM, where additional instances allocate additional data segments without normally providing another independent sending path.
