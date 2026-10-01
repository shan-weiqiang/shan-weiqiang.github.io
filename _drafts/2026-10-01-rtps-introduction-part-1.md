---
layout: post
title:  "RTPS Introduction — Part 1: Discovery, Locators, Transports, and Data Transmission"
date:   2026-10-01 00:00:00 +0800
tags: [dds, rtps, middleware, fast-dds]
---

* toc
{:toc}

This guide explains RTPS discovery and data transmission through the Fast DDS 3.6.2 implementation. Payload handling is outside its scope.

## 1. What is discovered?

### Participant information

Participant discovery exchanges identity, reachability, and presence information. Fast DDS stores it in `ParticipantProxyData`, which extends `ParticipantBuiltinTopicData`.

| Information                       | Purpose                                                  |
| --------------------------------- | -------------------------------------------------------- |
| Participant GUID                  | Identifies the participant                               |
| Participant name                  | Configured name; not a globally unique identity          |
| Metatraffic locators              | Receiving destinations for built-in discovery traffic    |
| Default locators                  | Default receiving destinations for application endpoints |
| Available built-in endpoint flags | Identifies supported discovery endpoints                 |
| Lease duration                    | Controls detection of an unresponsive participant        |
| Vendor and protocol information   | Identifies the implementation and protocol version       |

The local record also contains presence state, timers, and endpoint collections. These bookkeeping objects are not transmitted.

### Endpoint information

Endpoint discovery describes application writers and readers.

| Fast DDS record   | Base type                      | Describes |
| ----------------- | ------------------------------ | --------- |
| `WriterProxyData` | `PublicationBuiltinTopicData`  | A writer  |
| `ReaderProxyData` | `SubscriptionBuiltinTopicData` | A reader  |

Both descriptions contain:

| Information                        | Purpose                                                        |
| ---------------------------------- | -------------------------------------------------------------- |
| Endpoint GUID and participant GUID | Identifies the endpoint and its owner                          |
| Topic name                         | Identifies the topic                                           |
| Type name and type information     | Supports type compatibility checks                             |
| Keyed/unkeyed topic kind           | Describes the topic's instance model                           |
| QoS                                | Describes offered writer behavior or requested reader behavior |
| Receiving locators                 | Describes where the endpoint receives RTPS traffic             |

Discovery records describe endpoints; they are not application samples or remote C++ objects. Discovery fields are serialized as parameter lists, not as in-memory object layouts.

`ProxyData` means descriptive metadata. `ReaderProxy` and `WriterProxy` instead hold per-peer communication state for stateful endpoints.

### Locators

A locator describes a transport destination or receiving resource, not a topic or endpoint identity.

| `Locator_t` field | Meaning                                        |
| ----------------- | ---------------------------------------------- |
| `kind`            | Transport kind                                 |
| `address[16]`     | Transport-specific address                     |
| `port`            | Port or transport-specific resource identifier |

| Transport | Address and port interpretation                                                              |
| --------- | -------------------------------------------------------------------------------------------- |
| UDP       | IP address and UDP port                                                                      |
| TCP       | IP address with transport-specific addressing; physical socket and logical RTPS ports        |
| SHM       | Host identifier and shared-memory queue-port identifier, not an IP address or memory pointer |

Several endpoints can share receiving resources. RTPS identifiers distinguish their traffic after reception.

#### Unicast and multicast

Receiving locators are grouped into unicast and multicast lists.

| UDP destination | Meaning                          | Typical use                                                |
| --------------- | -------------------------------- | ---------------------------------------------------------- |
| Unicast         | A particular IP address and port | Initial peers, discovery exchanges, and application traffic |
| Multicast       | A group address and port         | Participant announcements or delivery to several readers   |

Multicast is not broadcast. Receivers join a group on selected interfaces. Receiving multicast traffic does not make an endpoint a subscriber; matching and RTPS identifiers still govern acceptance.

Discovery multicast and application-data multicast are configured separately.

#### Both readers and writers advertise receiving locators

| Endpoint | Receives from its matched peer                                                                   |
| -------- | ------------------------------------------------------------------------------------------------ |
| Reader   | Application data and writer control messages                                                     |
| Writer   | Reader feedback, including acknowledgments and retransmission requests in reliable communication |

Writer and reader describe application-data roles, not one-way transport roles. Best-effort communication does not require reliable feedback.

Endpoints can advertise several locators. When endpoint-specific locators are absent, participant defaults supply the receiving destinations.

A remote receiving locator becomes a local sending destination. It does not directly select the sender's interface; transport configuration, socket setup, and OS routing determine the outgoing path.

#### Shared memory also uses locators

A Fast DDS SHM locator identifies a host-local receiving queue. Buffer descriptors delivered through that queue identify the shared-memory payload buffers.

SHM requires access to shared-memory resources on the same host. It cannot communicate across physical hosts.

With normal UDP + SHM defaults, discovery uses network transport while same-host application data can use SHM. SHM-only participants can also discover each other through SHM. SHM transport and data-sharing delivery are separate mechanisms.

## 2. SIMPLE discovery: SPDP and SEDP

Normal SIMPLE discovery uses two cooperating protocols:

| Protocol                                    | Discovers                       | Fast DDS implementation |
| ------------------------------------------- | ------------------------------- | ----------------------- |
| SPDP: Simple Participant Discovery Protocol | Participants                    | `PDPSimple`             |
| SEDP: Simple Endpoint Discovery Protocol    | Application writers and readers | `EDPSimple`             |

### Built-in topics

Normal, non-secure SIMPLE discovery uses three core built-in topics. With all discovery directions enabled, each participant creates one writer and one reader per topic: six endpoints.

| Built-in topic      | Protocol | Fast DDS metadata type | Information exchanged                                                      |
| ------------------- | -------- | ---------------------- | -------------------------------------------------------------------------- |
| `DCPSParticipant`   | SPDP     | `ParticipantProxyData` | Participant identity, locators, built-in endpoint flags, and lease duration |
| `DCPSPublications`  | SEDP     | `WriterProxyData`      | Writer identity, topic, type, QoS, and receiving locators                   |
| `DCPSSubscriptions` | SEDP     | `ReaderProxyData`      | Reader identity, topic, type, QoS, and receiving locators                   |

These types name metadata records, not application-registered type-name strings.

SPDP and SEDP use built-in RTPS writers/readers and the same message and transport machinery as application traffic. Their predefined entity IDs identify discovery roles. They are not application-created DDS writers/readers.

SPDP uses best effort with repeated announcements. SEDP uses reliable, transient-local endpoints. Other built-in features, such as security, liveliness, and type lookup, can add endpoints.

### Why participant discovery comes first

SPDP supplies the remote participant's GUID prefix, available built-in endpoint flags, and metatraffic locators. Together with predefined entity IDs, these identify and locate its SEDP endpoints.

SEDP then exchanges application endpoint descriptions through those metatraffic locators. It needs no independent initial-peer list and is not restricted to unicast.

The application locators carried inside an endpoint description are distinct from the metatraffic locators used to deliver that description.

```text
SPDP participant announcement
    ↓
Learn participant identity, built-in endpoints, and metatraffic locators
    ↓
Establish built-in SEDP endpoint matches
    ↓
Exchange application writer and reader descriptions
    ↓
Check compatibility and install application endpoint matches
```

SPDP and SEDP remain active together to track changes; they are not one-time, globally separated phases.

### SPDP and application writer sending behavior

SPDP must send before remote participants are known. Its initial announcements therefore use configured destinations without requiring discovered readers.

| Writer             | How destinations are established                                                  |
| ------------------ | --------------------------------------------------------------------------------- |
| SPDP writer        | Preconfigured multicast/unicast destinations, plus discovered remote SPDP readers |
| Application writer | Compatible endpoint matches                                                       |

After discovery, SPDP also schedules announcements to discovered peers. It is not limited to multicast, and SEDP is not limited to unicast.

### Presence and removal

Repeated participant announcements refresh presence tracking. Departure announcements or lease expiration remove remote participants and their matches. Individual endpoint removal announcements remove matches without removing the participant.

## 3. From discovery to communication

Discovery provides metadata. Matching checks topic, type, keyed/unkeyed kind, partitions, and compatible QoS. Security can impose further conditions.

The writer's offered QoS must satisfy the reader's requested QoS. For example, a best-effort writer cannot satisfy a reliable reader.

Both sides need discovery:

- Writers learn compatible readers and their receiving destinations.
- Readers learn compatible writers and identify accepted sources. Reliable readers also need destinations for feedback.

Best-effort readers still require matching, despite not sending reliability feedback.

Matching installs peer state and prepares communication resources. It does not prove network reachability or create a dedicated connection for every pair. UDP needs no connection handshake, and endpoints can share resources.

Application writes send samples to matched readers. Durability may also make retained samples available to late joiners.

## 4. Transports and message delivery

### Transport types, interfaces, and ports

Fast DDS provides five main concrete transport types:

| Type          | Communication                                  |
| ------------- | ---------------------------------------------- |
| UDPv4 / UDPv6 | Connectionless UDP over IPv4 / IPv6            |
| TCPv4 / TCPv6 | Bidirectional TCP connections over IPv4 / IPv6 |
| SHM           | Shared-memory communication on the same host   |

A transport instance can use multiple local interfaces; it is not one IP address or socket. An interface whitelist restricts eligible local addresses. Without restrictions, IPv4 reception normally uses wildcard binding (`0.0.0.0`); with a whitelist, sockets can be bound to selected interface addresses.

#### UDP and TCP port roles

| Detail                        | UDP                                          | Fast DDS TCP                                                      |
| ----------------------------- | -------------------------------------------- | ----------------------------------------------------------------- |
| Locator `<port>`              | Physical receiving port and registration key | Logical receive-registration key                                  |
| Locator `<physical_port>`     | Not needed                                   | Physical connection port                                          |
| Default RTPS port calculation | Supplies the physical receiving port         | Supplies the logical port                                         |
| Physical reception            | Bound datagram sockets                       | Listeners accept connection sockets                               |
| Remove receive registration   | Close associated receiving socket channels   | Remove logical-port callback without directly closing connections |

UDP receiving ports come from locators. TCP physical listening ports come from the transport's `listening_ports` configuration; setting a locator alone does not create a listener.

For a listening TCP transport, an unspecified locator physical port is filled from the configured listening port. The physical address/port establishes connectivity; the logical port carried in each message selects a receiver registration. One connection can carry several logical ports.

TCP connections are reused by physical destination. Different selected destinations or transport instances can produce multiple connections between the same participants.

#### Overlapping transports

Transport instances can overlap in supported kinds, interfaces, and destinations. They are not automatically merged. For example, an unrestricted built-in UDP transport can overlap a custom UDP transport restricted to one interface.

- Receiving sockets may compete for the same address/port and fail to bind. Where socket sharing is permitted, delivery depends on socket options and OS behavior.
- Multiple eligible sending paths can produce duplicate arrivals. RTPS sequence tracking normally suppresses duplicate application samples.
- A custom interface restriction does not restrict other enabled transports.

User transports supplement built-in transports by default. Set `useBuiltinTransports=false` when custom transports should replace them.

### Checking locators across transports

A participant can register multiple transport instances. User transports supplement built-in transports unless built-in transports are disabled.

The network factory iterates registered transports for each locator; it does not stop at the first compatible transport.

| Locator                     | Resource preparation                                                                                               |
| --------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| Remote destination          | Each transport checks support and reuses or creates suitable sender resources.                                     |
| Local receiving destination | For each supporting transport, an existing input registration is reused; otherwise, a `ReceiverResource` is created. |

Several transport instances can support the same locator kind. Checking them does not guarantee new resources or transmission through all of them: configuration, reuse checks, and resource-creation success still apply.

### What a transport contains

A transport combines an implementation, configuration, and communication resources. It is not one socket, port, connection, or endpoint.

| Transport | Resources it manages or uses                                     |
| --------- | ---------------------------------------------------------------- |
| UDP       | Sending/receiving sockets, bound ports, and multicast memberships |
| TCP       | Listening sockets and bidirectional connection sockets           |
| SHM       | Segments, mappings, queues, and synchronization resources         |

Transports move bytes. RTPS endpoints and histories handle sequence tracking and reliable-delivery state. Discovery establishes matches.

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

#### UML relationship overview

The model is shown in one layered view. A filled diamond means exclusive structural ownership, a hollow diamond means retained shared ownership, a solid arrow means an association, a dashed arrow means a dependency or delegation, and a hollow triangle means inheritance or interface realization. Multiplicities describe one object on the source side unless the label says otherwise.

[![Fast DDS participant, transport, sender-resource, and receiver-resource ownership UML](/assets/images/fast_dds_transport_resource_ownership_uml.svg)](/assets/images/fast_dds_transport_resource_ownership_uml.svg)

The upper layers show participant ownership and the common abstractions. The class boxes name the data members that implement each mapping rather than presenting only a conceptual association.

The operational sender workflow starts when a local endpoint needs to reach a matched remote endpoint. Discovery supplies that remote reader's or writer's advertised `remote_locators`; the local endpoint filters those unicast and multicast destinations using its own attributes and passes them to `createSenderResources(RemoteLocatorList, local_endpoint_attributes)`. Those remote destination locators determine which outgoing transport paths must exist. The resulting sender resources are still retained by the participant and may later serve other endpoints or destinations.

There is also a bootstrap path during local endpoint creation. Writers call `createSendResources(Endpoint*)`; reliable readers call it because they send RTPS reliability feedback. This path uses a configured `EndpointAttributes::remoteLocatorList` or fills an empty list with default output locators, allowing initial destinations to be prepared before a particular discovery match.

The diagram separates the common participant/network-factory loop from the concrete transport operations. Both preparation paths lock the participant's `send_resource_list_`. For each selected destination locator, `NetworkFactory::build_send_resources()` iterates `mRegisteredTransports` and passes the same `send_resource_list_` by reference to each transport's `OpenOutputChannel()`. The factory does not create or retain a `SenderResource` itself. Each supporting transport examines the participant list, reuses a suitable resource when possible, or appends a newly constructed resource directly to that list. The local endpoint retains its matched-remote proxy and locator-selection state, while the participant retains the reusable sender resources.

The three purple setup rows show the transport-specific meaning of `OpenOutputChannel()`. UDP finds local interfaces that do not yet have suitable output resources, creates the required output sockets, wraps each socket in a `UDPSenderResource`, and appends it directly to `send_resource_list_`. TCP reduces the destination to a physical locator and reuses an existing `TCPSenderResource` when its stored locator equals that remote physical locator, including the supported WAN-alias comparison. The logical port is not part of this reuse key: after selecting the resource and connection, TCP adds the logical port to the channel or records it in `channel_pending_logical_ports_[physical_locator]`. When no suitable resource exists, TCP reuses an accepted physical connection, initiates a connection, or records that it is waiting for the peer, then appends a new `TCPSenderResource`; its weak connection reference may initially be empty. Shared memory reuses one `SharedMemSenderResource` per transport instance or appends one when missing. It does not open the destination shared-memory port during setup.

The outgoing-data block starts after an RTPS endpoint has formed its message buffers and selected the current remote destination locators. `RTPSParticipantImpl::sendSync()` locks `send_resource_list_` and visits every `SenderResource`, giving each resource fresh iterators over the same destination range. Each resource invokes its transport-bound `send_lambda_` and filters the locators it can serve. UDP applies its transport, multicast-purpose, allowlist, and netmask restrictions before calling `send_to()` for each accepted destination. TCP accepts only destinations whose physical locator matches the resource, obtains the corresponding bidirectional `TCPChannelResource`, negotiates the destination logical port when necessary, adds that logical port to the TCP framing header, and writes through the connection. Shared memory copies the RTPS payload into its local segment once, then finds or opens each destination port and pushes the shared-buffer descriptor. Iteration over `send_resource_list_` does not stop after the first applicable resource.

The receiver workflow starts when a local endpoint is created or enabled. A local reader needs reception for incoming writer traffic; a reliable local writer needs reception for ACKNACK, NACK_FRAG, and related feedback. Participant setup calls `createAndAssociateReceiverswithEndpoint(Endpoint* pend)` for that local endpoint. Its enclosing receiver-setup block contains two independent phases. Phase 1 calls `createReceiverResources()` for the endpoint's local unicast list and then its multicast list. For each locator, `NetworkFactory::BuildReceiverResources()` iterates every registered transport instance. An unsupported transport is skipped, and a transport with an open matching input registration creates nothing. For a missing registration, the factory constructs one `ReceiverResource`; inside that constructor, `this` is a pointer to the `ReceiverResource` being constructed. The constructor passes it to `OpenInputChannel()` as the base-class pointer `TransportReceiverInterface* receiver`.

The three transport rows inside Phase 1 expand that virtual call. UDP obtains `get_binding_interfaces_list()` and creates one socket-backed `UDPChannelResource` for each returned binding entry, then appends each resource to `mInputSockets[physical_port]`. Every created channel copies the `receiver` argument into `UDPChannelResource::message_receiver_`; that base pointer points to the same `ReceiverResource` object. With no interface whitelist, the binding list can contain one wildcard entry rather than one entry per physical interface; multicast setup may additionally enumerate interfaces to join the group. TCP extracts the locator's logical port and stores the same `receiver` pointer plus a new `ReceiverInUseCV` in `receiver_resources_[logical_port]`; this call creates neither a connection nor a `TCPChannelResource`. Shared memory opens `locator.port`, creates a listener, constructs one `SharedMemChannelResource`, copies `receiver` into its `message_receiver_`, and appends it to `input_channels_`. After the selected transport row succeeds, the participant retains the returned `ReceiverResource` in a new `ReceiverControlBlock`, creates its `MessageReceiver`, and passes that pointer to `ReceiverResource::RegisterReceiver()`.

TCP handles interfaces at a different lifecycle stage. Each `TCPv4Transport` or `TCPv6Transport` instance uses at most one physical listening port. If its descriptor contains several entries in `listening_ports`, initialization logs an error, discards every entry after the first, and uses only `listening_ports.front()`. A transport with no configured listening port acts without a server listener. For the retained physical port, `create_acceptor_socket()` creates one wildcard acceptor when there is no interface allowlist; with an allowlist it iterates `get_binding_interfaces_list()` and creates one acceptor socket per returned interface, all for the same physical listening port. Later, `TCPTransportInterface::OpenInputChannel()` does not bind another socket or repeat that interface loop: it only registers the new `ReceiverResource` callback in `receiver_resources_[logical_port]`. Physical acceptors and established `TCPChannelResource` connections are transport-wide and can carry frames for several logical ports. After the transport-specific registration succeeds, the factory returns the new resource so the participant can create its `ReceiverControlBlock` and `MessageReceiver`.

Phase 2 begins only after both lists have been prepared; the diagram does not connect the two phase rows because their loop scopes are described independently. `assignEndpoint2LocatorList()` is called for the same unicast and multicast lists, and therefore makes a second pass over their effective locators. For each locator it scans the participant-wide `m_receiverResourcelist`, calls the transport-specific `ReceiverResource::SupportsLocator()`, and associates the endpoint with every matching `MessageReceiver`. This scan is intentional: `BuildReceiverResources()` returns newly created resources but does not return an already-open resource, one locator can match resources belonging to several supporting transport instances, and the participant has no direct locator-to-control-block index. `MessageReceiver::associateEndpoint()` suppresses duplicates when several locators select the same block.

The incoming-data block shows how those associations are used at runtime, with one purple row per transport. A `UDPChannelResource` blocks in `socket_.receive_from()`, converts the sender endpoint into `remote_locator`, and invokes the `TransportReceiverInterface*` stored in `message_receiver_`; the local `input_locator` was captured when the channel was created. A `SharedMemChannelResource` follows the same callback model: its listener pops a shared buffer, and its stored `message_receiver_` invokes the associated `ReceiverResource`.

TCP performs callback selection in the transport rather than storing one callback in each connection. Every accepted or locally initiated `TCPChannelResource` runs the same listening loop. The loop reads the `TCPHeader` and body, handles logical port zero as RTCP control traffic, and uses a nonzero `TCPHeader.logical_port` to find `receiver_resources_[logical_port]`. It increments that entry's `ReceiverInUseCV::in_use`, calls the stored `TransportReceiverInterface*`, and then decrements the counter so logical-port removal can wait for active callbacks.

All three paths converge at `ReceiverResource::OnDataReceived()`. It wraps the received bytes in a non-owning `CDRMessage_t` and calls `MessageReceiver::processCDRMsg()` with the supplied remote locator as the source and local locator as the reception locator. `processCDRMsg()` validates the RTPS header, initializes the source and destination participant context, iterates the contained submessages, reads each submessage header, and selects the corresponding `proc_Submsg_*()` handler.

Reader-directed submessages and writer-directed feedback then follow different lookup paths. For DATA, DATA_FRAG, HEARTBEAT, and GAP, the handler reads the destination reader entity ID and uses `findAllReaders()`. A concrete ID uses `associated_readers_.find(readerID)` to select that map entry's reader vector; the unknown reader ID visits every vector in the map. DATA and DATA_FRAG create a transient `CacheChange_t` whose serialized-payload view points into the received message buffer, then call `BaseReader::process_data_msg()` or `BaseReader::process_data_frag_msg()` for each selected reader. HEARTBEAT and GAP call `process_heartbeat_msg()` and `process_gap_msg()` through the same reader-selection rule.

ACKNACK and NACK_FRAG contain a destination writer GUID. `MessageReceiver` does not maintain a writer-ID map: it scans `associated_writers_` in vector order and calls `BaseWriter::process_acknack()` or `BaseWriter::process_nack_frag()`. Each writer handler checks whether it owns the destination GUID. The scan stops when one handler returns true; if none does, the destination writer is treated as unknown.

#### Ownership and lifetime

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

#### What `SenderResource` does

`SenderResource` is the type-erased sending interface retained by the participant. Its public `send()` function receives already-formed message buffers, a range of destination locators, a blocking deadline, and a transport priority. A concrete sender resource installs a callback that delegates this operation to its transport.

The resource stores the transport kind so a transport can recognize and reuse its own resources. It does not keep an endpoint registry because the caller has already selected the destinations and formed the RTPS message. The participant iterates its sender-resource list; each resource consumes or skips locators according to its transport and interface restrictions.

The concrete meaning of one sender resource varies:

- `UDPSenderResource` owns one moved-in UDP socket plus interface-related flags. The same socket can send datagrams to many remote locators.
- `TCPSenderResource` stores a remote physical locator and a weak identity reference to the connection that existed when the resource was created. The TCP transport owns the actual `TCPChannelResource` and socket. A sender resource can exist while the transport is waiting for the peer to establish that connection.
- `SharedMemSenderResource` owns no port or memory segment. One such resource is reused for the transport; each send asks the transport to allocate a buffer in its local segment and push a descriptor to each selected destination port.

#### What `ReceiverResource` does

`ReceiverResource` is an internal network-layer adapter between one transport input registration and one `MessageReceiver`. Only `NetworkFactory` can invoke its private constructor. Construction calls:

```cpp
transport.OpenInputChannel(locator, this, max_message_size);
```

Here, `this` points to the `ReceiverResource` under construction. Because `ReceiverResource` implements `TransportReceiverInterface`, the call implicitly converts that pointer to `TransportReceiverInterface*`. The transport retains this non-owning base pointer in its input registration or channel resources and later calls `OnDataReceived()` on it with the bytes plus local and remote locators. Dynamic dispatch enters `ReceiverResource::OnDataReceived()`, which wraps the bytes in a `CDRMessage_t` and forwards them to its registered `MessageReceiver`. The `MessageReceiver` then parses the RTPS message and dispatches it through its associated-reader and associated-writer indexes.

`ReceiverResource` does not own a socket, TCP connection, SHM port, or receive thread. It stores callbacks that capture the transport and the locator used at construction:

- `Cleanup` calls `CloseInputChannel(locator)`.
- `LocatorMapsToManagedChannel` calls `DoInputLocatorsMatch()` so the participant can reuse the registration for an equivalent local locator.

Its mutex, callback counter, and condition variable prevent shutdown from completing while `OnDataReceived()` is active. The enclosing `ReceiverControlBlock` keeps the `ReceiverResource` and its `MessageReceiver` together.

#### How many I/O objects are in one channel?

There is no transport-independent cardinality. The mappings in the current implementation are:

| Transport | Input-channel identity and backing | Output-channel identity and backing |
| --------- | ---------------------------------- | ----------------------------------- |
| **UDP** | Input-channel matching uses the physical UDP port. `mInputSockets[port]` is a vector, so one logical input channel can contain several `UDPChannelResource` objects, typically for different local interfaces. Each `UDPChannelResource` owns one socket and runs its receive loop. | Output preparation can add several `UDPSenderResource` objects for local interfaces. Each resource owns exactly one socket, and each socket can send to many destination addresses and ports. |
| **TCP** | An input channel is a `receiver_resources_[logical_port]` callback registration. It owns no socket. Any established `TCPChannelResource` can parse that logical port and invoke the registration, so one input channel can receive through many TCP connections. | A sender resource is keyed by a remote physical locator. The transport's `TCPChannelResource` represents one TCP connection and owns one connection socket; several logical ports share it. The sender resource observes rather than owns that connection and may temporarily have no connection. |
| **SHM** | An input channel is a `SharedMemChannelResource` for a locator. It owns one listener attached to a shared-memory port queue, not a memory region. Descriptors received on that port can refer to buffers allocated in different sending processes' segments. | The transport normally reuses one `SharedMemSenderResource` for all destinations. It owns one local allocation segment and caches multiple writable destination ports. There is no separate region per output channel or locator. |

At the lowest concrete layer, a UDP or TCP `ChannelResource` normally wraps one socket, and an SHM `SharedMemChannelResource` wraps one listener. At the participant-facing layer, however, one “input channel” can fan out over several UDP sockets or several TCP connections, while an SHM sender resource can fan out over several ports. The word *channel* names the communication relationship recognized by that transport, not a universal container with one fixed operating-system handle.

Channel-existence checks and endpoint-to-resource matching are also separate operations. UDP uses the physical port for both. SHM compares the locator kind and port. TCP's `IsInputChannelOpen()` checks the logical-port registry, whereas `ReceiverResource::SupportsLocator()` delegates to `DoInputLocatorsMatch()`, which currently compares physical ports. The first test prevents duplicate callback registrations; the second decides which `MessageReceiver` objects should index an endpoint. Treating all of these checks as one generic “locator equality” would hide an important layer boundary.

#### Locator-to-resource workflows

A sending locator names a selected remote receive destination. A receiving locator describes a local receive registration. The network factory asks every registered transport that supports the locator kind; support by one transport does not stop the search.

```text
Sending
remote locator
    -> NetworkFactory::build_send_resources()
    -> each supporting transport reuses or creates SenderResource objects
    -> SenderResource::send(message, selected remote locators)
    -> transport-specific sockets, connections, or SHM ports

Receiving setup
local locator
    -> NetworkFactory::BuildReceiverResources()
    -> if the supporting transport has no matching input registration:
         construct ReceiverResource
         -> TransportInterface::OpenInputChannel(locator, callback)
    -> participant creates and registers MessageReceiver

Incoming data
transport-owned receive object
    -> ReceiverResource::OnDataReceived()
    -> MessageReceiver::processCDRMsg()
    -> associated local reader or writer
```

One locator may be handled by resources from several transport instances of the same kind. A single resource never combines state from several transport instances.

For UDP reception, locators with the same physical port match the same input registration. Opening that port may create one socket channel per applicable local interface and register the same `ReceiverResource` callback with each. Disabling the receiver closes all socket channels stored under that port.

For TCP reception, the locator's physical address and port concern connectivity, while its logical port selects the callback registration. Opening or closing a `ReceiverResource` adds or removes that logical-port entry; it does not create or close a connection socket. A connection can carry several logical ports, and one logical-port registration can receive over several connections.

For TCP sending, locators with the same physical destination can reuse a sender resource and connection even when their logical ports differ. In normal output setup, the transport either initiates the connection or waits for the peer according to the listening-port ordering and equal-port locator tie-break. Initial-peer setup can explicitly initiate a connection through a separate path.

### Transport and resource creation

Transport descriptors supply configuration. Each participant creates its own transport instances from its selected descriptors, including enabled built-in defaults. Locators subsequently cause resource and channel registrations to be created or reused; configuring a locator does not itself instantiate a transport.

```text
XML profile or C++ participant QoS
    -> selected transport descriptors
    -> participant's NetworkFactory
    -> initialized transport instances
    -> locator-driven sender resources and receiver registrations
    -> transport-owned concrete I/O objects
```

### Locators and transport selection

A locator describes where to communicate; a transport implements how.

Its kind identifies a transport category, not one runtime instance. Several instances may support the same kind. A UDP transport cannot send to a TCP locator.

Configuring a locator does not create its transport. The participant must have a compatible transport and usable communication resources.

### Selecting destinations

A writer selects one or more locators for matched readers, not necessarily every advertised locator or exactly one.

Selection filters destinations using transport support, local reachability rules, and configured preferences. It is not an end-to-end connectivity test.

With normal same-host UDP + SHM configuration, usable SHM locators are preferred for application data. This is a locator-filtering preference, not simply transport registration order.

UDP selection prefers multicast shared by several targeted readers. It also permits multicast when a reader has no unicast locators. Otherwise, multiple supported unicast destinations can remain. TCP can also retain several unicast destinations; SHM selection uses unicast.

Selecting SHM does not guarantee automatic fallback to UDP after a failure.

### Sending and reception

The normal transport-based sending path is:

```text
Serialized sample in writer history
    ↓
Writer scheduling and matched-reader state
    ↓
Select destination locators and form RTPS messages
    ↓
Participant's sender-resource list
    ↓
Each resource's associated transport
    ↓
Socket or shared-memory channel
```

The participant iterates prepared sender resources. Each checks the selected destinations against its transport and resource restrictions; dispatch does not stop at the first successful send.

A sample can span several fragments, and one RTPS message can contain several submessages. One sample therefore does not imply one socket operation.

Reception follows the reverse direction:

```text
Transport input channel
    ↓
Receiver resource
    ↓
RTPS message parsing and destination identification
    ↓
Associated reader, or writer receiving feedback
```

Successful socket submission does not prove reader receipt. Reliable acknowledgment and retransmission remain RTPS responsibilities.

Intra-process and data-sharing delivery can bypass this transport path.

### Why duplicate copies can arrive

| Cause                              | Condition                                                    |
| ---------------------------------- | ------------------------------------------------------------ |
| Multiple selected locators         | Several destinations reach the same reader                   |
| Multiple suitable sender resources | Several resources send the message to a selected destination |
| Reliable retransmission            | A previously received sample is sent again                   |

Several configured transports do not necessarily cause duplicates. Locator filtering, resource reuse, and interface restrictions can prevent redundant sends.

Copies retain the same writer GUID and sequence number. Reader sequence tracking normally prevents repeated arrivals from becoming repeated application samples.

### Default transports and receiving locators

Normal built-in defaults enable UDPv4 and add SHM when built-in SHM is enabled. They do not enable TCP or UDPv6. XML, participant QoS, or environment configuration can select other transports.

The following defaults assume SIMPLE discovery, UDPv4 + SHM, and no explicit locator lists. Let `D` be the domain ID and `P` the participant ID.

| Traffic               | Default destination/resource                               | Initial port                                   |
| --------------------- | ---------------------------------------------------------- | ---------------------------------------------- |
| Metatraffic multicast | UDPv4 group `239.255.0.1`                                  | `7400 + 250 × D`                               |
| Metatraffic unicast   | Eligible local IPv4 addresses                              | `7410 + 250 × D + 2 × P`                       |
| Application unicast   | Eligible local IPv4 addresses and a host-local SHM locator | `7411 + 250 × D + 2 × P`                       |
| Application multicast | Not generated automatically                                | If configured with port zero: `7401 + 250 × D` |

For domain `0`, participant `0`, the initial UDP ports are `7400`, `7410`, and `7411`. SHM uses the unicast number as a queue-port identifier, not a UDP port.

Unspecified UDP unicast addresses expand into eligible local interface addresses. Multicast reception joins the group on eligible interfaces.
