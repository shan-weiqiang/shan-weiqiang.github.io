---
layout: post
title: "Life of a UDP Datagram"
date: 2026-10-17 08:00:00 +0800
tags: [networking, linux, udp]
---

This article follows the journey from `sendto()` on a UDP socket to `recvfrom()` on the receiving socket. It is a companion to [Life of a TCP Segment]({% post_url 2024-05-19-Life-of -a-TCP-segment %}), following the same sender-buffer, protocol-stack, and receiver-buffer sequence.

The example assumes a typical Linux IPv4 and Ethernet path, a 20-byte IPv4 header, an 8-byte UDP header, and a path MTU of 1,500 bytes. The diagrams show logical stages, rather than a literal kernel memory layout. NIC offloads, routing, and kernel settings can change the details.

| ![Application sends one UDP message through temporary socket send memory to the network device](/assets/images/udp_buffering_sender.svg) |
|:--:|
| *UDP kernel buffering, sender side* |

1. The application calls `sendto()` with a destination address and one message. In the ordinary case, this submits **one UDP datagram**. A connected UDP socket can use `write()` or `send()` with its configured peer. A UDP send either accepts the entire message as one datagram or fails; it never reports success for only part of the message. If a message is too large to send atomically, the call fails with `EMSGSIZE`. If send memory is unavailable, a blocking call can wait; a nonblocking call can fail with `EAGAIN` or `EWOULDBLOCK`. A successful return means local acceptance, not receipt by the remote application. See [send(2)](https://www.man7.org/linux/man-pages/man2/send.2.html).

   Linux accounts temporary outgoing memory against the socket's send-buffer limit, `SO_SNDBUF`. UDP does not retain data awaiting a peer ACK, so there is no TCP-style **LastByteAcked**, **LastByteSent**, or retransmission region. Packets can still wait in device queues after UDP processing; socket memory, qdisc queues, and NIC TX rings are separate resources.

| ![A 4,000-byte application message becomes one UDP datagram and, when allowed, three IPv4 fragments](/assets/images/udp_protocol_stack.svg) |
|:--:|
| *Starting a journey through the protocol stack* |

2. UDP adds its **8-byte header**, containing the source port, destination port, length, and checksum. The UDP length includes both header and payload. A 4,000-byte application message therefore becomes one 4,008-byte UDP datagram. UDP has no MSS, receive window (`rwnd`), or congestion window (`cwnd`) that automatically divides this message into smaller UDP datagrams. The header format is defined in [RFC 768](https://www.rfc-editor.org/rfc/rfc768.html).

3. IPv4 adds its header, producing a 4,028-byte IP packet in this example. If the packet fits the path MTU, it can travel without fragmentation. With an MTU of 1,500 bytes, the largest unfragmented UDP payload under these assumptions is `1500 - 20 - 8 = 1472` bytes.

   **If IPv4 fragmentation is allowed**, the larger packet can be split into IP fragments. Each fragment has its own IP header; the UDP header is part of the original IP payload and appears only at its beginning, in the first fragment. Fragments share the original packet's Identification value and use the fragment offset and More Fragments (`MF`) flag to describe their positions. The offset is measured in units of eight bytes. This is **IP fragmentation**, not the creation of several UDP messages. See [RFC 791](https://www.rfc-editor.org/rfc/rfc791.html).

   For the 4,000-byte message, the fragmentation example is:

   | Fragment | IP payload | IP header | Total IP length | Fragment offset | MF |
   |---|---|---|---|---|---|
   | First | 1,480 B: UDP header + first 1,472 B of application data | 20 B | 1,500 B | 0 | 1 |
   | Second | Next 1,480 B of application data | 20 B | 1,500 B | 185 | 1 |
   | Third | Remaining 1,048 B of application data | 20 B | 1,068 B | 370 | 0 |

   Linux UDP enables path MTU discovery by default and normally returns `EMSGSIZE` when a send exceeds the known path MTU. Fragmentation therefore describes an allowed configuration, not what every oversized send will do. The application should usually reduce its message size. See [udp(7)](https://www.man7.org/linux/man-pages/man7/udp.7.html).

4. The Ethernet layer encloses each outgoing IP packet or fragment in a **frame**, adding an Ethernet header and a frame check sequence. Packets may pass through a qdisc and the driver's TX ring before the NIC transmits them. Switches forward frames on the Ethernet path; routers forward IP packets between networks and create new link-layer frames for the outgoing link.

5. At the receiver, the NIC receives frames into RX buffers, and the driver processes them. Link-layer checks and processing precede delivery to IPv4. A frame may be lost before reaching IP because of link errors, NIC RX-ring pressure, or kernel packet-processing overload. UDP provides no recovery for these losses.

6. IPv4 checks each incoming IP header. An unfragmented packet can proceed to UDP. A fragmented packet enters an **IP reassembly queue**, where its fragments are associated using the source address, destination address, protocol, and IP Identification value. Fragments may arrive out of order. Only after the original packet is complete can UDP process it. If a required fragment is missing and reassembly times out, or reassembly cannot complete because of memory pressure, the datagram is not delivered. This memory is shared within the network namespace; it is separate from the destination socket's `SO_RCVBUF`. Linux exposes reassembly memory and timeout controls as `ipfrag_high_thresh` and `ipfrag_time`; see the [kernel IP sysctl documentation](https://docs.kernel.org/networking/ip-sysctl.html#ip-fragmentation).

| ![IPv4 reassembly precedes the UDP socket receive queue, where complete datagrams wait for the application](/assets/images/udp_buffering_recv.svg) |
|:--:|
| *UDP kernel buffering at the receiver* |

7. UDP validates the datagram's length and, when present, checksum, and selects an eligible destination socket using the destination address and port, along with other socket matching rules. A valid datagram can then enter that socket's receive queue. The queue contains **complete datagrams**, with each message boundary preserved. UDP sends no ACK and advertises no receive window. If receive-buffer pressure prevents queueing, the datagram can be dropped; the sender is not automatically slowed by a TCP-style window. `SO_RCVBUF` controls receive-memory accounting, including kernel overhead, so it is not simply a count of available payload bytes. See [socket(7)](https://www.man7.org/linux/man-pages/man7/socket.7.html).

8. The application calls `recvfrom()` or `recvmsg()` to consume one queued datagram. A large buffer does not combine several datagrams into one receive. A buffer smaller than the datagram receives only the part that fits, and the remainder is discarded; the next receive reads the next datagram. `recvmsg()` reports this truncation through `MSG_TRUNC`. Consuming a message releases its receive-queue memory. A valid zero-length UDP datagram can return zero bytes, which does not mean the peer closed a connection. See [recv(2)](https://www.man7.org/linux/man-pages/man2/recv.2.html).

In the steps above, there are some notes to keep in mind:

1. **UDP preserves messages, not delivery guarantees.** Datagrams may be lost, duplicated, or reordered. UDP provides no built-in retransmission or ordering of separate messages. Applications needing these properties must supply them at a higher layer.

2. **IP fragments are parts of one IP packet.** Reassembly restores the UDP datagram carried by that packet; it does not combine independent UDP datagrams into a larger application message. With a 20-byte IPv4 header, the theoretical maximum UDP payload is `65535 - 20 - 8 = 65507` bytes. That protocol limit is much larger than the payload that fits an ordinary Ethernet MTU.

3. **Fragmentation increases the consequences of a single loss.** Losing any required fragment prevents delivery of the entire datagram. Applications should generally avoid IP fragmentation and implement congestion control appropriate to their traffic, as discussed in [RFC 8085](https://www.rfc-editor.org/rfc/rfc8085.html).

4. **This is the ordinary datagram path.** Features such as `UDP_CORK`, `MSG_MORE`, `UDP_SEGMENT`, and `UDP_GRO` change how data is submitted or presented. They are outside the one-send, one-datagram example here.

The whole picture:

![The UDP datagram lifecycle from application send, through UDP and IPv4, across Ethernet, and back up to application receive](/assets/images/udp_datagram_lifecycle.svg)
