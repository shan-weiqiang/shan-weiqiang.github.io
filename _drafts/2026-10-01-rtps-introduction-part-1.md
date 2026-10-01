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

### Ownership and resource relationships

Each RTPS participant owns a network factory, which owns its transport instances. Built-in and application endpoints share this infrastructure.

Sender resources provide sending access; receiver resources register incoming-data delivery. Neither abstraction universally corresponds to one socket.

The participant retains resource objects. Resources and transports cooperate to manage the underlying channels.

```text
RTPSParticipantImpl
|
+-- m_network_Factory : NetworkFactory                                            // Owns transports; coordinates locator and resource operations.
|   +-- mRegisteredTransports
|       : vector<unique_ptr<TransportInterface>>                                  // Retains successfully initialized transport instances.
|           --> UDPv4Transport / TCPv4Transport / SharedMemTransport
|                                                                                 // UDP-specific members below; TCP and SHM have different resources.
|               +-- mInputSockets : map<uint16_t, vector<UDPChannelResource*>>
|                                                                                 // UDP transport owns these input channels, grouped by physical port.
|                   +-- UDPChannelResource                                        // Transport deletes it when closing the input channel.
|                       +-- socket_ : eProsimaUDPSocket                           // Owned by this input channel; closed when the channel is destroyed.
|
+-- send_resource_list_ : SendResourceList                                        // Owns reusable sender resources used by participant dispatch.
|                                                                                 // SendResourceList = vector<unique_ptr<SenderResource>>
|   +-- SenderResource                                                            // Accepts message buffers and destination locators.
|                                                                                 // No endpoint registry: the calling endpoint has already formed the RTPS message.
|       --> UDPSenderResource                                                     // Owns its sending socket; delegates sending and cleanup to the transport.
|           +-- socket_ : eProsimaUDPSocket                                       // Socket moved into this resource; destructor requests cancel/close.
|           +-- transport_ : UDPTransportInterface&                               // Non-owning reference; implements socket operations.
|
+-- m_receiverResourcelist
|   : list<ReceiverControlBlock>                                                  // Retains input resources and their RTPS message receivers.
|   +-- ReceiverControlBlock
|       +-- Receiver : shared_ptr<ReceiverResource>                               // Registers reception with one transport instance.
|       |   --> TransportInterface instance                                       // Non-owning association through callback captures; no transport_ member.
|       |   +-- Cleanup : function<void()>                                        // Captures that transport and locator; closes UDP channels or unregisters a TCP logical port.
|       |   +-- LocatorMapsToManagedChannel
|       |   |   : function<bool(const Locator_t&)>                                // Captures the same transport and locator; delegates channel matching.
|       |   +-- receiver : MessageReceiver*                                       // Forwards incoming bytes to the registered parser.
|       |                                                                         // Receives from this transport's associated channels only; does not own their sockets.
|       +-- mp_receiver : MessageReceiver*                                        // Parses RTPS identifiers to choose local destinations.
|                                                                                 // One input channel can carry traffic for several endpoints; reception needs this index.
|           +-- associated_writers_
|           |   : vector<BaseWriter*>                                             // References writers receiving reader feedback here.
|           +-- associated_readers_
|               : unordered_map<EntityId_t,
|                               vector<BaseReader*>>                              // Indexes local readers for incoming writer traffic.
|
+-- m_allWriterList : vector<BaseWriter*>                                         // Registers all local writers, including built-in writers.
+-- m_allReaderList : vector<BaseReader*>                                         // Registers all local readers, including built-in readers.
+-- m_userWriterList : vector<BaseWriter*>                                        // References the non-built-in subset of local writers.
+-- m_userReaderList : vector<BaseReader*>                                        // References the non-built-in subset of local readers.
|
+-- mp_builtinProtocols : BuiltinProtocols*                                       // Manages built-in protocol components.
    +-- mp_PDP : PDP*                                                             // Participant discovery; PDPSimple in SIMPLE mode.
        +-- mp_EDP : EDP*                                                         // Endpoint discovery/pairing; EDPSimple for SIMPLE EDP.
```

Resources are not paired one-to-one with endpoints. Several endpoints can share a receiver resource, and one endpoint can use several resources.

`MessageReceiver` holds endpoint associations for incoming dispatch. Sender resources need no endpoint registry: the caller supplies the message and destinations.

#### Locator-to-resource workflows

A sending locator is a selected remote receiving destination. A receiving locator describes local reception.

The following resource lifecycle applies to both UDP and TCP:

- **Sending:** Discovery setup, endpoint matching, and locator updates prepare sender resources. Transports reuse existing resources or create missing ones; the participant retains them. Each transport-path send iterates the sender-resource list with the selected destination locators. Each resource applies its transport's destination restrictions; iteration does not stop at the first successful send.
- **Receiving:** Participant and endpoint setup prepare reception from local locators. For each supporting transport, the network factory creates a `ReceiverResource` only when the corresponding input registration is absent. The resource registers its callback with the transport, and the participant attaches a `MessageReceiver` for endpoint dispatch. Existing registrations are reused.

Resource checks start from destination locators for sending and local locators for receiving. Resources can serve multiple locators.

Both transports follow this abstraction:

```text
Sending:
Destination locator → check registered transports → reuse/create suitable sender resources
    Each sender resource → one associated transport instance
                         → one UDP sending socket or resolved TCP connection

Receiving setup:
Local locator → check registered transports → reuse/create a registration per supporting transport
    Each ReceiverResource → one associated transport instance
                          ← that transport's associated receiving socket channels

Incoming data:
Socket channel → its transport's ReceiverResource → MessageReceiver → RTPS endpoint
```

One locator can use resources associated with different transport instances. Each resource is bound to one transport; it does not combine channels from several transports. A transport can provide multiple sender resources. One receiver resource can receive through multiple UDP socket channels or TCP connections belonging to the same transport instance.

Resource cleanup differs by transport:

- **UDP:** Sender-resource destruction closes its sending socket through transport code. Disabling a receiver resource closes its associated transport-owned receiving socket channels.
- **TCP:** Sender-resource destruction invalidates its destination locator; disabling a receiver resource unregisters its logical port. Neither directly closes the connection socket; the transport manages connection lifetime separately.

#### UDP sending

```text
Destination locator (IP + UDP port)
    → Network factory asks the UDP transport to prepare sending resources
    → Reuse suitable resources; create sockets only as required by interface setup
    → UDPSenderResource holds a sending socket
    → Transport sends through that socket to the destination
```

Multiple destination locators reuse sender resources. Each UDP sender resource holds one socket in the move-enabled implementation; interface-specific sockets use separate resources.

#### TCP sending

```text
Destination locator (IP + physical port + logical port)
    → Transport reuses or creates a sender resource for the physical destination
    → Reuse a connection, initiate one, or wait for an incoming connection
    → Sender resource delegates transmission to the transport
    → Transport adds the destination logical port to its framing header
    → Connection socket sends the message
```

Locators sharing a physical destination can reuse one sender resource and connection, even with different logical ports. The transport retains the connection; the sender resource does not own its socket. A sender resource can exist before connection establishment.

Both readers and writers prepare sender resources; their application roles do not determine who initiates TCP. In normal output setup, when no connection exists, the transport initiates if the remote physical port exceeds its first configured listening port (or zero for a non-listening client). Otherwise, it awaits the peer, except for the equal-port tie-break.

For equal ports, the transport compares its first eligible local-interface locator, with the port set to the remote physical port, against the remote physical locator. A smaller local locator triggers connection initiation. This is a bytewise comparison of locator representations, not simply IP strings. Initial-peer setup can explicitly initiate connections through a separate path.

#### UDP receiving

```text
Local receiving locator (IP + UDP port)
    → Network factory checks the transport's receiving-port registry
    → Existing port: reuse its receiver registration
    → New port: create ReceiverResource
        → Transport creates applicable interface/multicast socket channels
        → Register the same receiver callback with each UDPChannelResource
```

Within one UDP transport instance, locators sharing a receiving port reuse one receiver registration. That registration can serve several transport-owned `UDPChannelResource` objects, each holding one socket.

Received bytes flow from a socket channel to `ReceiverResource`, then `MessageReceiver`, then the associated RTPS endpoint. Disabling the registration closes its UDP socket channels.

For UDP, the receiver resource controls the associated input channels through the transport; the transport owns their socket-holding objects.

#### TCP receiving

A physical port establishes TCP connectivity. A logical port selects a receive registration inside the transport. The logical port comes from configuration or default locator generation; it does not identify an endpoint or bind another socket.

```text
Local receiving locator (IP + physical port + logical port)
    → Network factory checks the transport's logical-port registry
    → Existing logical port: reuse its receiver registration
    → New logical port: create ReceiverResource and register its callback
    → Transport dispatches arriving connection data by the message's logical port
    → ReceiverResource → MessageReceiver → associated RTPS endpoint
```

Within one TCP transport instance, locators sharing a logical port reuse one receiver registration. TCP connections are managed separately: one connection can carry several logical ports, and one registration can receive through several connections.

Creating or removing a registration does not create or close a connection socket. Removing it unregisters the logical port; connection shutdown is separate.

### Transport and resource creation

Transport descriptors supply configuration. Each participant creates its own transport instances from its selected descriptors, including enabled built-in defaults.

```text
XML profile or C++ participant QoS
    ↓
Selected transport descriptors
    ↓
Participant's network factory
    ↓
Create and initialize transport instances
    ↓
Create or reuse sending/receiving resources as needed
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
