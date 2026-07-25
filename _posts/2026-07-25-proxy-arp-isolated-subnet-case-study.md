---
layout: post
title:  "Proxy ARP, Routing, and NAT: A Network Case Study"
date:   2026-07-25 16:00:00 +0800
tags: [networking, linux]
---

* toc
{:toc}

A Linux client produced a surprising set of network observations:

- two destination addresses were covered by the client's directly connected route;
- all observed IPv4 neighbors resolved to one MAC address;
- `traceroute` nevertheless reported the default gateway before a destination in the same configured subnet.

On a conventional Ethernet LAN, an on-link destination answers ARP with its own MAC and is reached without an IP router. Why does this network behave differently?

This case study works from the evidence outward. It uses the observations to connect **subnet masks**, **Layer 2**, **Layer 3**, **ARP**, **Proxy ARP**, **routing**, and **traceroute**, then extends the same principles to Internet communication through a NAT gateway. The addresses and interface names below are fictional, but their network relationships match the original observation.

The discussion has three parts:

1. diagnose the surprising local Proxy ARP and traceroute results;
2. follow a packet from a private host through Layer 2, routers, NAT, and back;
3. separate symmetric IP/transport behavior from the practical asymmetry between an initiator and a responder.

## Part I — Diagnosing the local Proxy ARP case

We begin with the commands exactly as the client sees them, then explain the apparent contradiction one layer at a time.

### The observations

The client first sent ARP probes to `192.168.24.65`:

```console
user@client-host:~$ sudo arping -c 3 -I wlan0 192.168.24.65
ARPING 192.168.24.65
58 bytes from 02:00:00:00:00:01 (192.168.24.65): index=0 time=34.995 msec
58 bytes from 02:00:00:00:00:01 (192.168.24.65): index=1 time=38.442 msec
58 bytes from 02:00:00:00:00:01 (192.168.24.65): index=2 time=37.416 msec

--- 192.168.24.65 statistics ---
3 packets transmitted, 3 packets received, 0% unanswered (0 extra)
rtt min/avg/max/std-dev = 34.995/36.951/38.442/1.445 ms
```

A trace to another address showed two IP hops:

```console
user@client-host:~$ traceroute -n 192.168.16.75
traceroute to 192.168.16.75 (192.168.16.75), 30 hops max, 60 byte packets
 1  192.168.16.1   12.602 ms  12.495 ms  12.452 ms
 2  192.168.16.75   6.491 ms   8.998 ms   8.962 ms
```

The ARP cache contained the same MAC for the gateway and both peers:

```console
user@client-host:~$ arp -a
? (192.168.24.65) at 02:00:00:00:00:01 [ether] on wlan0
_gateway (192.168.16.1) at 02:00:00:00:00:01 [ether] on wlan0
? (192.168.16.75) at 02:00:00:00:00:01 [ether] on wlan0
```

Finally, the routing table said that the entire `/20` was directly connected:

```console
user@client-host:~$ route -n
Kernel IP routing table
Destination      Gateway          Genmask          Flags Metric Ref Use Iface
0.0.0.0          192.168.16.1     0.0.0.0          UG    600    0   0   wlan0
192.168.16.0     0.0.0.0          255.255.240.0    U     600    0   0   wlan0
192.168.50.0     0.0.0.0          255.255.255.0    U     100    0   0   eth0
```

The `eth0` network is unrelated to this investigation. The important entries are the directly connected `/20` on `wlan0` and the default route through `192.168.16.1`.

### First principle: a subnet is a Layer 3 decision

An IPv4 subnet mask divides an address into:

- a **network prefix**, used to identify the subnet;
- a **host part**, used to identify an interface within that subnet.

The route uses mask `255.255.240.0`, which is `/20` because its binary representation contains twenty leading `1` bits:

```text
255       .255       .240      .0
11111111  .11111111  .11110000 .00000000
```

The third octet has four network bits and four host bits. Its subnet block size is:

```text
256 - 240 = 16
```

The block containing third-octet value `16` therefore runs from `16` through `31`:

| Property | Value |
| --- | --- |
| Network | `192.168.16.0/20` |
| Mask | `255.255.240.0` |
| Address range | `192.168.16.0`–`192.168.31.255` |
| Directed broadcast | `192.168.31.255` |
| Typical usable host range | `192.168.16.1`–`192.168.31.254` |

Both test destinations are inside that range:

```text
192.168.16.75  AND 255.255.240.0 = 192.168.16.0
192.168.24.65  AND 255.255.240.0 = 192.168.16.0
```

The local kernel therefore classifies both as **on-link**. It does not select the default route for either one. Instead, it tries to resolve the destination IP address itself into a link-layer address.

This is an important distinction:

> The subnet mask controls the host's Layer 3 route selection. It does not guarantee that every address in the prefix is directly reachable through a normal shared Layer 2 LAN.

### Layer 2 and Layer 3 answer different questions

In this case, the two most important layers are:

| Layer | Unit and address | Main question |
| --- | --- | --- |
| Layer 2, data link | Ethernet/Wi-Fi frame and MAC address | Which neighbor receives this frame on the current link? |
| Layer 3, network | IP packet and IP address | Which interface or router moves this packet toward its destination? |

A switch or bridge normally forwards Layer 2 frames by destination MAC. A router accepts an IP packet on one interface, consults a Layer 3 routing table, decrements the packet's TTL, and sends it onward in a new link-layer frame.

The IP source and destination generally remain end-to-end. The MAC addresses are only for the current link and can change at every routed hop.

### What a conventional same-subnet LAN would do

Assume client A wants to reach `192.168.16.75`. On a normal shared Layer 2 LAN:

1. A's `/20` route says the destination is on-link.
2. A broadcasts: “Who has `192.168.16.75`?”
3. The destination itself replies with its own MAC.
4. A sends an Ethernet frame directly to that MAC.
5. A switch may relay the frame, but no router processes the IP packet.
6. Because no router forwards it, the packet's TTL is not decremented.

The destination would normally be the first and only result in `traceroute`.

The observed network differs in two ways: the supposed peers resolve to the gateway's apparent MAC, and the gateway appears as an IP hop.

![The client's on-link view compared with the actual gateway-mediated forwarding path](/assets/images/proxy_arp_shared_vs_isolated.png)

The important distinction is between the **client's logical view** and the **actual forwarding path**.

From the client's Layer 3 configuration, every address in `192.168.16.0/20` is on-link. The client therefore treats `192.168.16.75` and `192.168.24.65` as directly reachable IP neighbors: it issues ARP for each destination itself instead of sending the packet to the configured default gateway.

But ARP does not return each peer's own MAC. It returns the proxy's MAC. The client consequently sends a Layer 2 frame to the proxy, even though the IP packet inside that frame is addressed to the peer. The proxy then performs a Layer 3 forwarding operation, which is why TTL decreases and the gateway appears in `traceroute`.

It would be imprecise to say that the peers are “in the same subnet at Layer 2,” because a subnet and subnet mask are Layer 3 concepts. It is also not proven that every client occupies a physically separate network. A precise statement supported by the captures is:

> The client considers the peers on-link because they share its configured Layer 3 prefix, but their frames are delivered to a proxy MAC and the enclosed IP packets are forwarded through a Layer 3 gateway.

### ARP: turning the selected next hop into a MAC address

ARP, the Address Resolution Protocol, connects the Layer 3 routing decision to Layer 2 delivery.

For each IPv4 packet, the host first decides the **next-hop IP**:

- on-link destination: next hop is the destination IP;
- off-link destination: next hop is a router, usually the default gateway.

It then uses ARP to obtain a MAC address for that next hop.

An ARP request is carried in a Layer 2 broadcast frame. It asks which interface owns a particular IPv4 address. The reply normally comes from the owner and is usually unicast back to the requester. The resulting IP-to-MAC mapping is cached in the neighbor table.

ARP is often described as operating “between Layer 2 and Layer 3” because it carries an IP address question but exists to produce a link-layer address. It does not route application traffic and it does not decrement IP TTL.

### Proxy ARP: answering on behalf of another address

With **Proxy ARP**, a router or other network element answers an ARP request for an address that is not assigned to the requesting-side interface. It effectively says:

> “To reach that IP address, send the Ethernet frame to my MAC address.”

The sender still believes the IP destination is on-link. It builds a frame like this:

```text
Ethernet source:      client's MAC
Ethernet destination: 02:00:00:00:00:01
IP source:            client's IP
IP destination:       192.168.24.65
```

Notice that the Ethernet destination identifies the immediate receiver, while the IP destination remains the final peer.

![ARP resolution followed by gateway routing](/assets/images/proxy_arp_packet_flow.png)

Proxy ARP only supplies the MAC mapping. After receiving the frame, the gateway must separately perform **IP forwarding**:

1. remove the incoming link-layer framing;
2. inspect the IP destination;
3. consult its routing or forwarding state;
4. decrement TTL;
5. create the appropriate outgoing link-layer frame;
6. transmit toward the real destination.

Proxy ARP and routing are therefore complementary but distinct mechanisms:

| Mechanism | Role |
| --- | --- |
| Proxy ARP | Makes a remote or isolated IP appear reachable through the proxy's MAC |
| IP forwarding | Moves the contained IP packet toward the real destination |
| Traceroute | Reveals routers that decrement TTL while forwarding |

### Why traceroute shows two hops

Traceroute discovers routers by sending probes with increasing IP TTL values.

For the first probe:

1. the client sets `TTL = 1`;
2. the gateway receives the frame and tries to route the IP packet;
3. routing decrements TTL from `1` to `0`;
4. the gateway discards the packet and returns ICMP Time Exceeded;
5. traceroute records `192.168.16.1` as hop 1.

For the next probe:

1. the client sets `TTL = 2`;
2. the gateway decrements it to `1` and forwards it;
3. the probe reaches `192.168.16.75`;
4. the destination response identifies hop 2.

![TTL behavior that creates two traceroute hops](/assets/images/proxy_arp_traceroute_ttl.png)

If the destination were reached directly at Layer 2, a switch could forward its Ethernet frame without touching the IP TTL. Traceroute would normally show the destination as hop 1.

The additional hop is thus not produced by the ARP reply itself. It appears because the device that supplied the MAC also performs Layer 3 forwarding:

```text
Proxy ARP selects the gateway MAC
              +
Gateway routes and decrements TTL
              =
Gateway appears in traceroute
```

## Part II — From one local hop to the whole Internet

The same division of responsibility explains how two hosts communicate across the Internet. A client normally does **not** know the remote server's MAC address. It does not need to.

A MAC address has meaning only on the current Layer 2 link. Ethernet and Wi-Fi do not carry one frame unchanged across the Internet. Every router removes the incoming link-layer header, processes the enclosed IP packet, and creates new link-layer framing for the next link.

The following fictional example uses IPv4 ranges reserved for documentation:

| Role | Address |
| --- | --- |
| Private client | `192.168.1.10:51514` |
| Client's default gateway | `192.168.1.1` |
| Gateway's public NAT mapping | `198.51.100.10:62000` |
| Public HTTPS server | `203.0.113.20:443` |

The values after `:` are TCP ports. A destination IP identifies a Layer 3 routing endpoint, while the destination port selects a transport endpoint and ultimately an application socket.

### What identifies the final target?

There is no single universal identifier at every layer. Communication succeeds because each mechanism answers a smaller question:

| Mechanism | Question it answers |
| --- | --- |
| DNS | Which public IP address currently represents this service name? |
| Destination IP | Which host or network interface should receive the packet? |
| TCP/UDP destination port | Which service on that host should receive the data? |
| Subnet mask and local routes | Is the destination on-link, or must a gateway be used? |
| Router forwarding table | Which next hop moves this destination prefix closer to its network? |
| ARP | What MAC address can receive the packet on this local IPv4 link? |
| Switch MAC table | Through which Layer 2 port should this frame leave? |
| NAT state | Which private connection corresponds to this public IP and port? |
| TTL | How many more Layer 3 forwarding hops may the packet cross? |

An application may begin with a name such as `www.example.test`. DNS resolves that name to an IP such as `203.0.113.20`. The application selects port `443` for HTTPS. Together, the destination IP and destination port identify the remote network endpoint for this connection.

The remote MAC is not part of that identity. It may be thousands of kilometers away and separated from the client by many different Layer 2 technologies. The client only needs the MAC of the **next hop on its own link**.

### Outbound: private client to public server

#### 1. The client creates the transport and IP headers

The operating system chooses an ephemeral source port, here `51514`, and creates a TCP segment:

```text
TCP source port:      51514
TCP destination port: 443
```

It then places that segment in an IP packet:

```text
IP source:      192.168.1.10
IP destination: 203.0.113.20
```

#### 2. The subnet mask selects direct delivery or a gateway

The client compares `203.0.113.20` against its connected subnet. The public address is not inside the client's private network, so the routing table selects the default route:

```text
default via 192.168.1.1
```

This decision is different from the Proxy ARP case:

- in the case study, the `/20` route classified the peer as on-link, so the client issued ARP for the **peer IP**;
- for an Internet destination, the route classifies it as off-link, so the client issues ARP for the **gateway IP**.

#### 3. ARP finds only the first-hop MAC

The client asks:

```text
Who has 192.168.1.1?
```

Suppose the gateway replies with fictional MAC `02:00:00:00:01:01`. The first frame is then:

```text
Ethernet source:      client's MAC
Ethernet destination: gateway's LAN MAC
IP source:            192.168.1.10
IP destination:       203.0.113.20
```

The Layer 2 destination and Layer 3 destination intentionally name different devices. The frame is for the next hop; the enclosed packet is for the final server.

#### 4. A switch delivers the local frame

A Layer 2 switch learns source MAC addresses and associates them with switch ports. It forwards the frame toward the port where it learned the gateway's MAC.

This is the scope of Layer 2 forwarding: it delivers frames inside the current Layer 2 network. It does not choose an Internet route and it does not inspect or decrement IP TTL.

#### 5. The home gateway applies NAT

Private address `192.168.1.10` is not globally routed on the public Internet. The home gateway therefore creates a NAT/PAT mapping:

```text
inside:  192.168.1.10:51514
outside: 198.51.100.10:62000
remote:  203.0.113.20:443
```

The outbound packet becomes:

```text
IP source:            198.51.100.10
TCP source port:      62000
IP destination:       203.0.113.20
TCP destination port: 443
```

NAT changes the source IP and often the source port at this one boundary. Ordinary routers after it do **not** keep changing those values. They normally preserve both endpoint IP addresses and transport ports while decrementing TTL.

#### 6. Every router makes one next-hop decision

An Internet router does not need the sender's complete path to the server. It reads the destination IP, performs a **longest-prefix match** in its forwarding information base, and obtains:

- an outgoing interface;
- a directly reachable next hop, or a directly connected destination.

The router then resolves or retrieves the next hop's link-layer address, creates new link-layer framing, and transmits the packet.

This repeats independently at every router:

```text
destination IP → longest matching route → next hop → local link delivery
```

Routing protocols such as BGP and internal gateway protocols distribute reachability information from which routers build their tables. The data packet does not carry a list of all routers it must visit.

#### 7. The final link reaches the server

Eventually a router has a connected route for the server-side network. On an Ethernet-like IPv4 link, it uses ARP to learn the server's MAC and creates the final frame:

```text
Ethernet source:      final router's MAC
Ethernet destination: server's MAC
IP source:            198.51.100.10
IP destination:       203.0.113.20
```

Only this final router needs the server's MAC. The original client never learns it.

### Complete outbound and return flow

![Private client communicating with a public server through Layer 2, routing, and NAT](/assets/images/internet_l2_l3_nat_flow.png)

The diagram separates three different kinds of state:

- **Layer 2 state** is local to each link and changes at every routed hop.
- **Layer 3 destination state** guides the packet across routers toward the public server.
- **NAT connection state** associates the public translated flow with the private client flow.

### Return: public server to private client

The server receives a connection from:

```text
198.51.100.10:62000
```

It does not see the client's private `192.168.1.10` address. To reply, the server creates:

```text
IP source:            203.0.113.20
TCP source port:      443
IP destination:       198.51.100.10
TCP destination port: 62000
```

Because `198.51.100.10` is outside the server's local subnet, the server sends the frame to its own default gateway's MAC—not to the client's MAC and not necessarily to the MAC of the router that delivered the request.

Routers forward the reply toward `198.51.100.10`. The return path can differ from the outbound path; IP routing does not require symmetry.

When the reply reaches the NAT gateway, the gateway looks up its state:

```text
198.51.100.10:62000 → 192.168.1.10:51514
```

It rewrites the destination IP and port, consults its route for `192.168.1.10`, obtains the client's local MAC through ARP or its neighbor cache, and transmits the final local frame.

This NAT state is why a reply can reach a client whose private address is not routed on the Internet. Without an existing mapping, port-forwarding rule, or similar policy, an unsolicited inbound packet generally cannot identify which private host should receive it.

### What changes at each stage?

For the outbound direction:

| Field | Client LAN | Public Internet after NAT | Final server link |
| --- | --- | --- | --- |
| Source IP and port | `192.168.1.10:51514` | `198.51.100.10:62000` | `198.51.100.10:62000` |
| Destination IP and port | `203.0.113.20:443` | `203.0.113.20:443` | `203.0.113.20:443` |
| Source MAC | client | current router/interface | final router |
| Destination MAC | home gateway | next router on that link | server |
| TTL | initial value | decreases once per router | lower than initial value |

The key correction is:

> MAC addresses change at routed link boundaries. In ordinary outbound communication through source NAT, only the initiator's private source IP and possibly its source port are translated; the responder IP and port selected by the initiator remain unchanged. Return traffic receives the inverse translation so it reaches the private initiator.

From the initiator's perspective, it communicates directly with the destination IP and port it selected. A gateway may later apply destination NAT, load balancing, or proxying to reach a different backend, but reverse translation preserves the original endpoint as the initiator's logical peer. Ordinary routers perform neither translation: they preserve the IP endpoints while replacing the Layer 2 framing and decrementing TTL.

IPv6 uses the same next-hop principle, although Neighbor Discovery replaces ARP and ordinary IPv6 Internet access generally does not require address translation.

## Part III — Symmetric protocols, asymmetric initiation

IP does not define client and server roles. Its packet format is symmetric: every packet has a source and a destination, and either reachable host can theoretically send to the other.

UDP is similarly peer-neutral. It carries independent datagrams in either direction. TCP does distinguish an **active opener**, which sends the first `SYN`, from a **passive opener**, which listens for it, but the established TCP connection is full-duplex: either side can send application data.

The practical asymmetry begins with the application:

> The initiator must first obtain a reachable address for the responder.

It might obtain that address from DNS, configuration, service discovery, or a rendezvous service. The responder does not need to know the initiator in advance; it listens on a known address and port and learns the initiator's observed source endpoint from the first packet.

The destination must be unambiguous and reachable in the initiator's routing context. For ordinary Internet communication, this normally means a globally routable public service IP. From the initiator's perspective, that IP and port are the final logical responder:

```text
initiator ↔ selected destination IP:port
```

The selected address does not have to identify one physical server. It may represent an anycast service, CDN edge, load balancer, reverse proxy, or public address translated to a private backend. Those systems preserve the selected endpoint as the initiator's logical peer, so their internal backend selection is normally invisible to it.

### Initiator and responder are roles, not IP properties

“Client” and “server” often align with initiation, but they are application roles rather than properties imposed by IP:

| Network behavior | Precise term |
| --- | --- |
| Sends the first packet | Initiator |
| Waits for the first packet | Responder |
| Sends the first TCP `SYN` | Active opener |
| Listens for a TCP `SYN` | Passive opener |
| Requests an application service | Client |
| Provides an application service | Server |

The key question under NAT and stateful firewalls is:

> Which side sends first and creates the translation and filtering state required for the reverse traffic?

That first packet creates the practical asymmetry. It does not make IP or UDP intrinsically client/server protocols.

### IP does not listen on ports

“Listening on a port” is not an IP-layer operation. An IP header contains source and destination IP addresses plus a protocol number, but it contains no TCP or UDP ports:

```text
IP destination + protocol number
               │
               ├── protocol 6  → TCP
               ├── protocol 17 → UDP
               └── protocol 1  → ICMP
```

After link-layer filtering, IP validation, routing, and firewall processing, the kernel's IP layer decides whether an accepted packet is for the local host and which upper-layer protocol should receive it. Only then does TCP or UDP inspect its own header and perform a socket lookup using IP addresses and ports.

TCP supports the passive-open mechanism commonly called listening:

```text
bind(local IP, port) → listen() → accept()
```

The TCP subsystem first looks for an established connection matching the source/destination IP-and-port tuple. For a new `SYN`, it may instead find a listening socket for the local address and port. If no socket matches, the kernel normally rejects the attempt with TCP `RST`.

UDP has ports but no TCP-style listen or accept operation:

```text
bind(local IP, port) → recvfrom()
```

The UDP subsystem delivers a datagram to a matching bound socket. If none exists, the host may return ICMP Port Unreachable.

The precise separation is:

> IP delivers an accepted packet to the appropriate transport protocol. TCP or UDP uses port numbers to select a socket. The socket layer connects that transport endpoint to an application; only TCP has the specific listen/accept mechanism.

### What NAT changes about that relationship

Without NAT or firewall restrictions, either globally reachable host can initiate traffic to the other. With ordinary source NAT, the private host normally must send first:

```text
actual initiator:   192.168.1.10:51514
observed initiator: 198.51.100.10:62000
responder:          203.0.113.20:443
```

The initiator knows the responder's reachable destination, `203.0.113.20:443`. The responder learns and replies to `198.51.100.10:62000`. It does not learn the private `192.168.1.10:51514` address from the IP and TCP headers.

The responder therefore does know an address for the initiator, but it is the **translated public endpoint**, not necessarily the initiator's actual interface address. That public endpoint is usable while the NAT mapping and firewall state permit the flow. It does not necessarily allow the responder to create an unrelated inbound flow later.

Unlike the responder's reachable logical destination, the initiator's original source address need not be globally unique:

```text
Home A client: 192.168.1.10:51514
Home B client: 192.168.1.10:51514
```

The identical private endpoints are valid because they exist in different routing domains. NAT gives each flow a usable public mapping. Even that public IP can be shared by many clients, distinguished by ports, protocol, and connection state:

```text
198.51.100.10:62000 → private client A
198.51.100.10:62001 → private client B
```

This is the practical initiation asymmetry:

> The initiator must know a reachable logical destination, but its own address need not be globally unique or independently reachable. The responder returns traffic to the translated source endpoint created for that flow.

This principle also applies to UDP even though UDP has no connection handshake. A NAT gateway usually creates temporary UDP flow state when it sees the first outbound datagram:

```text
private UDP endpoint → public UDP mapping → responder
```

Return datagrams matching that state can reach the initiator. The mapping eventually expires, so real-time applications may send keepalives. In this context, “initiator” means the side that sends the first packet and creates the necessary network state—not necessarily a TCP client.

### Two private hosts in different networks

Suppose two users are behind unrelated home routers:

```text
User A: 192.168.1.10 behind NAT A
User B: 192.168.1.10 behind NAT B
```

Their identical private addresses are not a conflict because the addresses belong to different routing domains. Neither private address is globally reachable, so A cannot simply send an Internet packet to B's `192.168.1.10`.

A messaging service commonly solves this with two outbound connections:

```text
User A ──outbound connection──► public service
User B ──outbound connection──► public service
```

When A sends a message to B:

1. A sends it through A's established connection to the public service.
2. The service identifies B by an application identity, not by B's private IP.
3. The service delivers it through B's separate established connection.
4. B's NAT mapping directs the returning packets to B's private endpoint.

In this design, the publicly reachable service is a relay and the two clients never need to learn each other's IP addresses.

A relay is common, but it is not always required for the entire data path. Peer-to-peer systems may use a public **rendezvous service** to discover the peers' translated public IP-and-port mappings, then try STUN, ICE, and UDP hole punching to establish a direct flow:

```text
NAT A public mapping ← direct packets → NAT B public mapping
```

If their NAT or firewall behavior prevents a direct flow, a public relay such as TURN carries the traffic. The accurate rule is therefore:

> Two private hosts in different networks usually need publicly reachable infrastructure for discovery and coordination; they often use it as a relay, but compatible NAT traversal can sometimes create a direct public-mapping-to-public-mapping path.

## Putting it all together: cooperation, not one global table

Routing tables contain essential information, but they are not the entire mechanism and no router needs one global end-to-end route.

End-to-end communication works because:

1. **Application discovery, DNS, or rendezvous** gives the initiator a reachable responder IP; the destination port identifies the requested transport service.
2. **The subnet mask and host routing table** decide whether the first next hop is the destination or a gateway.
3. **ARP and Layer 2 switching** deliver a frame to that next hop on the current local network.
4. **Each router's forwarding table** independently moves the IP packet one hop closer to the destination prefix.
5. **New Layer 2 framing** carries the packet across each successive link while routers preserve its logical endpoints and decrement TTL.
6. **NAT state**, when private IPv4 is involved, translates the initiating flow at the public/private boundary and provides the inverse mapping for replies.
7. **The destination IP, transport protocol, and port** let the final host's kernel select the correct socket and application.
8. **Public relay infrastructure**, when direct NAT traversal is impossible or undesirable, joins the separate outbound flows of hosts in unrelated private networks.

The Proxy ARP case at the start is a special variation on the first-hop step. The subnet mask tells the client that the peer is on-link, but Proxy ARP returns a gateway MAC. From that point onward, the gateway routes the packet just like any other Layer 3 forwarding device.

In short:

> An initiator first discovers a reachable responder IP and port, but addresses each Layer 2 frame only to the next hop. Routers repeat that next-hop process, NAT state reconnects replies to a private initiator, and public rendezvous or relay infrastructure lets hosts in unrelated private networks find or communicate with one another.
