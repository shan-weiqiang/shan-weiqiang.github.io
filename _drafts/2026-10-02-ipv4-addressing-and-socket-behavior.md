---
layout: post
title: "IPv4 Addressing and Socket Behavior: Unicast, Multicast, Broadcast, Wildcard Binding, and Loopback"
date: 2026-10-02 00:00:00 +0800
tags: [networking, linux, ipv4, sockets, udp]
---

* toc
{:toc}

An IPv4 address in a socket call can describe a destination, a local binding, or an interface choice. These roles are easy to confuse, especially when one UDP socket handles several kinds of traffic. This guide separates them using ordinary Linux IPv4 sockets. All addresses are illustrative.

## 1. Destinations, bindings, and interfaces

| Concept | Example | Meaning |
| --- | --- | --- |
| Unicast | `192.168.10.200` | One destination address |
| Multicast | `239.255.0.1` | A receiver group |
| Limited broadcast | `255.255.255.255` | Hosts on a local network segment |
| Subnet broadcast | `192.168.10.255` for `192.168.10.0/24` | Hosts on that subnet |
| Wildcard bind | `0.0.0.0:7400` | No single local IPv4 address selected |
| Loopback | `127.0.0.1` | This network namespace, through loopback |

Unicast, multicast, and broadcast describe **packet destinations**. Wildcard binding describes a socket's **local address selection**. Loopback provides **local communication**. TCP and UDP add ports to IP addresses. Ordinary TCP connections use unicast; UDP can use unicast, multicast, or broadcast. None of those UDP destination choices guarantees delivery. See [Linux IPv4](https://man7.org/linux/man-pages/man7/ip.7.html) and [UDP](https://man7.org/linux/man-pages/man7/udp.7.html).

## 2. Unicast: send to one destination

A UDP send to `192.168.10.200:7410` addresses that IP and port. It does not distribute the datagram to every host on the subnet.

For ordinary unicast sending, routing selects the outgoing interface and next hop, subject to socket and policy restrictions. If the socket has no fixed source address, the kernel selects one. See [Linux routing](https://man7.org/linux/man-pages/man8/ip-route.8.html).

```text
Remote destination IP and port
    → Route lookup, subject to socket restrictions
    → Outgoing interface and source address
    → Destination directly, or through a gateway
```

One unconnected UDP socket can send to different destinations. Those sends may take different interface paths; a separate socket per destination is unnecessary. UDP `connect()` sets a peer association, not a TCP-style connection. See [UDP socket behavior](https://man7.org/linux/man-pages/man7/udp.7.html).

## 3. Multicast: send to a receiver group

IPv4 multicast addresses occupy `224.0.0.0/4`. A group address identifies neither an interface nor an individual receiver. The sender addresses the group without listing its receivers and does not need to join it to send. Crossing subnets requires multicast forwarding and suitable scope and TTL; ordinary unicast reachability is insufficient. See [RFC 1112](https://www.rfc-editor.org/rfc/rfc1112.html).

### Receiving: bind and join

A typical UDP receiver binds a port and joins the group on a chosen interface. A membership specifies a group and local interface, not a remote sender or UDP port.

```text
One UDP socket bound to 0.0.0.0:7400
    ├── Join 239.255.0.1 on eth0
    └── Join 239.255.0.1 on eth1

Matching multicast datagrams arriving through either interface
    → The same socket's receive queue
```

One socket can join several groups or the same group on several interfaces. Leaving the interface unspecified lets the kernel choose an interface; it does not request all interfaces. Binding to `0.0.0.0` by itself joins no group. See [Linux multicast membership parameters](https://man7.org/linux/man-pages/man2/ip_mreqn.2type.html).

There is one Linux-specific wrinkle: `IP_MULTICAST_ALL` defaults to `1`. An otherwise matching wildcard socket can therefore receive traffic for groups joined by *other* sockets in its network namespace. Set it to `0` to restrict delivery to the socket's own memberships. See [Linux multicast options](https://manpages.debian.org/bookworm/manpages/ip.7.en.html#IP_MULTICAST_ALL).

### Sending: select an outgoing interface

`IP_MULTICAST_IF` selects the outgoing multicast interface. Without an explicit selection, the kernel chooses an outgoing path. Receive memberships do not select sending interfaces. See [IP_MULTICAST_IF](https://man7.org/linux/man-pages/man2/IP_MULTICAST_IF.2const.html).

```text
Send to 239.255.0.1:7400
    → One selected outgoing interface
    → Multicast-capable network distributes the datagram

To transmit on eth0 and eth1:
    → Send once through eth0
    → Send again through eth1
```

Joining a group on two interfaces does not make one send transmit through both. The application or middleware must arrange separate transmissions. See [RFC 1112, sending multicast](https://www.rfc-editor.org/rfc/rfc1112.html#section-6.1).

`IP_MULTICAST_LOOP` controls local delivery of sent multicast packets to eligible sockets. It is separate from addressing a packet to `127.0.0.1`. See [Linux multicast loopback](https://manpages.debian.org/bookworm/manpages/ip.7.en.html#IP_MULTICAST_LOOP).

### Source and destination addresses

The packet's source IP is normally the local unicast IP of the selected outgoing interface; an explicit local unicast binding can constrain that choice. The source port is the socket's bound local port, or a port the kernel assigns if the socket was not explicitly bound. The destination is the group IP and port passed to `sendto()`.

```text
Socket bound to 0.0.0.0:9000
Outgoing interface: eth0, IP 192.168.10.95
sendto(239.255.0.1:7400)

Packet:
    Source      = 192.168.10.95:9000
    Destination = 239.255.0.1:7400
```

Source and destination ports need not match. A multicast group address is never the packet's source IP, even if the socket is bound to that group address. See [RFC 1112](https://www.rfc-editor.org/rfc/rfc1112.html#section-6.2), [UDP port assignment](https://man7.org/linux/man-pages/man7/udp.7.html), and [Linux binding](https://github.com/torvalds/linux/blob/master/net/ipv4/af_inet.c).

## 4. Broadcast: address a local network

Broadcast targets hosts on a network rather than members of a selected group. No multicast membership is required.

- `255.255.255.255` is limited broadcast. Routers do not forward it beyond the local link.
- A subnet broadcast address has all host bits set. For `192.168.10.0/24`, it is `192.168.10.255`; a different prefix length changes the result.

These forms are defined in [RFC 1122](https://www.rfc-editor.org/rfc/rfc1122.html#section-3.2.1.3). Routers disable directed-broadcast forwarding by default under [RFC 2644](https://www.rfc-editor.org/rfc/rfc2644.html).

Linux UDP senders must enable `SO_BROADCAST` to send broadcast datagrams. That option is not required merely to receive them. Broadcast does not deliver to every application: destination port, socket matching, and filtering still apply. See [socket options](https://man7.org/linux/man-pages/man7/socket.7.html).

Broadcast also does not instruct Linux to transmit through every local interface. The outgoing path still needs selection; applications that require several links must arrange transmission on each. [RFC 1122](https://www.rfc-editor.org/rfc/rfc1122.html#section-3.3.6) does not require all-interface broadcast transmission.

## 5. Wildcard `0.0.0.0`: accept local addresses without choosing one

For `bind()`, `0.0.0.0` means `INADDR_ANY`. One socket can accept traffic addressed to different local IPv4 addresses in its network namespace at the bound port. It does not create one socket per interface. See [Linux IPv4 binding](https://man7.org/linux/man-pages/man7/ip.7.html).

For ordinary unicast reception:

| Local binding | Destination addresses accepted |
| --- | --- |
| `0.0.0.0:9000` | Any local IPv4 address, subject to other socket restrictions |
| `192.168.10.95:9000` | That local IPv4 address |
| `127.0.0.1:9000` | That loopback address |

Binding an IP address differs from binding a network device. Linux provides `SO_BINDTODEVICE` for device restrictions. Wildcard binding neither joins multicast groups nor bypasses firewall rules. See [socket binding options](https://man7.org/linux/man-pages/man7/socket.7.html).

For TCP, a wildcard listener can accept connections through different local addresses. Each accepted connection gets a new connected socket with a concrete local and remote address pair. See [accept()](https://man7.org/linux/man-pages/man2/accept.2.html).

`0.0.0.0` is not a remote peer address to advertise: a peer needs a reachable address. A send from a wildcard-bound socket still requires an outgoing route and does not transmit through all interfaces.

## 6. Loopback `127.0.0.1`: communicate locally

`127.0.0.1` is the conventional IPv4 loopback address; `127.0.0.0/8` is reserved for loopback. Ordinary loopback traffic stays inside the host networking stack and does not leave through Ethernet or Wi-Fi. See [RFC 1122](https://www.rfc-editor.org/rfc/rfc1122.html#section-3.2.1.3).

```text
Process A → 127.0.0.1:9000 → Local IP stack → Process B
                          No physical network hop
```

On Linux, “local” means the current network namespace. A container in a separate network namespace has its own loopback; its `127.0.0.1` does not refer to the host namespace. Processes sharing a network namespace share that network view. See [network namespaces](https://man7.org/linux/man-pages/man7/network_namespaces.7.html).

A remote computer using `127.0.0.1` addresses itself, not your computer. Loopback communication still uses sockets and TCP or UDP; it is not shared-memory delivery.

## 7. One UDP socket can handle all three destinations

A UDP socket is not inherently a unicast, multicast, or broadcast socket. The same unconnected socket can send and receive all three kinds of traffic when its binding, memberships, and options permit them.

For a socket bound to `0.0.0.0:9000`:

| Traffic | Receive | Send |
| --- | --- | --- |
| Unicast | Receive packets addressed to local IPv4 addresses on port `9000` | Specify the destination IP and port in `sendto()` |
| Multicast | Join the desired group on the receiving interface; receive group traffic on port `9000` | Specify the group IP and destination port; membership is not required |
| Broadcast | Receive matching local-network broadcasts on port `9000`; no join is needed | Enable `SO_BROADCAST` and specify the broadcast IP and destination port |

Socket matching, interface restrictions, and firewall rules still apply. See [Linux socket options](https://man7.org/linux/man-pages/man7/socket.7.html).

The bound port is the local receiving port and the source port of outgoing datagrams. The destination port is chosen independently:

```text
One socket bound to 0.0.0.0:9000, joined to 239.255.0.1

Receive: remote sender → 239.255.0.1:9000 → this socket
Send:    this socket, source local-IP:9000 → 239.255.0.1:7400
```

Group membership contains a group and interface, not a UDP port. `bind()` selects the local address and port; `sendto()` selects each datagram's destination.

A send-only socket need not explicitly bind: the kernel can assign its local port automatically. A wildcard-bound sender uses a concrete source IP selected for its outgoing path, not `0.0.0.0`. See [UDP sockets](https://man7.org/linux/man-pages/man7/udp.7.html) and [routing](https://man7.org/linux/man-pages/man8/ip-route.8.html).

Linux also permits `bind(239.255.0.1:9000)`. This restricts reception to that destination IP and port; it does not join the group or make the group address an outgoing source IP. Use wildcard binding when the same socket should receive different destination addresses. See [Linux binding](https://github.com/torvalds/linux/blob/master/net/ipv4/af_inet.c) and [UDP receive matching](https://github.com/torvalds/linux/blob/master/net/ipv4/udp.c).

The practical rule is: **the sender needs the destination IP and port, but can let Linux choose its own source IP and port**. Membership governs multicast reception, binding governs local socket matching, and routing governs the outgoing path.
