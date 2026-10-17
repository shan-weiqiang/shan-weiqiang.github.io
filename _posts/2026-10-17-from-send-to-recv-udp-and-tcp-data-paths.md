---
layout: post
title: "The UDP and TCP Data Paths"
date: 2026-10-17 09:00:01 +0800
tags: [networking, linux, udp, tcp, ipv4]
---

This document describes a typical Linux IPv4 and Ethernet path. Routing, container networking, NIC offloads, and kernel settings can change the actual path. The buffers shown include socket memory, kernel queues, and NIC or switch buffers; they are separate resources.

* toc
{:toc}

## What send() means

- **UDP:** A call to `sendto()` or `sendmsg()` normally submits one complete UDP datagram and preserves its message boundary. Success means the local kernel accepted the send; it does not mean the peer received it. The theoretical maximum IPv4 UDP payload is 65,507 bytes. If fragmentation is disallowed, exceeding the path MTU may return `EMSGSIZE`.
- **TCP:** A call to `send()` writes bytes to a TCP byte stream and may accept only some of them. One write does not correspond to one TCP packet or one `recv()` call at the receiver. Success also does not mean the peer application has read the bytes.

## UDP: The path of one datagram

The sizes below assume a **20 B IPv4 header, an 8 B UDP header, and a 1,500 B path MTU**. They exclude IP options, tunnels, and other overhead. "Maximum" refers to a protocol limit; "MTU 1500" limits the size of each IP fragment on this path.

```text
Sender                                    Receiver
-------------------------------- L7 APPLICATION --------------------------------
+------------------------------------+    +------------------------------------+
|[L7 APP] sendto()/sendmsg()         |    |[L7 APP] recvfrom()/recvmsg()       |
|one message = UDP payload           |    |reads one complete datagram         |
|IPv4 payload max: 65,507 B          |    |payload max: 65,507 B               |
|message boundary preserved          |    |short buffer may truncate           |
+------------------------------------+    +------------------------------------+
-------------------+------------- L4 TRANSPORT --------------+------------------
                   v                                         ^
+------------------------------------+    +------------------------------------+
|[L4 TRANS][BUFFER] UDP socket TX    |    |[L4 TRANS][BUFFER] UDP socket RX    |
|per socket: SO_SNDBUF               |    |per socket: SO_RCVBUF               |
|temporary send memory               |    |holds complete datagrams            |
|no UDP retransmit buffer            |    |may overflow if app reads slowly    |
+------------------------------------+    +------------------------------------+
                   |                                         |
                   v                                         ^
+------------------------------------+    +------------------------------------+
|[L4 TRANS] UDP adds 8 B header      |    |[L4 TRANS] UDP header / demux       |
|datagram = header + payload         |    |8 B header identifies dst socket    |
|UDP datagram max: 65,515 B          |    |complete datagram -> socket RX      |
|still one UDP message               |    |preserves one-message boundary      |
+------------------------------------+    +------------------------------------+
-------------------+-------------- L3 NETWORK ---------------+------------------
                   v                                         ^
+------------------------------------+    +------------------------------------+
|[L3 NET] IPv4 adds 20 B header      |    |[L3 NET][BUFFER] IP frag queue      |
|original IPv4 packet                |    |hold fragments until all arrive     |
|total max: 65,535 B                 |    |ipfrag_high_thresh per netns        |
|route and path MTU check            |    |restore packet; then UDP processing |
+------------------------------------+    +------------------------------------+
                   |                                         |
                   v                                         ^
+------------------------------------+    +------------------------------------+
|[L3 NET] IPv4 fragmentation         |    |[L3 NET] IPv4 header pre-check      |
|each fragment <= path MTU           |    |validate header; read ID/offset/MF  |
|MTU 1500: fragment <= 1,500 B       |    |key: src/dst/proto/IP ID            |
|DF/PMTU may cause EMSGSIZE          |    |fragment -> reassembly queue        |
+------------------------------------+    +------------------------------------+
-------------------+------------- L2 DATA LINK --------------+------------------
                   v                                         ^
+------------------------------------+    +------------------------------------+
|[L2 LINK][QUEUE] qdisc/TX ring      |    |[L2 LINK][BUFFER] NIC RX ring       |
|queued outbound IP fragments        |    |DMA + driver/NAPI/softirq           |
|TX ring / DMA descriptors           |    |incoming link-layer frames          |
|NIC sends link-layer frames         |    |NIC / driver can drop               |
+------------------------------------+    +------------------------------------+
                   |                                         ^
                   +---NIC --> [L2 switch BUFFER] --> NIC----+
--------------------------------- L1 PHYSICAL ----------------------------------
                   wire / PHY on each link
```

**Legend:** [BUFFER] denotes buffer memory; [QUEUE] denotes a point where packets wait. UDP socket buffers are accounted per socket, IPv4 reassembly memory is shared within a network namespace, and a NIC ring belongs to a network device or queue.

**Size relationship:** UDP payload ≤ 65,507 B → UDP datagram (including UDP header) ≤ 65,515 B → original IPv4 packet (including IP header) ≤ 65,535 B. With an MTU of 1,500 B, the largest **unfragmented** IPv4 UDP payload is **1,472 B**. If a larger original packet may be fragmented, each transmitted IP fragment is at most **1,500 B** in total length.

At the receiver, the IP layer first checks each IPv4 fragment header, then uses the source address, destination address, protocol number, and IP ID to find its reassembly queue. Once all fragments arrive, it reconstructs the original IP packet. Only then can UDP place the datagram in the destination socket's receive queue. An unfragmented packet skips the reassembly queue. If a required fragment is missing, the entire datagram cannot be delivered. IP reassembly **does not** combine multiple UDP datagrams into one application message; fragmentation across datagrams requires reassembly by a higher-layer protocol.

## TCP: The path of a byte stream

```text
Sender                                    Receiver
-------------------------------- L7 APPLICATION --------------------------------
+------------------------------------+    +------------------------------------+
|[L7 APP] send() writes bytes        |    |[L7 APP] recv() reads byte stream   |
|may accept only part of write       |    |can split or combine writes         |
|no app-message boundary             |    |no TCP segment boundary             |
|return != peer delivery             |    |read may return fewer bytes         |
+------------------------------------+    +------------------------------------+
-------------------+------------- L4 TRANSPORT --------------+------------------
                   v                                         ^
+------------------------------------+    +------------------------------------+
|[L4 TRANS][BUFFER] TCP socket TX    |    |[L4 TRANS][BUFFER] TCP socket RX    |
|per socket: SO_SNDBUF               |    |per socket: SO_RCVBUF               |
|retain unacknowledged bytes         |    |hold received / reordered bytes     |
|retransmit when needed              |    |application reads from here         |
+------------------------------------+    +------------------------------------+
                   |                                         |
                   v                                         ^
+------------------------------------+    +------------------------------------+
|[L4 TRANS] TCP segmentation         |    |[L4 TRANS] TCP reorder / ACK        |
|sequence numbers + TCP header       |    |hold out-of-order segments          |
|MTU 1500: MSS about 1,460 B         |    |ACK received bytes to sender        |
|GSO/TSO may defer segmentation      |    |lost data triggers retransmit       |
+------------------------------------+    +------------------------------------+
-------------------+-------------- L3 NETWORK ---------------+------------------
                   v                                         ^
+------------------------------------+    +------------------------------------+
|[L3 NET] IPv4 adds IP header        |    |[L3 NET] IPv4 header check          |
|TCP packet usually fits path MTU    |    |[BUFFER] IP frag queue if needed    |
|rare IP fragmentation possible      |    |reassemble, then deliver to TCP     |
|then link-layer transmission        |    |otherwise bypass frag queue         |
+------------------------------------+    +------------------------------------+
-------------------+------------- L2 DATA LINK --------------+------------------
                   v                                         ^
+------------------------------------+    +------------------------------------+
|[L2 LINK][QUEUE] qdisc/TX ring      |    |[L2 LINK][BUFFER] NIC RX ring       |
|queued outbound packets             |    |DMA + driver/NAPI/softirq           |
|DMA to network adapter              |    |incoming packet processing          |
|send link-layer frames              |    |link-layer to IPv4                  |
+------------------------------------+    +------------------------------------+
                   |                                         ^
                   +---NIC --> [L2 switch BUFFER] --> NIC----+
--------------------------------- L1 PHYSICAL ----------------------------------
                   wire / PHY on each link
```

After the receiver sends a TCP ACK, the sender releases the corresponding acknowledged bytes from its send buffer. TCP retransmits lost data.

TCP reordering of a byte stream and IPv4 fragment reassembly are separate operations. TCP normally divides data into segments that fit the path MTU, so it seldom relies on IP fragmentation. If a TCP/IP packet is fragmented, the IP layer holds its fragments in the same per-network-namespace IPv4 reassembly buffer used by other IPv4 traffic, then passes the reassembled packet to TCP. Unfragmented packets bypass that buffer.

## Buffer and queue ownership

| Location | Scope | Contents or purpose | Common observation point |
|---|---|---|---|
| Socket send buffer | Per socket | Data waiting to be sent; TCP also retains unacknowledged bytes | `SO_SNDBUF`, `ss -m` |
| qdisc and driver TX ring | Network device and its TX queues | Packets waiting for the NIC to transmit | `tc -s qdisc`, `ethtool -S` |
| Switch buffer | Switch port or queue | Frames held before forwarding | Switch port drop counters |
| NIC RX ring and driver/softirq queue | NIC receive queue and CPU | Packets not yet delivered to the IP layer | `ethtool -S`, `/proc/net/softnet_stat` |
| IPv4 fragment reassembly | Shared within a network namespace | Fragments of incomplete original IPv4 packets, including protocols other than UDP | `ipfrag_high_thresh`, `IpReasmFails`, FRAG memory |
| UDP socket receive buffer | Per UDP socket | Complete datagrams after any IP reassembly | `SO_RCVBUF`, `UdpRcvbufErrors` |
| TCP socket receive buffer | Per TCP socket | TCP byte-stream data, including data awaiting ordering | `SO_RCVBUF`, `ss -m` |

**Boundary of observation:** A successful `send()` return means only that the local kernel accepted the data. Receipt by the remote NIC, IP reassembly, socket queueing, and the application's `recv()` are separate later events. Counting only at the final receiver cannot identify which earlier layer dropped or delayed a packet.

## Segmentation, fragmentation, and receive-buffer overflow

**TCP segmentation happens at the transport layer.** TCP divides a byte stream into segments, normally choosing an MSS that lets each segment and its headers fit within the path MTU. The sender can adjust the MSS when it learns that the path MTU is smaller. If an IPv4 packet carrying a TCP segment is still too large, IP fragmentation is possible only when allowed; otherwise it cannot be sent at that size.

**UDP preserves datagram boundaries.** One ordinary `sendto()` produces one UDP datagram; UDP does not automatically split it into smaller UDP datagrams using an MSS. If the resulting IPv4 packet exceeds the path MTU, IPv4 may fragment it when allowed. Otherwise the send can fail with `EMSGSIZE`. An application may instead send smaller datagrams and handle any message reassembly itself. Losing one IP fragment prevents delivery of its entire UDP datagram.

| Receive-side pressure | UDP result | TCP result |
|---|---|---|
| NIC RX ring or kernel packet-processing queue overflows | Packets are dropped; affected datagrams are lost. | Packets may be dropped; TCP normally detects the loss and retransmits, adding delay. |
| IPv4 fragment reassembly runs out of memory or a fragment never arrives | The affected datagram cannot be delivered. | If the TCP/IP packet was fragmented, the TCP segment cannot be delivered until retransmission succeeds. |
| Socket receive buffer fills because the application reads too slowly | Complete datagrams can be dropped; UDP has no built-in retry. | The advertised receive window shrinks, possibly to zero, so the sender slows or pauses. Any actual packet loss can trigger retransmission. |

TCP recovery improves eventual delivery, but it does not guarantee a deadline: retransmissions and a closed receive window can add substantial latency. UDP applications that need recovery or flow control must implement it at a higher layer.
